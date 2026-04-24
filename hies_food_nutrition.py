"""
Extract HIES 2022 food consumption, calorie intake, and expenditure data.
Source: hies_bd_2022_report.pdf Chapter 4 (expenditure) + Chapter 5 (food).
All values manually extracted from official BBS tables.
"""
import csv
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "nutrition")

# Table 5.1: Average food intake (grams) by locality
FOOD_INTAKE_GRAMS = {
    2022: {"national": 1129.8, "rural": 1125.4, "urban": 1139.5},
    2016: {"national": 975.5, "rural": 974.4, "urban": 978.7},
    2010: {"national": 1000.0, "rural": 1000.5, "urban": 985.5},
    2005: {"national": 947.8, "rural": 946.3, "urban": 952.1},
    2000: {"national": 893.1, "rural": 898.7, "urban": 870.7},
}

# Table 5.3: Average per capita daily calorie intake (K.Cal)
CALORIE_INTAKE = {
    2022: {"national": 2393.0, "rural": 2424.2, "urban": 2324.6},
    2016: {"national": 2210.4, "rural": 2240.2, "urban": 2130.7},
    2010: {"national": 2318.3, "rural": 2344.6, "urban": 2244.5},
    2005: {"national": 2238.5, "rural": 2253.2, "urban": 2193.8},
    2000: {"national": 2240.3, "rural": 2263.2, "urban": 2150.0},
}

# Table 5.6: Average per capita daily protein intake (grams)
PROTEIN_INTAKE = {
    2022: {"national": 72.56, "rural": 71.90, "urban": 74.02},
    2016: {"national": 63.80, "rural": 63.34, "urban": 65.02},
    2010: {"national": 66.26, "rural": 65.24, "urban": 69.11},
    2005: {"national": 62.52, "rural": 61.74, "urban": 64.88},
    2000: {"national": 62.50, "rural": 61.88, "urban": 64.96},
}

# Table 5.2: Per capita daily food intake by major items (grams), national 2022
FOOD_ITEMS_GRAMS_2022 = {
    "cereals": {"national": 385.0, "rural": 403.0, "urban": 345.55},
    "rice": {"national": 328.92, "rural": 349.12, "urban": 284.68},
    "wheat": {"national": 22.92, "rural": 18.31, "urban": 33.01},
    "potato": {"national": 69.70, "rural": 71.85, "urban": 65.00},
    "vegetables": {"national": 201.92, "rural": 202.21, "urban": 201.28},
    "pulses": {"national": 17.15, "rural": 15.88, "urban": 19.91},
    "milk_products": {"national": 34.10, "rural": 32.06, "urban": 38.55},
    "edible_oils": {"national": 30.85, "rural": 30.00, "urban": 32.70},
    "meat_poultry_eggs": {"national": 52.78, "rural": 46.07, "urban": 67.46},
    "fish": {"national": 67.83, "rural": 67.67, "urban": 68.20},
    "fruits": {"national": 95.4, "rural": 90.89, "urban": 105.35},
    "sugar_gur": {"national": 16.37, "rural": 16.72, "urban": 15.58},
    "condiments_spices": {"national": 63.97, "rural": 62.36, "urban": 67.49},
}

# Table 4.9: Consumption expenditure shares (%) by locality
EXPENDITURE_SHARES = {
    2022: {
        "food_beverage": {"national": 45.76, "rural": 50.08, "urban": 39.72},
        "cloth_footwear": {"national": 6.74, "rural": 6.79, "urban": 6.68},
        "housing_rent": {"national": 10.25, "rural": 8.73, "urban": 12.38},
        "fuel_lighting": {"national": 5.25, "rural": 5.16, "urban": 5.38},
        "household_effects": {"national": 2.19, "rural": 2.26, "urban": 2.09},
        "miscellaneous": {"national": 29.80, "rural": 26.98, "urban": 33.75},
    },
    2016: {
        "food_beverage": {"national": 47.69, "rural": 50.49, "urban": 42.59},
        "cloth_footwear": {"national": 7.12, "rural": 7.50, "urban": 6.42},
        "housing_rent": {"national": 12.43, "rural": 9.80, "urban": 17.25},
        "fuel_lighting": {"national": 6.07, "rural": 6.65, "urban": 5.02},
        "household_effects": {"national": 2.93, "rural": 2.88, "urban": 3.03},
        "miscellaneous": {"national": 23.76, "rural": 22.68, "urban": 25.69},
    },
}

# Table 4.11: COICOP expenditure (BDT) by locality, 2022
COICOP_EXPENDITURE_2022 = [
    {"division": "Food and Nonalcoholic Beverages", "national": 13193, "rural": 12318, "urban": 15058},
    {"division": "Alcoholic Beverages, Tobacco and Narcotics", "national": 810, "rural": 806, "urban": 816},
    {"division": "Clothing and Footwear", "national": 2063, "rural": 1779, "urban": 2669},
    {"division": "Housing, Water, Electricity, Gas, Other Fuels", "national": 4418, "rural": 3334, "urban": 6727},
    {"division": "Furnishings, HH Equipment, Maintenance", "national": 1638, "rural": 1115, "urban": 2752},
    {"division": "Health", "national": 2115, "rural": 1906, "urban": 2560},
    {"division": "Transport", "national": 1682, "rural": 1230, "urban": 2645},
    {"division": "Communication", "national": 860, "rural": 734, "urban": 1129},
    {"division": "Recreation and Culture", "national": 431, "rural": 303, "urban": 704},
    {"division": "Education", "national": 578, "rural": 383, "urban": 993},
    {"division": "Restaurants and Hotels", "national": 62, "rural": 66, "urban": 52},
    {"division": "Miscellaneous Goods and Services", "national": 1509, "rural": 1264, "urban": 2032},
    {"division": "Others", "national": 2140, "rural": 1602, "urban": 3286},
]

# Table 4.2: Income Gini and decile distribution
INCOME_DECILE_2022 = {
    "bottom_5pct": 0.37, "decile_1": 1.31, "decile_2": 2.86, "decile_3": 3.88,
    "decile_4": 4.82, "decile_5": 5.81, "decile_6": 6.92, "decile_7": 8.36,
    "decile_8": 10.49, "decile_9": 14.62, "decile_10": 40.92, "top_5pct": 30.04,
    "gini": 0.499,
}


def export_all():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Calorie/protein timeseries
    path = os.path.join(OUTPUT_DIR, "hies_nutrition_timeseries.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "food_intake_g", "calorie_kcal", "protein_g",
                     "food_intake_rural", "calorie_rural", "protein_rural",
                     "food_intake_urban", "calorie_urban", "protein_urban"])
        for year in sorted(CALORIE_INTAKE.keys()):
            w.writerow([
                year,
                FOOD_INTAKE_GRAMS[year]["national"], CALORIE_INTAKE[year]["national"], PROTEIN_INTAKE[year]["national"],
                FOOD_INTAKE_GRAMS[year]["rural"], CALORIE_INTAKE[year]["rural"], PROTEIN_INTAKE[year]["rural"],
                FOOD_INTAKE_GRAMS[year]["urban"], CALORIE_INTAKE[year]["urban"], PROTEIN_INTAKE[year]["urban"],
            ])
    print(f"  Wrote {path}")

    # 2. Food items breakdown 2022
    path = os.path.join(OUTPUT_DIR, "hies_food_items_2022.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["food_item", "national_g", "rural_g", "urban_g"])
        for item, vals in FOOD_ITEMS_GRAMS_2022.items():
            w.writerow([item, vals["national"], vals["rural"], vals["urban"]])
    print(f"  Wrote {path}")

    # 3. Expenditure shares
    path = os.path.join(OUTPUT_DIR, "hies_expenditure_shares.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "category", "national_pct", "rural_pct", "urban_pct"])
        for year, cats in sorted(EXPENDITURE_SHARES.items()):
            for cat, vals in cats.items():
                w.writerow([year, cat, vals["national"], vals["rural"], vals["urban"]])
    print(f"  Wrote {path}")

    # 4. COICOP expenditure 2022
    path = os.path.join(OUTPUT_DIR, "hies_coicop_expenditure_2022.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["coicop_division", "national_bdt", "rural_bdt", "urban_bdt"])
        for item in COICOP_EXPENDITURE_2022:
            w.writerow([item["division"], item["national"], item["rural"], item["urban"]])
    print(f"  Wrote {path}")

    # 5. Income decile distribution
    path = os.path.join(OUTPUT_DIR, "hies_income_decile_2022.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["decile", "income_share_pct"])
        for k, v in INCOME_DECILE_2022.items():
            w.writerow([k, v])
    print(f"  Wrote {path}")

    print(f"\n  HIES food/nutrition: 5 CSVs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    export_all()

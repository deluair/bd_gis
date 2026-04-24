"""
Extract HIES 2022 ground truth poverty data from the BBS Final Report.
Source: hies_bd_2022_report.pdf (BBS, Dec 2023), Chapter 6 + Chapter 3-4.

All values are manually extracted from official tables. No interpolation.
"""
import csv
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "poverty")

# Table 6.4: Head Count Rate by Division (Upper and Lower Poverty Line)
HIES_HCR_BY_DIVISION = {
    # division: {year: {upl: %, lpl: %, upl_rural: %, upl_urban: %, lpl_rural: %, lpl_urban: %}}
    "Barishal": {
        2022: {"upl": 26.9, "lpl": 11.8, "upl_rural": 28.4, "upl_urban": 21.3, "lpl_rural": 13.1, "lpl_urban": 6.7},
        2016: {"upl": 26.5, "lpl": 14.5, "upl_rural": 25.7, "upl_urban": 30.4, "lpl_rural": 14.9, "lpl_urban": 12.2},
    },
    "Chattogram": {
        2022: {"upl": 15.8, "lpl": 5.1, "upl_rural": 17.9, "upl_urban": 11.3, "lpl_rural": 6.3, "lpl_urban": 2.3},
        2016: {"upl": 18.4, "lpl": 8.7, "upl_rural": 19.4, "upl_urban": 15.9, "lpl_rural": 9.6, "lpl_urban": 6.5},
    },
    "Dhaka": {
        2022: {"upl": 17.9, "lpl": 2.8, "upl_rural": 21.7, "upl_urban": 14.3, "lpl_rural": 1.9, "lpl_urban": 3.7},
        2016: {"upl": 16.0, "lpl": 7.2, "upl_rural": 19.2, "upl_urban": 12.5, "lpl_rural": 10.7, "lpl_urban": 3.3},
    },
    "Khulna": {
        2022: {"upl": 14.8, "lpl": 2.9, "upl_rural": 16.2, "upl_urban": 9.9, "lpl_rural": 2.8, "lpl_urban": 3.1},
        2016: {"upl": 27.5, "lpl": 12.4, "upl_rural": 27.3, "upl_urban": 28.3, "lpl_rural": 13.1, "lpl_urban": 10.0},
    },
    "Mymensingh": {
        2022: {"upl": 24.2, "lpl": 10.0, "upl_rural": 26.2, "upl_urban": 16.0, "lpl_rural": 10.3, "lpl_urban": 8.5},
        2016: {"upl": 32.8, "lpl": 17.6, "upl_rural": 32.9, "upl_urban": 32.0, "lpl_rural": 18.3, "lpl_urban": 13.8},
    },
    "Rajshahi": {
        2022: {"upl": 16.7, "lpl": 6.7, "upl_rural": 17.2, "upl_urban": 14.9, "lpl_rural": 8.0, "lpl_urban": 2.5},
        2016: {"upl": 28.9, "lpl": 14.2, "upl_rural": 30.6, "upl_urban": 22.5, "lpl_rural": 15.2, "lpl_urban": 10.7},
    },
    "Rangpur": {
        2022: {"upl": 24.8, "lpl": 10.0, "upl_rural": 23.6, "upl_urban": 29.9, "lpl_rural": 10.3, "lpl_urban": 8.7},
        2016: {"upl": 47.2, "lpl": 30.5, "upl_rural": 48.2, "upl_urban": 41.5, "lpl_rural": 31.3, "lpl_urban": 26.3},
    },
    "Sylhet": {
        2022: {"upl": 17.4, "lpl": 4.6, "upl_rural": 18.1, "upl_urban": 14.4, "lpl_rural": 5.2, "lpl_urban": 1.3},
        2016: {"upl": 16.2, "lpl": 11.5, "upl_rural": 15.6, "upl_urban": 19.5, "lpl_rural": 11.8, "lpl_urban": 9.5},
    },
}

# Table 6.2/6.3: National HCR time series
HIES_HCR_NATIONAL = {
    2022: {"upl": 18.7, "lpl": 5.6, "upl_rural": 20.5, "upl_urban": 14.7, "lpl_rural": 6.5, "lpl_urban": 3.8},
    2016: {"upl": 24.3, "lpl": 12.9, "upl_rural": 26.4, "upl_urban": 18.9, "lpl_rural": 14.9, "lpl_urban": 7.6},
    2010: {"upl": 31.5, "lpl": 17.6, "upl_rural": 35.2, "upl_urban": 21.3, "lpl_rural": 21.1, "lpl_urban": 7.7},
    2005: {"upl": 40.0, "lpl": 25.1, "upl_rural": 43.8, "upl_urban": 28.4, "lpl_rural": 28.6, "lpl_urban": 14.6},
    2000: {"upl": 48.9, "lpl": 34.3, "upl_rural": 52.3, "upl_urban": 35.2, "lpl_rural": 39.5, "lpl_urban": 13.7},
}

# Table 6.5: Poverty Gap and Squared Poverty Gap by division (2022, UPL)
HIES_POVERTY_GAP = {
    "National":   {"pg": 3.77, "spg": 1.17},
    "Barishal":   {"pg": 5.84, "spg": 1.85},
    "Chattogram": {"pg": 3.36, "spg": 1.13},
    "Dhaka":      {"pg": 3.74, "spg": 1.14},
    "Khulna":     {"pg": 2.43, "spg": 0.69},
    "Mymensingh": {"pg": 4.99, "spg": 1.63},
    "Rajshahi":   {"pg": 2.99, "spg": 0.84},
    "Rangpur":    {"pg": 5.34, "spg": 1.71},
    "Sylhet":     {"pg": 2.98, "spg": 0.77},
}

# Table 4.5: Monthly household income and consumption by division (2022)
HIES_INCOME_BY_DIVISION = {
    "National":   {"income_bdt": 32422, "consumption_bdt": 30603},
    "Barishal":   {"income_bdt": 25892, "consumption_bdt": 23940},
    "Chattogram": {"income_bdt": 34054, "consumption_bdt": 34843},
    "Dhaka":      {"income_bdt": 42696, "consumption_bdt": 37935},
    "Khulna":     {"income_bdt": 28192, "consumption_bdt": 26135},
    "Mymensingh": {"income_bdt": 24183, "consumption_bdt": 24554},
    "Rajshahi":   {"income_bdt": 30398, "consumption_bdt": 25358},
    "Rangpur":    {"income_bdt": 21674, "consumption_bdt": 21667},
    "Sylhet":     {"income_bdt": 22861, "consumption_bdt": 30402},
}

# Table 4.2: Gini coefficient (national)
HIES_GINI = {
    2022: {"income": 0.499, "expenditure": None},
    2016: {"income": 0.482, "expenditure": None},
}

# Table 3.5: Household facilities by division (2022, national %)
HIES_FACILITIES_BY_DIVISION = {
    "National":   {"electricity": 99.34, "internet": 66.43, "computer": 8.05, "mobile": 98.48},
    "Barishal":   {"electricity": 99.49, "internet": 63.25, "computer": 4.33, "mobile": 99.11},
    "Chattogram": {"electricity": 98.98, "internet": 73.79, "computer": 7.32, "mobile": 98.99},
    "Dhaka":      {"electricity": 99.84, "internet": 80.50, "computer": 14.26, "mobile": 99.22},
    "Khulna":     {"electricity": 98.89, "internet": 63.40, "computer": 6.48, "mobile": 98.39},
    "Mymensingh": {"electricity": 99.31, "internet": 53.19, "computer": 2.99, "mobile": 96.77},
    "Rajshahi":   {"electricity": 99.24, "internet": 51.80, "computer": 5.37, "mobile": 97.62},
    "Rangpur":    {"electricity": 99.21, "internet": 45.45, "computer": 4.14, "mobile": 97.47},
    "Sylhet":     {"electricity": 99.22, "internet": 69.09, "computer": 4.61, "mobile": 98.78},
}

# Table 6.9: HCR by education (2022, UPL)
HIES_HCR_BY_EDUCATION = {
    "illiterate": 26.9,
    "literate": 14.2,
    "no_education": 26.6,
    "class_i_iv": 24.1,
    "class_v_ix": 17.7,
    "ssc_plus": 6.7,
}

# Table 6.11: HCR by land ownership (2022, UPL)
HIES_HCR_BY_LAND = {
    "no_land": 25.8,
    "lt_0.05": 25.1,
    "0.05_0.49": 19.2,
    "0.50_1.49": 12.5,
    "1.50_2.49": 8.1,
    "2.50_7.49": 7.2,
    "gte_7.50": 3.9,
}


def export_hies_ground_truth():
    """Export all HIES ground truth data to CSVs."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Division-level HCR (main calibration target)
    path = os.path.join(OUTPUT_DIR, "hies_division_hcr.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["division", "year", "hcr_upl", "hcr_lpl",
                     "hcr_upl_rural", "hcr_upl_urban", "hcr_lpl_rural", "hcr_lpl_urban"])
        for div, years in HIES_HCR_BY_DIVISION.items():
            for year, d in years.items():
                w.writerow([div, year, d["upl"], d["lpl"],
                            d["upl_rural"], d["upl_urban"], d["lpl_rural"], d["lpl_urban"]])
    print(f"  Wrote {path}")

    # 2. National HCR time series
    path = os.path.join(OUTPUT_DIR, "hies_national_hcr_timeseries.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "hcr_upl", "hcr_lpl",
                     "hcr_upl_rural", "hcr_upl_urban", "hcr_lpl_rural", "hcr_lpl_urban"])
        for year in sorted(HIES_HCR_NATIONAL.keys()):
            d = HIES_HCR_NATIONAL[year]
            w.writerow([year, d["upl"], d["lpl"],
                        d["upl_rural"], d["upl_urban"], d["lpl_rural"], d["lpl_urban"]])
    print(f"  Wrote {path}")

    # 3. Poverty gap by division
    path = os.path.join(OUTPUT_DIR, "hies_division_poverty_gap.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["division", "year", "poverty_gap_upl", "squared_poverty_gap_upl"])
        for div, d in HIES_POVERTY_GAP.items():
            w.writerow([div, 2022, d["pg"], d["spg"]])
    print(f"  Wrote {path}")

    # 4. Income by division
    path = os.path.join(OUTPUT_DIR, "hies_division_income.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["division", "year", "monthly_hh_income_bdt", "monthly_hh_consumption_bdt"])
        for div, d in HIES_INCOME_BY_DIVISION.items():
            w.writerow([div, 2022, d["income_bdt"], d["consumption_bdt"]])
    print(f"  Wrote {path}")

    # 5. Facilities by division
    path = os.path.join(OUTPUT_DIR, "hies_division_facilities.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["division", "year", "electricity_pct", "internet_pct", "computer_pct", "mobile_pct"])
        for div, d in HIES_FACILITIES_BY_DIVISION.items():
            w.writerow([div, 2022, d["electricity"], d["internet"], d["computer"], d["mobile"]])
    print(f"  Wrote {path}")

    # 6. HCR by education
    path = os.path.join(OUTPUT_DIR, "hies_hcr_by_education.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["education_level", "year", "hcr_upl"])
        for level, hcr in HIES_HCR_BY_EDUCATION.items():
            w.writerow([level, 2022, hcr])
    print(f"  Wrote {path}")

    # 7. HCR by land ownership
    path = os.path.join(OUTPUT_DIR, "hies_hcr_by_land.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["land_holding_acres", "year", "hcr_upl"])
        for holding, hcr in HIES_HCR_BY_LAND.items():
            w.writerow([holding, 2022, hcr])
    print(f"  Wrote {path}")

    print(f"\n  HIES ground truth: 7 CSVs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    export_hies_ground_truth()

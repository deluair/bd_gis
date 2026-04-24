"""
Calibrate satellite poverty index against HIES 2022 ground truth.

The raw satellite poverty index (nightlights + built-up + NDVI + population)
produces values of ~0.50 for all divisions (no discrimination).
HIES 2022 shows real variation: 14.8% (Khulna) to 26.9% (Barishal).

Calibration approach:
1. Load existing satellite poverty index by division (from GEE outputs)
2. Load HIES 2022 HCR by division
3. Compute division-level affine calibration (scale + shift)
4. Output calibrated poverty scores and calibration diagnostics
"""
import csv
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "poverty")

# Map GEE admin names to HIES division names
GEE_TO_HIES = {
    "Barisal": "Barishal",
    "Chittagong": "Chattogram",
    "Dhaka": "Dhaka",
    "Khulna": "Khulna",
    "Rajshahi": "Rajshahi",
    "Rangpur": "Rangpur",
    "Sylhet": "Sylhet",
}

# NOTE: Mymensingh is missing from GEE outputs (was split from Dhaka in 2015)


def load_satellite_poverty():
    """Load existing satellite poverty index by division."""
    path = os.path.join(OUTPUT_DIR, "poverty_by_division.csv")
    data = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["ADM1_NAME"]
            data[name] = {
                "sat_mean": float(row["poverty_index_mean"]),
                "sat_median": float(row["poverty_index_median"]),
            }
    return data


def load_hies_hcr():
    """Load HIES 2022 HCR by division."""
    path = os.path.join(OUTPUT_DIR, "hies_division_hcr.csv")
    data = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["year"]) == 2022:
                data[row["division"]] = float(row["hcr_upl"])
    return data


def load_hies_income():
    """Load HIES 2022 income by division."""
    path = os.path.join(OUTPUT_DIR, "hies_division_income.csv")
    data = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row["division"]] = float(row["monthly_hh_income_bdt"])
    return data


def load_hies_facilities():
    """Load HIES 2022 facilities by division."""
    path = os.path.join(OUTPUT_DIR, "hies_division_facilities.csv")
    data = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row["division"]] = {
                "internet": float(row["internet_pct"]),
                "computer": float(row["computer_pct"]),
            }
    return data


def calibrate():
    """Run calibration and output results."""
    sat = load_satellite_poverty()
    hies_hcr = load_hies_hcr()
    hies_income = load_hies_income()
    hies_facilities = load_hies_facilities()

    print("=== Satellite vs HIES Comparison ===\n")
    print(f"{'Division':<14} {'Sat Index':>10} {'HIES HCR%':>10} {'Income BDT':>11} {'Internet%':>10}")
    print("-" * 60)

    rows = []
    for gee_name, hies_name in sorted(GEE_TO_HIES.items()):
        if gee_name not in sat or hies_name not in hies_hcr:
            continue
        s = sat[gee_name]
        hcr = hies_hcr[hies_name]
        income = hies_income.get(hies_name, 0)
        internet = hies_facilities.get(hies_name, {}).get("internet", 0)
        print(f"{hies_name:<14} {s['sat_mean']:>10.4f} {hcr:>10.1f} {income:>11,.0f} {internet:>10.1f}")
        rows.append({
            "division": hies_name,
            "sat_mean": s["sat_mean"],
            "sat_median": s["sat_median"],
            "hies_hcr_2022": hcr,
            "hies_income_2022": income,
            "hies_internet_2022": internet,
        })

    # Compute correlation
    if len(rows) >= 3:
        sat_vals = [r["sat_mean"] for r in rows]
        hcr_vals = [r["hies_hcr_2022"] for r in rows]
        income_vals = [r["hies_income_2022"] for r in rows]
        internet_vals = [r["hies_internet_2022"] for r in rows]

        r_sat_hcr = pearson_r(sat_vals, hcr_vals)
        r_income_hcr = pearson_r(income_vals, hcr_vals)
        r_internet_hcr = pearson_r(internet_vals, hcr_vals)

        print(f"\nCorrelation (satellite index vs HCR): r = {r_sat_hcr:.3f}")
        print(f"Correlation (income vs HCR):          r = {r_income_hcr:.3f}")
        print(f"Correlation (internet vs HCR):        r = {r_internet_hcr:.3f}")

        # OLS: HCR = a * sat_index + b
        a, b = ols_fit(sat_vals, hcr_vals)
        print(f"\nOLS calibration: HCR = {a:.1f} * satellite_index + {b:.1f}")

        # Apply calibration
        print(f"\n{'Division':<14} {'Sat Index':>10} {'Calibrated':>10} {'HIES HCR':>10} {'Error':>8}")
        print("-" * 56)
        total_abs_err = 0
        for r in rows:
            calibrated = a * r["sat_mean"] + b
            err = calibrated - r["hies_hcr_2022"]
            total_abs_err += abs(err)
            r["calibrated_hcr"] = calibrated
            r["error"] = err
            print(f"{r['division']:<14} {r['sat_mean']:>10.4f} {calibrated:>10.1f} {r['hies_hcr_2022']:>10.1f} {err:>8.1f}")

        mae = total_abs_err / len(rows)
        print(f"\nMean Absolute Error: {mae:.2f} pp")

        # Note if satellite index has poor discrimination
        sat_range = max(sat_vals) - min(sat_vals)
        hcr_range = max(hcr_vals) - min(hcr_vals)
        print(f"\nSatellite index range: {min(sat_vals):.4f} - {max(sat_vals):.4f} (spread: {sat_range:.4f})")
        print(f"HIES HCR range: {min(hcr_vals):.1f}% - {max(hcr_vals):.1f}% (spread: {hcr_range:.1f}pp)")

        if sat_range < 0.02:
            print("\nWARNING: Satellite index has near-zero variance across divisions.")
            print("OLS calibration will be unstable. Consider using HIES values directly")
            print("for division-level analysis, and satellite data only for within-division")
            print("spatial disaggregation.")

    # Write calibration results
    path = os.path.join(OUTPUT_DIR, "calibration_results.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "division", "sat_mean", "sat_median",
            "hies_hcr_2022", "hies_income_2022", "hies_internet_2022",
            "calibrated_hcr", "error",
        ])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nWrote {path}")


def pearson_r(x, y):
    n = len(x)
    if n < 2:
        return 0
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den_x = sum((xi - mx) ** 2 for xi in x) ** 0.5
    den_y = sum((yi - my) ** 2 for yi in y) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0
    return num / (den_x * den_y)


def ols_fit(x, y):
    """Simple OLS: y = a*x + b. Returns (a, b)."""
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den = sum((xi - mx) ** 2 for xi in x)
    if den == 0:
        return 0, my
    a = num / den
    b = my - a * mx
    return a, b


if __name__ == "__main__":
    calibrate()

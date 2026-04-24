"""
Extract demographic indicators from IPUMS Bangladesh census data by district.
Outputs: age pyramids, dependency ratios, religion, disability, family structure.
"""
import csv
import gzip
import os
from collections import defaultdict

IPUMS_PATH = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-UniversityofTennessee/"
    "bd_data_repository/ipumsi_bd_comprehensive_v3.csv.gz"
)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "demographics")


def parse_int(v, default=0):
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def parse_float(v, default=0.0):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def process():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Reading {IPUMS_PATH}...")

    # Accumulators by (year, geolev2)
    acc = defaultdict(lambda: {
        "pop_weighted": 0, "male": 0, "female": 0,
        "age_0_14": 0, "age_15_64": 0, "age_65p": 0,
        "age_bins": defaultdict(float),  # 5-year bins
        "literate": 0, "literate_total": 0,
        "in_school": 0, "school_age": 0,  # 6-17
        "employed": 0, "working_age": 0,  # 15-64
        "disabled": 0,
        "religion": defaultdict(float),
        "urban_wt": 0,
        "married": 0, "marst_total": 0,
        "mean_famsize": 0, "famsize_count": 0,
        "mean_yrschool": 0, "yrschool_count": 0,
        "geolev1": "",
    })

    n = 0
    with gzip.open(IPUMS_PATH, "rt") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n += 1
            if n % 5000000 == 0:
                print(f"  {n:,} rows...")

            year = row.get("YEAR", "")
            geo2 = row.get("GEOLEV2", "")
            if not geo2:
                continue

            key = (year, geo2)
            a = acc[key]
            a["geolev1"] = row.get("GEOLEV1", "")

            wt = parse_float(row.get("PERWT", 1))
            age = parse_int(row.get("AGE", 0))
            sex = parse_int(row.get("SEX", 0))

            a["pop_weighted"] += wt
            if sex == 1:
                a["male"] += wt
            elif sex == 2:
                a["female"] += wt

            # Age groups
            if age < 15:
                a["age_0_14"] += wt
            elif age < 65:
                a["age_15_64"] += wt
            else:
                a["age_65p"] += wt

            # 5-year bins
            bin_start = (age // 5) * 5
            bin_label = f"{bin_start}-{bin_start+4}" if bin_start < 80 else "80+"
            a["age_bins"][bin_label] += wt

            # Literacy (age 15+)
            if age >= 15:
                lit = parse_int(row.get("LIT", 0))
                a["literate_total"] += wt
                if lit == 2:  # literate
                    a["literate"] += wt

            # School attendance (age 6-17)
            if 6 <= age <= 17:
                a["school_age"] += wt
                school = parse_int(row.get("SCHOOL", 0))
                if school == 2:  # attending
                    a["in_school"] += wt

            # Employment (age 15-64)
            if 15 <= age <= 64:
                a["working_age"] += wt
                empstat = parse_int(row.get("EMPSTAT", 0))
                if empstat == 1:  # employed
                    a["employed"] += wt

            # Disability
            disabled = parse_int(row.get("DISABLED", 0))
            if disabled == 1:
                a["disabled"] += wt

            # Religion
            rel = parse_int(row.get("RELIGION", 0))
            rel_map = {1: "buddhist", 2: "hindu", 3: "jewish", 4: "muslim", 5: "christian", 9: "other"}
            a["religion"][rel_map.get(rel, "unknown")] += wt

            # Urban
            urban = parse_int(row.get("URBAN", 0))
            if urban == 2:  # urban
                a["urban_wt"] += wt

            # Marital status (age 15+)
            if age >= 15:
                marst = parse_int(row.get("MARST", 0))
                a["marst_total"] += wt
                if marst == 2:  # married/in union
                    a["married"] += wt

            # Years of schooling
            yrschool = parse_int(row.get("YRSCHOOL", 99))
            if 0 <= yrschool <= 30 and age >= 15:
                a["mean_yrschool"] += yrschool * wt
                a["yrschool_count"] += wt

            # Family size (from first person in HH only, but we approximate with per-person)
            famsize = parse_int(row.get("FAMSIZE", 0))
            if famsize > 0:
                a["mean_famsize"] += famsize * wt
                a["famsize_count"] += wt

    print(f"  Total: {n:,} rows, {len(acc)} district-year cells")

    # 1. Summary indicators by district
    path = os.path.join(OUTPUT_DIR, "ipums_district_demographics.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "year", "geolev1", "geolev2", "population", "male_pct", "female_pct",
            "age_0_14_pct", "age_15_64_pct", "age_65p_pct", "dependency_ratio",
            "literacy_rate", "school_attendance_rate", "employment_rate",
            "disability_pct", "urban_pct", "married_pct",
            "mean_yrschool", "mean_famsize",
            "muslim_pct", "hindu_pct",
        ])
        for (year, geo2), a in sorted(acc.items()):
            p = a["pop_weighted"]
            if p == 0:
                continue
            dep_ratio = (a["age_0_14"] + a["age_65p"]) / a["age_15_64"] * 100 if a["age_15_64"] > 0 else 0
            lit_rate = a["literate"] / a["literate_total"] * 100 if a["literate_total"] > 0 else 0
            school_rate = a["in_school"] / a["school_age"] * 100 if a["school_age"] > 0 else 0
            emp_rate = a["employed"] / a["working_age"] * 100 if a["working_age"] > 0 else 0
            married_pct = a["married"] / a["marst_total"] * 100 if a["marst_total"] > 0 else 0
            avg_yr = a["mean_yrschool"] / a["yrschool_count"] if a["yrschool_count"] > 0 else 0
            avg_fam = a["mean_famsize"] / a["famsize_count"] if a["famsize_count"] > 0 else 0
            muslim = a["religion"].get("muslim", 0) / p * 100
            hindu = a["religion"].get("hindu", 0) / p * 100

            w.writerow([
                year, a["geolev1"], geo2, f"{p:.0f}",
                f"{a['male']/p*100:.1f}", f"{a['female']/p*100:.1f}",
                f"{a['age_0_14']/p*100:.1f}", f"{a['age_15_64']/p*100:.1f}", f"{a['age_65p']/p*100:.1f}",
                f"{dep_ratio:.1f}",
                f"{lit_rate:.1f}", f"{school_rate:.1f}", f"{emp_rate:.1f}",
                f"{a['disabled']/p*100:.2f}", f"{a['urban_wt']/p*100:.1f}",
                f"{married_pct:.1f}", f"{avg_yr:.1f}", f"{avg_fam:.1f}",
                f"{muslim:.1f}", f"{hindu:.1f}",
            ])
    print(f"  Wrote {path}")

    # 2. Age pyramids (5-year bins by district)
    path = os.path.join(OUTPUT_DIR, "ipums_age_pyramids.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "geolev2", "age_bin", "population_weighted"])
        for (year, geo2), a in sorted(acc.items()):
            for bin_label, pop in sorted(a["age_bins"].items(), key=lambda x: int(x[0].split("-")[0]) if "-" in x[0] else 80):
                w.writerow([year, geo2, bin_label, f"{pop:.0f}"])
    print(f"  Wrote {path}")

    # 3. Religion by district
    path = os.path.join(OUTPUT_DIR, "ipums_religion.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "geolev2", "religion", "population_weighted", "pct"])
        for (year, geo2), a in sorted(acc.items()):
            p = a["pop_weighted"]
            if p == 0:
                continue
            for rel, pop in sorted(a["religion"].items()):
                if pop > 0:
                    w.writerow([year, geo2, rel, f"{pop:.0f}", f"{pop/p*100:.2f}"])
    print(f"  Wrote {path}")


if __name__ == "__main__":
    process()

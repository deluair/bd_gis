"""
Build Multi-Dimensional Poverty Index (MPI) from IPUMS International Bangladesh census data.

Input: ipumsi_bd_comprehensive_v3.csv.gz (30.2M rows, 66 cols, censuses 1991/2001/2011)
Output: District-level MPI scores for each census year.

Indicators (10 total, 4 dimensions):
  Housing (4): wall material, roof material, toilet type, electricity
  Education (3): literacy, years of schooling, school attendance
  Employment (2): labor force participation, employment status
  Assets (1): home ownership

Each indicator is binary (deprived=1, not deprived=0).
MPI = weighted average of deprivation indicators per household, aggregated to district.
"""
import csv
import gzip
import os
import sys
from collections import defaultdict

IPUMS_PATH = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-UniversityofTennessee/"
    "bd_data_repository/ipumsi_bd_comprehensive_v3.csv.gz"
)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "poverty")

# IPUMS coded values for deprivation thresholds
# See IPUMS documentation for code meanings

# WALL: deprived if not brick/cement (codes vary, but generally:
#   1xx = no wall/natural, 2xx = rudimentary, 3xx = finished)
# For BD: bamboo, mud, tin, etc. are deprived
WALL_DEPRIVED = {100, 110, 120, 130, 140, 150, 200, 210, 220, 230, 240, 250, 310, 320}

# ROOF: deprived if thatch/bamboo/tin (not concrete/tile)
ROOF_DEPRIVED = {100, 110, 120, 130, 140, 200, 210, 220, 230, 310}

# TOILET: deprived if no facility or unimproved
#   10 = no facility, 11 = no facility, 20-21 = unimproved
TOILET_DEPRIVED = {0, 10, 11, 20, 21}

# ELECTRIC: deprived if no electricity (0 or 1 = no)
ELECTRIC_DEPRIVED = {0, 1}

# LIT: deprived if illiterate (1 = no/illiterate, 2 = yes/literate)
LIT_DEPRIVED = {0, 1, 9}

# EDATTAIN: deprived if less than primary (0 = NIU, 1 = less than primary, 2 = primary)
EDATTAIN_DEPRIVED = {0, 1}

# SCHOOL: deprived if not attending (0 = NIU, 1 = no)
SCHOOL_DEPRIVED = {0, 1}

# EMPSTAT: deprived if inactive/unemployed (looking at household level)
EMPSTAT_DEPRIVED = {0, 2, 3}

# LABFORCE: deprived if not in labor force
LABFORCE_DEPRIVED = {0, 1}

# OWNERSHIP: deprived if not owned
OWNERSHIP_DEPRIVED = {0, 1}


def parse_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def parse_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def compute_household_deprivations(rows):
    """Given all person rows for one household, compute deprivation indicators."""
    if not rows:
        return None

    first = rows[0]
    hhwt = parse_float(first.get("HHWT", 1))
    year = parse_int(first.get("YEAR"))
    geolev1 = first.get("GEOLEV1", "")
    geolev2 = first.get("GEOLEV2", "")
    urban = parse_int(first.get("URBAN", 0))

    # Housing indicators (household level, from first row)
    wall = parse_int(first.get("WALL", 0))
    roof = parse_int(first.get("ROOF", 0))
    toilet = parse_int(first.get("TOILET", 0))
    electric = parse_int(first.get("ELECTRIC", 0))
    ownership = parse_int(first.get("OWNERSHIP", 0))

    wall_dep = 1 if wall in WALL_DEPRIVED else 0
    roof_dep = 1 if roof in ROOF_DEPRIVED else 0
    toilet_dep = 1 if toilet in TOILET_DEPRIVED else 0
    electric_dep = 1 if electric in ELECTRIC_DEPRIVED else 0
    ownership_dep = 1 if ownership in OWNERSHIP_DEPRIVED else 0

    # Education indicators (any adult 15+ literate? any child 6-14 in school?)
    any_literate = 0
    max_edattain = 0
    any_child_in_school = 0
    any_employed = 0
    any_in_labforce = 0

    for r in rows:
        age = parse_int(r.get("AGE", 0))
        if age >= 15:
            lit = parse_int(r.get("LIT", 0))
            if lit not in LIT_DEPRIVED:
                any_literate = 1
            edattain = parse_int(r.get("EDATTAIN", 0))
            max_edattain = max(max_edattain, edattain)
            empstat = parse_int(r.get("EMPSTAT", 0))
            if empstat not in EMPSTAT_DEPRIVED:
                any_employed = 1
            labforce = parse_int(r.get("LABFORCE", 0))
            if labforce not in LABFORCE_DEPRIVED:
                any_in_labforce = 1
        if 6 <= age <= 14:
            school = parse_int(r.get("SCHOOL", 0))
            if school not in SCHOOL_DEPRIVED:
                any_child_in_school = 1

    lit_dep = 0 if any_literate else 1
    educ_dep = 1 if max_edattain in EDATTAIN_DEPRIVED else 0
    school_dep = 0 if any_child_in_school else 1
    employ_dep = 0 if any_employed else 1
    labforce_dep = 0 if any_in_labforce else 1

    # MPI: equal weights across 4 dimensions, equal within dimension
    # Housing (4 indicators, weight 1/4 each within dimension, dimension weight 1/4)
    # Education (3 indicators), Employment (2), Assets (1)
    housing_score = (wall_dep + roof_dep + toilet_dep + electric_dep) / 4.0
    education_score = (lit_dep + educ_dep + school_dep) / 3.0
    employment_score = (employ_dep + labforce_dep) / 2.0
    assets_score = ownership_dep

    mpi = (housing_score + education_score + employment_score + assets_score) / 4.0

    return {
        "year": year,
        "geolev1": geolev1,
        "geolev2": geolev2,
        "urban": urban,
        "hhwt": hhwt,
        "mpi": mpi,
        "housing": housing_score,
        "education": education_score,
        "employment": employment_score,
        "assets": assets_score,
        "n_members": len(rows),
    }


def process_ipums():
    """Stream through IPUMS CSV, compute MPI per household, aggregate to district."""
    if not os.path.exists(IPUMS_PATH):
        print(f"IPUMS file not found: {IPUMS_PATH}")
        sys.exit(1)

    print(f"Reading {IPUMS_PATH}...")

    # Accumulators: {(year, geolev2): {sum_mpi_weighted, sum_weight, count, ...}}
    district_acc = defaultdict(lambda: {
        "sum_mpi": 0.0, "sum_housing": 0.0, "sum_education": 0.0,
        "sum_employment": 0.0, "sum_assets": 0.0,
        "sum_weight": 0.0, "count": 0,
        "geolev1": "", "urban_weight": 0.0, "urban_count": 0,
    })

    current_serial = None
    current_year = None
    current_rows = []
    hh_count = 0

    with gzip.open(IPUMS_PATH, "rt") as f:
        reader = csv.DictReader(f)
        for row in reader:
            serial = row.get("SERIAL", "")
            year = row.get("YEAR", "")
            key = (year, serial)

            if key != (current_year, current_serial):
                # Process previous household
                if current_rows:
                    result = compute_household_deprivations(current_rows)
                    if result and result["geolev2"]:
                        dk = (result["year"], result["geolev2"])
                        acc = district_acc[dk]
                        w = result["hhwt"]
                        acc["sum_mpi"] += result["mpi"] * w
                        acc["sum_housing"] += result["housing"] * w
                        acc["sum_education"] += result["education"] * w
                        acc["sum_employment"] += result["employment"] * w
                        acc["sum_assets"] += result["assets"] * w
                        acc["sum_weight"] += w
                        acc["count"] += 1
                        acc["geolev1"] = result["geolev1"]
                        if result["urban"] == 2:
                            acc["urban_weight"] += w
                            acc["urban_count"] += 1

                    hh_count += 1
                    if hh_count % 500000 == 0:
                        print(f"  Processed {hh_count:,} households...")

                current_serial = serial
                current_year = year
                current_rows = [row]
            else:
                current_rows.append(row)

    # Process last household
    if current_rows:
        result = compute_household_deprivations(current_rows)
        if result and result["geolev2"]:
            dk = (result["year"], result["geolev2"])
            acc = district_acc[dk]
            w = result["hhwt"]
            acc["sum_mpi"] += result["mpi"] * w
            acc["sum_housing"] += result["housing"] * w
            acc["sum_education"] += result["education"] * w
            acc["sum_employment"] += result["employment"] * w
            acc["sum_assets"] += result["assets"] * w
            acc["sum_weight"] += w
            acc["count"] += 1
            acc["geolev1"] = result["geolev1"]
        hh_count += 1

    print(f"  Total households: {hh_count:,}")
    print(f"  District-year cells: {len(district_acc)}")

    # Write output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "ipums_district_mpi.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "year", "geolev1", "geolev2", "households", "total_weight",
            "mpi", "housing_dep", "education_dep", "employment_dep", "assets_dep",
            "urban_pct",
        ])
        for (year, geolev2), acc in sorted(district_acc.items()):
            if acc["sum_weight"] == 0:
                continue
            sw = acc["sum_weight"]
            w.writerow([
                year, acc["geolev1"], geolev2, acc["count"], f"{sw:.1f}",
                f"{acc['sum_mpi'] / sw:.4f}",
                f"{acc['sum_housing'] / sw:.4f}",
                f"{acc['sum_education'] / sw:.4f}",
                f"{acc['sum_employment'] / sw:.4f}",
                f"{acc['sum_assets'] / sw:.4f}",
                f"{acc['urban_weight'] / sw * 100:.1f}" if sw > 0 else "0",
            ])

    print(f"  Wrote {path}")
    return path


if __name__ == "__main__":
    process_ipums()

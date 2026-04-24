"""
Extract DHS wealth index by division from household recode (HR) flat files.

DHS fixed-width .DAT format. Column positions parsed from .DCT dictionary files.
Key variables:
  hv024 = Division (1-8)
  hv025 = Urban/rural (1=urban, 2=rural)
  hv270 = Wealth index quintile (1=poorest, 5=richest)
  hv271 = Wealth index factor score (5 decimals)
  hv005 = Sample weight (6 decimals implied)
  shdist = District code (DHS8 only)
"""
import csv
import os
import zipfile
from collections import defaultdict

DHS_DIR = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-UniversityofTennessee/"
    "bd_data_repository/dhs_downloads"
)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs", "poverty")

# Survey configs: zip filename, column positions (0-indexed start, width)
# Positions derived from .DCT cumulative widths
SURVEYS = {
    "DHS8_2022": {
        "zip": "BDHR81FL.zip",
        "dat": "BDHR81FL.DAT",
        "cols": {
            # Cumulative positions from DCT: hhid(0,12) hv000(12,3) hv001(15,6)
            # hv002(21,6) hv003(27,3) hv004(30,4) hv005(34,8) hv006(42,2) hv007(44,4)
            # ... hv024 is col 29 in DCT order
            # Need to compute exact byte offsets from DCT widths
        },
    },
}

# Division code mapping for DHS Bangladesh
DHS_DIVISION_CODES = {
    1: "Barishal",
    2: "Chattogram",
    3: "Dhaka",
    4: "Khulna",
    5: "Mymensingh",
    6: "Rajshahi",
    7: "Rangpur",
    8: "Sylhet",
    # Older surveys may use different codes
    10: "Barishal",
    20: "Chattogram",
    30: "Dhaka",
    40: "Khulna",
    50: "Rajshahi",
    55: "Rangpur",
    60: "Sylhet",
}


def parse_dct(dct_path):
    """Parse Stata .DCT dictionary to get column positions.
    Handles two formats:
      New: byte hv024 %2f (cumulative widths)
      Old: byte hv024 1: 85-86 (explicit positions)
    """
    columns = []
    pos = 0
    with open(dct_path) as f:
        for line in f:
            line = line.strip()
            parts = line.split()
            if len(parts) < 3:
                continue

            # New format: type name %Nf
            if parts[2].startswith("%"):
                dtype = parts[0]
                name = parts[1]
                fmt = parts[2]
                width = int("".join(c for c in fmt if c.isdigit()))
                columns.append({"name": name, "start": pos, "width": width, "type": dtype})
                pos += width

            # Old format: type name 1: start-end
            elif len(parts) >= 4 and ":" in parts[2] and "-" in parts[3]:
                dtype = parts[0]
                name = parts[1]
                # Parse "1:" prefix and "start-end"
                range_str = parts[3]
                start_end = range_str.split("-")
                if len(start_end) == 2:
                    start = int(start_end[0]) - 1  # Convert to 0-indexed
                    end = int(start_end[1])
                    width = end - start
                    columns.append({"name": name, "start": start, "width": width, "type": dtype})

    return {c["name"]: c for c in columns}


def extract_wealth_from_dat(dat_path, col_map):
    """Read fixed-width DAT file and extract wealth index data."""
    results = []

    hv005 = col_map.get("hv005")
    hv024 = col_map.get("hv024")
    hv025 = col_map.get("hv025")
    hv270 = col_map.get("hv270")
    hv271 = col_map.get("hv271")

    if not all([hv005, hv024, hv025, hv270]):
        print("  Missing required columns in DCT")
        return results

    with open(dat_path, "r", encoding="latin-1") as f:
        for line in f:
            try:
                weight = int(line[hv005["start"]:hv005["start"] + hv005["width"]].strip() or "0")
                division = int(line[hv024["start"]:hv024["start"] + hv024["width"]].strip() or "0")
                urban = int(line[hv025["start"]:hv025["start"] + hv025["width"]].strip() or "0")
                quintile = int(line[hv270["start"]:hv270["start"] + hv270["width"]].strip() or "0")
                score = 0
                if hv271:
                    score_raw = line[hv271["start"]:hv271["start"] + hv271["width"]].strip()
                    score = int(score_raw or "0") / 100000.0  # 5 implied decimals

                if division > 0 and quintile > 0:
                    results.append({
                        "division_code": division,
                        "urban": urban,
                        "quintile": quintile,
                        "score": score,
                        "weight": weight / 1000000.0,  # 6 implied decimals
                    })
            except (ValueError, IndexError):
                continue

    return results


def aggregate_by_division(records):
    """Aggregate wealth quintile distribution by division."""
    div_data = defaultdict(lambda: {
        "total_weight": 0, "quintile_weights": defaultdict(float),
        "score_sum": 0, "count": 0,
    })

    for r in records:
        div_name = DHS_DIVISION_CODES.get(r["division_code"], f"code_{r['division_code']}")
        w = r["weight"] if r["weight"] > 0 else 1.0
        div_data[div_name]["total_weight"] += w
        div_data[div_name]["quintile_weights"][r["quintile"]] += w
        div_data[div_name]["score_sum"] += r["score"] * w
        div_data[div_name]["count"] += 1

    results = []
    for div_name, d in sorted(div_data.items()):
        tw = d["total_weight"]
        if tw == 0:
            continue
        row = {
            "division": div_name,
            "households": d["count"],
            "mean_wealth_score": d["score_sum"] / tw,
        }
        for q in range(1, 6):
            row[f"quintile_{q}_pct"] = d["quintile_weights"][q] / tw * 100
        results.append(row)
    return results


def process_survey(zip_name, label):
    """Process a single DHS survey zip file."""
    zip_path = os.path.join(DHS_DIR, zip_name)
    if not os.path.exists(zip_path):
        print(f"  {zip_name} not found, skipping")
        return None

    # Find FL zip (flat file)
    prefix = zip_name.replace(".zip", "")

    # Extract to temp
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmpdir)

        # Find .DAT and .DCT files
        dat_file = None
        dct_file = None
        for root, dirs, files in os.walk(tmpdir):
            for fn in files:
                if fn.upper().endswith(".DAT"):
                    dat_file = os.path.join(root, fn)
                if fn.upper().endswith(".DCT"):
                    dct_file = os.path.join(root, fn)

        if not dat_file or not dct_file:
            print(f"  No .DAT or .DCT found in {zip_name}")
            return None

        print(f"  Parsing {os.path.basename(dct_file)}...")
        col_map = parse_dct(dct_file)

        print(f"  Reading {os.path.basename(dat_file)}...")
        records = extract_wealth_from_dat(dat_file, col_map)
        print(f"  {len(records):,} households with wealth data")

        if not records:
            return None

        return aggregate_by_division(records)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Process recent surveys with wealth index
    surveys = [
        ("BDHR81FL.zip", "DHS8_2022"),
        ("BDHR7RFL.zip", "DHS7R_2017"),
        ("BDHR72FL.zip", "DHS7_2014"),
        ("BDHR61FL.zip", "DHS6_2011"),
        ("BDHR51FL.zip", "DHS5_2007"),
    ]

    all_results = []
    for zip_name, label in surveys:
        print(f"\n=== {label} ({zip_name}) ===")
        results = process_survey(zip_name, label)
        if results:
            for r in results:
                r["survey"] = label
            all_results.extend(results)

            # Print summary
            print(f"\n  {'Division':<14} {'HHs':>6} {'Q1(poor)':>9} {'Q2':>6} {'Q3':>6} {'Q4':>6} {'Q5(rich)':>9}")
            for r in results:
                print(f"  {r['division']:<14} {r['households']:>6} "
                      f"{r['quintile_1_pct']:>8.1f}% {r['quintile_2_pct']:>5.1f}% "
                      f"{r['quintile_3_pct']:>5.1f}% {r['quintile_4_pct']:>5.1f}% "
                      f"{r['quintile_5_pct']:>8.1f}%")

    # Write combined output
    if all_results:
        path = os.path.join(OUTPUT_DIR, "dhs_wealth_by_division.csv")
        fieldnames = ["survey", "division", "households", "mean_wealth_score",
                       "quintile_1_pct", "quintile_2_pct", "quintile_3_pct",
                       "quintile_4_pct", "quintile_5_pct"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in all_results:
                w.writerow({k: r.get(k, "") for k in fieldnames})
        print(f"\nWrote {path}")


if __name__ == "__main__":
    main()

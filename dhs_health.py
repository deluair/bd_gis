"""
Extract DHS child health, nutrition, and women's indicators by division.
Datasets: KR (kids recode), IR (individual/women), PR (person recode).

Key indicators:
  KR: stunting, wasting, underweight, vaccination, diarrhea, ARI
  IR: contraception, antenatal care, delivery, fertility, empowerment
  PR: education, employment by sex
"""
import csv
import os
import zipfile
import tempfile
from collections import defaultdict

DHS_DIR = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-UniversityofTennessee/"
    "bd_data_repository/dhs_downloads"
)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")

DHS_DIVISION_CODES = {
    1: "Barishal", 2: "Chattogram", 3: "Dhaka", 4: "Khulna",
    5: "Mymensingh", 6: "Rajshahi", 7: "Rangpur", 8: "Sylhet",
    10: "Barishal", 20: "Chattogram", 30: "Dhaka", 40: "Khulna",
    50: "Rajshahi", 55: "Rangpur", 60: "Sylhet",
}


def parse_dct(dct_path):
    """Parse Stata .DCT dictionary to get column positions."""
    columns = []
    pos = 0
    with open(dct_path) as f:
        for line in f:
            line = line.strip()
            parts = line.split()
            if len(parts) < 3:
                continue
            if parts[2].startswith("%"):
                name = parts[1]
                width = int("".join(c for c in parts[2] if c.isdigit()))
                columns.append({"name": name, "start": pos, "width": width})
                pos += width
            elif len(parts) >= 4 and ":" in parts[2] and "-" in parts[3]:
                name = parts[1]
                se = parts[3].split("-")
                if len(se) == 2:
                    start = int(se[0]) - 1
                    end = int(se[1])
                    columns.append({"name": name, "start": start, "width": end - start})
    return {c["name"]: c for c in columns}


def read_field(line, col_map, field, default=""):
    c = col_map.get(field)
    if not c:
        return default
    return line[c["start"]:c["start"] + c["width"]].strip() or default


def read_int(line, col_map, field, default=0):
    v = read_field(line, col_map, field)
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def extract_from_zip(zip_name):
    """Extract DAT and DCT from a DHS zip file, return (dat_path, col_map, tmpdir)."""
    zip_path = os.path.join(DHS_DIR, zip_name)
    if not os.path.exists(zip_path):
        return None, None, None

    tmpdir = tempfile.mkdtemp()
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmpdir)

    dat_file = dct_file = None
    for root, dirs, files in os.walk(tmpdir):
        for fn in files:
            if fn.upper().endswith(".DAT"):
                dat_file = os.path.join(root, fn)
            if fn.upper().endswith(".DCT"):
                dct_file = os.path.join(root, fn)

    if not dat_file or not dct_file:
        return None, None, tmpdir

    col_map = parse_dct(dct_file)
    return dat_file, col_map, tmpdir


def process_kids_recode(zip_name, label):
    """Extract child health indicators from KR dataset.
    Key vars: hw70 (height-for-age z), hw71 (weight-for-height z), hw72 (weight-for-age z),
    h11 (diarrhea), h22 (ARI/fever), h2-h9 (vaccinations), v024 (division), v005 (weight)."""
    print(f"\n=== {label}: Kids Recode ({zip_name}) ===")
    dat_path, col_map, tmpdir = extract_from_zip(zip_name)
    if not dat_path:
        print(f"  Not found or no DAT/DCT")
        return None

    # Check available fields
    has_hw70 = "hw70" in col_map
    has_v024 = "v024" in col_map
    has_h11 = "h11" in col_map
    print(f"  Fields: hw70={has_hw70}, v024={has_v024}, h11={has_h11}")
    print(f"  Available: {len(col_map)} columns")

    div_data = defaultdict(lambda: {
        "count": 0, "weight": 0,
        "stunted": 0, "wasted": 0, "underweight": 0,
        "stunted_severe": 0, "wasted_severe": 0, "underweight_severe": 0,
        "diarrhea": 0, "diarrhea_total": 0,
        "fever": 0, "fever_total": 0,
        "bcg": 0, "measles": 0, "vacc_total": 0,
    })

    with open(dat_path, "r", encoding="latin-1") as f:
        for line in f:
            div = read_int(line, col_map, "v024")
            wt = read_int(line, col_map, "v005", 1000000) / 1000000.0
            div_name = DHS_DIVISION_CODES.get(div, f"code_{div}")

            d = div_data[div_name]
            d["count"] += 1
            d["weight"] += wt

            # Anthropometry (z-scores, 2 implied decimals in DHS)
            # Stunted: HAZ < -200, severe: < -300
            if has_hw70:
                haz = read_int(line, col_map, "hw70", 9999)
                if -600 <= haz <= 600:
                    if haz < -200:
                        d["stunted"] += wt
                    if haz < -300:
                        d["stunted_severe"] += wt

            hw71 = read_int(line, col_map, "hw71", 9999) if "hw71" in col_map else 9999
            if -500 <= hw71 <= 500:
                if hw71 < -200:
                    d["wasted"] += wt
                if hw71 < -300:
                    d["wasted_severe"] += wt

            hw72 = read_int(line, col_map, "hw72", 9999) if "hw72" in col_map else 9999
            if -600 <= hw72 <= 600:
                if hw72 < -200:
                    d["underweight"] += wt
                if hw72 < -300:
                    d["underweight_severe"] += wt

            # Diarrhea in last 2 weeks
            if has_h11:
                h11 = read_int(line, col_map, "h11", 9)
                if h11 in (0, 1, 2):
                    d["diarrhea_total"] += wt
                    if h11 in (1, 2):
                        d["diarrhea"] += wt

            # Fever in last 2 weeks
            if "h22" in col_map:
                h22 = read_int(line, col_map, "h22", 9)
                if h22 in (0, 1):
                    d["fever_total"] += wt
                    if h22 == 1:
                        d["fever"] += wt

            # BCG vaccination
            if "h2" in col_map:
                h2 = read_int(line, col_map, "h2", 9)
                if h2 in (0, 1, 2, 3):
                    d["vacc_total"] += wt
                    if h2 in (1, 2, 3):
                        d["bcg"] += wt

            # Measles
            if "h9" in col_map:
                h9 = read_int(line, col_map, "h9", 9)
                if h9 in (1, 2, 3):
                    d["measles"] += wt

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    results = []
    for div_name, d in sorted(div_data.items()):
        if d["weight"] == 0:
            continue
        w = d["weight"]
        results.append({
            "survey": label, "division": div_name, "children": d["count"],
            "stunted_pct": d["stunted"] / w * 100 if w else 0,
            "wasted_pct": d["wasted"] / w * 100 if w else 0,
            "underweight_pct": d["underweight"] / w * 100 if w else 0,
            "diarrhea_pct": d["diarrhea"] / d["diarrhea_total"] * 100 if d["diarrhea_total"] else 0,
            "fever_pct": d["fever"] / d["fever_total"] * 100 if d["fever_total"] else 0,
            "bcg_pct": d["bcg"] / d["vacc_total"] * 100 if d["vacc_total"] else 0,
        })

    print(f"  {sum(d['count'] for d in div_data.values()):,} children")
    for r in results:
        print(f"  {r['division']:<14} stunted={r['stunted_pct']:.1f}% wasted={r['wasted_pct']:.1f}% underweight={r['underweight_pct']:.1f}%")

    return results


def process_women_recode(zip_name, label):
    """Extract women's health indicators from IR dataset.
    Key vars: v024 (division), v005 (weight), v313 (current contraception),
    m14 (antenatal visits), m15 (delivery place), v201 (children ever born)."""
    print(f"\n=== {label}: Women's Recode ({zip_name}) ===")
    dat_path, col_map, tmpdir = extract_from_zip(zip_name)
    if not dat_path:
        print(f"  Not found or no DAT/DCT")
        return None

    print(f"  Available: {len(col_map)} columns")

    div_data = defaultdict(lambda: {
        "count": 0, "weight": 0,
        "using_contraception": 0, "modern_method": 0,
        "anc_4plus": 0, "anc_total": 0,
        "facility_delivery": 0, "delivery_total": 0,
        "total_children": 0,
    })

    with open(dat_path, "r", encoding="latin-1") as f:
        for line in f:
            div = read_int(line, col_map, "v024")
            wt = read_int(line, col_map, "v005", 1000000) / 1000000.0
            div_name = DHS_DIVISION_CODES.get(div, f"code_{div}")

            d = div_data[div_name]
            d["count"] += 1
            d["weight"] += wt

            # Current contraception use
            if "v313" in col_map:
                v313 = read_int(line, col_map, "v313", 9)
                if v313 > 0 and v313 < 9:
                    d["using_contraception"] += wt
                if v313 == 3:  # modern method
                    d["modern_method"] += wt

            # Antenatal care (4+ visits)
            if "m14" in col_map:
                m14 = read_int(line, col_map, "m14", 99)
                if m14 < 98:
                    d["anc_total"] += wt
                    if m14 >= 4:
                        d["anc_4plus"] += wt

            # Delivery place (facility vs home)
            if "m15" in col_map:
                m15 = read_int(line, col_map, "m15", 99)
                if m15 < 98:
                    d["delivery_total"] += wt
                    if 20 <= m15 <= 49:  # facility codes
                        d["facility_delivery"] += wt

            # Children ever born
            if "v201" in col_map:
                v201 = read_int(line, col_map, "v201", 0)
                d["total_children"] += v201 * wt

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    results = []
    for div_name, d in sorted(div_data.items()):
        if d["weight"] == 0:
            continue
        w = d["weight"]
        results.append({
            "survey": label, "division": div_name, "women": d["count"],
            "contraception_pct": d["using_contraception"] / w * 100,
            "modern_method_pct": d["modern_method"] / w * 100,
            "anc_4plus_pct": d["anc_4plus"] / d["anc_total"] * 100 if d["anc_total"] else 0,
            "facility_delivery_pct": d["facility_delivery"] / d["delivery_total"] * 100 if d["delivery_total"] else 0,
            "mean_children": d["total_children"] / w,
        })

    print(f"  {sum(d['count'] for d in div_data.values()):,} women")
    for r in results:
        print(f"  {r['division']:<14} contraception={r['contraception_pct']:.1f}% facility_delivery={r['facility_delivery_pct']:.1f}% mean_children={r['mean_children']:.1f}")

    return results


def main():
    # Kids recode surveys
    kr_surveys = [
        ("BDKR81FL.zip", "DHS8_2022"),
        ("BDKR7RFL.zip", "DHS7R_2017"),
        ("BDKR72FL.zip", "DHS7_2014"),
        ("BDKR61FL.zip", "DHS6_2011"),
        ("BDKR51FL.zip", "DHS5_2007"),
    ]

    all_kr = []
    for zip_name, label in kr_surveys:
        results = process_kids_recode(zip_name, label)
        if results:
            all_kr.extend(results)

    if all_kr:
        outdir = os.path.join(OUTPUT_DIR, "health")
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, "dhs_child_nutrition.csv")
        fields = ["survey", "division", "children", "stunted_pct", "wasted_pct",
                   "underweight_pct", "diarrhea_pct", "fever_pct", "bcg_pct"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in all_kr:
                w.writerow({k: f"{v:.1f}" if isinstance(v, float) else v for k, v in r.items() if k in fields})
        print(f"\nWrote {path}")

    # Women's recode surveys
    ir_surveys = [
        ("BDIR81FL.zip", "DHS8_2022"),
        ("BDIR7RFL.zip", "DHS7R_2017"),
        ("BDIR72FL.zip", "DHS7_2014"),
        ("BDIR61FL.zip", "DHS6_2011"),
        ("BDIR51FL.zip", "DHS5_2007"),
    ]

    # Check which IR files exist
    existing_ir = []
    for zip_name, label in ir_surveys:
        p = os.path.join(DHS_DIR, zip_name)
        if os.path.exists(p):
            existing_ir.append((zip_name, label))

    # Also try DT format
    if not existing_ir:
        ir_surveys_dt = [
            ("BDIR81DT.zip", "DHS8_2022"),
            ("BDIR7RDT.zip", "DHS7R_2017"),
            ("BDIR72DT.zip", "DHS7_2014"),
        ]
        for zip_name, label in ir_surveys_dt:
            p = os.path.join(DHS_DIR, zip_name)
            if os.path.exists(p):
                existing_ir.append((zip_name, label))

    all_ir = []
    for zip_name, label in existing_ir:
        results = process_women_recode(zip_name, label)
        if results:
            all_ir.extend(results)

    if all_ir:
        outdir = os.path.join(OUTPUT_DIR, "health")
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, "dhs_women_health.csv")
        fields = ["survey", "division", "women", "contraception_pct", "modern_method_pct",
                   "anc_4plus_pct", "facility_delivery_pct", "mean_children"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in all_ir:
                w.writerow({k: f"{v:.1f}" if isinstance(v, float) else v for k, v in r.items() if k in fields})
        print(f"\nWrote {path}")


if __name__ == "__main__":
    main()

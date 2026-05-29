"""Ground-truth reference loaders. Each returns {spatial_unit_name: value}."""
import csv as _csv

from hies_ground_truth import HIES_HCR_BY_DIVISION


def load_hies_division_hcr(year=2022, line="upl"):
    """Division -> headcount poverty rate (percent), HIES 2022 (BBS)."""
    out = {}
    for division, by_year in HIES_HCR_BY_DIVISION.items():
        rec = by_year.get(year)
        if rec and line in rec:
            out[division] = float(rec[line])
    return out


def load_csv_reference(path, unit_col, value_col):
    """Generic CSV -> {unit: value}."""
    out = {}
    with open(path) as f:
        for row in _csv.DictReader(f):
            out[row[unit_col]] = float(row[value_col])
    return out


# loader name -> callable, looked up by registry.INDICATORS[...]["reference"]
LOADERS = {
    "hies_division_hcr": load_hies_division_hcr,
}

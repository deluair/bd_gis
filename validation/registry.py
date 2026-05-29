"""Quality-tier thresholds and the per-indicator validation registry."""

TIER_THRESHOLDS = {
    "continuous": {"A": 0.8, "B": 0.5},   # pearson r
    "categorical": {"A": 0.85, "B": 0.7},  # overall accuracy
}


def assign_tier(comparison, score):
    """A (validated), B (calibrated), C (weak/uncalibrated)."""
    if comparison not in TIER_THRESHOLDS:
        raise ValueError(f"unknown comparison: {comparison}")
    t = TIER_THRESHOLDS[comparison]
    if score >= t["A"]:
        return "A"
    if score >= t["B"]:
        return "B"
    return "C"


# indicator_id -> validation config. Only indicators whose reference loader is
# implemented in reference.LOADERS may appear here (enforced by test_coverage).
INDICATORS = {
    "gis_poverty_index": {
        "label": "Satellite poverty proxy",
        "classification": "proxy",
        "comparison": "continuous",
        "spatial_unit": "division",
        "reference": "hies_division_hcr",
        "reference_source": "HIES 2022 (BBS)",
        "reference_citation": "BBS, Household Income and Expenditure Survey 2022, Final Report, December 2023",
    },
}

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
    "gis_optical_flood_monsoon_water_division": {
        "label": "Optical (Landsat) monsoon water extent (division)",
        "classification": "measured",
        "comparison": "continuous",
        "spatial_unit": "division",
        "reference": "jrc_division_water",
        "reference_source": "JRC Global Surface Water v1.4 Monthly History",
        "reference_citation": "Pekel et al. 2016, doi:10.1038/nature20584",
        "static_caveats": [
            "JRC is Landsat-derived, so this optical comparison shares sensor lineage; the high agreement is partly circular and is NOT a fully independent validation.",
        ],
    },
    "gis_sar_flood_monsoon_water_division": {
        "label": "Sentinel-1 SAR monsoon water extent (division)",
        "classification": "measured",
        "comparison": "continuous",
        "spatial_unit": "division",
        "reference": "jrc_division_water",
        "reference_source": "JRC Global Surface Water v1.4 Monthly History",
        "reference_citation": "Pekel et al. 2016, doi:10.1038/nature20584",
        "static_caveats": [
            "JRC is Landsat-derived; SAR is an independent sensor, so this is a genuine cross-sensor comparison. The negative bias reflects the conservative -17 dB threshold, not necessarily lower accuracy.",
        ],
    },
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

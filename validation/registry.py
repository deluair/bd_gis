"""Quality-tier thresholds and the per-indicator validation registry."""

# GAUL 2015 spells two divisions differently from BBS. Reuse the single mapping
# already maintained in calibrate_poverty rather than keeping a second copy.
from calibrate_poverty import GEE_TO_HIES

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
        "key_aliases": GEE_TO_HIES,
        "static_caveats": [
            "Geography mismatch: the satellite side uses FAO GAUL 2015 level-1 boundaries, which predate the 2015 creation of Mymensingh and therefore carry 7 divisions, while HIES 2022 reports 8. Mymensingh has no satellite counterpart, and GAUL 'Dhaka' still contains the area BBS reports separately as Mymensingh, so the Dhaka pair mixes two BBS reporting units.",
            "Unit mismatch: the predicted value is a unitless 0-1 composite index and the reference is a headcount percentage. bias, mae and rmse are differences between incommensurate units and are NOT interpretable; only pearson_r, which is invariant to affine rescaling, should be read from this card.",
        ],
    },
}

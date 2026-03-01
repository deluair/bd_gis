"""
Water body gain/loss detection – water occurrence frequency mapping,
permanent/seasonal/rare classification, and decade-wise change detection.
"""
import ee
import config as cfg
from data_acquisition import (
    get_study_area, get_landsat_collection, make_composite, get_jrc_water
)
from water_classification import classify_water, compute_water_area


# ═══════════════════════════════════════════════════════════════════════════════
# Water Occurrence Frequency
# ═══════════════════════════════════════════════════════════════════════════════

def compute_water_occurrence(start_year, end_year, region=None, scale=30):
    """
    Compute water occurrence frequency: fraction of annual observations
    where each pixel is classified as water (using dry-season composites
    to capture persistent/permanent water).
    Returns image with values 0–1.
    """
    if region is None:
        region = get_study_area()

    water_sum = ee.Image.constant(0).toFloat()
    obs_count = ee.Image.constant(0).toFloat()
    valid_years = 0

    for year in range(start_year, end_year + 1):
        try:
            start = f"{year}-01-01"
            end = f"{year}-12-31"
            col = get_landsat_collection(start, end, region)
            # Check collection size to skip empty years
            size = col.size().getInfo()
            if size == 0:
                continue
            composite = make_composite(col)
            # Use fixed thresholds to avoid Otsu failures on sparse data
            water = classify_water(composite, region=region, method="fixed")
            water_sum = water_sum.add(water)
            obs_count = obs_count.add(ee.Image.constant(1))
            valid_years += 1
        except Exception:
            pass

    if valid_years == 0:
        # Return zeros if no valid years found
        return ee.Image.constant(0).toFloat().rename("water_occurrence").clip(region)

    occurrence = water_sum.divide(obs_count).rename("water_occurrence")
    return occurrence.clip(region)


def classify_water_persistence(occurrence_image):
    """
    Classify water occurrence into persistence categories:
    - 3: Permanent water (>75%)
    - 2: Seasonal water (25–75%)
    - 1: Rare/ephemeral water (<25%)
    - 0: Non-water (0%)
    """
    permanent = occurrence_image.gte(cfg.PERMANENT_WATER_MIN)
    seasonal = occurrence_image.gte(cfg.SEASONAL_WATER_MIN).And(
        occurrence_image.lt(cfg.PERMANENT_WATER_MIN)
    )
    rare = occurrence_image.gt(0).And(
        occurrence_image.lt(cfg.SEASONAL_WATER_MIN)
    )

    classified = (
        ee.Image.constant(0)
        .where(rare, 1)
        .where(seasonal, 2)
        .where(permanent, 3)
        .rename("water_persistence")
    )
    return classified


# ═══════════════════════════════════════════════════════════════════════════════
# Decade-Wise Change Detection
# ═══════════════════════════════════════════════════════════════════════════════

def get_decade_ranges():
    """Return list of (start_year, end_year, label) tuples for each decade."""
    return [
        (1985, 1994, "1985-1994"),
        (1995, 2004, "1995-2004"),
        (2005, 2014, "2005-2014"),
        (2015, 2025, "2015-2025"),
    ]


def compute_decade_water_occurrence(region=None):
    """
    Compute water occurrence for each decade.
    Returns dict {label: occurrence_image}.
    """
    if region is None:
        region = get_study_area()

    decades = get_decade_ranges()
    results = {}
    for start, end, label in decades:
        print(f"  Computing water occurrence for {label}...")
        results[label] = compute_water_occurrence(start, end, region)
    return results


def compute_change_map(occ_early, occ_late):
    """
    Compute change between two occurrence maps.
    Returns image with values:
      Positive = water gain (more frequent water in later period)
      Negative = water loss (less frequent water)
    """
    return occ_late.subtract(occ_early).rename("water_change")


def classify_change(change_image, threshold=0.25):
    """
    Classify change into categories:
    - 2: Significant water gain (> +threshold)
    - 1: Moderate water gain
    - 0: Stable
    - -1: Moderate water loss
    - -2: Significant water loss (< -threshold)
    """
    classified = (
        ee.Image.constant(0)
        .where(change_image.gt(threshold), 2)
        .where(change_image.gt(0).And(change_image.lte(threshold)), 1)
        .where(change_image.lt(0).And(change_image.gte(-threshold)), -1)
        .where(change_image.lt(-threshold), -2)
        .rename("change_class")
    )
    return classified


def compute_all_decade_changes(region=None):
    """
    Compute change maps between consecutive decades.
    Returns list of dicts with period info and change maps.
    """
    decade_occ = compute_decade_water_occurrence(region)
    labels = list(decade_occ.keys())

    changes = []
    for i in range(len(labels) - 1):
        early_label = labels[i]
        late_label = labels[i + 1]
        change = compute_change_map(decade_occ[early_label], decade_occ[late_label])
        change_class = classify_change(change)
        changes.append({
            "period": f"{early_label} → {late_label}",
            "early_label": early_label,
            "late_label": late_label,
            "change": change,
            "change_class": change_class,
            "early_occ": decade_occ[early_label],
            "late_occ": decade_occ[late_label],
        })

    return {"decade_occurrences": decade_occ, "changes": changes}


# ═══════════════════════════════════════════════════════════════════════════════
# Water-to-Land Conversion Detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_water_to_land(occ_early, occ_late, threshold=0.5):
    """
    Detect pixels that were frequently water (>threshold) in early period
    but rarely/never water in late period – indicates conversion to
    agriculture or settlements.
    """
    was_water = occ_early.gte(threshold)
    now_land = occ_late.lt(0.1)
    converted = was_water.And(now_land).rename("water_to_land")
    return converted


def detect_land_to_water(occ_early, occ_late, threshold=0.5):
    """
    Detect pixels that were rarely water in early period but frequently
    water in late period – indicates new water bodies or flooding increase.
    """
    was_land = occ_early.lt(0.1)
    now_water = occ_late.gte(threshold)
    converted = was_land.And(now_water).rename("land_to_water")
    return converted


# ═══════════════════════════════════════════════════════════════════════════════
# JRC Validation
# ═══════════════════════════════════════════════════════════════════════════════

def get_jrc_occurrence(region=None):
    """
    Get JRC Global Surface Water occurrence (0-100%) for validation.
    """
    if region is None:
        region = get_study_area()
    jrc = get_jrc_water()
    return jrc.select("occurrence").clip(region)


def validate_against_jrc(our_occurrence, region=None, scale=300):
    """
    Compare our water occurrence with JRC reference.
    Uses coarser scale (300m) to avoid memory limits on large regions.
    Returns correlation statistics.
    """
    if region is None:
        region = get_study_area()

    jrc_occ = get_jrc_occurrence(region).divide(100).rename("jrc_occurrence")
    combined = our_occurrence.addBands(jrc_occ)

    correlation = combined.reduceRegion(
        reducer=ee.Reducer.pearsonsCorrelation(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return correlation


def compute_area_stats(persistence_image, region, scale=30):
    """
    Compute area (km²) for each water persistence category.
    """
    stats = {}
    for class_val, label in [(3, "permanent"), (2, "seasonal"), (1, "rare")]:
        mask = persistence_image.eq(class_val)
        area = mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=region,
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        stats[label] = ee.Number(area.get("water_persistence")).divide(1e6)
    return stats

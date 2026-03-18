"""
Flood extent mapping – monsoon vs dry season classification,
seasonal inundation, extreme flood analysis, and district-level statistics.
"""
import ee
import config as cfg
from data_acquisition import (
    get_study_area, get_seasonal_composite, get_admin_boundaries
)
from water_classification import classify_water, compute_water_area


def _scale_for_scope():
    """Choose reduceRegion scale based on configured scope.

    National-scale needs coarser scale (300) to avoid GEE computation limits.
    Division-scale (e.g. sylhet) uses 100. District-scale uses 30.
    """
    if cfg.SCOPE == "national":
        return 300
    if cfg.SCOPE.startswith("district:"):
        return 30
    return 100


# ═══════════════════════════════════════════════════════════════════════════════
# Annual Seasonal Water Mapping
# ═══════════════════════════════════════════════════════════════════════════════

def get_annual_water_extents(year, region=None, sensor="landsat"):
    """
    Classify water extent for dry and monsoon seasons in a given year.
    Returns dict with water masks and area stats.
    Falls back to fixed thresholds if Otsu fails (e.g. small ROI or sparse data).
    """
    if region is None:
        region = get_study_area()

    # Dry season composite & water classification
    # Use config default method (fixed for national, otsu for smaller regions)
    method = cfg.DEFAULT_THRESHOLD_METHOD
    dry_composite = get_seasonal_composite(year, "dry", sensor, region)
    try:
        dry_water = classify_water(dry_composite, region=region, method=method)
    except Exception:
        dry_water = classify_water(dry_composite, region=region, method="fixed")

    # Monsoon composite & water classification
    monsoon_composite = get_seasonal_composite(year, "monsoon", sensor, region)
    try:
        monsoon_water = classify_water(monsoon_composite, region=region, method=method)
    except Exception:
        monsoon_water = classify_water(monsoon_composite, region=region, method="fixed")

    # Seasonal inundation = monsoon water minus permanent (dry) water
    # Rename to "water" so compute_water_area can find the band
    seasonal_flood = monsoon_water.And(dry_water.Not()).rename("water")

    # Area calculations (scope-aware scale to avoid undercount at national extent)
    scale = _scale_for_scope()
    dry_area = compute_water_area(dry_water, region, scale=scale)
    monsoon_area = compute_water_area(monsoon_water, region, scale=scale)
    seasonal_area = compute_water_area(seasonal_flood, region, scale=scale)

    # Sanity check: monsoon extent must be >= dry extent. If not, flag it.
    # This can happen when composites are mislabeled or have poor data coverage.
    sanity_clamped = False
    if monsoon_area.getInfo() < dry_area.getInfo():
        sanity_clamped = True
        print(f"  WARNING: monsoon < dry for {year}, clamping")
        monsoon_area = dry_area
    seasonal_area = monsoon_area.subtract(dry_area)

    return {
        "year": year,
        "dry_water": dry_water,
        "monsoon_water": monsoon_water,
        "seasonal_flood": seasonal_flood,
        "dry_composite": dry_composite,
        "monsoon_composite": monsoon_composite,
        "dry_area_km2": dry_area,
        "monsoon_area_km2": monsoon_area,
        "seasonal_area_km2": seasonal_area,
        "sanity_clamped": sanity_clamped,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-Year Flood Time Series
# ═══════════════════════════════════════════════════════════════════════════════

def build_flood_time_series(start_year, end_year, region=None, step=1):
    """
    Build a time series of seasonal flood extents.
    Returns list of {year, dry_area_km2, monsoon_area_km2, seasonal_area_km2}.
    step: year interval (1=every year, 2=biennial, 4=every 4 years).
    """
    if region is None:
        region = get_study_area()

    results = []
    for year in range(start_year, end_year + 1, step):
        try:
            extents = get_annual_water_extents(year, region)
            results.append({
                "year": year,
                "dry_area_km2": extents["dry_area_km2"],
                "monsoon_area_km2": extents["monsoon_area_km2"],
                "seasonal_area_km2": extents["seasonal_area_km2"],
            })
        except Exception as e:
            print(f"  Skipping {year}: {e}")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Extreme Flood Year Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_extreme_flood(year, region=None):
    """
    Detailed analysis for extreme flood years.
    Compares peak monsoon extent to long-term average.
    """
    if region is None:
        region = get_study_area()

    # Target year monsoon
    extents = get_annual_water_extents(year, region)

    # Reference average around the event, excluding all known extreme flood years
    ref_years = [
        y for y in range(year - 5, year + 6)
        if y not in cfg.EXTREME_FLOOD_YEARS
    ]
    ref_monsoon_areas = []
    for y in ref_years:
        try:
            ref = get_annual_water_extents(y, region)
            ref_monsoon_areas.append(ref["monsoon_area_km2"])
        except Exception:
            pass

    if ref_monsoon_areas:
        avg_ref = ee.Number(0)
        for a in ref_monsoon_areas:
            avg_ref = avg_ref.add(a)
        avg_ref = avg_ref.divide(len(ref_monsoon_areas))
    else:
        avg_ref = ee.Number(0)

    return {
        "year": year,
        "monsoon_area_km2": extents["monsoon_area_km2"],
        "reference_avg_km2": avg_ref,
        "anomaly_km2": extents["monsoon_area_km2"].subtract(avg_ref),
        "monsoon_water": extents["monsoon_water"],
        "dry_water": extents["dry_water"],
        "seasonal_flood": extents["seasonal_flood"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# District-Level Statistics
# ═══════════════════════════════════════════════════════════════════════════════

def compute_district_flood_stats(water_mask, districts_fc):
    """
    Compute water area per district for a given water mask.
    Returns ee.FeatureCollection with area stats.
    """
    scale = _scale_for_scope()

    def _compute_per_district(feature):
        geom = feature.geometry()
        area_km2 = compute_water_area(water_mask, geom, scale=scale)
        total_area = geom.area().divide(1e6)  # district area in km²
        return feature.set({
            "water_area_km2": area_km2,
            "total_area_km2": total_area,
            "water_pct": area_km2.divide(total_area).multiply(100),
        })

    return districts_fc.map(_compute_per_district)


def build_district_time_series(start_year, end_year, districts_fc=None):
    """
    Build time series of flood stats per district.
    Returns list of dicts with year and per-district stats.
    """
    if districts_fc is None:
        admin = get_admin_boundaries()
        districts_fc = admin.filter(
            ee.Filter.inList("ADM2_NAME", cfg.DISTRICTS)
        )

    results = []
    for year in range(start_year, end_year + 1):
        try:
            extents = get_annual_water_extents(year)
            monsoon_stats = compute_district_flood_stats(
                extents["monsoon_water"], districts_fc
            )
            results.append({
                "year": year,
                "district_stats": monsoon_stats,
            })
        except Exception as e:
            print(f"  Skipping district stats {year}: {e}")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Flood Duration / Trend Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def compute_flood_frequency(start_year, end_year, region=None):
    """
    For each pixel, compute the fraction of years it was flooded (monsoon water).
    Returns an image with values 0-1 indicating flood frequency.
    """
    if region is None:
        region = get_study_area()

    # Build image collection server-side for flood frequency
    flood_images = []
    for year in range(start_year, end_year + 1):
        try:
            extents = get_annual_water_extents(year, region)
            flood_images.append(extents["monsoon_water"].selfMask().rename("flood"))
        except Exception:
            pass

    if not flood_images:
        return ee.Image.constant(0).rename("flood_frequency")

    collection = ee.ImageCollection(flood_images)
    frequency = collection.sum().divide(collection.count()).rename("flood_frequency")
    return frequency


def detect_flood_trend(start_year, end_year, region=None):
    """
    Simple trend analysis: compare first-half vs second-half flood frequency.
    Positive values = increasing flood tendency.
    """
    if region is None:
        region = get_study_area()

    mid = (start_year + end_year) // 2
    freq_early = compute_flood_frequency(start_year, mid, region)
    freq_late = compute_flood_frequency(mid + 1, end_year, region)
    trend = freq_late.subtract(freq_early).rename("flood_trend")
    return trend

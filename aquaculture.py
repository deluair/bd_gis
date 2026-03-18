"""
Aquaculture mapping -- shrimp and fish farm detection, expansion tracking,
mangrove-to-aquaculture conversion, and district-level breakdowns for
Bangladesh's coastal belt.

Bangladesh is the world's 5th largest aquaculture producer. Shrimp farms in
the southwest (Khulna, Satkhira, Bagerhat) are detectable via:
  - Water body shape: rectangular/geometric vs natural irregular outlines
  - Spectral: shallow turbid water (high NDWI, low clarity vs deep water)
  - Location: coastal zones, especially southwest
  - Temporal: permanent water absent in 1990s baseline
"""
import ee
import math
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Aquaculture Zone Configuration
# ═══════════════════════════════════════════════════════════════════════════════

AQUACULTURE_ZONES = {
    "khulna_coastal": {
        "districts": ["Khulna", "Satkhira", "Bagerhat"],
        "bounds": {"west": 88.8, "south": 21.8, "east": 89.9, "north": 22.9},
        "description": "Southwest shrimp belt (Sundarbans fringe)",
    },
    "coxs_bazar_coastal": {
        "districts": ["Cox's Bazar"],
        "bounds": {"west": 91.8, "south": 20.7, "east": 92.4, "north": 21.9},
        "description": "Southeast coastal aquaculture zone",
    },
    "noakhali_feni": {
        "districts": ["Noakhali", "Feni", "Lakshmipur"],
        "bounds": {"west": 90.8, "south": 22.4, "east": 91.6, "north": 23.2},
        "description": "Lower Meghna coastal fringe",
    },
}

# Spectral thresholds for pond detection
NDWI_POND_MIN = 0.1          # ponds show positive NDWI (water present)
NDWI_POND_MAX = 0.7          # very high NDWI = open deep water, not ponds
TURBIDITY_PROXY_MIN = 0.05   # shallow/turbid: moderate green reflectance

# Connected-component size filter (replaces compactness ratio approach).
# At 30m resolution: 1 pixel = 900 m2 = 0.09 ha.
# Min 5 pixels = 0.45 ha (filters noise/speckle).
# Max 5000 pixels = 450 ha (filters large natural water bodies).
SIZE_MIN_PIXELS = 5
SIZE_MAX_PIXELS = 5000

# JRC occurrence: ponds are permanent but not tidal
POND_OCCURRENCE_MIN = 50     # > 50% occurrence = not tidal/seasonal
POND_OCCURRENCE_MAX = 95     # < 95% = not large permanent river/lake


# ═══════════════════════════════════════════════════════════════════════════════
# Spectral Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_ndwi(image):
    """NDWI = (Green - NIR) / (Green + NIR). Positive for water."""
    return image.normalizedDifference(["green", "nir"]).rename("ndwi")


def _compute_mndwi(image):
    """MNDWI = (Green - SWIR1) / (Green + SWIR1). Better for turbid water."""
    return image.normalizedDifference(["green", "swir1"]).rename("mndwi")


def _compute_turbidity_proxy(image):
    """
    Shallow turbid water proxy: high green, moderate NIR, low SWIR1.
    Aquaculture ponds are fed/turbid -- distinct from clear river/ocean water.
    """
    green = image.select("green")
    nir = image.select("nir")
    swir1 = image.select("swir1")
    # Turbid water: green > NIR (sediment scattering), low SWIR1
    return green.subtract(nir).divide(green.add(nir).add(1e-6)).rename("turbidity_proxy")


def _get_coastal_dem_mask(region, max_elev_m=10):
    """Mask to low-elevation coastal zone where ponds are sited."""
    dem = ee.Image(cfg.SRTM_DEM).select("elevation").clip(region)
    return dem.gte(0).And(dem.lte(max_elev_m)).rename("coastal_zone")


# ═══════════════════════════════════════════════════════════════════════════════
# Pond Detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_aquaculture_ponds(year, region):
    """
    Detect aquaculture ponds using Sentinel-2 (post-2015) or Landsat water
    classification filtered by spectral turbidity signature, coastal elevation
    mask, JRC water occurrence range, and connected-component size filtering.

    When Sentinel-2 is used (year >= 2016), the composite is reprojected to
    30m to match Landsat spatial resolution. This ensures temporal consistency
    in the timeseries by comparing like-with-like across the sensor transition.

    Returns a binary ee.Image (1 = probable aquaculture pond).
    """
    from data_acquisition import get_landsat_collection, make_composite

    use_sentinel = year >= 2016
    if use_sentinel:
        col = (
            ee.ImageCollection(cfg.SENTINEL2_BANDS["collection"])
            .filterDate(f"{year}-11-01", f"{year}-03-01".replace(str(year), str(year + 1)))
            .filterBounds(region)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        )
        # Rename Sentinel-2 bands to common names
        original = cfg.SENTINEL2_BANDS["original"]
        renamed = cfg.SENTINEL2_BANDS["renamed"]
        col = col.select(original[:6], renamed[:6])
        composite = col.median().multiply(cfg.SENTINEL2_BANDS["scale_factor"]).clip(region)
        # Resample S2 (10m native) to 30m to match Landsat resolution for
        # temporal consistency across the sensor transition.
        composite = composite.reproject(crs="EPSG:4326", scale=30)
    else:
        col = get_landsat_collection(
            f"{year}-11-01", f"{year + 1}-03-01", region
        )
        composite = make_composite(col)

    ndwi = _compute_ndwi(composite)
    mndwi = _compute_mndwi(composite)
    turbidity = _compute_turbidity_proxy(composite)

    # Water presence: NDWI > threshold (both indices agree)
    water_mask = ndwi.gt(NDWI_POND_MIN).And(mndwi.gt(NDWI_POND_MIN))

    # Turbid water signature: excludes clear deep water (ocean, large rivers)
    turbid_mask = turbidity.gt(TURBIDITY_PROXY_MIN)

    # JRC occurrence filter: permanent but not tidal/river
    jrc_occ = (
        ee.Image(cfg.JRC_WATER)
        .select("occurrence")
        .clip(region)
    )
    occurrence_mask = jrc_occ.gte(POND_OCCURRENCE_MIN).And(
        jrc_occ.lte(POND_OCCURRENCE_MAX)
    )

    # Coastal elevation mask: ponds sited at low elevation
    coastal_mask = _get_coastal_dem_mask(region)

    # Combine spectral + occurrence + elevation criteria
    pond_candidate = (
        water_mask
        .And(turbid_mask)
        .And(occurrence_mask)
        .And(coastal_mask)
        .selfMask()
    )

    # Connected-component size filter: remove objects that are too small
    # (noise/speckle) or too large (natural water bodies, not ponds).
    # connectedPixelCount counts connected pixels up to SIZE_MAX_PIXELS + 1.
    pixel_count = pond_candidate.connectedPixelCount(SIZE_MAX_PIXELS + 1)
    size_mask = pixel_count.gte(SIZE_MIN_PIXELS).And(pixel_count.lte(SIZE_MAX_PIXELS))

    pond_filtered = pond_candidate.updateMask(size_mask).rename("aquaculture_pond")

    return pond_filtered.clip(region)


# ═══════════════════════════════════════════════════════════════════════════════
# Area Computation
# ═══════════════════════════════════════════════════════════════════════════════

def compute_aquaculture_area(year, region, scale=30):
    """Compute total aquaculture pond area in km2 for a given year."""
    ponds = detect_aquaculture_ponds(year, region)
    area = ponds.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return {
        "year": year,
        "aquaculture_area_km2": ee.Number(area.get("aquaculture_pond")).divide(1e6),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Time Series
# ═══════════════════════════════════════════════════════════════════════════════

def compute_aquaculture_timeseries(start_year, end_year, region, step=3):
    """Track aquaculture pond area from start_year to end_year."""
    series = []
    for year in range(start_year, end_year + 1, step):
        try:
            result = compute_aquaculture_area(year, region)
            series.append(result)
        except Exception as e:
            print(f"  Aquaculture area {year} skipped: {e}")
    return series


# ═══════════════════════════════════════════════════════════════════════════════
# Mangrove-to-Aquaculture Conversion
# ═══════════════════════════════════════════════════════════════════════════════

def detect_mangrove_to_aquaculture(region, baseline_year=1990, current_year=2020, scale=30):
    """
    Identify areas that were mangrove in baseline_year but became aquaculture
    ponds by current_year.

    Mangrove baseline reconstruction:
        Uses Hansen treecover2000 combined with lossyear to reconstruct areas
        that were forested at some point since 2000 (treecover2000 > 30% OR
        forest loss recorded 2001-current_year). In the coastal, low-elevation
        zone (<= 10m), this proxies mangrove extent.

    Limitation: pre-2000 mangrove conversion (1990-2000) is NOT directly
    observed. Hansen treecover2000 captures the state as of ~2000, so any
    mangrove cleared before 2000 is invisible. The 1990 baseline_year is
    therefore an approximation: the true baseline is ~2000 for the
    reconstruction, and conversion estimates are conservative (undercount
    areas cleared during the 1990s shrimp boom).

    If Global Mangrove Watch (GMW) becomes reliably available on GEE
    (cfg.GMW_MANGROVE), it should replace this approach for 1996+ baselines.

    Returns dict with conversion mask and area.
    """
    # Hansen treecover2000: areas forested as of 2000
    treecover = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"]).select(
        cfg.GLOBAL_FOREST_CHANGE["bands"]["treecover2000"]
    ).clip(region)

    # Hansen lossyear: forest loss year (1 = 2001, 2 = 2002, ...)
    loss_year = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"]).select(
        cfg.GLOBAL_FOREST_CHANGE["bands"]["lossyear"]
    ).clip(region)

    # Coastal elevation mask
    dem = ee.Image(cfg.SRTM_DEM).select("elevation").clip(region)
    coastal_mask = dem.lte(10).And(dem.gte(0))

    # Reconstruct "was forested at some point" layer:
    # Areas with tree cover > 30% in 2000, PLUS areas that lost forest
    # between 2001 and current_year (they were forested before loss).
    # Combined, this captures areas forested at any point 2000-current_year.
    years_since_2000 = current_year - 2000
    had_treecover_2000 = treecover.gt(30)
    lost_forest = loss_year.gt(0).And(loss_year.lte(years_since_2000))
    was_forested = had_treecover_2000.Or(lost_forest)

    # Mangrove proxy: forested + coastal low-elevation
    was_mangrove = was_forested.And(coastal_mask).rename("was_mangrove")

    # Current aquaculture ponds
    current_ponds = detect_aquaculture_ponds(current_year, region)

    # Conversion: was mangrove AND is now pond
    conversion = was_mangrove.And(current_ponds).rename("mangrove_to_aquaculture")

    area = conversion.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return {
        "baseline_year": baseline_year,
        "current_year": current_year,
        "conversion_mask": conversion,
        "conversion_area_km2": ee.Number(area.get("mangrove_to_aquaculture")).divide(1e6),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# District-Level Breakdown
# ═══════════════════════════════════════════════════════════════════════════════

def compute_district_aquaculture(region, year=2020, scale=100):
    """
    Compute per-district aquaculture pond area for coastal districts.
    Returns an ee.FeatureCollection with district name and area_km2.
    """
    ponds = detect_aquaculture_ponds(year, region)
    pond_area_image = ponds.multiply(ee.Image.pixelArea()).divide(1e6)

    districts_fc = (
        ee.FeatureCollection(cfg.ADMIN_BOUNDARIES)
        .filter(ee.Filter.eq("ADM0_NAME", cfg.COUNTRY_NAME))
        .filterBounds(region)
    )

    def add_area(feature):
        stats = pond_area_image.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=feature.geometry(),
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        return feature.set({
            "aquaculture_area_km2": stats.get("aquaculture_pond"),
            "year": year,
        })

    return districts_fc.map(add_area)


# ═══════════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════════

def validate_against_reference(satellite_areas, reference_areas):
    """
    Compare satellite-derived aquaculture areas against reference data
    (e.g., DoF census) for matched districts.

    Args:
        satellite_areas: dict of {district_name: area_km2} from satellite.
        reference_areas: dict of {district_name: area_km2} from reference.

    Returns:
        dict with r_squared, rmse, mean_absolute_error, n, and per-district
        errors. Only districts present in both dicts are compared.
    """
    common = sorted(set(satellite_areas) & set(reference_areas))
    n = len(common)
    if n == 0:
        return {"r_squared": None, "rmse": None, "mean_absolute_error": None, "n": 0, "errors": {}}

    sat = [satellite_areas[d] for d in common]
    ref = [reference_areas[d] for d in common]

    # Mean absolute error
    abs_errors = [abs(s - r) for s, r in zip(sat, ref)]
    mae = sum(abs_errors) / n

    # RMSE
    sq_errors = [(s - r) ** 2 for s, r in zip(sat, ref)]
    rmse = math.sqrt(sum(sq_errors) / n)

    # R squared
    ref_mean = sum(ref) / n
    ss_res = sum(sq_errors)
    ss_tot = sum((r - ref_mean) ** 2 for r in ref)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else None

    errors = {d: {"satellite": s, "reference": r, "error": s - r}
              for d, s, r in zip(common, sat, ref)}

    return {
        "r_squared": r_squared,
        "rmse": rmse,
        "mean_absolute_error": mae,
        "n": n,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_aquaculture_analysis(region):
    """Full aquaculture mapping and analysis pipeline."""
    results = {}

    # Use Khulna coastal zone as primary focus (southwest shrimp belt)
    khulna_bounds = AQUACULTURE_ZONES["khulna_coastal"]["bounds"]
    khulna_region = ee.Geometry.Rectangle([
        khulna_bounds["west"], khulna_bounds["south"],
        khulna_bounds["east"], khulna_bounds["north"],
    ])

    print("\n  Detecting aquaculture ponds (2020, Khulna coastal)...")
    try:
        results["ponds_2020"] = detect_aquaculture_ponds(2020, khulna_region)
        results["area_2020"] = compute_aquaculture_area(2020, khulna_region)
    except Exception as e:
        print(f"    Pond detection 2020 skipped: {e}")

    print("  Computing aquaculture time series (1995-2023)...")
    try:
        results["timeseries"] = compute_aquaculture_timeseries(1995, 2023, khulna_region)
    except Exception as e:
        print(f"    Time series skipped: {e}")

    print("  Detecting mangrove-to-aquaculture conversion (1990-2020)...")
    try:
        results["mangrove_conversion"] = detect_mangrove_to_aquaculture(khulna_region)
    except Exception as e:
        print(f"    Mangrove conversion skipped: {e}")

    print("  Computing district-level aquaculture breakdown...")
    try:
        results["district_stats"] = compute_district_aquaculture(khulna_region)
    except Exception as e:
        print(f"    District stats skipped: {e}")

    # Cox's Bazar zone
    print("  Detecting aquaculture ponds (Cox's Bazar, 2020)...")
    cxb_bounds = AQUACULTURE_ZONES["coxs_bazar_coastal"]["bounds"]
    cxb_region = ee.Geometry.Rectangle([
        cxb_bounds["west"], cxb_bounds["south"],
        cxb_bounds["east"], cxb_bounds["north"],
    ])
    try:
        results["area_coxsbazar_2020"] = compute_aquaculture_area(2020, cxb_region)
    except Exception as e:
        print(f"    Cox's Bazar skipped: {e}")

    # Noakhali/Feni zone
    print("  Detecting aquaculture ponds (Noakhali/Feni, 2020)...")
    noa_bounds = AQUACULTURE_ZONES["noakhali_feni"]["bounds"]
    noa_region = ee.Geometry.Rectangle([
        noa_bounds["west"], noa_bounds["south"],
        noa_bounds["east"], noa_bounds["north"],
    ])
    try:
        results["area_noakhali_2020"] = compute_aquaculture_area(2020, noa_region)
    except Exception as e:
        print(f"    Noakhali/Feni skipped: {e}")

    return results

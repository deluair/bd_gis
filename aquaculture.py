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
# Shape regularity: compactness ratio threshold (area / perimeter^2 * 4*pi)
# Circular = 1.0, rectangles ~ 0.785; natural water bodies typically < 0.4
SHAPE_COMPACTNESS_MIN = 0.35

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
    mask, and JRC water occurrence range (permanent but not open deep water).

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

    # Combine all criteria
    pond_candidate = (
        water_mask
        .And(turbid_mask)
        .And(occurrence_mask)
        .And(coastal_mask)
        .rename("aquaculture_pond")
    )

    return pond_candidate.clip(region)


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
    ponds by current_year. Uses Hansen forest cover as mangrove proxy in
    coastal low-elevation zones, and current-year pond detection.

    Returns dict with conversion mask and area.
    """
    # Mangrove baseline proxy: tree cover > 30% in coastal zone <= 10m elevation
    treecover = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"]).select(
        cfg.GLOBAL_FOREST_CHANGE["bands"]["treecover2000"]
    ).clip(region)
    dem = ee.Image(cfg.SRTM_DEM).select("elevation").clip(region)
    coastal_forest = treecover.gt(30).And(dem.lte(10)).And(dem.gte(0))

    # Forest loss before current_year (Hansen lossyear is years since 2000, 1-based)
    loss_year = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"]).select(
        cfg.GLOBAL_FOREST_CHANGE["bands"]["lossyear"]
    ).clip(region)
    years_since_baseline = current_year - 2000
    lost_by_current = loss_year.gt(0).And(loss_year.lte(years_since_baseline))

    # Mangrove in baseline: had tree cover in 2000 and either no loss yet, or
    # loss happened after baseline. For 1990 baseline we use 2000 treecover as proxy.
    was_mangrove = coastal_forest.rename("was_mangrove")

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

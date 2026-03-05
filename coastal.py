"""
Coastal analysis – shoreline change detection, mangrove extent tracking,
low-elevation coastal zone (LECZ) mapping, cyclone exposure assessment,
and salinity intrusion vulnerability for Bangladesh's coastal belt.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Coastal Zone Configuration
# ═══════════════════════════════════════════════════════════════════════════════

COASTAL_DISTRICTS = [
    "Satkhira", "Khulna", "Bagerhat", "Pirojpur", "Barguna", "Patuakhali",
    "Bhola", "Jhalokati", "Barishal", "Lakshmipur", "Noakhali", "Feni",
    "Chittagong", "Cox's Bazar",
]

COASTAL_BOUNDS = {
    "west": 89.0, "south": 20.5, "east": 92.5, "north": 23.0,
}

CYCLONE_LANDFALL_POINTS = {
    "Sidr 2007":     {"lat": 22.0, "lon": 89.8, "radius": 50000},
    "Aila 2009":     {"lat": 22.3, "lon": 89.5, "radius": 40000},
    "Roanu 2016":    {"lat": 22.5, "lon": 91.6, "radius": 30000},
    "Mora 2017":     {"lat": 22.0, "lon": 91.8, "radius": 30000},
    "Bulbul 2019":   {"lat": 21.8, "lon": 89.2, "radius": 40000},
    "Amphan 2020":   {"lat": 22.0, "lon": 89.0, "radius": 50000},
    "Yaas 2021":     {"lat": 21.5, "lon": 89.5, "radius": 40000},
    "Mocha 2023":    {"lat": 21.0, "lon": 92.0, "radius": 50000},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Low-Elevation Coastal Zone (LECZ)
# ═══════════════════════════════════════════════════════════════════════════════

def map_lecz(region, threshold_m=5):
    """
    Map Low-Elevation Coastal Zone: areas below a given elevation threshold.
    Default 5m — extremely vulnerable to sea level rise and storm surge.
    """
    dem = ee.Image(cfg.SRTM_DEM).select("elevation")
    lecz = dem.lt(threshold_m).And(dem.gte(0)).rename("lecz")
    return lecz.clip(region)


def compute_lecz_area(region, thresholds=None, scale=30):
    """Compute area below various elevation thresholds."""
    if thresholds is None:
        thresholds = [1, 2, 3, 5, 10]
    dem = ee.Image(cfg.SRTM_DEM).select("elevation").clip(region)

    results = []
    for thresh in thresholds:
        mask = dem.lt(thresh).And(dem.gte(0))
        area = mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=region,
            scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
        )
        results.append({
            "elevation_threshold_m": thresh,
            "area_km2": ee.Number(area.get("elevation")).divide(1e6),
        })
    return results


def compute_lecz_population(region, year=2020, threshold_m=5, scale=100):
    """Estimate population living in LECZ."""
    lecz = map_lecz(region, threshold_m)
    pop = (
        ee.ImageCollection(cfg.WORLDPOP["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .select(cfg.WORLDPOP["band"])
        .median()
        .clip(region)
    )
    pop_in_lecz = pop.updateMask(lecz)
    total = pop_in_lecz.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "threshold_m": threshold_m,
        "year": year,
        "population_in_lecz": total.get(cfg.WORLDPOP["band"]),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Shoreline Change Detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_shoreline(year, season, region):
    """
    Extract shoreline (water-land boundary) using water classification.
    Returns binary water mask for shoreline extraction.
    """
    from data_acquisition import get_seasonal_composite
    from water_classification import classify_water

    composite = get_seasonal_composite(year, season, "landsat", region)
    water = classify_water(composite, region=region)
    return water


def compute_shoreline_change(year1, year2, region, scale=30):
    """
    Detect shoreline accretion (land gain) and erosion (land loss)
    between two years using dry-season water masks.
    """
    water1 = detect_shoreline(year1, "dry", region)
    water2 = detect_shoreline(year2, "dry", region)

    # Land gain (was water, now land): accretion
    accretion = water1.And(water2.Not()).rename("accretion")
    # Land loss (was land, now water): erosion
    erosion = water2.And(water1.Not()).rename("erosion")

    acc_area = accretion.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    ero_area = erosion.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "period": f"{year1}-{year2}",
        "accretion_km2": ee.Number(acc_area.get("accretion")).divide(1e6),
        "erosion_km2": ee.Number(ero_area.get("erosion")).divide(1e6),
        "accretion_mask": accretion,
        "erosion_mask": erosion,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Mangrove Analysis (Sundarbans focus)
# ═══════════════════════════════════════════════════════════════════════════════

def get_mangrove_extent(region, year=2021):
    """
    Extract mangrove extent from ESA WorldCover (class 95 = Mangroves).
    """
    from land_cover import get_esa_worldcover
    wc = get_esa_worldcover(year, region)
    return wc.eq(95).rename("mangrove")


def compute_mangrove_area(region, year=2021, scale=30):
    """Compute total mangrove area."""
    mangrove = get_mangrove_extent(region, year)
    area = mangrove.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "year": year,
        "mangrove_area_km2": ee.Number(area.get("mangrove")).divide(1e6),
    }


def compute_mangrove_health(year, region, scale=1000):
    """
    Assess mangrove health using NDVI within mangrove extent.
    Lower NDVI in mangroves indicates degradation or die-off.
    """
    mangrove = get_mangrove_extent(region)
    ndvi = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .select(cfg.MODIS_NDVI["ndvi_band"])
        .mean()
        .multiply(cfg.MODIS_NDVI["scale_factor"])
        .clip(region)
    )
    mangrove_ndvi = ndvi.updateMask(mangrove)
    stats = mangrove_ndvi.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=region, scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "year": year,
        "mean_mangrove_ndvi": stats.get("NDVI_mean"),
        "std_mangrove_ndvi": stats.get("NDVI_stdDev"),
    }


def detect_mangrove_change(year1, year2, region, scale=30):
    """Detect mangrove gain/loss using ESA WorldCover or DW."""
    from vegetation import get_forest_cover_2000, get_forest_loss

    # Use Hansen forest data in Sundarbans region
    loss = get_forest_loss(region)
    treecover = get_forest_cover_2000(region)
    # Mangrove proxy: tree cover > 30% in coastal low-elevation areas
    dem = ee.Image(cfg.SRTM_DEM).select("elevation").clip(region)
    coastal_forest = treecover.gt(30).And(dem.lt(10))
    mangrove_loss = loss.And(coastal_forest).rename("mangrove_loss")

    area = mangrove_loss.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "mangrove_loss_mask": mangrove_loss,
        "mangrove_loss_km2": ee.Number(area.get("mangrove_loss")).divide(1e6),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Cyclone Impact Assessment
# ═══════════════════════════════════════════════════════════════════════════════

def assess_cyclone_impact(cyclone_name, pre_year=None, post_year=None):
    """
    Assess vegetation damage from a cyclone by comparing NDVI before/after.
    """
    if cyclone_name not in CYCLONE_LANDFALL_POINTS:
        raise ValueError(f"Unknown cyclone: {cyclone_name}")

    info = CYCLONE_LANDFALL_POINTS[cyclone_name]
    # Extract year from name
    year = int(cyclone_name.split()[-1])
    center = ee.Geometry.Point([info["lon"], info["lat"]])
    impact_zone = center.buffer(info["radius"])

    if pre_year is None:
        pre_year = year - 1
    if post_year is None:
        post_year = year

    # Pre and post NDVI
    pre_ndvi = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate(f"{pre_year}-01-01", f"{pre_year}-12-31")
        .filterBounds(impact_zone)
        .select(cfg.MODIS_NDVI["ndvi_band"])
        .mean()
        .multiply(cfg.MODIS_NDVI["scale_factor"])
    )
    post_ndvi = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate(f"{post_year}-01-01", f"{post_year}-12-31")
        .filterBounds(impact_zone)
        .select(cfg.MODIS_NDVI["ndvi_band"])
        .mean()
        .multiply(cfg.MODIS_NDVI["scale_factor"])
    )

    ndvi_drop = pre_ndvi.subtract(post_ndvi).rename("ndvi_damage")

    stats = ndvi_drop.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.max(), sharedInputs=True),
        geometry=impact_zone, scale=1000,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "cyclone": cyclone_name,
        "mean_ndvi_drop": stats.get("ndvi_damage_mean"),
        "max_ndvi_drop": stats.get("ndvi_damage_max"),
        "ndvi_damage_image": ndvi_drop.clip(impact_zone),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_coastal_analysis(region):
    """Full coastal analysis pipeline."""
    results = {}

    # Use coastal bounds for focused analysis
    coastal_region = ee.Geometry.Rectangle([
        COASTAL_BOUNDS["west"], COASTAL_BOUNDS["south"],
        COASTAL_BOUNDS["east"], COASTAL_BOUNDS["north"],
    ])

    print("\n  Mapping Low-Elevation Coastal Zone...")
    try:
        results["lecz"] = map_lecz(coastal_region)
        results["lecz_areas"] = compute_lecz_area(coastal_region)
    except Exception as e:
        print(f"    LECZ mapping skipped: {e}")

    print("  Estimating LECZ population...")
    try:
        results["lecz_population"] = compute_lecz_population(coastal_region)
    except Exception as e:
        print(f"    LECZ population skipped: {e}")

    print("  Computing shoreline change (1990–2020)...")
    results["shoreline_changes"] = []
    for y1, y2 in [(1990, 2000), (2000, 2010), (2010, 2020)]:
        try:
            results["shoreline_changes"].append(
                compute_shoreline_change(y1, y2, coastal_region)
            )
        except Exception as e:
            print(f"    Shoreline {y1}-{y2} skipped: {e}")

    print("  Computing mangrove extent and health...")
    try:
        results["mangrove_area"] = compute_mangrove_area(coastal_region)
    except Exception as e:
        print(f"    Mangrove area skipped: {e}")

    results["mangrove_health"] = []
    for year in [2005, 2010, 2015, 2020, 2023]:
        try:
            results["mangrove_health"].append(compute_mangrove_health(year, coastal_region))
        except Exception as e:
            print(f"    Mangrove health {year} skipped: {e}")

    print("  Detecting mangrove change (Hansen)...")
    try:
        results["mangrove_change"] = detect_mangrove_change(2000, 2023, coastal_region)
    except Exception as e:
        print(f"    Mangrove change skipped: {e}")

    print("  Assessing cyclone impacts...")
    results["cyclone_impacts"] = []
    for cyclone in CYCLONE_LANDFALL_POINTS:
        try:
            results["cyclone_impacts"].append(assess_cyclone_impact(cyclone))
        except Exception as e:
            print(f"    {cyclone} skipped: {e}")

    return results

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
    "west": 89.0, "south": 20.5, "east": 92.5, "north": 23.5,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Low-Elevation Coastal Zone (LECZ)
# ═══════════════════════════════════════════════════════════════════════════════

def map_lecz(region, threshold_m=5):
    """
    Map Low-Elevation Coastal Zone: areas below a given elevation threshold.
    Default 5m, extremely vulnerable to sea level rise and storm surge.
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


def lecz_coverage_fraction(region, threshold_m, target_scale):
    """Share of each `target_scale` cell that lies inside the LECZ (0-1).

    A population grid holds a *count per cell*, so masking it with a mask finer
    than its own cells is all-or-nothing: a 928 m LandScan cell is kept whole or
    dropped whole. Against a 30 m SRTM mask over a fragmented delta fringe that
    is not a rounding error. Measured over COASTAL_BOUNDS for 2020, naive
    masking undercounts LandScan by 65% (2.86M vs 8.21M) and WorldPop by 10%
    (6.27M vs 6.94M). Weighting each cell by the share of it actually inside the
    zone removes the quantisation and makes coarse and fine grids comparable.

    maxPixels=4096 caps the aggregation at 64x64 SRTM pixels, i.e. target scales
    up to ~1.9 km. Coarser targets need a larger cap.
    """
    dem = ee.Image(cfg.SRTM_DEM).select("elevation")
    # unmask(0) so ocean and SRTM voids count as outside the zone rather than
    # propagating a mask; setDefaultProjection because unmask() drops it.
    lecz01 = (
        dem.lt(threshold_m).And(dem.gte(0)).unmask(0)
        .setDefaultProjection(dem.projection())
    )
    return (
        lecz01.reduceResolution(reducer=ee.Reducer.mean(), maxPixels=4096)
        .reproject(ee.Projection("EPSG:4326").atScale(target_scale))
        .clip(region)
    )


def _pop_spec(source):
    """Resolve a population source name to its config block."""
    try:
        return {"landscan": cfg.LANDSCAN, "worldpop": cfg.WORLDPOP}[source]
    except KeyError:
        raise ValueError(
            f"unknown population source {source!r}, expected 'landscan' or 'worldpop'"
        ) from None


def get_population_grid(year, region, source="landscan"):
    """Population count grid for `year`, clipped to `region`.

    `source` is explicit and has no default fallback across products, because
    LandScan counts *ambient* population and WorldPop counts *residential*:
    mixing them in one series or ratio compares different quantities.

    Returns (image renamed "population", native scale in metres). The scale is
    returned with the image on purpose. Both grids are counts per cell, so
    summing one at the wrong scale rescales the answer: WorldPop is people per
    100 m cell and summing it at 1 km undercounts by ~100x. Always reduce with
    the scale this returns.
    """
    spec = _pop_spec(source)
    lo, hi = spec["years"]
    if not lo <= year <= hi:
        raise ValueError(
            f"{source} has no {year} layer (covers {lo}-{hi}). Pick a covered "
            f"year explicitly rather than letting it clamp silently."
        )
    img = (
        ee.ImageCollection(spec["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .select(spec["band"])
        .median()
        .clip(region)
        .rename("population")
    )
    return img, spec["scale"]


def compute_lecz_population(region, year=None, threshold_m=5, source="landscan",
                            scale=None):
    """Estimate population living in the low-elevation coastal zone.

    Defaults to LandScan: ambient population is the correct exposure basis for
    a storm surge, which does not wait for people to be home, and LandScan runs
    to 2024 where WorldPop stops at 2020. `year` defaults to the newest layer
    the chosen source has, so this tracks config instead of pinning a year that
    silently goes stale.

    Returns the count alongside its provenance so the number can never be
    quoted without knowing which grid and which year produced it.
    """
    spec = _pop_spec(source)
    if year is None:
        year = spec["years"][1]
    pop, native_scale = get_population_grid(year, region, source)
    scale = native_scale if scale is None else scale
    frac = lecz_coverage_fraction(region, threshold_m, scale)
    pop_in_lecz = pop.multiply(frac).rename("population")
    # bestEffort=False deliberately, against the usual convention here. This is
    # a summed count, not a mean: if the reduction exceeded maxPixels,
    # bestEffort would silently coarsen the scale and return a wrong
    # population. Better to raise than to publish a quiet error.
    total = pop_in_lecz.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=False,
    )
    return {
        "threshold_m": threshold_m,
        "year": year,
        "population_source": source,
        "population_measure": spec["measure"],
        "scale_m": scale,
        "population_in_lecz": total.get("population"),
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


def _get_mangrove_mask(region, year=2021):
    """Get mangrove mask for a given year, with fallback for pre-2020."""
    if year >= 2020:
        return get_mangrove_extent(region, year)
    # ESA WorldCover not available before 2020: use Hansen-based mangrove proxy
    from vegetation import get_forest_cover_2000
    treecover = get_forest_cover_2000(region)
    dem = ee.Image(cfg.SRTM_DEM).select("elevation").clip(region)
    return treecover.gt(30).And(dem.lt(10)).rename("mangrove")


def compute_mangrove_health(year, region, scale=1000):
    """
    Assess mangrove health using NDVI within mangrove extent.
    Lower NDVI in mangroves indicates degradation or die-off.
    """
    mangrove = _get_mangrove_mask(region, year)
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
    """Detect mangrove gain/loss using Hansen lossyear filtered to year1-year2."""
    from vegetation import get_forest_cover_2000, get_forest_loss_year

    # Use Hansen forest data in Sundarbans region
    lossyear = get_forest_loss_year(region)
    treecover = get_forest_cover_2000(region)
    # Mangrove proxy: tree cover > 30% in coastal low-elevation areas
    dem = ee.Image(cfg.SRTM_DEM).select("elevation").clip(region)
    coastal_forest = treecover.gt(30).And(dem.lt(10))

    # Filter Hansen lossyear to the requested period
    loss_in_period = lossyear.gt(0).And(
        lossyear.gte(year1 - 2000)
    ).And(
        lossyear.lte(year2 - 2000)
    )
    mangrove_loss = loss_in_period.And(coastal_forest).rename("mangrove_loss")

    area = mangrove_loss.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "period": f"{year1}-{year2}",
        "mangrove_loss_mask": mangrove_loss,
        "mangrove_loss_km2": ee.Number(area.get("mangrove_loss")).divide(1e6),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Cyclone Impact Assessment
# ═══════════════════════════════════════════════════════════════════════════════

def assess_cyclone_impact(cyclone_name, pre_year=None, post_year=None):
    """
    Assess vegetation damage from a cyclone by comparing NDVI before/after.
    Uses 3-month windows around the landfall date for sharper signal.
    """
    if cyclone_name not in cfg.CYCLONE_LANDFALL_POINTS:
        raise ValueError(f"Unknown cyclone: {cyclone_name}")

    info = cfg.CYCLONE_LANDFALL_POINTS[cyclone_name]
    year = int(info["date"][:4])
    center = ee.Geometry.Point([info["lon"], info["lat"]])
    impact_zone = center.buffer(info["radius"])

    # Compute 3-month pre/post windows from the landfall date
    landfall_date = ee.Date(info["date"])
    pre_start = landfall_date.advance(-3, "month")
    pre_end = landfall_date
    post_start = landfall_date
    post_end = landfall_date.advance(3, "month")

    if pre_year is not None and post_year is not None:
        # Caller override: use full-year ranges
        pre_start = ee.Date(f"{pre_year}-01-01")
        pre_end = ee.Date(f"{pre_year}-12-31")
        post_start = ee.Date(f"{post_year}-01-01")
        post_end = ee.Date(f"{post_year}-12-31")

    # Pre and post NDVI
    pre_ndvi = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate(pre_start, pre_end)
        .filterBounds(impact_zone)
        .select(cfg.MODIS_NDVI["ndvi_band"])
        .mean()
        .multiply(cfg.MODIS_NDVI["scale_factor"])
    )
    post_ndvi = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate(post_start, post_end)
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
        "year": year,
        "mean_ndvi_drop": stats.get("ndvi_damage_mean"),
        "max_ndvi_drop": stats.get("ndvi_damage_max"),
        "ndvi_damage_image": ndvi_drop.clip(impact_zone),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_coastal_analysis(region=None):
    """Full coastal analysis pipeline."""
    results = {}

    # Use passed region, or fall back to coastal bounds
    if region is None:
        region = ee.Geometry.Rectangle([
            COASTAL_BOUNDS["west"], COASTAL_BOUNDS["south"],
            COASTAL_BOUNDS["east"], COASTAL_BOUNDS["north"],
        ])
    coastal_region = region

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
    for cyclone in cfg.CYCLONE_LANDFALL_POINTS:
        try:
            results["cyclone_impacts"].append(assess_cyclone_impact(cyclone))
        except Exception as e:
            print(f"    {cyclone} skipped: {e}")

    return results

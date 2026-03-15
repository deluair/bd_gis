"""
River erosion and channel migration analysis – extract centerlines,
compute lateral migration, and identify erosion hotspots.
"""
import signal
import ee
import config as cfg

# Timeout for individual GEE getInfo() calls (seconds)
GEE_TIMEOUT = 300  # 5 minutes


class GEETimeoutError(Exception):
    pass


def _getinfo_with_timeout(ee_obj, timeout=GEE_TIMEOUT):
    """Thread-safe getInfo() with timeout using concurrent.futures."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(ee_obj.getInfo)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            raise GEETimeoutError("GEE call timed out")
        except Exception:
            raise
from data_acquisition import (
    get_study_area, get_landsat_collection, make_composite
)
from water_classification import classify_water


# ═══════════════════════════════════════════════════════════════════════════════
# River Corridor ROI
# ═══════════════════════════════════════════════════════════════════════════════

def get_river_roi(river_name):
    """Create a buffered corridor geometry for a named river."""
    river = cfg.RIVERS[river_name]
    points = [ee.Geometry.Point(lon, lat) for lat, lon in river["points"]]
    line = ee.Geometry.MultiPoint(points).convexHull()
    return line.buffer(river["buffer_m"])


# ═══════════════════════════════════════════════════════════════════════════════
# Decadal Water Masks & Centerlines
# ═══════════════════════════════════════════════════════════════════════════════

def get_decadal_water_mask(year, river_roi, window=2):
    """
    Get a water mask for a river corridor around a target year.
    Uses a ±window year range for dry-season compositing to reduce noise.
    Uses method='fixed' because river corridor ROIs are too small for
    reliable Otsu histogram thresholding.
    """
    import datetime
    # Widen window for the earliest decade: Landsat 5 coverage over Bangladesh
    # is sparse before 1988, so the default ±2yr window around 1985 yields
    # mostly masked pixels, causing the 1985-1995 erosion period to be all zeros.
    effective_window = window if year >= 1990 else max(window, 5)
    start = f"{year - effective_window}-12-01"
    # Clamp end date to today so we never query into the future
    max_end = datetime.date.today().isoformat()
    end = min(f"{year + effective_window}-02-28", max_end)
    # Clamp start to Landsat 5 launch (1984-03-01)
    if start < "1984-03-01":
        start = "1984-03-01"
    col = get_landsat_collection(start, end, river_roi)

    # Guard against empty collections (e.g. for very recent years)
    col_size = _getinfo_with_timeout(col.size())
    if col_size == 0:
        # Fall back to a wider window
        start = f"{max(year - effective_window - 2, 1984)}-03-01"
        end = max_end
        col = get_landsat_collection(start, end, river_roi)

    composite = make_composite(col, method="median")
    water = classify_water(composite, region=river_roi, method="fixed")
    # Unmask to 0 so that masked pixels are treated as non-water in
    # downstream .And() / .subtract() operations. Without this, masked
    # pixels propagate as masked through change detection and the
    # reduceRegion sum returns null/0.
    return water.unmask(0)


def extract_centerline(water_mask, river_roi, scale=30):
    """
    Extract river centerline by morphological thinning of the water mask.
    Uses iterative erosion to approximate the skeleton/medial axis.
    """
    # Focal erosion iterations to thin the mask
    kernel = ee.Kernel.circle(radius=scale, units="meters")
    thinned = water_mask
    for _ in range(5):
        eroded = thinned.focalMin(kernel=kernel)
        thinned = thinned.subtract(eroded).gt(0).Or(eroded)

    # The skeleton is the set of pixels that remain after thinning
    skeleton = water_mask.subtract(
        water_mask.focalMin(kernel=ee.Kernel.circle(radius=scale * 2, units="meters"))
    ).gt(0).selfMask()

    return skeleton.rename("centerline")


def get_decadal_centerlines(river_name, decades=None):
    """
    Extract centerlines for a river across multiple decades.
    Returns dict {year: ee.Image centerline}.
    """
    if decades is None:
        decades = cfg.DECADES
    river_roi = get_river_roi(river_name)

    centerlines = {}
    for year in decades:
        water_mask = get_decadal_water_mask(year, river_roi)
        centerlines[year] = extract_centerline(water_mask, river_roi)
    return centerlines


# ═══════════════════════════════════════════════════════════════════════════════
# Channel Migration & Erosion
# ═══════════════════════════════════════════════════════════════════════════════

def compute_channel_migration(water_masks, decades=None):
    """
    Compute channel migration between consecutive decades.
    Returns list of dicts with migration info.
    """
    if decades is None:
        decades = cfg.DECADES

    migrations = []
    for i in range(len(decades) - 1):
        y1, y2 = decades[i], decades[i + 1]
        mask1 = water_masks[y1]
        mask2 = water_masks[y2]

        # Erosion: was water in y1 but not in y2 (land gain / bank erosion on opposite side)
        eroded = mask1.And(mask2.Not()).rename("eroded")
        # Accretion: was not water in y1 but is water in y2
        accreted = mask2.And(mask1.Not()).rename("accreted")
        # Net change
        net_change = mask2.subtract(mask1).rename("net_change")

        migrations.append({
            "period": f"{y1}-{y2}",
            "start_year": y1,
            "end_year": y2,
            "eroded": eroded,
            "accreted": accreted,
            "net_change": net_change,
        })
    return migrations


def compute_erosion_area(eroded_mask, region, scale=30):
    """Calculate total erosion area in hectares."""
    area = eroded_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    # Guard against null result (e.g. when reduceRegion returns None for
    # the band due to computation limits or fully masked input)
    raw = area.get("eroded")
    return ee.Number(ee.Algorithms.If(raw, raw, 0)).divide(10000)  # m² to ha


def compute_erosion_rate(eroded_mask, region, years_elapsed, scale=30):
    """Calculate erosion rate in hectares per year."""
    area_ha = compute_erosion_area(eroded_mask, region, scale)
    return area_ha.divide(years_elapsed)


def identify_erosion_hotspots(migrations, river_roi, scale=30):
    """
    Identify persistent erosion hotspots – areas eroded in multiple periods.
    Returns an image where pixel value = number of periods with erosion.
    """
    hotspot = ee.Image.constant(0).clip(river_roi)
    for m in migrations:
        hotspot = hotspot.add(m["eroded"])
    return hotspot.rename("erosion_frequency")


def _scale_for_river(river_name):
    """Choose reduceRegion scale based on river buffer size.

    Large-buffer rivers (>=8000m) cover huge areas. At scale=30, the
    reduceRegion call exceeds GEE computation limits and silently returns
    null/0. Use coarser scale for these rivers to stay within limits.
    """
    buffer_m = cfg.RIVERS[river_name]["buffer_m"]
    if buffer_m >= 8000:
        return 300
    if buffer_m >= 5000:
        return 100
    return 30


def run_river_analysis(river_name):
    """
    Full river analysis pipeline for a single river.
    Returns dict with all products.
    """
    river_roi = get_river_roi(river_name)
    decades = cfg.DECADES
    scale = _scale_for_river(river_name)

    # Water masks per decade
    water_masks = {}
    for year in decades:
        water_masks[year] = get_decadal_water_mask(year, river_roi)

    # Centerlines
    centerlines = {}
    for year in decades:
        centerlines[year] = extract_centerline(water_masks[year], river_roi)

    # Channel migration
    migrations = compute_channel_migration(water_masks, decades)

    # Erosion hotspots
    hotspots = identify_erosion_hotspots(migrations, river_roi)

    # Erosion rates per period
    rates = []
    for m in migrations:
        years_elapsed = m["end_year"] - m["start_year"]
        rate = compute_erosion_rate(m["eroded"], river_roi, years_elapsed, scale)
        rates.append({"period": m["period"], "rate_ha_per_year": rate})

    return {
        "river_name": river_name,
        "roi": river_roi,
        "water_masks": water_masks,
        "centerlines": centerlines,
        "migrations": migrations,
        "hotspots": hotspots,
        "erosion_rates": rates,
    }

"""
Char (river island) detection and land accretion analysis for Bangladesh river deltas.
Tracks new land formation through water-to-land pixel transitions in the Meghna estuary,
Padma-Jamuna confluence, and coastal Noakhali/Bhola.
"""
import signal
import ee
import config as cfg

GEE_TIMEOUT = 300


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
    get_landsat_collection, make_composite
)
from water_classification import classify_water


# ═══════════════════════════════════════════════════════════════════════════════
# Accretion Zone ROIs
# ═══════════════════════════════════════════════════════════════════════════════

def get_accretion_roi(zone_name):
    """Create a geometry for a named accretion zone from cfg.ACCRETION_ZONES."""
    zone = cfg.ACCRETION_ZONES[zone_name]
    return ee.Geometry.Rectangle(
        [zone["west"], zone["south"], zone["east"], zone["north"]]
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Water Masks (dry season composites for reliable land/water separation)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_dry_water_mask(year, region, window=2):
    """
    Dry-season water mask for a given year (Dec-Feb composite, ±window years).
    Uses fixed threshold -- accretion zones are large and Otsu is unreliable.
    """
    import datetime
    effective_window = window if year >= 1990 else max(window, 5)
    start = f"{year - effective_window}-12-01"
    max_end = datetime.date.today().isoformat()
    end = min(f"{year + effective_window}-02-28", max_end)
    if start < "1984-03-01":
        start = "1984-03-01"

    col = get_landsat_collection(start, end, region)
    col_size = _getinfo_with_timeout(col.size())
    if col_size == 0:
        start = f"{max(year - effective_window - 2, 1984)}-03-01"
        end = max_end
        col = get_landsat_collection(start, end, region)

    composite = make_composite(col, method="median")
    water = classify_water(composite, region=region, method="fixed")
    return water.unmask(0)


# ═══════════════════════════════════════════════════════════════════════════════
# Core Detection Functions
# ═══════════════════════════════════════════════════════════════════════════════

def detect_new_land(early_year, late_year, region, scale=30):
    """
    Binary mask of pixels that were water in early_year but land in late_year.
    Value 1 = new land (water-to-land transition).

    early_year: int, reference period start
    late_year: int, reference period end
    region: ee.Geometry
    """
    early_water = _get_dry_water_mask(early_year, region)
    late_water = _get_dry_water_mask(late_year, region)
    # was water (1) in early, is NOT water (0) in late
    new_land = early_water.And(late_water.Not()).rename("new_land")
    return new_land.unmask(0)


def compute_accretion_area(early_year, late_year, region, scale=30):
    """
    Total new land area in km2 between early_year and late_year.
    Returns ee.Number.
    """
    new_land = detect_new_land(early_year, late_year, region, scale)
    area = new_land.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    raw = area.get("new_land")
    return ee.Number(ee.Algorithms.If(raw, raw, 0)).divide(1e6)  # m2 to km2


def compute_accretion_timeseries(region, decades=None, scale=30):
    """
    Decadal accretion rates for a region.
    Returns list of dicts: {period, start_year, end_year, new_land_km2, rate_km2_per_year}.
    Each dict has ee.Number values -- resolve downstream.
    """
    if decades is None:
        decades = cfg.DECADES

    timeseries = []
    for i in range(len(decades) - 1):
        y1, y2 = decades[i], decades[i + 1]
        years_elapsed = y2 - y1
        area_km2 = compute_accretion_area(y1, y2, region, scale)
        rate = area_km2.divide(years_elapsed)
        timeseries.append({
            "period": f"{y1}-{y2}",
            "start_year": y1,
            "end_year": y2,
            "new_land_km2": area_km2,
            "rate_km2_per_year": rate,
        })
    return timeseries


def identify_major_chars(early_year, late_year, region, min_area_m2=500000, scale=30):
    """
    Identify distinct new land formations (chars) larger than min_area_m2.
    Returns ee.FeatureCollection with centroid lon/lat and area_km2 per char.

    min_area_m2: minimum connected patch size (default 0.5 km2 = 500000 m2)
    """
    new_land = detect_new_land(early_year, late_year, region, scale)

    # Label connected components
    connected = new_land.selfMask().connectedComponents(
        connectedness=ee.Kernel.plus(1),
        maxSize=1024,
    )
    labels = connected.select("labels")

    # Vectorize to polygons
    vectors = labels.reduceToVectors(
        geometry=region,
        scale=scale,
        geometryType="polygon",
        eightConnected=True,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )

    # Compute area and filter
    def add_area(feat):
        area_m2 = feat.geometry().area(maxError=1)
        centroid = feat.geometry().centroid(maxError=1)
        return feat.set({
            "area_km2": ee.Number(area_m2).divide(1e6),
            "centroid_lon": centroid.coordinates().get(0),
            "centroid_lat": centroid.coordinates().get(1),
            "period": f"{early_year}-{late_year}",
        })

    chars = vectors.map(add_area).filter(
        ee.Filter.gte("area_km2", ee.Number(min_area_m2).divide(1e6))
    )
    return chars.sort("area_km2", ascending=False)


def compute_char_vulnerability(early_year, late_year, region, scale=30):
    """
    Overlay new land pixels with JRC flood frequency to assess vulnerability.
    Returns dict with:
      new_land: ee.Image (binary new land mask)
      flood_freq: ee.Image (JRC occurrence on new land pixels)
      vulnerable_area_km2: ee.Number (new land pixels with occurrence >= 25%)
      mean_flood_occurrence: ee.Number (mean JRC occurrence on new land)
    """
    new_land = detect_new_land(early_year, late_year, region, scale)

    jrc = ee.Image(cfg.JRC_WATER).select("occurrence").clip(region)
    # Occurrence is 0-100 (percent of time observed as water 1984-2021)
    flood_freq_on_new_land = jrc.updateMask(new_land.selfMask()).rename("flood_occurrence")

    # Vulnerable = new land that was water >= 25% of historical record
    vulnerable = new_land.And(jrc.gte(25)).rename("vulnerable_new_land")
    vuln_area = vulnerable.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    raw_vuln = vuln_area.get("vulnerable_new_land")
    vuln_km2 = ee.Number(ee.Algorithms.If(raw_vuln, raw_vuln, 0)).divide(1e6)

    mean_occ = flood_freq_on_new_land.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    ).get("flood_occurrence")

    return {
        "new_land": new_land,
        "flood_freq": flood_freq_on_new_land,
        "vulnerable_area_km2": vuln_km2,
        "mean_flood_occurrence": ee.Number(ee.Algorithms.If(mean_occ, mean_occ, 0)),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Scale Helper
# ═══════════════════════════════════════════════════════════════════════════════

def _scale_for_zone(zone_name):
    """Coarser scale for large zones to avoid GEE computation limits."""
    z = cfg.ACCRETION_ZONES[zone_name]
    lon_span = z["east"] - z["west"]
    lat_span = z["north"] - z["south"]
    area_deg2 = lon_span * lat_span
    if area_deg2 >= 2.0:
        return 300
    if area_deg2 >= 0.5:
        return 100
    return 30


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

def run_char_accretion_analysis(region):
    """
    Full char/land accretion analysis for a given region (ee.Geometry).
    Returns dict with all products.
    """
    decades = cfg.DECADES
    # Use a scale appropriate for national/large regions
    is_large = cfg.SCOPE == "national"
    scale = 300 if is_large else 30

    # Accretion time series
    timeseries = compute_accretion_timeseries(region, decades, scale)

    # Most recent period new land mask and chars
    y1, y2 = decades[-2], decades[-1]
    new_land_recent = detect_new_land(y1, y2, region, scale)

    # Major chars (recent period)
    try:
        major_chars = identify_major_chars(y1, y2, region, scale=scale)
    except Exception as e:
        print(f"  identify_major_chars failed: {e}")
        major_chars = None

    # Vulnerability (recent period)
    try:
        vulnerability = compute_char_vulnerability(y1, y2, region, scale)
    except Exception as e:
        print(f"  compute_char_vulnerability failed: {e}")
        vulnerability = None

    # Cumulative new land 1985-2025
    try:
        new_land_cumulative = detect_new_land(decades[0], decades[-1], region, scale)
    except Exception as e:
        print(f"  cumulative new land failed: {e}")
        new_land_cumulative = None

    return {
        "region": region,
        "decades": decades,
        "timeseries": timeseries,
        "new_land_recent": new_land_recent,
        "recent_period": f"{y1}-{y2}",
        "major_chars": major_chars,
        "vulnerability": vulnerability,
        "new_land_cumulative": new_land_cumulative,
    }

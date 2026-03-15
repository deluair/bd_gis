"""
Cyclone damage assessment using pre/post satellite imagery.

Analyses vegetation loss (NDVI difference), flood extent, and damage severity
for major Bangladesh cyclones using Landsat/Sentinel composites.
"""
import datetime

import ee

import config as cfg
from data_acquisition import get_landsat_collection, get_sentinel2_collection, make_composite
from water_classification import classify_water


# ── Damage severity thresholds (NDVI drop) ───────────────────────────────────
NDVI_SEVERE   = 0.20   # NDVI drop >= 0.20  => severe damage
NDVI_MODERATE = 0.10   # NDVI drop >= 0.10  => moderate damage
NDVI_MILD     = 0.05   # NDVI drop >= 0.05  => mild damage


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _date_range(date_str, offset_days):
    """Return (start, end) ISO strings for a window centered offset_days before/after date_str."""
    d = datetime.date.fromisoformat(date_str)
    half = datetime.timedelta(days=15)
    if offset_days < 0:
        center = d + datetime.timedelta(days=offset_days)
    else:
        center = d + datetime.timedelta(days=offset_days)
    return (center - half).isoformat(), (center + half).isoformat()


def _get_composite(start, end, region, sensor="auto"):
    """Get cloud-free median composite for a date window.

    sensor='auto' picks Sentinel-2 for post-2015 dates, Landsat otherwise.
    """
    start_year = int(start[:4])
    if sensor == "auto":
        sensor = "sentinel2" if start_year >= 2015 else "landsat"

    if sensor == "sentinel2":
        col = get_sentinel2_collection(start, end, region)
    else:
        col = get_landsat_collection(start, end, region)

    return make_composite(col)


def _compute_ndvi(composite):
    """Compute NDVI from a harmonized composite (bands: nir, red)."""
    nir = composite.select("nir")
    red = composite.select("red")
    return nir.subtract(red).divide(nir.add(red)).rename("ndvi")


# ═══════════════════════════════════════════════════════════════════════════════
# Core Analysis Functions
# ═══════════════════════════════════════════════════════════════════════════════

def get_pre_post_composites(cyclone_name, region=None):
    """Get Landsat/Sentinel composites 1 month before and 1 month after cyclone landfall.

    Returns:
        dict with keys 'pre', 'post', 'cyclone', 'landfall_date', 'impact_zone'
    """
    if cyclone_name not in cfg.CYCLONE_LANDFALL_POINTS:
        raise ValueError(f"Unknown cyclone: {cyclone_name}. "
                         f"Available: {list(cfg.CYCLONE_LANDFALL_POINTS)}")

    info = cfg.CYCLONE_LANDFALL_POINTS[cyclone_name]
    landfall = info["date"]

    center = ee.Geometry.Point([info["lon"], info["lat"]])
    impact_zone = center.buffer(info["radius"])

    if region is None:
        region = impact_zone

    # 30-day window ending 5 days before landfall (pre)
    pre_start, pre_end = _date_range(landfall, -33), _date_range(landfall, -3)[1]
    pre_start = _date_range(landfall, -33)[0]

    # 30-day window starting 5 days after landfall (post)
    post_start = _date_range(landfall, 5)[0]
    post_end   = _date_range(landfall, 35)[1]

    pre  = _get_composite(pre_start,  pre_end,  impact_zone)
    post = _get_composite(post_start, post_end, impact_zone)

    return {
        "cyclone":      cyclone_name,
        "landfall_date": landfall,
        "impact_zone":  impact_zone,
        "pre":          pre.clip(impact_zone),
        "post":         post.clip(impact_zone),
        "pre_window":   (pre_start, pre_end),
        "post_window":  (post_start, post_end),
    }


def compute_vegetation_damage(pre, post, region, scale=30):
    """Compute NDVI difference (negative = vegetation loss).

    Returns:
        dict with keys 'ndvi_pre', 'ndvi_post', 'ndvi_diff',
        'mean_ndvi_pre', 'mean_ndvi_post', 'mean_ndvi_diff', 'max_ndvi_drop'
    """
    ndvi_pre  = _compute_ndvi(pre)
    ndvi_post = _compute_ndvi(post)
    # Positive diff = pre was higher = vegetation loss
    ndvi_diff = ndvi_pre.subtract(ndvi_post).rename("ndvi_diff")

    stats = ndvi_diff.reduceRegion(
        reducer=ee.Reducer.mean().combine(
            ee.Reducer.max(), sharedInputs=True
        ).combine(
            ee.Reducer.percentile([25, 75]), sharedInputs=True
        ),
        geometry=region,
        scale=max(scale, 100),
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )

    pre_stats = ndvi_pre.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region,
        scale=max(scale, 100),
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    post_stats = ndvi_post.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region,
        scale=max(scale, 100),
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )

    return {
        "ndvi_pre":       ndvi_pre,
        "ndvi_post":      ndvi_post,
        "ndvi_diff":      ndvi_diff,
        "mean_ndvi_pre":  pre_stats.get("ndvi"),
        "mean_ndvi_post": post_stats.get("ndvi"),
        "mean_ndvi_diff": stats.get("ndvi_diff_mean"),
        "max_ndvi_drop":  stats.get("ndvi_diff_max"),
        "p25_ndvi_diff":  stats.get("ndvi_diff_p25"),
        "p75_ndvi_diff":  stats.get("ndvi_diff_p75"),
    }


def compute_flood_extent(post, region, scale=30):
    """Classify post-cyclone flooding using water classification.

    Returns:
        dict with keys 'flood_mask', 'flood_area_km2'
    """
    flood_mask = classify_water(post, region=region, scale=scale)
    flood_mask = flood_mask.rename("flood")

    area = flood_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=max(scale, 100),
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    flood_area_km2 = ee.Number(area.get("flood")).divide(1e6)

    return {
        "flood_mask":     flood_mask,
        "flood_area_km2": flood_area_km2,
    }


def compute_damage_area(cyclone_name, region=None, scale=30):
    """Compute total affected area by damage severity (severe/moderate/mild).

    Severity tiers based on NDVI drop thresholds:
        severe   >= NDVI_SEVERE   (0.20)
        moderate >= NDVI_MODERATE (0.10)
        mild     >= NDVI_MILD     (0.05)

    Returns:
        dict with keys 'cyclone', 'severe_km2', 'moderate_km2', 'mild_km2',
        'total_damaged_km2', 'flood_area_km2', and raw images.
    """
    composites = get_pre_post_composites(cyclone_name, region)
    impact_zone = composites["impact_zone"]
    pre  = composites["pre"]
    post = composites["post"]

    veg = compute_vegetation_damage(pre, post, impact_zone, scale=scale)
    fld = compute_flood_extent(post, impact_zone, scale=scale)

    ndvi_diff = veg["ndvi_diff"]

    severe_mask   = ndvi_diff.gte(NDVI_SEVERE)
    moderate_mask = ndvi_diff.gte(NDVI_MODERATE).And(ndvi_diff.lt(NDVI_SEVERE))
    mild_mask     = ndvi_diff.gte(NDVI_MILD).And(ndvi_diff.lt(NDVI_MODERATE))
    total_mask    = ndvi_diff.gte(NDVI_MILD)

    def _area(mask, band=None):
        m = mask.rename("area") if band is None else mask.rename(band)
        a = m.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=impact_zone,
            scale=max(scale, 100),
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        return ee.Number(a.get("area")).divide(1e6)

    return {
        "cyclone":           cyclone_name,
        "landfall_date":     composites["landfall_date"],
        "severe_km2":        _area(severe_mask),
        "moderate_km2":      _area(moderate_mask),
        "mild_km2":          _area(mild_mask),
        "total_damaged_km2": _area(total_mask),
        "flood_area_km2":    fld["flood_area_km2"],
        "mean_ndvi_diff":    veg["mean_ndvi_diff"],
        "max_ndvi_drop":     veg["max_ndvi_drop"],
        "severe_mask":       severe_mask.clip(impact_zone),
        "moderate_mask":     moderate_mask.clip(impact_zone),
        "mild_mask":         mild_mask.clip(impact_zone),
        "flood_mask":        fld["flood_mask"],
        "impact_zone":       impact_zone,
    }


def compare_all_cyclones(region=None, scale=100):
    """Run damage assessment for all cyclones in cfg.CYCLONE_LANDFALL_POINTS.

    Returns:
        list of damage dicts, one per cyclone (sorted by date)
    """
    results = []
    for name in sorted(
        cfg.CYCLONE_LANDFALL_POINTS,
        key=lambda n: cfg.CYCLONE_LANDFALL_POINTS[n]["date"],
    ):
        print(f"  Assessing {name} ({cfg.CYCLONE_LANDFALL_POINTS[name]['date']})...")
        try:
            damage = compute_damage_area(name, region=region, scale=scale)
            results.append(damage)
            print(f"    Done.")
        except Exception as e:
            print(f"    {name} skipped: {e}")
            results.append({
                "cyclone":       name,
                "landfall_date": cfg.CYCLONE_LANDFALL_POINTS[name]["date"],
                "error":         str(e),
            })
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

def run_cyclone_damage_analysis(region=None):
    """Full cyclone damage assessment pipeline.

    Returns:
        dict with key 'cyclone_damage' (list of per-cyclone results)
    """
    print("\n  Comparing all cyclones: pre/post vegetation and flood damage...")
    results = compare_all_cyclones(region=region)

    return {"cyclone_damage": results}

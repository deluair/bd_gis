"""
Sentinel-1 SAR flood mapping: all-weather (cloud-penetrating) inundation
detection from VV backscatter. Complements optical flood_analysis, which fails
under the monsoon cloud cover that obscures Bangladesh more than 70 percent of
the time. Source: COPERNICUS/S1_GRD (ESA Copernicus).
"""
import ee
import config as cfg
from data_acquisition import get_study_area


def _scale_for_scope():
    """reduceRegion scale by configured scope (coarser at national extent)."""
    if cfg.SCOPE == "national":
        return 300
    if cfg.SCOPE.startswith("district:"):
        return 30
    return 100


def _seasonal_vv_composite(year, season, region):
    """Mean VV composite (dB) for a season. dry = Dec(y-1)-Feb(y), monsoon = Jul-Sep(y)."""
    if season == "dry":
        start_m, end_m = cfg.DRY_SEASON
        start = ee.Date.fromYMD(year - 1, start_m, 1)
        end = ee.Date.fromYMD(year, end_m, 28)
    else:
        start_m, end_m = cfg.MONSOON_SEASON
        start = ee.Date.fromYMD(year, start_m, 1)
        end = ee.Date.fromYMD(year, end_m, 30)

    col = (
        ee.ImageCollection(cfg.SENTINEL1_GRD["collection"])
        .filterBounds(region)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", cfg.SENTINEL1_GRD["instrument_mode"]))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .select("VV")
    )
    return col.mean().clip(region)


def get_sar_water(year, season="monsoon", region=None):
    """Binary water mask (band 'water') from Sentinel-1 VV thresholding."""
    if region is None:
        region = get_study_area()
    vv = _seasonal_vv_composite(year, season, region)
    # Speckle reduction before thresholding (focal median).
    smoothed = vv.focal_median(cfg.SENTINEL1_GRD["speckle_radius_m"], "circle", "meters")
    thr = cfg.SENTINEL1_GRD["vv_water_threshold_db"]
    return smoothed.lt(thr).rename("water")


def compute_sar_area_km2(mask, region, scale):
    """Area of a binary mask in km2 via pixelArea sum."""
    area_img = mask.multiply(ee.Image.pixelArea())
    stats = area_img.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return ee.Number(stats.get("water")).divide(1e6)


def get_annual_sar_flood(year, region=None):
    """Dry, monsoon, and seasonal (monsoon minus permanent) SAR water areas."""
    if region is None:
        region = get_study_area()
    scale = _scale_for_scope()
    dry = get_sar_water(year, "dry", region)
    monsoon = get_sar_water(year, "monsoon", region)
    seasonal = monsoon.And(dry.Not()).rename("water")
    dry_area = compute_sar_area_km2(dry, region, scale)
    monsoon_area = compute_sar_area_km2(monsoon, region, scale)
    seasonal_area = monsoon_area.subtract(dry_area)
    return {
        "year": year,
        "dry_water": dry,
        "monsoon_water": monsoon,
        "seasonal_flood": seasonal,
        "dry_area_km2": dry_area,
        "monsoon_area_km2": monsoon_area,
        "seasonal_area_km2": seasonal_area,
    }


def build_sar_flood_time_series(start_year, end_year, region=None, step=1):
    """List of annual SAR flood result dicts across a year range."""
    if region is None:
        region = get_study_area()
    results = []
    for year in range(start_year, end_year + 1, step):
        try:
            results.append(get_annual_sar_flood(year, region))
        except Exception as e:
            print(f"  Skipping SAR {year}: {e}")
    return results


def sar_division_water(year=2020, season="monsoon", scale=300):
    """{division ADM1_NAME: SAR water area km2} for a year and season.

    Keys are the same ADM1_NAME values used by the JRC reference loader, so the
    validation join is exact.
    """
    from data_acquisition import get_admin_boundaries
    admin = get_admin_boundaries()
    names = admin.aggregate_array("ADM1_NAME").distinct().getInfo()
    out = {}
    for name in names:
        geom = admin.filter(ee.Filter.eq("ADM1_NAME", name)).geometry()
        mask = get_sar_water(year, season, geom)
        out[name] = compute_sar_area_km2(mask, geom, scale).getInfo()
    return out


def compute_district_sar_stats(water_mask, districts_fc):
    """Per-district SAR water area and percent for a given mask."""
    scale = _scale_for_scope()

    def _per(feature):
        geom = feature.geometry()
        area_km2 = compute_sar_area_km2(water_mask, geom, scale)
        total = geom.area().divide(1e6)
        return feature.set({
            "sar_water_area_km2": area_km2,
            "total_area_km2": total,
            "sar_water_pct": area_km2.divide(total).multiply(100),
        })

    return districts_fc.map(_per)

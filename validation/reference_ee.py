"""Earth Engine ground-truth reference loaders. These call GEE (need init), so they
are isolated from the pure loaders in reference.py. Each returns {spatial_unit: value}."""
import ee

import config as cfg
from data_acquisition import get_admin_boundaries


def _division_units():
    """Return (admin FeatureCollection, list of ADM1_NAME division names)."""
    admin = get_admin_boundaries()
    names = admin.aggregate_array("ADM1_NAME").distinct().getInfo()
    return admin, names


def _area_km2(mask, geom, scale=300):
    """km2 of a binary mask (band 'water') over a geometry."""
    img = mask.multiply(ee.Image.pixelArea())
    stats = img.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=geom, scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return ee.Number(stats.get("water")).divide(1e6).getInfo()


def load_jrc_division_water(year=2020, season_months=(7, 8, 9)):
    """{division ADM1_NAME: JRC monthly water area km2} for the season months.

    Source JRC/GSW1_4/MonthlyHistory band 'water' (2 = water). A pixel counts as
    seasonal water if classified water in ANY of the season months (max over months),
    matching the SAR monsoon composite. Reference period recorded on the card.
    """
    start = ee.Date.fromYMD(year, season_months[0], 1)
    end = ee.Date.fromYMD(year, season_months[-1], 28)
    water = (
        ee.ImageCollection(cfg.JRC_MONTHLY)
        .filterDate(start, end)
        .map(lambda im: im.select("water").eq(2))
        .max()
        .rename("water")
    )
    admin, names = _division_units()
    out = {}
    for name in names:
        geom = admin.filter(ee.Filter.eq("ADM1_NAME", name)).geometry()
        out[name] = _area_km2(water.clip(geom), geom)
    return out

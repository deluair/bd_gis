"""
Timelapse animation module – yearly GIF animations from satellite composites.

Uses GEE's getVideoThumbURL() to generate animated GIFs directly from
ImageCollections, then saves them to outputs/timelapse/.

Functions:
    generate_urban_timelapse(region, start_year, end_year)
    generate_ndvi_timelapse(region, start_year, end_year)
    generate_water_timelapse(region, start_year, end_year)
    generate_nightlights_timelapse(region, start_year, end_year)
    run_timelapse(region)
"""
import os
import urllib.request

import ee
import config as cfg
from export_utils import ensure_output_dir


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _get_region(region):
    """Resolve region to ee.Geometry if not already provided."""
    if region is not None:
        return region
    b = cfg.STUDY_AREA_BOUNDS
    return ee.Geometry.Rectangle([b["west"], b["south"], b["east"], b["north"]])


def _timelapse_dir():
    return ensure_output_dir("timelapse")


def _output_path(name, start_year, end_year):
    return os.path.join(_timelapse_dir(), f"{name}_{start_year}_{end_year}.gif")


def _download_gif(url, out_path):
    """Download GIF bytes from GEE thumbnail URL to disk."""
    print(f"  Downloading: {out_path}")
    try:
        urllib.request.urlretrieve(url, out_path)
        size_kb = os.path.getsize(out_path) / 1024
        print(f"  Saved ({size_kb:.1f} KB): {out_path}")
        return out_path
    except Exception as e:
        print(f"  Download failed: {e}")
        return None


def _year_range(start_year, end_year):
    return list(range(start_year, end_year + 1))


# ═══════════════════════════════════════════════════════════════════════════════
# Urban (GHSL built-up area)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_urban_timelapse(region=None, start_year=1990, end_year=2020):
    """
    GHSL built-up area growth animation.

    GHSL epochs are 5-year intervals (1975, 1980, ..., 2020, 2025).
    Years between epochs snap to the nearest available epoch.

    Returns path to saved GIF or None on failure.
    """
    region = _get_region(region)
    out_path = _output_path("urban_ghsl", start_year, end_year)

    print(f"\n[urban timelapse] GHSL built-up {start_year}-{end_year}")

    try:
        ghsl_col = ee.ImageCollection(cfg.GHSL_BUILT["collection"])

        # GHSL available epochs
        ghsl_epochs = [1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025]

        def nearest_epoch(year):
            return min(ghsl_epochs, key=lambda e: abs(e - year))

        # Build per-year images (snapped to nearest GHSL epoch)
        images = []
        years_used = []
        for year in _year_range(start_year, end_year):
            epoch = nearest_epoch(year)
            if epoch in years_used:
                continue
            years_used.append(epoch)
            img = (
                ghsl_col
                .filterMetadata("system:index", "contains", str(epoch))
                .first()
            )
            if img is not None:
                images.append(img.select(cfg.GHSL_BUILT["band"]).set("year", epoch))

        if not images:
            print("  No GHSL images found for the requested range.")
            return None

        col = ee.ImageCollection(images)

        vis_params = {
            "min": 0,
            "max": 5000,
            "palette": ["000000", "1a1a1a", "ffcc00", "ff6600", "cc0000", "ffffff"],
            "region": region,
            "dimensions": 512,
            "framesPerSecond": 2,
            "crs": "EPSG:4326",
        }

        url = col.getVideoThumbURL(vis_params)
        return _download_gif(url, out_path)

    except Exception as e:
        print(f"  Urban timelapse failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# NDVI (vegetation change)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_ndvi_timelapse(region=None, start_year=2000, end_year=2024):
    """
    Annual NDVI vegetation change animation using MODIS MOD13A2.

    Each frame is the dry-season (Jan-Mar) mean NDVI for that year,
    scaled by MODIS scale factor (0.0001).

    Returns path to saved GIF or None on failure.
    """
    region = _get_region(region)
    out_path = _output_path("ndvi_vegetation", start_year, end_year)

    print(f"\n[ndvi timelapse] MODIS NDVI {start_year}-{end_year}")

    modis_start = cfg.MODIS_NDVI["years"][0]
    modis_end = cfg.MODIS_NDVI["years"][1]
    start_year = max(start_year, modis_start)
    end_year = min(end_year, modis_end)

    try:
        modis = ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        scale = cfg.MODIS_NDVI["scale_factor"]

        images = []
        for year in _year_range(start_year, end_year):
            # Dry season (Jan-Mar) avoids cloud issues and shows vegetation stress
            img = (
                modis
                .filterBounds(region)
                .filterDate(f"{year}-01-01", f"{year}-03-31")
                .select(cfg.MODIS_NDVI["ndvi_band"])
                .mean()
                .multiply(scale)
                .set("year", year)
                .rename("NDVI")
            )
            images.append(img)

        col = ee.ImageCollection(images)

        vis_params = {
            "min": 0.0,
            "max": 0.8,
            "palette": [
                "ffffff", "ce7e45", "df923d", "f1b555", "fcd163",
                "99b718", "74a901", "66a000", "529400", "3e8601",
                "207401", "056201", "004c00", "023b01", "012e01",
            ],
            "region": region,
            "dimensions": 512,
            "framesPerSecond": 3,
            "crs": "EPSG:4326",
            "bands": ["NDVI"],
        }

        url = col.getVideoThumbURL(vis_params)
        return _download_gif(url, out_path)

    except Exception as e:
        print(f"  NDVI timelapse failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Water extent (monsoon season)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_water_timelapse(region=None, start_year=1985, end_year=2024):
    """
    Annual monsoon-season water extent animation using JRC Monthly Water History.

    Each frame is the August water mask for that year (peak monsoon inundation).

    Returns path to saved GIF or None on failure.
    """
    region = _get_region(region)
    out_path = _output_path("water_monsoon", start_year, end_year)

    print(f"\n[water timelapse] JRC monsoon water {start_year}-{end_year}")

    # JRC Monthly Water available from 1984
    start_year = max(start_year, 1984)

    try:
        jrc_monthly = ee.ImageCollection(cfg.JRC_MONTHLY)

        images = []
        for year in _year_range(start_year, end_year):
            # August = peak monsoon in Bangladesh
            img = (
                jrc_monthly
                .filterBounds(region)
                .filterDate(f"{year}-08-01", f"{year}-08-31")
                .select("water")
                .max()
                .set("year", year)
                .rename("water")
            )
            images.append(img)

        col = ee.ImageCollection(images)

        vis_params = {
            "min": 0,
            "max": 2,
            "palette": ["ffffff", "4169e1", "000080"],
            "region": region,
            "dimensions": 512,
            "framesPerSecond": 3,
            "crs": "EPSG:4326",
            "bands": ["water"],
        }

        url = col.getVideoThumbURL(vis_params)
        return _download_gif(url, out_path)

    except Exception as e:
        print(f"  Water timelapse failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Nighttime lights
# ═══════════════════════════════════════════════════════════════════════════════

def generate_nightlights_timelapse(region=None, start_year=1992, end_year=2024):
    """
    Annual nighttime lights growth animation.

    Uses DMSP-OLS (1992-2013) and VIIRS DNB (2014+).
    Cross-sensor values are not comparable; the animation shows relative
    within-sensor trends. DMSP and VIIRS are normalized separately to [0,1]
    before encoding to avoid abrupt visual breaks at the 2013/2014 boundary.

    Returns path to saved GIF or None on failure.
    """
    region = _get_region(region)
    out_path = _output_path("nightlights", start_year, end_year)

    print(f"\n[nightlights timelapse] DMSP/VIIRS {start_year}-{end_year}")

    dmsp_start, dmsp_end = cfg.DMSP_OLS["years"]
    viirs_start, viirs_end = cfg.VIIRS_DNB["years"]

    try:
        images = []

        # DMSP-OLS segment
        if start_year <= dmsp_end:
            dmsp_col = ee.ImageCollection(cfg.DMSP_OLS["collection"])
            for year in _year_range(max(start_year, dmsp_start), min(end_year, dmsp_end)):
                img = (
                    dmsp_col
                    .filterBounds(region)
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                    .select(cfg.DMSP_OLS["band"])
                    .mean()
                    # Normalize DMSP to [0, 1] (raw range 0-63)
                    .divide(63.0)
                    .set("year", year)
                    .rename("lights")
                )
                images.append(img)

        # VIIRS DNB segment
        if end_year >= viirs_start:
            viirs_col = ee.ImageCollection(cfg.VIIRS_DNB["collection"])
            for year in _year_range(max(start_year, viirs_start), min(end_year, viirs_end)):
                img = (
                    viirs_col
                    .filterBounds(region)
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                    .select(cfg.VIIRS_DNB["band"])
                    .mean()
                    # Normalize VIIRS to [0, 1] (clip at 100 nW/cm2/sr)
                    .divide(100.0)
                    .clamp(0, 1)
                    .set("year", year)
                    .rename("lights")
                )
                images.append(img)

        if not images:
            print("  No nightlights images found for the requested range.")
            return None

        col = ee.ImageCollection(images)

        vis_params = {
            "min": 0.0,
            "max": 1.0,
            "palette": ["000000", "1a1a2e", "16213e", "0f3460", "533483",
                        "e94560", "f5a623", "ffffff"],
            "region": region,
            "dimensions": 512,
            "framesPerSecond": 3,
            "crs": "EPSG:4326",
            "bands": ["lights"],
        }

        url = col.getVideoThumbURL(vis_params)
        return _download_gif(url, out_path)

    except Exception as e:
        print(f"  Nightlights timelapse failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

def run_timelapse(region=None):
    """
    Run all four timelapse animations with default year ranges.

    Year ranges are chosen to maximize data availability per sensor:
      - Urban:       1990-2020 (GHSL epochs)
      - NDVI:        2000-2024 (MODIS)
      - Water:       1985-2024 (JRC Monthly)
      - Nightlights: 1992-2024 (DMSP + VIIRS)

    Returns dict of {name: path_or_None}.
    """
    from data_acquisition import init_gee, get_study_area

    init_gee()
    if region is None:
        region = get_study_area()

    ensure_output_dir("timelapse")

    print("\n" + "=" * 60)
    print(f"TIMELAPSE ANIMATIONS – {cfg.scope_label()}")
    print("=" * 60)

    results = {}

    results["urban"] = generate_urban_timelapse(
        region=region, start_year=1990, end_year=2020
    )
    results["ndvi"] = generate_ndvi_timelapse(
        region=region, start_year=2000, end_year=2024
    )
    results["water"] = generate_water_timelapse(
        region=region, start_year=1985, end_year=2024
    )
    results["nightlights"] = generate_nightlights_timelapse(
        region=region, start_year=1992, end_year=2024
    )

    print("\n" + "=" * 60)
    ok = [k for k, v in results.items() if v is not None]
    failed = [k for k, v in results.items() if v is None]
    print(f"TIMELAPSE COMPLETE: {len(ok)} saved, {len(failed)} failed")
    for name, path in results.items():
        status = path if path else "FAILED"
        print(f"  {name}: {status}")
    print("=" * 60)

    return results

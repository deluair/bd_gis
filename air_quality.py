"""
Air quality analysis – Sentinel-5P TROPOMI pollutant mapping for NO2, SO2,
CO, aerosol index, and formaldehyde over Bangladesh (2018–present).
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Data Loading
# ═══════════════════════════════════════════════════════════════════════════════

def get_pollutant(pollutant, start_date, end_date, region):
    """
    Get Sentinel-5P mean composite for a pollutant over a date range.
    pollutant: one of 'NO2', 'SO2', 'CO', 'AEROSOL', 'HCHO'
    """
    info = cfg.SENTINEL5P[pollutant]
    col = (
        ee.ImageCollection(info["collection"])
        .filterDate(start_date, end_date)
        .filterBounds(region)
        .select(info["band"])
    )
    return col.mean().clip(region)


def get_no2(start_date, end_date, region):
    """Get tropospheric NO2 column density."""
    return get_pollutant("NO2", start_date, end_date, region)


def get_so2(start_date, end_date, region):
    """Get SO2 column density."""
    return get_pollutant("SO2", start_date, end_date, region)


def get_co(start_date, end_date, region):
    """Get CO column density."""
    return get_pollutant("CO", start_date, end_date, region)


def get_aerosol_index(start_date, end_date, region):
    """Get UV Absorbing Aerosol Index."""
    return get_pollutant("AEROSOL", start_date, end_date, region)


# ═══════════════════════════════════════════════════════════════════════════════
# Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def compute_pollutant_stats(pollutant, start_date, end_date, region, scale=5000):
    """Compute mean, max, and median of a pollutant over a region."""
    image = get_pollutant(pollutant, start_date, end_date, region)
    info = cfg.SENTINEL5P[pollutant]
    band = info["band"]

    stats = image.reduceRegion(
        reducer=ee.Reducer.mean().combine(
            ee.Reducer.max(), sharedInputs=True
        ).combine(
            ee.Reducer.median(), sharedInputs=True
        ),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return {
        "pollutant": pollutant,
        "period": f"{start_date} to {end_date}",
        "mean": stats.get(f"{band}_mean"),
        "max": stats.get(f"{band}_max"),
        "median": stats.get(f"{band}_median"),
    }


def compute_annual_pollutant_timeseries(pollutant, region, start_year=2019,
                                         end_year=2024, scale=5000):
    """Annual mean pollutant concentration over time."""
    series = []
    for year in range(start_year, end_year + 1):
        try:
            stats = compute_pollutant_stats(
                pollutant, f"{year}-01-01", f"{year}-12-31", region, scale
            )
            stats["year"] = year
            series.append(stats)
        except Exception as e:
            print(f"  {pollutant} {year} skipped: {e}")
    return series


def compute_seasonal_pollutant(pollutant, year, region, scale=5000):
    """Compute pollutant stats by season for a given year."""
    seasons = {
        "winter": (f"{year}-01-01", f"{year}-02-28"),
        "pre_monsoon": (f"{year}-03-01", f"{year}-05-31"),
        "monsoon": (f"{year}-06-01", f"{year}-09-30"),
        "post_monsoon": (f"{year}-10-01", f"{year}-12-31"),
    }
    results = {"year": year, "pollutant": pollutant}
    for season, (start, end) in seasons.items():
        try:
            stats = compute_pollutant_stats(pollutant, start, end, region, scale)
            results[f"{season}_mean"] = stats["mean"]
        except Exception:
            results[f"{season}_mean"] = None
    return results


def compute_urban_pollution(pollutant, year, scale=2000):
    """Compute pollutant levels for each major urban center."""
    results = []
    for city, info in cfg.URBAN_CENTERS.items():
        point = ee.Geometry.Point([info["lon"], info["lat"]])
        city_region = point.buffer(info["radius"])
        try:
            stats = compute_pollutant_stats(
                pollutant, f"{year}-01-01", f"{year}-12-31", city_region, scale
            )
            stats["city"] = city
            stats["year"] = year
            results.append(stats)
        except Exception as e:
            print(f"  {city} {pollutant} skipped: {e}")
    return results


def compute_pollution_hotspots(pollutant, start_date, end_date, region,
                                percentile=90, scale=5000):
    """
    Identify pollution hotspots (pixels above a given percentile).
    Returns binary hotspot mask and threshold value.
    """
    image = get_pollutant(pollutant, start_date, end_date, region)
    info = cfg.SENTINEL5P[pollutant]
    band = info["band"]

    threshold = image.reduceRegion(
        reducer=ee.Reducer.percentile([percentile]),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    thresh_val = ee.Number(threshold.get(f"{band}_p{percentile}"))
    hotspots = image.select(band).gte(thresh_val).rename("hotspot")

    return {
        "hotspots": hotspots,
        "threshold": thresh_val,
        "pollutant": pollutant,
    }


def compute_aqi_composite(start_date, end_date, region):
    """
    Create a multi-pollutant composite image for air quality overview.
    Bands: NO2, SO2, CO, AEROSOL.
    """
    no2 = get_no2(start_date, end_date, region).rename("NO2")
    so2 = get_so2(start_date, end_date, region).rename("SO2")
    co = get_co(start_date, end_date, region).rename("CO")
    aer = get_aerosol_index(start_date, end_date, region).rename("Aerosol")
    return no2.addBands([so2, co, aer])


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_air_quality_analysis(region):
    """Full air quality analysis pipeline."""
    results = {}

    pollutants = ["NO2", "SO2", "CO", "AEROSOL"]

    print("\n  Computing annual pollutant time series (2019–2024)...")
    results["timeseries"] = {}
    for p in pollutants:
        print(f"    {p}...")
        results["timeseries"][p] = compute_annual_pollutant_timeseries(p, region)

    print("  Computing seasonal patterns for 2023...")
    results["seasonal_2023"] = {}
    for p in pollutants:
        try:
            results["seasonal_2023"][p] = compute_seasonal_pollutant(p, 2023, region)
        except Exception as e:
            print(f"    Seasonal {p} skipped: {e}")

    print("  Computing urban center pollution levels...")
    results["urban_pollution"] = {}
    for p in ["NO2", "SO2"]:
        try:
            results["urban_pollution"][p] = compute_urban_pollution(p, 2023)
        except Exception as e:
            print(f"    Urban {p} skipped: {e}")

    print("  Identifying pollution hotspots...")
    results["hotspots"] = {}
    for p in pollutants:
        try:
            results["hotspots"][p] = compute_pollution_hotspots(
                p, "2023-01-01", "2023-12-31", region
            )
        except Exception as e:
            print(f"    Hotspots {p} skipped: {e}")

    print("  Creating multi-pollutant composite...")
    try:
        results["aqi_composite"] = compute_aqi_composite(
            "2023-01-01", "2023-12-31", region
        )
    except Exception as e:
        print(f"    AQI composite skipped: {e}")

    return results

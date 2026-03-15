"""
Climate analysis – rainfall (CHIRPS), land surface temperature (MODIS LST),
drought indices, and ERA5 reanalysis for long-term climate trend detection.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Rainfall (CHIRPS)
# ═══════════════════════════════════════════════════════════════════════════════

def get_chirps_annual(year, region):
    """Get CHIRPS total annual precipitation (mm)."""
    col = (
        ee.ImageCollection(cfg.CHIRPS["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .select(cfg.CHIRPS["band"])
    )
    return col.sum().clip(region).rename("annual_precip_mm")


def get_chirps_monthly(year, month, region):
    """Get CHIRPS total monthly precipitation (mm)."""
    end_month = month + 1 if month < 12 else 1
    end_year = year if month < 12 else year + 1
    col = (
        ee.ImageCollection(cfg.CHIRPS["collection"])
        .filterDate(f"{year}-{month:02d}-01", f"{end_year}-{end_month:02d}-01")
        .filterBounds(region)
        .select(cfg.CHIRPS["band"])
    )
    return col.sum().clip(region).rename("monthly_precip_mm")


def compute_rainfall_timeseries(region, start_year=1985, end_year=2024, step=1, scale=5000):
    """Compute annual total and mean rainfall over time."""
    series = []
    for year in range(start_year, end_year + 1, step):
        try:
            annual = get_chirps_annual(year, region)
            stats = annual.reduceRegion(
                reducer=ee.Reducer.mean().combine(
                    ee.Reducer.max(), sharedInputs=True
                ),
                geometry=region, scale=scale,
                maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            series.append({
                "year": year,
                "mean_precip_mm": stats.get("annual_precip_mm_mean"),
                "max_precip_mm": stats.get("annual_precip_mm_max"),
            })
        except Exception as e:
            print(f"  Rainfall {year} skipped: {e}")
    return series


def compute_monsoon_rainfall(year, region, scale=5000):
    """Compute total monsoon season (Jun-Sep) rainfall."""
    col = (
        ee.ImageCollection(cfg.CHIRPS["collection"])
        .filterDate(f"{year}-06-01", f"{year}-09-30")
        .filterBounds(region)
        .select(cfg.CHIRPS["band"])
    )
    monsoon_total = col.sum().clip(region)
    stats = monsoon_total.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region, scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "year": year,
        "monsoon_precip_mm": stats.get("precipitation"),
        "image": monsoon_total,
    }


def compute_rainfall_anomaly(year, region, ref_start=1985, ref_end=2015):
    """
    Compute rainfall anomaly: deviation from long-term mean.
    Positive = wetter than average, negative = drier.
    """
    # Long-term mean annual precipitation
    lt_years = list(range(ref_start, ref_end + 1))
    lt_images = []
    for y in lt_years:
        try:
            lt_images.append(get_chirps_annual(y, region))
        except Exception:
            pass

    if not lt_images:
        raise ValueError("No reference data available")

    lt_col = ee.ImageCollection(lt_images)
    lt_mean = lt_col.mean().rename("annual_precip_mm")

    current = get_chirps_annual(year, region)
    anomaly = current.subtract(lt_mean).rename("precip_anomaly_mm")
    return anomaly


# ═══════════════════════════════════════════════════════════════════════════════
# Temperature (MODIS LST)
# ═══════════════════════════════════════════════════════════════════════════════

def get_lst_annual(year, region, time_of_day="day"):
    """
    Get MODIS annual mean land surface temperature (Celsius).
    time_of_day: 'day' or 'night'
    """
    band = cfg.MODIS_LST["day_band"] if time_of_day == "day" else cfg.MODIS_LST["night_band"]
    col = (
        ee.ImageCollection(cfg.MODIS_LST["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .select(band)
    )
    # Scale to Kelvin, then convert to Celsius
    mean_lst = col.mean().multiply(cfg.MODIS_LST["scale_factor"]).add(
        cfg.MODIS_LST["kelvin_offset"]
    ).clip(region).rename("lst_celsius")
    return mean_lst


def compute_lst_timeseries(region, start_year=2000, end_year=2024, step=1, scale=1000):
    """Compute annual mean day/night LST over time."""
    series = []
    for year in range(start_year, end_year + 1, step):
        try:
            day_lst = get_lst_annual(year, region, "day")
            night_lst = get_lst_annual(year, region, "night")

            day_stats = day_lst.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region,
                scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            night_stats = night_lst.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region,
                scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            series.append({
                "year": year,
                "day_lst_c": day_stats.get("lst_celsius"),
                "night_lst_c": night_stats.get("lst_celsius"),
            })
        except Exception as e:
            print(f"  LST {year} skipped: {e}")
    return series


def compute_uhi_effect(year, city_name, buffer_urban=5000, buffer_rural=25000, scale=1000):
    """
    Compute Urban Heat Island effect for a city.
    UHI = mean urban LST - mean surrounding rural LST.
    """
    if city_name not in cfg.URBAN_CENTERS:
        raise ValueError(f"Unknown city: {city_name}")

    info = cfg.URBAN_CENTERS[city_name]
    center = ee.Geometry.Point([info["lon"], info["lat"]])
    urban_zone = center.buffer(buffer_urban)
    rural_ring = center.buffer(buffer_rural).difference(center.buffer(buffer_urban + 2000))

    day_lst = get_lst_annual(year, urban_zone.union(rural_ring), "day")

    urban_temp = day_lst.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=urban_zone,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    rural_temp = day_lst.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=rural_ring,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )

    return {
        "city": city_name,
        "year": year,
        "urban_lst_c": urban_temp.get("lst_celsius"),
        "rural_lst_c": rural_temp.get("lst_celsius"),
        "uhi_intensity_c": ee.Number(urban_temp.get("lst_celsius")).subtract(
            ee.Number(rural_temp.get("lst_celsius"))
        ),
    }


def compute_seasonal_temperature(year, region, scale=1000):
    """Compute seasonal mean LST for a given year."""
    seasons = {
        "winter": (f"{year}-01-01", f"{year}-02-28"),
        "pre_monsoon": (f"{year}-03-01", f"{year}-05-31"),
        "monsoon": (f"{year}-06-01", f"{year}-09-30"),
        "post_monsoon": (f"{year}-10-01", f"{year}-12-31"),
    }
    results = {"year": year}
    for season, (start, end) in seasons.items():
        try:
            col = (
                ee.ImageCollection(cfg.MODIS_LST["collection"])
                .filterDate(start, end)
                .filterBounds(region)
                .select(cfg.MODIS_LST["day_band"])
            )
            mean_img = col.mean().multiply(cfg.MODIS_LST["scale_factor"]).add(
                cfg.MODIS_LST["kelvin_offset"]
            ).clip(region)
            stats = mean_img.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region,
                scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            results[f"{season}_lst_c"] = stats.get(cfg.MODIS_LST["day_band"])
        except Exception:
            results[f"{season}_lst_c"] = None
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Drought Index
# ═══════════════════════════════════════════════════════════════════════════════

def compute_drought_severity(year, region, scale=5000):
    """
    Simple drought proxy using rainfall anomaly + temperature anomaly.
    Negative values = drought conditions.
    """
    try:
        precip_anomaly = compute_rainfall_anomaly(year, region)
    except Exception:
        return None

    # Normalize precipitation anomaly to roughly -1 to 1
    precip_norm = precip_anomaly.divide(500).clamp(-2, 2).rename("precip_norm")

    # Temperature anomaly (higher temp = worse drought)
    try:
        lst = get_lst_annual(year, region, "day")
        lt_lst = (
            ee.ImageCollection(cfg.MODIS_LST["collection"])
            .filterDate("2000-01-01", "2020-12-31")
            .filterBounds(region)
            .select(cfg.MODIS_LST["day_band"])
            .mean()
            .multiply(cfg.MODIS_LST["scale_factor"])
            .add(cfg.MODIS_LST["kelvin_offset"])
            .clip(region)
            .rename("lst_celsius")
        )
        temp_anomaly = lst.subtract(lt_lst).divide(5).multiply(-1).rename("temp_norm")
        drought = precip_norm.add(temp_anomaly).divide(2).rename("drought_index")
    except Exception:
        drought = precip_norm.rename("drought_index")

    return drought


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_climate_analysis(region):
    """Full climate analysis pipeline."""
    results = {}

    print("\n  Computing rainfall time series (CHIRPS 1985–2024)...")
    results["rainfall_timeseries"] = compute_rainfall_timeseries(region, step=2)

    print("  Computing LST time series (MODIS 2000–2024)...")
    results["lst_timeseries"] = compute_lst_timeseries(region, step=2)

    print("  Computing Urban Heat Island effects...")
    results["uhi"] = {}
    for city in ["Dhaka", "Chittagong", "Khulna", "Rajshahi"]:
        try:
            results["uhi"][city] = compute_uhi_effect(2023, city)
        except Exception as e:
            print(f"    UHI {city} skipped: {e}")

    print("  Computing monsoon rainfall trends...")
    results["monsoon_rainfall"] = []
    for year in range(1990, 2025, 2):
        try:
            results["monsoon_rainfall"].append(compute_monsoon_rainfall(year, region))
        except Exception as e:
            print(f"    Monsoon rainfall {year} skipped: {e}")

    print("  Computing drought severity for recent years...")
    results["drought"] = {}
    for year in [2010, 2015, 2019, 2022, 2024]:
        try:
            results["drought"][year] = compute_drought_severity(year, region)
        except Exception as e:
            print(f"    Drought {year} skipped: {e}")

    return results

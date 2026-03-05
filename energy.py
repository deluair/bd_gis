"""
Renewable energy potential mapping – solar irradiance, wind resource
estimation, biomass availability, and energy access indicators
for Bangladesh using satellite-derived datasets.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Solar Energy Potential
# ═══════════════════════════════════════════════════════════════════════════════

# NASA POWER / ERA5 shortwave radiation as solar proxy
SOLAR_RADIATION = {
    "collection": "ECMWF/ERA5_LAND/MONTHLY_AGGR",
    "band": "surface_net_solar_radiation_sum",
    "scale": 11132,
}


def compute_solar_irradiance(year, region, scale=10000):
    """
    Compute annual mean solar irradiance (W/m2) from ERA5.
    Higher values = better solar energy potential.
    """
    col = (
        ee.ImageCollection(SOLAR_RADIATION["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .select(SOLAR_RADIATION["band"])
    )
    # Monthly sum → daily average (J/m2 → W/m2 roughly: divide by seconds in month)
    annual_mean = col.mean().clip(region).rename("solar_irradiance")
    return annual_mean


def compute_solar_potential_map(region, year=2023, scale=10000):
    """
    Map solar energy potential across Bangladesh.
    Accounts for: irradiance, cloud cover, available land.
    """
    irradiance = compute_solar_irradiance(year, region)

    # Cloud cover penalty: use rainy months (Jun-Sep) vs dry (Nov-Feb)
    dry_season = (
        ee.ImageCollection(SOLAR_RADIATION["collection"])
        .filterDate(f"{year}-11-01", f"{year + 1}-02-28")
        .filterBounds(region)
        .select(SOLAR_RADIATION["band"])
        .mean()
        .clip(region)
    )
    monsoon = (
        ee.ImageCollection(SOLAR_RADIATION["collection"])
        .filterDate(f"{year}-06-01", f"{year}-09-30")
        .filterBounds(region)
        .select(SOLAR_RADIATION["band"])
        .mean()
        .clip(region)
    )

    # Seasonal variation ratio (lower = more consistent)
    consistency = monsoon.divide(dry_season.max(ee.Image.constant(1))).clamp(0, 1).rename("solar_consistency")

    # Available land (exclude water and dense urban)
    from land_cover import get_esa_worldcover
    try:
        wc = get_esa_worldcover(2021, region)
        available = wc.neq(80).And(wc.neq(50))  # not water, not built-up
    except Exception:
        available = ee.Image.constant(1).clip(region)

    solar_score = irradiance.unitScale(0, 20000000).clamp(0, 1).multiply(
        available.unmask(0)
    ).rename("solar_potential")

    return {
        "solar_potential": solar_score,
        "irradiance": irradiance,
        "consistency": consistency,
    }


def compute_solar_stats(region, year=2023, scale=10000):
    """Compute regional solar statistics."""
    irradiance = compute_solar_irradiance(year, region)
    stats = irradiance.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.max(), sharedInputs=True),
        geometry=region, scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "year": year,
        "mean_irradiance": stats.get("solar_irradiance_mean"),
        "max_irradiance": stats.get("solar_irradiance_max"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Wind Energy Potential
# ═══════════════════════════════════════════════════════════════════════════════

def compute_wind_speed(year, region, scale=10000):
    """
    Compute annual mean 10m wind speed from ERA5-Land.
    Wind speed = sqrt(u^2 + v^2)
    """
    col = (
        ee.ImageCollection(cfg.ERA5_LAND["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
    )

    def calc_wind(img):
        u = img.select("u_component_of_wind_10m")
        v = img.select("v_component_of_wind_10m")
        return u.pow(2).add(v.pow(2)).sqrt().rename("wind_speed_ms")

    wind_col = col.map(calc_wind)
    return wind_col.mean().clip(region)


def compute_wind_potential(region, year=2023, scale=10000):
    """
    Map wind energy potential. Wind power density ~ wind_speed^3.
    """
    wind = compute_wind_speed(year, region)
    # Wind power density proxy (normalized)
    wpd = wind.pow(3).rename("wind_power_density")
    # Normalize to 0-1 for scoring
    score = wpd.unitScale(0, 500).clamp(0, 1).rename("wind_potential")
    return {"wind_speed": wind, "wind_potential": score}


# ═══════════════════════════════════════════════════════════════════════════════
# Biomass Estimation
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_biomass(year, region, scale=1000):
    """
    Estimate above-ground biomass proxy using NDVI.
    Biomass ~ NDVI^2 (empirical relationship for tropical regions).
    """
    from vegetation import get_modis_ndvi_annual
    ndvi = get_modis_ndvi_annual(year, region)
    biomass = ndvi.pow(2).multiply(100).rename("biomass_proxy")  # arbitrary units
    return biomass


def compute_biomass_stats(year, region, scale=1000):
    """Compute regional biomass statistics."""
    biomass = estimate_biomass(year, region)
    stats = biomass.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.sum(), sharedInputs=True),
        geometry=region, scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "year": year,
        "mean_biomass": stats.get("biomass_proxy_mean"),
        "total_biomass": stats.get("biomass_proxy_sum"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Energy Access
# ═══════════════════════════════════════════════════════════════════════════════

def compute_energy_access(year, region, scale=1000):
    """
    Energy access indicator combining electrification status + light intensity.
    Uses nighttime lights as proxy for electricity availability and quality.
    """
    from nightlights import get_nightlights, classify_electrification

    try:
        elec = classify_electrification(year, region, threshold=0.5)
    except Exception:
        return None

    lights = get_nightlights(year, region)
    band_name = lights.bandNames().getInfo()[0]
    light_quality = lights.select(band_name).unitScale(0, 30).clamp(0, 1).rename("light_quality")

    # Energy access score: electrified * light quality
    access = elec["mask"].toFloat().multiply(light_quality).rename("energy_access")
    return access


def compute_energy_poverty(year, region, scale=1000):
    """
    Energy poverty: population in unelectrified or poorly-lit areas.
    """
    access = compute_energy_access(year, region)
    if access is None:
        return None

    from poverty import get_population_density
    try:
        pop = get_population_density(year, region)
    except Exception:
        return None

    # Energy poor = population * (1 - access)
    energy_deficit = ee.Image.constant(1).subtract(access)
    energy_poor = pop.multiply(energy_deficit).rename("energy_poor_pop")

    stats = energy_poor.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region, scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "year": year,
        "energy_poor_population": stats.get("energy_poor_pop"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_energy_analysis(region):
    """Full energy analysis pipeline."""
    results = {}

    print("\n  Computing solar energy potential...")
    try:
        results["solar"] = compute_solar_potential_map(region)
        results["solar_stats"] = compute_solar_stats(region)
    except Exception as e:
        print(f"    Solar potential skipped: {e}")

    print("  Computing wind energy potential...")
    try:
        results["wind"] = compute_wind_potential(region)
    except Exception as e:
        print(f"    Wind potential skipped: {e}")

    print("  Estimating biomass resources...")
    try:
        results["biomass"] = estimate_biomass(2023, region)
        results["biomass_stats"] = compute_biomass_stats(2023, region)
    except Exception as e:
        print(f"    Biomass estimation skipped: {e}")

    print("  Computing energy access...")
    try:
        results["energy_access"] = compute_energy_access(2020, region)
    except Exception as e:
        print(f"    Energy access skipped: {e}")

    print("  Computing energy poverty...")
    try:
        results["energy_poverty"] = compute_energy_poverty(2020, region)
    except Exception as e:
        print(f"    Energy poverty skipped: {e}")

    print("  Computing energy access time series...")
    results["energy_timeseries"] = []
    for year in [2000, 2005, 2010, 2015, 2020]:
        try:
            ep = compute_energy_poverty(year, region)
            if ep:
                results["energy_timeseries"].append(ep)
        except Exception as e:
            print(f"    Energy {year} skipped: {e}")

    return results

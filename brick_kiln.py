"""
Brick kiln detection -- thermal anomaly, spectral signature, and density mapping
for Bangladesh. ~8,000 kilns are active Oct-May (dry season), dormant Jun-Sep.
Detection uses MODIS LST hotspots + Landsat SWIR bare-soil index in known kiln zones.
Emission estimates follow literature values per kiln (CO2 and PM2.5).
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Data Loading
# ═══════════════════════════════════════════════════════════════════════════════

def _get_dry_season_lst(year, region):
    """
    Load MODIS LST day composite for the dry/active kiln season (Oct-May).
    Returns scaled image in Celsius.
    """
    col = cfg.MODIS_LST
    # Oct of previous year through May of given year
    start = f"{year - 1}-10-01"
    end = f"{year}-05-31"
    lst = (
        ee.ImageCollection(col["collection"])
        .filterDate(start, end)
        .filterBounds(region)
        .select(col["day_band"])
        .mean()
        .multiply(col["scale_factor"])
        .add(col["kelvin_offset"])
        .rename("lst_c")
        .clip(region)
    )
    return lst


def _get_kiln_season_landsat(year, region):
    """
    Load Landsat surface reflectance composite for the kiln-active season (Nov-Apr).
    Uses L8 for 2014+, L7 for 2000-2013, L5 for 1999 and earlier.
    """
    start = f"{year - 1}-11-01"
    end = f"{year}-04-30"

    if year >= 2014:
        sensor = "L8"
    elif year >= 2000:
        sensor = "L7"
    else:
        sensor = "L5"

    info = cfg.LANDSAT_BANDS[sensor]
    col = (
        ee.ImageCollection(info["collection"])
        .filterDate(start, end)
        .filterBounds(region)
        .filter(ee.Filter.lt("CLOUD_COVER", 20))
        .select(info["original"], info["renamed"])
        .map(lambda img: img
             .multiply(info["scale_factor"])
             .add(info["scale_offset"])
             .copyProperties(img, ["system:time_start"]))
        .median()
        .clip(region)
    )
    return col


# ═══════════════════════════════════════════════════════════════════════════════
# Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def detect_thermal_hotspots(year, region, scale=1000):
    """
    Detect thermal anomalies during kiln-active season (Oct-May) using MODIS LST.
    Hotspot threshold: pixels > mean + 2 * stddev of regional LST.
    Returns: dict with hotspot mask image, mean, stddev, and threshold value.
    """
    lst = _get_dry_season_lst(year, region)

    stats = lst.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    mean_lst = ee.Number(stats.get("lst_c_mean"))
    std_lst = ee.Number(stats.get("lst_c_stdDev"))
    threshold = mean_lst.add(std_lst.multiply(2))

    hotspots = lst.select("lst_c").gte(threshold).rename("thermal_hotspot")

    hotspot_area = hotspots.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )

    return {
        "year": year,
        "hotspot_mask": hotspots,
        "lst_image": lst,
        "mean_lst_c": mean_lst,
        "stddev_lst_c": std_lst,
        "threshold_lst_c": threshold,
        "hotspot_area_km2": ee.Number(hotspot_area.get("thermal_hotspot")).divide(1e6),
    }


def detect_kiln_spectral(year, region, scale=300):
    """
    Detect kiln spectral signature using Landsat during active season (Nov-Apr).
    Kilns expose bare clay/brick with high SWIR reflectance and low NDVI.
    Bare Soil Index (BSI) = ((SWIR1 + Red) - (NIR + Blue)) / ((SWIR1 + Red) + (NIR + Blue))
    SWIR/NIR ratio flags exposed brick and heated bare surfaces.
    Mask constrained to known kiln zones to reduce false positives.
    Returns: dict with spectral kiln candidate mask, BSI image, SWIR/NIR image.
    """
    img = _get_kiln_season_landsat(year, region)

    bsi = img.expression(
        "((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))",
        {
            "SWIR1": img.select("swir1"),
            "RED": img.select("red"),
            "NIR": img.select("nir"),
            "BLUE": img.select("blue"),
        },
    ).rename("bsi")

    swir_nir_ratio = img.select("swir1").divide(img.select("nir")).rename("swir_nir")

    ndvi = img.normalizedDifference(["nir", "red"]).rename("ndvi")

    # Kiln spectral signature: high BSI + high SWIR/NIR + low NDVI
    # BSI > 0.05: bare/exposed soil
    # SWIR/NIR > 1.0: SWIR dominant (brick/clay/heated surface)
    # NDVI < 0.2: no vegetation cover
    kiln_spectral_mask = (
        bsi.gt(0.05)
        .And(swir_nir_ratio.gt(1.0))
        .And(ndvi.lt(0.2))
        .rename("kiln_candidate")
    )

    # Intersect with known kiln zone buffers
    kiln_zone_masks = []
    for zone_name, zone_info in cfg.KNOWN_KILN_ZONES.items():
        center = ee.Geometry.Point([zone_info["lon"], zone_info["lat"]])
        zone_geom = center.buffer(zone_info["radius"])
        zone_mask = ee.Image.constant(1).clip(zone_geom)
        kiln_zone_masks.append(zone_mask)

    if kiln_zone_masks:
        combined_zones = kiln_zone_masks[0]
        for m in kiln_zone_masks[1:]:
            combined_zones = combined_zones.Or(m)
        kiln_in_zones = kiln_spectral_mask.And(combined_zones.unmask(0).gt(0))
    else:
        kiln_in_zones = kiln_spectral_mask

    candidate_area = kiln_in_zones.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )

    return {
        "year": year,
        "bsi": bsi,
        "swir_nir": swir_nir_ratio,
        "ndvi": ndvi,
        "kiln_spectral_mask": kiln_spectral_mask,
        "kiln_in_zones_mask": kiln_in_zones,
        "candidate_area_km2": ee.Number(candidate_area.get("kiln_candidate")).divide(1e6),
    }


def compute_kiln_density(region, year=2023, scale=1000):
    """
    Compute thermal hotspot density per district.
    Returns: list of dicts with district name and hotspot pixel count.
    """
    thermal = detect_thermal_hotspots(year, region, scale=scale)
    hotspot_img = thermal["hotspot_mask"]

    districts = (
        ee.FeatureCollection(cfg.ADMIN_BOUNDARIES)
        .filter(ee.Filter.eq("ADM0_NAME", cfg.COUNTRY_NAME))
    )

    density = hotspot_img.reduceRegions(
        collection=districts,
        reducer=ee.Reducer.sum().combine(
            ee.Reducer.mean(), sharedInputs=True
        ),
        scale=scale,
    )

    return {
        "year": year,
        "density_by_district": density,
        "hotspot_mask": hotspot_img,
    }


def compute_kiln_timeseries(start_year, end_year, region, scale=1000):
    """
    Compute annual kiln-related thermal hotspot count and spectral candidate area
    over the dry season from start_year to end_year (inclusive).
    Returns: list of dicts per year.
    """
    series = []
    for year in range(start_year, end_year + 1):
        try:
            thermal = detect_thermal_hotspots(year, region, scale=scale)
            try:
                spectral = detect_kiln_spectral(year, region, scale=scale)
                spectral_area = spectral["candidate_area_km2"]
            except Exception as e:
                print(f"    Spectral {year} skipped: {e}")
                spectral_area = None

            series.append({
                "year": year,
                "hotspot_area_km2": thermal["hotspot_area_km2"],
                "spectral_candidate_area_km2": spectral_area,
                "threshold_lst_c": thermal["threshold_lst_c"],
                "mean_lst_c": thermal["mean_lst_c"],
            })
        except Exception as e:
            print(f"  Kiln timeseries {year} skipped: {e}")

    return series


def estimate_emissions(kiln_area_km2, region=None):
    """
    Rough emission estimate from kiln area proxy.

    Literature values (per kiln per year, Fixed Chimney Kiln / FCBTK):
      CO2:  about 4,600 tonnes CO2 per kiln per year
            (Rahman et al. 2019, IFC/World Bank estimates for BD kilns)
      PM2.5: about 1.5 tonnes PM2.5 per kiln per year
            (Saha et al. 2021, BD brick sector emission factors)

    Kiln footprint proxy: average FCBTK in Bangladesh occupies ~0.04 km2
    (400m x 100m kiln + clay storage).

    kiln_area_km2: ee.Number or float representing total detected kiln-spectral area.
    Returns dict with estimated kiln count and total emissions as ee.Number objects
    (or plain floats if kiln_area_km2 is a plain float).
    """
    # Average kiln footprint: 0.04 km2
    AVG_KILN_FOOTPRINT_KM2 = 0.04
    # Annual emissions per kiln
    CO2_PER_KILN_TONNES = 4600.0
    PM25_PER_KILN_TONNES = 1.5

    if isinstance(kiln_area_km2, (int, float)):
        kiln_count = kiln_area_km2 / AVG_KILN_FOOTPRINT_KM2
        return {
            "input_area_km2": kiln_area_km2,
            "avg_kiln_footprint_km2": AVG_KILN_FOOTPRINT_KM2,
            "estimated_kiln_count": kiln_count,
            "co2_tonnes_per_year": kiln_count * CO2_PER_KILN_TONNES,
            "pm25_tonnes_per_year": kiln_count * PM25_PER_KILN_TONNES,
            "note": (
                "FCBTK emission factors: CO2 ~4600 t/kiln/yr (IFC/World Bank), "
                "PM2.5 ~1.5 t/kiln/yr (Saha et al. 2021). "
                "Footprint ~0.04 km2/kiln."
            ),
        }
    else:
        # ee.Number path
        area = ee.Number(kiln_area_km2)
        kiln_count = area.divide(AVG_KILN_FOOTPRINT_KM2)
        return {
            "input_area_km2": area,
            "avg_kiln_footprint_km2": AVG_KILN_FOOTPRINT_KM2,
            "estimated_kiln_count": kiln_count,
            "co2_tonnes_per_year": kiln_count.multiply(CO2_PER_KILN_TONNES),
            "pm25_tonnes_per_year": kiln_count.multiply(PM25_PER_KILN_TONNES),
            "note": (
                "FCBTK emission factors: CO2 ~4600 t/kiln/yr (IFC/World Bank), "
                "PM2.5 ~1.5 t/kiln/yr (Saha et al. 2021). "
                "Footprint ~0.04 km2/kiln."
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_brick_kiln_analysis(region):
    """Full brick kiln detection and emission estimation pipeline."""
    results = {}

    print("\n  Detecting thermal hotspots (2023 dry season)...")
    try:
        results["thermal_2023"] = detect_thermal_hotspots(2023, region)
    except Exception as e:
        print(f"    Thermal hotspots 2023 skipped: {e}")

    print("  Detecting kiln spectral signature (2023)...")
    try:
        results["spectral_2023"] = detect_kiln_spectral(2023, region)
    except Exception as e:
        print(f"    Spectral detection 2023 skipped: {e}")

    print("  Computing kiln density by district (2023)...")
    try:
        results["density_2023"] = compute_kiln_density(region, year=2023)
    except Exception as e:
        print(f"    Kiln density skipped: {e}")

    print("  Computing kiln timeseries (2015-2023)...")
    try:
        results["timeseries"] = compute_kiln_timeseries(2015, 2023, region)
    except Exception as e:
        print(f"    Kiln timeseries skipped: {e}")

    print("  Estimating emissions from 2023 spectral area...")
    try:
        spectral = results.get("spectral_2023", {})
        candidate_area = spectral.get("candidate_area_km2")
        if candidate_area is not None:
            results["emissions_2023"] = estimate_emissions(candidate_area, region)
        else:
            print("    Emissions skipped: no candidate area available")
    except Exception as e:
        print(f"    Emissions estimate skipped: {e}")

    return results

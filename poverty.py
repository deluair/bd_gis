"""
Poverty proxy mapping – multi-indicator spatial poverty estimation using
nighttime lights, population density, vegetation, built-up area, and
accessibility as proxy indicators.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Individual Indicators
# ═══════════════════════════════════════════════════════════════════════════════

def get_population_density(year, region):
    """Get WorldPop population density for a given year (2000–2020)."""
    pop_year = min(max(year, 2000), 2020)
    col = (
        ee.ImageCollection(cfg.WORLDPOP["collection"])
        .filterDate(f"{pop_year}-01-01", f"{pop_year}-12-31")
        .filterBounds(region)
        .select(cfg.WORLDPOP["band"])
    )
    return col.median().clip(region).rename("population")


def get_light_intensity(year, region):
    """Get nighttime light intensity (auto-selects DMSP or VIIRS)."""
    from nightlights import get_nightlights
    return get_nightlights(year, region)


def get_built_fraction(year, region):
    """Get GHSL built-up fraction (0–1 range)."""
    from urbanization import get_ghsl_built
    built = get_ghsl_built(year, region)
    # Normalize to 0-1 (max built-up per 100m pixel ~ 10000 m2)
    return built.divide(10000).clamp(0, 1).rename("built_fraction")


def get_vegetation_greenness(year, region):
    """Get MODIS annual max NDVI as vegetation proxy."""
    from vegetation import get_modis_ndvi_annual
    return get_modis_ndvi_annual(year, region)


def get_cropland_fraction(region, year=2021):
    """Get cropland fraction from ESA WorldCover."""
    from vegetation import detect_cropland
    cropland = detect_cropland(region, year)
    # Smooth to ~1km resolution for comparison with other indicators
    return cropland.reduceNeighborhood(
        reducer=ee.Reducer.mean(),
        kernel=ee.Kernel.circle(1000, "meters"),
    ).rename("cropland_fraction")


# ═══════════════════════════════════════════════════════════════════════════════
# Composite Poverty Index
# ═══════════════════════════════════════════════════════════════════════════════

def compute_poverty_index(year, region, scale=1000):
    """
    Compute a multi-indicator poverty proxy index (0–1, higher = more deprived).

    Methodology:
    - Low nighttime lights → high deprivation
    - Low built-up fraction → high deprivation
    - High population with low lights → high deprivation
    - Low vegetation health in agricultural areas → high deprivation

    Each indicator is normalized to 0–1 and combined with equal weights.
    The result is a relative index, NOT an absolute poverty measure.
    """
    # 1. Nighttime lights (inverted: dark = deprived)
    lights = get_light_intensity(year, region)
    band_name = lights.bandNames().getInfo()[0]
    light_norm = lights.select(band_name).unitScale(0, 63).clamp(0, 1)
    light_deprivation = ee.Image.constant(1).subtract(light_norm).rename("light_dep")

    # 2. Built-up fraction (inverted: no buildings = deprived)
    try:
        built = get_built_fraction(year, region)
        built_deprivation = ee.Image.constant(1).subtract(built).rename("built_dep")
    except Exception:
        built_deprivation = ee.Image.constant(0.5).rename("built_dep").clip(region)

    # 3. Population-weighted light deficit
    try:
        pop = get_population_density(year, region)
        pop_norm = pop.unitScale(0, 5000).clamp(0, 1)
        # High population + low light = poverty hotspot
        pop_light_gap = pop_norm.multiply(light_deprivation).rename("pop_light_gap")
    except Exception:
        pop_light_gap = ee.Image.constant(0.5).rename("pop_light_gap").clip(region)

    # 4. Vegetation stress (low NDVI in crop areas = food insecurity proxy)
    try:
        ndvi = get_vegetation_greenness(year, region)
        ndvi_norm = ndvi.unitScale(0, 0.8).clamp(0, 1)
        veg_stress = ee.Image.constant(1).subtract(ndvi_norm).rename("veg_stress")
    except Exception:
        veg_stress = ee.Image.constant(0.5).rename("veg_stress").clip(region)

    # Combine with equal weights
    poverty_index = (
        light_deprivation
        .add(built_deprivation)
        .add(pop_light_gap)
        .add(veg_stress)
        .divide(4)
        .rename("poverty_index")
    )

    return poverty_index


def classify_poverty_levels(poverty_index):
    """
    Classify poverty index into discrete levels.
    Returns: 1=Low, 2=Moderate, 3=High, 4=Very High deprivation.
    """
    classified = (
        poverty_index.where(poverty_index.lt(0.25), 1)
        .where(poverty_index.gte(0.25).And(poverty_index.lt(0.5)), 2)
        .where(poverty_index.gte(0.5).And(poverty_index.lt(0.75)), 3)
        .where(poverty_index.gte(0.75), 4)
        .rename("poverty_level")
    )
    return classified.toInt()


def compute_poverty_stats_by_division(year, region, scale=1000):
    """Compute poverty index statistics per administrative division."""
    from data_acquisition import get_division_boundaries_all
    poverty = compute_poverty_index(year, region, scale)
    divisions = get_division_boundaries_all()

    def _compute_div_stats(feature):
        stats = poverty.reduceRegion(
            reducer=ee.Reducer.mean().combine(
                ee.Reducer.median(), sharedInputs=True
            ),
            geometry=feature.geometry(),
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        return feature.set(stats).set("year", year)

    return divisions.map(_compute_div_stats)


def compute_poverty_change(year1, year2, region, scale=1000):
    """
    Compute change in poverty index between two years.
    Negative change = improvement, positive = worsening.
    """
    p1 = compute_poverty_index(year1, region, scale)
    p2 = compute_poverty_index(year2, region, scale)
    change = p2.subtract(p1).rename("poverty_change")
    return change


def compute_district_poverty_ranking(year, region, scale=1000):
    """Rank districts by mean poverty index."""
    from data_acquisition import get_admin_boundaries
    poverty = compute_poverty_index(year, region, scale)
    districts = get_admin_boundaries()

    def _compute_stats(feature):
        stats = poverty.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=feature.geometry(),
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        return feature.set(stats).set("year", year)

    return districts.map(_compute_stats)


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_poverty_analysis(region):
    """Full poverty proxy analysis pipeline."""
    results = {}

    print("\n  Computing poverty proxy index for 2020...")
    try:
        results["poverty_2020"] = compute_poverty_index(2020, region)
        results["poverty_levels_2020"] = classify_poverty_levels(results["poverty_2020"])
    except Exception as e:
        print(f"    Poverty index 2020 skipped: {e}")

    print("  Computing poverty by division...")
    try:
        results["division_stats"] = compute_poverty_stats_by_division(2020, region)
    except Exception as e:
        print(f"    Division stats skipped: {e}")

    print("  Computing poverty change 2012 → 2020...")
    try:
        results["poverty_change"] = compute_poverty_change(2012, 2020, region)
    except Exception as e:
        print(f"    Poverty change skipped: {e}")

    print("  Computing district poverty ranking...")
    try:
        results["district_ranking"] = compute_district_poverty_ranking(2020, region)
    except Exception as e:
        print(f"    District ranking skipped: {e}")

    print("  Computing poverty index for multiple years...")
    results["poverty_timeseries"] = {}
    for year in [2000, 2005, 2010, 2015, 2020]:
        try:
            pi = compute_poverty_index(year, region)
            stats = pi.reduceRegion(
                reducer=ee.Reducer.mean().combine(
                    ee.Reducer.median(), sharedInputs=True
                ),
                geometry=region, scale=1000,
                maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            results["poverty_timeseries"][year] = stats
        except Exception as e:
            print(f"    Poverty {year} skipped: {e}")

    return results

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
# Normalization
# ═══════════════════════════════════════════════════════════════════════════════

# Percentile bounds for the robust stretch. 2/98 trims sensor outliers (gas
# flares, saturated urban cores) without discarding the real upper tail.
NORM_LOW_PCT = 2
NORM_HIGH_PCT = 98


def robust_unit_scale(img, region, scale, log_transform=False):
    """Stretch an image to 0-1 against its own distribution over `region`.

    Fixed physical ranges (VIIRS 0-200, WorldPop 0-25000) put essentially all
    of Bangladesh in the bottom 2% of the scale, which collapses a component to
    a near-constant and removes it from the composite. Stretching against the
    observed 2nd-98th percentile keeps each component on a comparable footing.

    log_transform=True first applies log1p, for quantities whose distribution is
    close to log-normal (radiance, population density). Without it the stretch
    is set by Dhaka's extreme tail and everywhere else collapses again.
    """
    # ee.Image has no log1p. max(0) first because VIIRS radiance can be slightly
    # negative over dark water, which would make the log undefined.
    work = img.max(0).add(1).log() if log_transform else img
    band = ee.String(work.bandNames().get(0))
    pct = work.reduceRegion(
        reducer=ee.Reducer.percentile([NORM_LOW_PCT, NORM_HIGH_PCT]),
        geometry=region, scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    lo = ee.Number(pct.get(band.cat(f"_p{NORM_LOW_PCT}")))
    hi = ee.Number(pct.get(band.cat(f"_p{NORM_HIGH_PCT}")))
    # A degenerate spread would divide by zero and poison the whole composite.
    span = hi.subtract(lo)
    safe_span = ee.Number(ee.Algorithms.If(span.gt(0), span, 1))
    return work.subtract(lo).divide(safe_span).clamp(0, 1)


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

    Each indicator is stretched to 0-1 against its own observed distribution
    across `region` (see robust_unit_scale) and combined with equal weights.
    Region-relative normalization is what makes the components comparable: on
    fixed physical ranges, light and built-up deprivation both pin at ~0.997
    and the population gap at ~0.0004, so the composite degenerates to a
    constant near 0.5 plus a quarter of the vegetation term.

    The result is a relative index, NOT an absolute poverty measure. It ranks
    areas within `region`; values are not comparable across different regions
    or across years, because the stretch bounds are recomputed each time.
    """
    # 1. Nighttime lights (inverted: dark = deprived). Radiance is close to
    #    log-normal, so stretch in log space.
    lights = get_light_intensity(year, region)
    band_name = lights.bandNames().getInfo()[0]
    light_norm = robust_unit_scale(
        lights.select(band_name), region, scale, log_transform=True
    )
    light_deprivation = ee.Image.constant(1).subtract(light_norm).rename("light_dep")

    # 2. Built-up fraction (inverted: no buildings = deprived). Also heavily
    #    right-skewed, most rural pixels sit near zero.
    try:
        built = get_built_fraction(year, region)
        built_norm = robust_unit_scale(built, region, scale, log_transform=True)
        built_deprivation = ee.Image.constant(1).subtract(built_norm).rename("built_dep")
    except Exception as e:
        print(f"  WARNING: built_fraction failed ({e}); dropping it from the composite")
        built_deprivation = None

    # 3. Population-weighted light deficit
    try:
        pop = get_population_density(year, region)
        pop_norm = robust_unit_scale(pop, region, scale, log_transform=True)
        # High population + low light = poverty hotspot. Both terms now carry
        # real variance, so the product is no longer pinned at zero.
        pop_light_gap = pop_norm.multiply(light_deprivation).rename("pop_light_gap")
    except Exception as e:
        print(f"  WARNING: population_density failed ({e}); dropping it from the composite")
        pop_light_gap = None

    # 4. Vegetation stress (low NDVI in crop areas = food insecurity proxy).
    #    Roughly symmetric, so no log transform.
    try:
        ndvi = get_vegetation_greenness(year, region)
        ndvi_norm = robust_unit_scale(ndvi, region, scale)
        veg_stress = ee.Image.constant(1).subtract(ndvi_norm).rename("veg_stress")
    except Exception as e:
        print(f"  WARNING: vegetation_greenness failed ({e}); dropping it from the composite")
        veg_stress = None

    # Combine the indicators that actually computed, with equal weights. A dropped
    # indicator (None) is excluded rather than replaced by a fabricated 0.5 constant
    # (which the prior code did, silently injecting fake deprivation). The index is
    # the mean of the indicators truly available for this year and region.
    components = [
        img for img in (light_deprivation, built_deprivation, pop_light_gap, veg_stress)
        if img is not None
    ]
    if len(components) < 4:
        print(f"  poverty_index built from {len(components)}/4 indicators (failed ones dropped)")
    acc = components[0]
    for img in components[1:]:
        acc = acc.add(img)
    poverty_index = acc.divide(len(components)).rename("poverty_index")

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


def _population_weighted_mean(index_img, pop_img, feature, scale):
    """Population-weighted mean of `index_img` over one feature.

    A plain spatial mean weights every pixel equally, so Sundarbans mangrove and
    empty char land count as much as Dhaka. Survey poverty rates are shares of
    *people*, so the satellite aggregate has to be weighted by population to be
    comparable. Water and forest carry ~0 population and drop out naturally.
    """
    stack = index_img.multiply(pop_img).rename("weighted").addBands(
        pop_img.rename("pop_total")
    )
    sums = stack.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=feature.geometry(), scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    # NOTE: this is the sum of WorldPop values *sampled at `scale`*, not a
    # population count. WorldPop is people per 100 m pixel, so sampling at 1 km
    # undercounts by roughly 100x. The factor cancels in the weighted mean, but
    # never report this number as a population.
    weight_sum = ee.Number(sums.get("pop_total"))
    weighted = ee.Algorithms.If(
        weight_sum.gt(0), ee.Number(sums.get("weighted")).divide(weight_sum), None
    )
    return weighted, weight_sum


def compute_poverty_stats_by_division(year, region, scale=1000):
    """Compute poverty index statistics per administrative division.

    Reports both the population-weighted mean (comparable to survey headcount
    rates) and the unweighted spatial mean (comparable to earlier runs).
    """
    from data_acquisition import get_division_boundaries_all
    poverty = compute_poverty_index(year, region, scale)
    pop = get_population_density(year, region)
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
        weighted, weight_sum = _population_weighted_mean(poverty, pop, feature, scale)
        return (feature.set(stats)
                .set("poverty_index_popwt", weighted)
                .set("population_weight_sum", weight_sum)
                .set("year", year))

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
    """Rank districts by mean poverty index (spatial and population-weighted)."""
    from data_acquisition import get_admin_boundaries
    poverty = compute_poverty_index(year, region, scale)
    pop = get_population_density(year, region)
    districts = get_admin_boundaries()

    def _compute_stats(feature):
        stats = poverty.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=feature.geometry(),
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        weighted, weight_sum = _population_weighted_mean(poverty, pop, feature, scale)
        return (feature.set(stats)
                .set("poverty_index_popwt", weighted)
                .set("population_weight_sum", weight_sum)
                .set("year", year))

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

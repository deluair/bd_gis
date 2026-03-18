"""
Haor-specific analysis – delineate individual haor boundaries,
track area over time, analyze seasonal filling cycles, and compare
pre-2000 vs post-2000 dynamics.
"""
import ee
import config as cfg
from data_acquisition import (
    get_study_area, get_srtm_dem, get_seasonal_composite,
    get_landsat_collection, make_composite
)
from water_classification import classify_water, compute_water_area


# ═══════════════════════════════════════════════════════════════════════════════
# Haor Boundary Delineation
# ═══════════════════════════════════════════════════════════════════════════════

def get_haor_roi(haor_name):
    """Get a circular ROI for a named haor from config."""
    h = cfg.HAORS[haor_name]
    return ee.Geometry.Point(h["lon"], h["lat"]).buffer(h["radius"])


def delineate_haor_boundary(haor_name, region=None):
    """
    Delineate haor boundary using:
    1. DEM elevation mask (haors are low-lying depressions)
    2. Maximum historical water extent (monsoon composites)
    The intersection gives the haor extent.
    """
    if region is None:
        region = get_haor_roi(haor_name)

    # DEM-based mask: low-elevation areas
    dem = get_srtm_dem()
    low_elevation = dem.lte(cfg.HAOR_MAX_ELEVATION).clip(region)

    # Maximum water extent from multiple monsoon seasons
    # Biennial sampling + extreme flood years (odd years like 1998, 2007 matter)
    water_union = ee.Image.constant(0)
    sample_years = sorted(
        set(range(2000, 2025, 2))
        | set(y for y in cfg.EXTREME_FLOOD_YEARS if 2000 <= y <= 2024)
    )
    skipped = 0
    for year in sample_years:
        try:
            composite = get_seasonal_composite(year, "monsoon", "landsat", region)
            water = classify_water(composite, region=region, method="fixed")
            water_union = water_union.Or(water)
        except Exception as e:
            print(f"  {haor_name} delineation year {year} skipped: {e}")
            skipped += 1

    if skipped == len(sample_years):
        print(f"  WARNING: all sample years failed for {haor_name} delineation")

    # Haor boundary = low elevation AND ever-flooded
    haor_mask = low_elevation.And(water_union).rename("haor_boundary")
    return haor_mask


def delineate_all_haors():
    """Delineate boundaries for all configured haors."""
    boundaries = {}
    for name in cfg.HAORS:
        print(f"  Delineating {name}...")
        boundaries[name] = delineate_haor_boundary(name)
    return boundaries


# ═══════════════════════════════════════════════════════════════════════════════
# Haor Area Tracking Over Time
# ═══════════════════════════════════════════════════════════════════════════════

def compute_haor_area_timeseries(haor_name, start_year, end_year, season="monsoon"):
    """
    Track the water area within a haor's ROI for each year.
    Returns list of {year, area_km2}.
    """
    region = get_haor_roi(haor_name)
    results = []

    for year in range(start_year, end_year + 1):
        try:
            composite = get_seasonal_composite(year, season, "landsat", region)
            water = classify_water(composite, region=region, method="fixed")
            area = compute_water_area(water, region)
            results.append({"year": year, "area_km2": area})
        except Exception as e:
            print(f"    Skipping {haor_name} {year}: {e}")

    return results


def compute_all_haor_timeseries(start_year=None, end_year=None):
    """Compute area time series for all configured haors."""
    if start_year is None:
        start_year = cfg.ANALYSIS_START_YEAR
    if end_year is None:
        end_year = cfg.ANALYSIS_END_YEAR

    all_series = {}
    for name in cfg.HAORS:
        print(f"  Computing time series for {name}...")
        all_series[name] = compute_haor_area_timeseries(name, start_year, end_year)
    return all_series


# ═══════════════════════════════════════════════════════════════════════════════
# Seasonal Filling / Drying Cycles
# ═══════════════════════════════════════════════════════════════════════════════

def compute_seasonal_cycle(haor_name, year):
    """
    Compute monthly water area for a haor in a given year to capture
    the filling/drying cycle.
    Returns list of {month, area_km2}.
    """
    region = get_haor_roi(haor_name)
    monthly = []

    for month in range(1, 13):
        try:
            start = f"{year}-{month:02d}-01"
            if month == 12:
                end = f"{year + 1}-01-01"
            else:
                end = f"{year}-{month + 1:02d}-01"

            col = get_landsat_collection(start, end, region)
            composite = make_composite(col)
            water = classify_water(composite, region=region, method="fixed")
            area = compute_water_area(water, region)
            monthly.append({"month": month, "area_km2": area})
        except Exception:
            monthly.append({"month": month, "area_km2": None})

    return monthly


def compute_avg_seasonal_cycle(haor_name, years=None):
    """
    Average seasonal cycle across multiple years for more robust results.
    """
    if years is None:
        years = list(range(2015, 2024))  # recent decade

    region = get_haor_roi(haor_name)
    monthly_sums = {m: [] for m in range(1, 13)}

    for year in years:
        cycle = compute_seasonal_cycle(haor_name, year)
        for entry in cycle:
            if entry["area_km2"] is not None:
                monthly_sums[entry["month"]].append(entry["area_km2"])

    return {m: (sum(v) / len(v)) if v else None for m, v in monthly_sums.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-2000 vs Post-2000 Comparison
# ═══════════════════════════════════════════════════════════════════════════════

def compare_haor_periods(haor_name, period1=(1985, 1999), period2=(2000, 2025)):
    """
    Compare haor water dynamics between two time periods.
    Returns dict with area stats for each period.
    """
    region = get_haor_roi(haor_name)

    # Period 1 monsoon average
    p1_areas = []
    p1_skipped = 0
    for year in range(period1[0], period1[1] + 1):
        try:
            composite = get_seasonal_composite(year, "monsoon", "landsat", region)
            water = classify_water(composite, region=region, method="fixed")
            area = compute_water_area(water, region)
            p1_areas.append(area)
        except Exception as e:
            print(f"  {haor_name} period1 year {year} skipped: {e}")
            p1_skipped += 1

    if p1_skipped == (period1[1] - period1[0] + 1):
        print(f"  WARNING: all years failed for {haor_name} period 1")

    # Period 2 monsoon average
    p2_areas = []
    p2_skipped = 0
    for year in range(period2[0], period2[1] + 1):
        try:
            composite = get_seasonal_composite(year, "monsoon", "landsat", region)
            water = classify_water(composite, region=region, method="fixed")
            area = compute_water_area(water, region)
            p2_areas.append(area)
        except Exception as e:
            print(f"  {haor_name} period2 year {year} skipped: {e}")
            p2_skipped += 1

    if p2_skipped == (period2[1] - period2[0] + 1):
        print(f"  WARNING: all years failed for {haor_name} period 2")

    def _avg(areas):
        if not areas:
            return ee.Number(0)
        total = ee.Number(0)
        for a in areas:
            total = total.add(a)
        return total.divide(len(areas))

    p1_avg = _avg(p1_areas)
    p2_avg = _avg(p2_areas)

    # Guard against division by zero when period 1 has no valid data
    if not p1_areas:
        return {
            "haor": haor_name,
            "period1": f"{period1[0]}-{period1[1]}",
            "period2": f"{period2[0]}-{period2[1]}",
            "period1_avg_km2": p1_avg,
            "period2_avg_km2": p2_avg,
            "change_km2": p2_avg,
            "change_pct": None,
            "error": "No valid data for period 1",
        }

    # Server-side safe division (guards near-zero p1_avg)
    pct_change = ee.Algorithms.If(
        ee.Number(p1_avg).abs().gt(0.01),
        p2_avg.subtract(p1_avg).divide(p1_avg).multiply(100),
        ee.Number(0),
    )

    return {
        "haor": haor_name,
        "period1": f"{period1[0]}-{period1[1]}",
        "period2": f"{period2[0]}-{period2[1]}",
        "period1_avg_km2": p1_avg,
        "period2_avg_km2": p2_avg,
        "change_km2": p2_avg.subtract(p1_avg),
        "change_pct": pct_change,
    }


def compare_all_haors():
    """Compare pre-2000 vs post-2000 for all haors."""
    results = {}
    for name in cfg.HAORS:
        print(f"  Comparing periods for {name}...")
        results[name] = compare_haor_periods(name)
    return results

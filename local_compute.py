"""Local satellite data computation -- replaces GEE for downloaded products."""
import math
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds

LOCAL_DATA = Path(__file__).parent / "local_data"

# Bangladesh bounds
BD_BOUNDS = {"west": 88.0, "south": 20.5, "east": 92.7, "north": 26.7}

# Mean latitude of Bangladesh (~23.7N) for degree-to-km conversion
_BD_MEAN_LAT = 23.7
_DEG_LAT_KM = 111.32
_DEG_LON_KM = 111.32 * math.cos(math.radians(_BD_MEAN_LAT))


# =============================================================================
# Helpers
# =============================================================================

def _read_bd(path):
    """Read a GeoTIFF clipped to Bangladesh bounds.

    Returns (array, transform, pixel_area_km2).
    """
    with rasterio.open(path) as src:
        window = from_bounds(
            BD_BOUNDS["west"], BD_BOUNDS["south"],
            BD_BOUNDS["east"], BD_BOUNDS["north"],
            transform=src.transform,
        )
        data = src.read(1, window=window)
        transform = src.window_transform(window)
        res = src.res  # (y_deg, x_deg)
        pixel_area_km2 = (res[0] * _DEG_LAT_KM) * (res[1] * _DEG_LON_KM)
        return data, transform, pixel_area_km2


def _find_file(pattern, subdir=None):
    """Find a single file matching a glob pattern under LOCAL_DATA."""
    base = LOCAL_DATA / subdir if subdir else LOCAL_DATA
    matches = sorted(base.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file matching '{pattern}' in {base}")
    return matches[0]


# =============================================================================
# Forest (Hansen Global Forest Change)
# =============================================================================

def compute_forest_stats_local(tree_threshold=30):
    """Compute forest cover stats from Hansen treecover2000, loss, gain.

    Returns dict with forest_2000_km2, forest_loss_km2, forest_gain_km2.
    """
    t0 = time.perf_counter()

    tc_path = _find_file("*treecover2000*")
    loss_path = _find_file("*loss*")
    gain_path = _find_file("*gain*")

    tc, _, px_area = _read_bd(tc_path)
    loss, _, _ = _read_bd(loss_path)
    gain, _, _ = _read_bd(gain_path)

    forest_mask = tc >= tree_threshold
    forest_2000_km2 = float(np.count_nonzero(forest_mask) * px_area)
    forest_loss_km2 = float(np.count_nonzero(loss > 0) * px_area)
    forest_gain_km2 = float(np.count_nonzero(gain > 0) * px_area)

    elapsed = time.perf_counter() - t0
    print(f"  Local forest stats: {elapsed:.2f}s (vs ~120s on GEE)")

    return {
        "forest_2000_km2": round(forest_2000_km2, 2),
        "forest_loss_km2": round(forest_loss_km2, 2),
        "forest_gain_km2": round(forest_gain_km2, 2),
    }


def compute_forest_loss_by_year_local(tree_threshold=30):
    """Compute annual forest loss area from Hansen lossyear band.

    lossyear values: 0 = no loss, 1-23 = year since 2000 (2001-2023).
    Returns list of {year, loss_km2}.
    """
    t0 = time.perf_counter()

    ly_path = _find_file("*lossyear*")
    tc_path = _find_file("*treecover2000*")

    lossyear, _, px_area = _read_bd(ly_path)
    tc, _, _ = _read_bd(tc_path)

    forest_mask = tc >= tree_threshold
    results = []
    for yr_code in range(1, 24):
        yr_loss = (lossyear == yr_code) & forest_mask
        loss_km2 = float(np.count_nonzero(yr_loss) * px_area)
        results.append({
            "year": 2000 + yr_code,
            "loss_km2": round(loss_km2, 4),
        })

    elapsed = time.perf_counter() - t0
    print(f"  Local forest loss by year: {elapsed:.2f}s (vs ~180s on GEE)")

    return results


# =============================================================================
# Water (JRC Global Surface Water)
# =============================================================================

def compute_water_stats_local():
    """Compute water area stats from JRC occurrence layer.

    Classifies pixels by occurrence percentage:
      permanent: >75%, seasonal: 25-75%, rare: <25% (but >0).
    Returns dict with permanent_km2, seasonal_km2, rare_km2.
    """
    t0 = time.perf_counter()

    occ_path = _find_file("*occurrence*")
    occ, _, px_area = _read_bd(occ_path)

    permanent = occ > 75
    seasonal = (occ >= 25) & (occ <= 75)
    rare = (occ > 0) & (occ < 25)

    permanent_km2 = float(np.count_nonzero(permanent) * px_area)
    seasonal_km2 = float(np.count_nonzero(seasonal) * px_area)
    rare_km2 = float(np.count_nonzero(rare) * px_area)

    elapsed = time.perf_counter() - t0
    print(f"  Local water stats: {elapsed:.2f}s (vs ~90s on GEE)")

    return {
        "permanent_km2": round(permanent_km2, 2),
        "seasonal_km2": round(seasonal_km2, 2),
        "rare_km2": round(rare_km2, 2),
    }


# =============================================================================
# Rainfall (CHIRPS)
# =============================================================================

def compute_rainfall_stats_local(year):
    """Compute rainfall stats from CHIRPS monthly GeoTIFFs.

    Expects files in local_data/chirps/ named like chirps_<year>_<MM>.tif.
    Returns dict with annual_mean_mm, annual_max_mm, monsoon_total_mm.
    """
    t0 = time.perf_counter()
    chirps_dir = LOCAL_DATA / "chirps"

    monthly_means = []
    monthly_maxes = []
    monsoon_totals = []  # Jun(6) - Sep(9)

    for month in range(1, 13):
        try:
            path = _find_file(f"*{year}*{month:02d}*", subdir="chirps")
        except FileNotFoundError:
            continue

        data, _, _ = _read_bd(path)
        valid = data[data > 0]
        if valid.size == 0:
            continue

        month_mean = float(np.mean(valid))
        month_max = float(np.max(valid))
        monthly_means.append(month_mean)
        monthly_maxes.append(month_max)

        if 6 <= month <= 9:
            monsoon_totals.append(month_mean)

    annual_mean_mm = sum(monthly_means) if monthly_means else 0.0
    annual_max_mm = max(monthly_maxes) if monthly_maxes else 0.0
    monsoon_total_mm = sum(monsoon_totals) if monsoon_totals else 0.0

    elapsed = time.perf_counter() - t0
    print(f"  Local rainfall stats ({year}): {elapsed:.2f}s (vs ~60s on GEE)")

    return {
        "year": year,
        "annual_mean_mm": round(annual_mean_mm, 2),
        "annual_max_mm": round(annual_max_mm, 2),
        "monsoon_total_mm": round(monsoon_total_mm, 2),
    }


# =============================================================================
# Population (WorldPop)
# =============================================================================

def compute_population_stats_local():
    """Compute population stats from WorldPop GeoTIFF.

    Returns dict with total_population and mean_density_per_km2.
    """
    t0 = time.perf_counter()

    pop_path = _find_file("*bgd_ppp*") or _find_file("*worldpop*")
    pop, _, px_area = _read_bd(pop_path)

    # WorldPop uses nodata values (often -99999 or very negative)
    valid = pop[pop > 0]
    total_pop = float(np.sum(valid))
    n_valid = valid.size
    total_area_km2 = n_valid * px_area
    mean_density = total_pop / total_area_km2 if total_area_km2 > 0 else 0.0

    elapsed = time.perf_counter() - t0
    print(f"  Local population stats: {elapsed:.2f}s (vs ~45s on GEE)")

    return {
        "total_population": round(total_pop),
        "mean_density_per_km2": round(mean_density, 2),
    }


# =============================================================================
# Orchestrator
# =============================================================================

def run_local_analysis(year=2023):
    """Run all local computations on downloaded satellite data.

    Returns results dict compatible with the existing pipeline output format.
    """
    print("\n" + "=" * 60)
    print("LOCAL SATELLITE DATA ANALYSIS (no GEE)")
    print("=" * 60)
    t_total = time.perf_counter()

    results = {}

    print("\n[1/5] Forest cover statistics (Hansen)...")
    try:
        results["forest_stats"] = compute_forest_stats_local()
    except FileNotFoundError as e:
        print(f"  Skipped: {e}")

    print("[2/5] Annual forest loss (Hansen)...")
    try:
        results["forest_loss_annual"] = compute_forest_loss_by_year_local()
    except FileNotFoundError as e:
        print(f"  Skipped: {e}")

    print("[3/5] Surface water statistics (JRC)...")
    try:
        results["water_stats"] = compute_water_stats_local()
    except FileNotFoundError as e:
        print(f"  Skipped: {e}")

    print(f"[4/5] Rainfall statistics (CHIRPS {year})...")
    try:
        results["rainfall_stats"] = compute_rainfall_stats_local(year)
    except FileNotFoundError as e:
        print(f"  Skipped: {e}")

    print("[5/5] Population statistics (WorldPop)...")
    try:
        results["population_stats"] = compute_population_stats_local()
    except FileNotFoundError as e:
        print(f"  Skipped: {e}")

    elapsed_total = time.perf_counter() - t_total
    n_completed = sum(1 for v in results.values() if v is not None)
    print(f"\nLocal analysis complete: {n_completed}/5 modules in {elapsed_total:.2f}s")

    return results

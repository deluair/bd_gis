"""
Local land cover classification using downloaded GeoTIFFs.
Replaces GEE-dependent land_cover.py for national-scale analysis.

Uses: Hansen forest, GHSL built-up, JRC water, WorldPop, Landsat NIR mosaics.
Produces: land cover area stats, timeseries, and slum proxy indicators.
"""
import csv
import os

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

LOCAL_DATA = os.path.join(os.path.dirname(__file__), "local_data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")


def read_bd_raster(path):
    """Read a BD-clipped raster, return (data, transform, crs, nodata)."""
    with rasterio.open(path) as src:
        data = src.read(1)
        return data, src.transform, src.crs, src.nodata, src.bounds


def compute_landcover_stats():
    """Compute land cover area breakdown from local data."""
    print("=== Local Land Cover Classification ===\n")

    results = {}

    # 1. Forest cover from Hansen GFC
    print("  Processing Hansen forest cover...")
    tree_path = os.path.join(LOCAL_DATA, "Hansen_GFC-2023-v1.11_treecover2000_30N_090E_bd.tif")
    loss_path = os.path.join(LOCAL_DATA, "Hansen_GFC-2023-v1.11_lossyear_30N_090E_bd.tif")
    gain_path = os.path.join(LOCAL_DATA, "Hansen_GFC-2023-v1.11_gain_30N_090E_bd.tif")

    if os.path.exists(tree_path):
        tree, tf, crs, nd, bounds = read_bd_raster(tree_path)
        # Pixel area at ~25N latitude, 30m resolution
        pixel_area_km2 = (30 * 30) / 1e6  # 0.0009 km2 per pixel

        # Forest = treecover > 25%
        forest_2000 = (tree > 25).sum() * pixel_area_km2
        total_pixels = (tree >= 0).sum()
        total_area = total_pixels * pixel_area_km2
        results["forest_2000_km2"] = forest_2000
        results["total_area_km2"] = total_area
        print(f"    Forest 2000: {forest_2000:,.0f} km2 ({forest_2000/total_area*100:.1f}%)")

        if os.path.exists(loss_path):
            loss, _, _, _, _ = read_bd_raster(loss_path)
            # Loss year: 1-23 = 2001-2023
            loss_by_year = {}
            for yr in range(1, 24):
                loss_pixels = (loss == yr).sum()
                loss_km2 = loss_pixels * pixel_area_km2
                loss_by_year[2000 + yr] = loss_km2

            total_loss = sum(loss_by_year.values())
            results["forest_loss_total_km2"] = total_loss
            results["forest_loss_by_year"] = loss_by_year
            print(f"    Forest loss 2001-2023: {total_loss:,.0f} km2")

        if os.path.exists(gain_path):
            gain, _, _, _, _ = read_bd_raster(gain_path)
            gain_km2 = (gain == 1).sum() * pixel_area_km2
            results["forest_gain_km2"] = gain_km2
            print(f"    Forest gain: {gain_km2:,.0f} km2")

            # Current forest estimate
            current = forest_2000 - total_loss + gain_km2
            results["forest_current_km2"] = current
            print(f"    Forest ~2023: {current:,.0f} km2 ({current/total_area*100:.1f}%)")

    # 2. Built-up area from existing GEE outputs (GHSL tiles on disk are wrong row: R4=50N, BD needs R7=20N)
    print("\n  Processing built-up area (from GEE timeseries)...")
    builtup_csv = os.path.join(OUTPUT_DIR, "urbanization", "builtup_timeseries.csv")
    if os.path.exists(builtup_csv):
        with open(builtup_csv) as f:
            for row in csv.DictReader(f):
                yr = int(row["year"])
                if yr == 2020:
                    built_km2 = float(row["built_area_km2"])
                    results["built_area_2020_km2"] = built_km2
                    print(f"    Built-up area 2020: {built_km2:,.0f} km2")
                    break
    else:
        print("    No builtup_timeseries.csv found, skipping")

    # 3. Water from JRC (use only BD-clipped files)
    print("\n  Processing JRC water occurrence...")
    jrc_files = [
        os.path.join(LOCAL_DATA, "occurrence_90E_30Nv1_4_2021_bd.tif"),
        os.path.join(LOCAL_DATA, "occurrence_80E_30Nv1_4_2021_bd.tif"),  # western BD if available
    ]
    permanent_water = 0
    seasonal_water = 0
    pixel_area_jrc = (30 * 30) / 1e6  # JRC is 30m

    for jf in jrc_files:
        if not os.path.exists(jf):
            continue
        data, tf, _, nd, bounds = read_bd_raster(jf)
        valid = data if nd is None else np.where(data != nd, data, 0)
        # Occurrence: 0-100 (% of time water present), 255 = nodata
        valid = np.where(valid <= 100, valid, 0)
        permanent_water += (valid >= 80).sum() * pixel_area_jrc
        seasonal_water += ((valid >= 20) & (valid < 80)).sum() * pixel_area_jrc

    results["permanent_water_km2"] = permanent_water
    results["seasonal_water_km2"] = seasonal_water
    print(f"    Permanent water (>=80% occurrence): {permanent_water:,.0f} km2")
    print(f"    Seasonal water (20-80%): {seasonal_water:,.0f} km2")

    # 4. Population from WorldPop
    print("\n  Processing WorldPop population...")
    pop_path = os.path.join(LOCAL_DATA, "bgd_ppp_2020_1km_Aggregated.tif")
    if os.path.exists(pop_path):
        pop, _, _, nd, _ = read_bd_raster(pop_path)
        valid = pop[pop > 0] if nd is None else pop[(pop != nd) & (pop > 0)]
        total_pop = valid.sum()
        results["population_2020"] = total_pop
        results["pop_density_mean"] = valid.mean()
        print(f"    Total population 2020: {total_pop:,.0f}")
        print(f"    Mean density: {valid.mean():,.0f} per km2")

    # 5. Landcover summary (derived)
    if "total_area_km2" in results:
        total = results["total_area_km2"]
        forest = results.get("forest_current_km2", 0)
        built = results.get("built_area_2020_km2", 0)
        water = results.get("permanent_water_km2", 0) + results.get("seasonal_water_km2", 0)
        other = total - forest - built - water  # cropland + other

        print(f"\n  === Land Cover Summary (approximate) ===")
        print(f"    Total area:     {total:>10,.0f} km2")
        print(f"    Forest:         {forest:>10,.0f} km2  ({forest/total*100:.1f}%)")
        print(f"    Built-up:       {built:>10,.0f} km2  ({built/total*100:.1f}%)")
        print(f"    Water:          {water:>10,.0f} km2  ({water/total*100:.1f}%)")
        print(f"    Cropland/other: {other:>10,.0f} km2  ({other/total*100:.1f}%)")

        results["cropland_other_km2"] = other

    return results


def compute_slum_proxy():
    """
    Slum proxy: high population density + low built-up quality.
    Uses WorldPop + GHSL at ~1km resolution.
    High pop density (>5000/km2) with low built-up fraction = informal settlement proxy.
    """
    print("\n=== Slum Proxy Estimation ===\n")

    pop_path = os.path.join(LOCAL_DATA, "bgd_ppp_2020_1km_Aggregated.tif")
    if not os.path.exists(pop_path):
        print("  WorldPop not found, skipping")
        return {}

    pop, pop_tf, pop_crs, pop_nd, pop_bounds = read_bd_raster(pop_path)

    # Count pixels with very high density
    valid_pop = np.where((pop > 0) if pop_nd is None else ((pop != pop_nd) & (pop > 0)), pop, 0)

    thresholds = [1000, 2000, 5000, 10000, 20000]
    results = {}
    print(f"  Population density distribution (1km pixels):")
    for t in thresholds:
        count = (valid_pop >= t).sum()
        results[f"pixels_gte_{t}"] = int(count)
        print(f"    >= {t:>6,}/km2: {count:>5} pixels ({count:>5} km2)")

    # Extreme density (>10000/km2) as slum proxy
    slum_proxy_km2 = (valid_pop >= 10000).sum()
    results["slum_proxy_km2"] = slum_proxy_km2
    print(f"\n  Slum proxy (density >= 10,000/km2): {slum_proxy_km2} km2")

    return results


def export_results(lc_results, slum_results):
    """Write results to CSVs."""
    lc_dir = os.path.join(OUTPUT_DIR, "landcover")
    slum_dir = os.path.join(OUTPUT_DIR, "slums")
    os.makedirs(lc_dir, exist_ok=True)
    os.makedirs(slum_dir, exist_ok=True)

    # Land cover summary
    path = os.path.join(lc_dir, "local_landcover_summary.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "area_km2", "year"])
        for key in ["forest_current_km2", "built_area_2020_km2", "permanent_water_km2",
                     "seasonal_water_km2", "cropland_other_km2"]:
            if key in lc_results:
                cat = key.replace("_km2", "").replace("_2020", "")
                w.writerow([cat, f"{lc_results[key]:.1f}", 2023 if "forest" in key else 2020])
    print(f"\n  Wrote {path}")

    # Forest loss timeseries
    if "forest_loss_by_year" in lc_results:
        path = os.path.join(lc_dir, "local_forest_loss_annual.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["year", "loss_km2"])
            for yr, loss in sorted(lc_results["forest_loss_by_year"].items()):
                w.writerow([yr, f"{loss:.1f}"])
        print(f"  Wrote {path}")

    # Slum proxy
    if slum_results:
        path = os.path.join(slum_dir, "local_slum_proxy.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["metric", "value", "year"])
            for k, v in slum_results.items():
                w.writerow([k, v, 2020])
        print(f"  Wrote {path}")


if __name__ == "__main__":
    lc = compute_landcover_stats()
    slum = compute_slum_proxy()
    export_results(lc, slum)
    print("\nDone.")

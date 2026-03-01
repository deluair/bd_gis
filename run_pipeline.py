#!/usr/bin/env python3
"""
Main orchestrator for Sylhet Haor Wetlands Geospatial Analysis Pipeline.

Usage:
    python run_pipeline.py --test       # Quick test: GEE auth + 2020 dry/monsoon composite
    python run_pipeline.py --full       # Full 40-year analysis (takes hours)
    python run_pipeline.py --rivers     # River erosion analysis only
    python run_pipeline.py --floods     # Flood extent analysis only
    python run_pipeline.py --changes    # Water change detection only
    python run_pipeline.py --haors      # Haor-specific analysis only
    python run_pipeline.py --viz        # Visualization/export only (requires prior runs)
"""
import argparse
import os
import sys
import time

import ee

sys.path.insert(0, os.path.dirname(__file__))

import config as cfg


def _resolve_ee(val):
    """Resolve ee.Number/ComputedObject to Python float, or return as-is."""
    if isinstance(val, (ee.Number, ee.ComputedObject)):
        try:
            return val.getInfo()
        except Exception:
            return None
    return val


from data_acquisition import (
    init_gee, get_study_area, get_seasonal_composite,
    get_srtm_dem, get_jrc_water
)
from water_classification import classify_water, compute_water_area
from export_utils import (
    ensure_output_dir, export_geotiff, export_csv,
    export_to_drive, export_shapefile
)
from visualization import (
    create_base_map, add_water_layer, add_occurrence_layer,
    add_persistence_layer, add_change_layer,
    create_water_comparison_map, create_temporal_map,
    create_river_migration_map, create_haor_map,
    save_map, plot_flood_time_series, plot_haor_area_trends,
    plot_erosion_rates, plot_period_comparison, create_change_figure,
)


def run_test():
    """Quick pipeline test: authenticate, pull composites, classify water."""
    print("=" * 60)
    print("PIPELINE TEST – Sylhet Haor 2020 Dry vs Monsoon")
    print("=" * 60)

    init_gee()
    region = get_study_area()

    # ── Dry Season 2020 ──────────────────────────────────────────────────
    print("\n[1/5] Generating dry season composite (Dec 2019 – Feb 2020)...")
    dry_composite = get_seasonal_composite(2020, "dry", "landsat", region)
    print("  Dry composite bands:", dry_composite.bandNames().getInfo())

    # ── Monsoon Season 2020 ──────────────────────────────────────────────
    print("\n[2/5] Generating monsoon composite (Jul – Sep 2020)...")
    monsoon_composite = get_seasonal_composite(2020, "monsoon", "landsat", region)
    print("  Monsoon composite bands:", monsoon_composite.bandNames().getInfo())

    # ── Water Classification ─────────────────────────────────────────────
    print("\n[3/5] Classifying water (Otsu + majority voting)...")
    dry_water = classify_water(dry_composite, region=region, method="otsu")
    monsoon_water = classify_water(monsoon_composite, region=region, method="otsu")

    dry_area = compute_water_area(dry_water, region).getInfo()
    monsoon_area = compute_water_area(monsoon_water, region).getInfo()
    print(f"  Dry season water area:    {dry_area:.1f} km²")
    print(f"  Monsoon season water area: {monsoon_area:.1f} km²")
    print(f"  Seasonal inundation:       {monsoon_area - dry_area:.1f} km²")

    # ── JRC Validation ───────────────────────────────────────────────────
    print("\n[4/5] Loading JRC Global Surface Water for comparison...")
    jrc = get_jrc_water()
    jrc_occ = jrc.select("occurrence").clip(region)
    jrc_stats = jrc_occ.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region,
        scale=30,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()
    print(f"  JRC mean water occurrence: {jrc_stats.get('occurrence', 'N/A')}%")

    # ── Interactive Map ──────────────────────────────────────────────────
    print("\n[5/5] Creating interactive map...")
    m = create_water_comparison_map(dry_water, monsoon_water, 2020)

    # Add DEM and JRC layers
    dem = get_srtm_dem()
    m.addLayer(dem, {"min": 0, "max": 50, "palette": [
        "006837", "1a9850", "66bd63", "d9ef8b", "fee08b", "fdae61", "d73027"
    ]}, "Elevation (SRTM)", shown=False)
    m.addLayer(jrc_occ, {"min": 0, "max": 100, "palette": [
        "ffffff", "89c4e8", "1a5fa4", "08306b"
    ]}, "JRC Water Occurrence", shown=False)

    m.addLayerControl()
    map_path = save_map(m, "test_2020_dry_vs_monsoon.html")

    # ── Export Test GeoTIFF ──────────────────────────────────────────────
    print("\nExporting test GeoTIFFs to Drive (local download may be slow)...")
    export_to_drive(dry_water, "test_dry_water_2020", region=region)
    export_to_drive(monsoon_water, "test_monsoon_water_2020", region=region)

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print(f"  Map saved:    {map_path}")
    print(f"  Dry area:     {dry_area:.1f} km²")
    print(f"  Monsoon area: {monsoon_area:.1f} km²")
    print("=" * 60)


def run_rivers():
    """River erosion and channel migration analysis."""
    from river_analysis import run_river_analysis

    print("\n" + "=" * 60)
    print("RIVER EROSION & CHANNEL MIGRATION ANALYSIS")
    print("=" * 60)

    init_gee()
    ensure_output_dir("rivers")

    for river_name in ["Surma", "Kushiyara"]:
        print(f"\n── {river_name} River ──")
        results = run_river_analysis(river_name)

        # Export centerlines
        for year, cl in results["centerlines"].items():
            export_to_drive(
                cl.toFloat(),
                f"{river_name.lower()}_centerline_{year}",
                region=results["roi"],
            )

        # Export erosion hotspots
        export_to_drive(
            results["hotspots"].toFloat(),
            f"{river_name.lower()}_erosion_hotspots",
            region=results["roi"],
        )

        # Erosion rates CSV – resolve ee.Number to Python float
        rates_resolved = []
        for r in results["erosion_rates"]:
            rate_val = _resolve_ee(r["rate_ha_per_year"])
            rates_resolved.append({
                "period": r["period"],
                "rate_ha_per_year": rate_val if rate_val is not None else 0.0,
            })
        export_csv(rates_resolved, f"{river_name.lower()}_erosion_rates.csv", "rivers")

        # Visualization
        try:
            m = create_river_migration_map(
                results["centerlines"], results["water_masks"], river_name
            )
            save_map(m, f"{river_name.lower()}_migration_map.html", "rivers")
        except Exception as e:
            print(f"  Migration map skipped for {river_name}: {e}")

        # Erosion rate plot
        try:
            plot_erosion_rates(
                rates_resolved,
                river_name,
                os.path.join(cfg.OUTPUT_DIR, "rivers", f"{river_name.lower()}_erosion_rates.png"),
            )
        except Exception as e:
            print(f"  Erosion rate plot skipped for {river_name}: {e}")

    print("\nRiver analysis complete.")


def run_floods():
    """Flood extent mapping and time series analysis."""
    from flood_analysis import (
        build_flood_time_series, analyze_extreme_flood,
        compute_flood_frequency, detect_flood_trend,
    )

    print("\n" + "=" * 60)
    print("FLOOD EXTENT MAPPING")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("floods")

    # Build time series (every 2 years for speed, full for production)
    print("\nBuilding flood time series (sampling every 2 years)...")
    sample_years = list(range(1986, 2025, 2))
    time_series = []
    for year in sample_years:
        print(f"  Processing {year}...")
        try:
            from flood_analysis import get_annual_water_extents
            extents = get_annual_water_extents(year, region)
            # Resolve ee.Number to Python float for matplotlib/pandas
            dry_val = _resolve_ee(extents["dry_area_km2"])
            monsoon_val = _resolve_ee(extents["monsoon_area_km2"])
            seasonal_val = _resolve_ee(extents["seasonal_area_km2"])
            if dry_val is not None and monsoon_val is not None:
                time_series.append({
                    "year": year,
                    "dry_area_km2": dry_val,
                    "monsoon_area_km2": monsoon_val,
                    "seasonal_area_km2": seasonal_val,
                })
                print(f"    Dry: {dry_val:.1f} km², Monsoon: {monsoon_val:.1f} km²")
            else:
                print(f"    Skipped: could not resolve area values")
        except Exception as e:
            print(f"    Skipped: {e}")

    export_csv(time_series, "flood_time_series.csv", "floods")
    if time_series:
        plot_flood_time_series(
            time_series,
            os.path.join(cfg.OUTPUT_DIR, "floods", "flood_time_series.png"),
        )
    else:
        print("  No time series data to plot.")

    # Extreme flood years
    print("\nAnalyzing extreme flood years...")
    for year in cfg.EXTREME_FLOOD_YEARS:
        print(f"  Extreme flood: {year}")
        try:
            result = analyze_extreme_flood(year, region)
            export_to_drive(
                result["monsoon_water"].toFloat(),
                f"extreme_flood_{year}",
                region=region,
            )
        except Exception as e:
            print(f"    Skipped: {e}")

    # Flood frequency map
    print("\nComputing flood frequency (2000-2024)...")
    freq = compute_flood_frequency(2000, 2024, region)
    export_to_drive(freq, "flood_frequency_2000_2024", region=region)

    # Flood trend
    print("Computing flood trend...")
    trend = detect_flood_trend(1990, 2024, region)
    export_to_drive(trend, "flood_trend_1990_2024", region=region)

    print("\nFlood analysis complete.")


def run_changes():
    """Water body gain/loss and change detection."""
    from water_change import (
        compute_water_occurrence, classify_water_persistence,
        compute_all_decade_changes, detect_water_to_land,
        detect_land_to_water, get_jrc_occurrence,
        validate_against_jrc, compute_area_stats,
    )

    print("\n" + "=" * 60)
    print("WATER BODY CHANGE DETECTION")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("changes")

    # Full-period water occurrence
    print("\nComputing 40-year water occurrence (sampled)...")
    occurrence = compute_water_occurrence(1985, 2025, region)
    persistence = classify_water_persistence(occurrence)

    export_to_drive(occurrence, "water_occurrence_1985_2025", region=region)
    export_to_drive(persistence, "water_persistence_1985_2025", region=region)

    # Persistence area stats -- resolve ee.Number to Python float
    stats = compute_area_stats(persistence, region)
    stats_resolved = {k: _resolve_ee(v) for k, v in stats.items()}
    export_csv(
        [{"category": k, "area_km2": v} for k, v in stats_resolved.items()],
        "water_persistence_stats.csv", "changes",
    )

    # Decade-wise changes
    print("\nComputing decade-wise changes...")
    result = compute_all_decade_changes(region)

    for change_info in result["changes"]:
        period_tag = change_info["period"].replace(" → ", "_to_")
        export_to_drive(
            change_info["change"],
            f"water_change_{period_tag}",
            region=region,
        )

    # Water-to-land conversion (1985-1994 vs 2015-2025)
    print("\nDetecting water-to-land conversions...")
    early_occ = result["decade_occurrences"]["1985-1994"]
    late_occ = result["decade_occurrences"]["2015-2025"]
    w2l = detect_water_to_land(early_occ, late_occ)
    l2w = detect_land_to_water(early_occ, late_occ)
    export_to_drive(w2l.toFloat(), "water_to_land_conversion", region=region)
    export_to_drive(l2w.toFloat(), "land_to_water_conversion", region=region)

    # JRC validation
    print("\nValidating against JRC Global Surface Water...")
    try:
        corr = validate_against_jrc(occurrence, region)
        corr_info = corr.getInfo()
        print(f"  Correlation with JRC: {corr_info}")
    except Exception as e:
        print(f"  JRC validation skipped (error: {e})")

    # Interactive map
    m = create_base_map()
    add_occurrence_layer(m, occurrence, "Our Water Occurrence")
    add_persistence_layer(m, persistence, "Water Persistence")
    jrc_occ = get_jrc_occurrence(region)
    m.addLayer(jrc_occ.divide(100), {
        "min": 0, "max": 1,
        "palette": ["ffffff", "d4e7f7", "89c4e8", "3e8ec4", "1a5fa4", "08306b"],
    }, "JRC Occurrence", shown=False)
    m.addLayerControl()
    save_map(m, "water_change_map.html", "changes")

    # Side-by-side change figure
    try:
        create_change_figure(
            early_occ, late_occ,
            "1985-1994 Occurrence", "2015-2025 Occurrence",
            region,
            os.path.join(cfg.OUTPUT_DIR, "changes", "change_1985_vs_2025.png"),
        )
    except Exception as e:
        print(f"  Change figure generation skipped (error: {e})")

    print("\nWater change analysis complete.")


def run_haors():
    """Haor-specific analysis."""
    from haor_analysis import (
        delineate_all_haors, compute_all_haor_timeseries,
        compare_all_haors,
    )

    print("\n" + "=" * 60)
    print("HAOR-SPECIFIC ANALYSIS")
    print("=" * 60)

    init_gee()
    ensure_output_dir("haors")

    # Delineate haor boundaries
    print("\nDelineating haor boundaries...")
    boundaries = delineate_all_haors()
    for name, boundary in boundaries.items():
        export_to_drive(
            boundary.toFloat(),
            f"{name.replace(' ', '_').lower()}_boundary",
        )

    # Haor map
    dem = get_srtm_dem()
    m = create_haor_map(boundaries, dem)
    save_map(m, "haor_boundaries_map.html", "haors")

    # Area time series (sampled for speed)
    print("\nComputing haor area time series (1990–2024, every 3 years)...")
    haor_series = {}
    for name in cfg.HAORS:
        print(f"  {name}...")
        series = []
        for year in range(1990, 2025, 3):
            try:
                from haor_analysis import compute_haor_area_timeseries
                ts = compute_haor_area_timeseries(name, year, year, "monsoon")
                if ts:
                    series.extend(ts)
            except Exception as e:
                print(f"    Skipped {year}: {e}")
        haor_series[name] = series

    # Resolve ee.Number values to Python floats for CSV and plotting
    for name in haor_series:
        for entry in haor_series[name]:
            entry["area_km2"] = _resolve_ee(entry["area_km2"])
        # Filter out entries where resolution failed
        haor_series[name] = [e for e in haor_series[name] if e["area_km2"] is not None]

    # Export CSVs
    for name, series in haor_series.items():
        export_csv(
            series,
            f"{name.replace(' ', '_').lower()}_area_timeseries.csv",
            "haors",
        )

    # Area trend plot
    plot_haor_area_trends(
        haor_series,
        os.path.join(cfg.OUTPUT_DIR, "haors", "haor_area_trends.png"),
    )

    # Pre-2000 vs Post-2000 comparison
    print("\nComparing pre-2000 vs post-2000...")
    comparisons = compare_all_haors()
    comp_csv = []
    for name, comp in comparisons.items():
        comp_csv.append({
            "haor": name,
            "period1_avg_km2": comp["period1_avg_km2"],
            "period2_avg_km2": comp["period2_avg_km2"],
            "change_km2": comp["change_km2"],
            "change_pct": comp["change_pct"],
        })
    export_csv(comp_csv, "haor_period_comparison.csv", "haors")

    # Comparison plot
    comp_resolved = {}
    for name, comp in comparisons.items():
        comp_resolved[name] = {
            "period1_avg_km2": _resolve_ee(comp["period1_avg_km2"]),
            "period2_avg_km2": _resolve_ee(comp["period2_avg_km2"]),
        }
    plot_period_comparison(
        comp_resolved,
        os.path.join(cfg.OUTPUT_DIR, "haors", "haor_period_comparison.png"),
    )

    print("\nHaor analysis complete.")


def run_full():
    """Run the complete pipeline."""
    print("\n" + "=" * 60)
    print("FULL PIPELINE – Sylhet Haor Wetlands (1985–2025)")
    print("=" * 60)

    start = time.time()
    run_test()
    run_rivers()
    run_floods()
    run_changes()
    run_haors()

    elapsed = (time.time() - start) / 60
    print(f"\n{'=' * 60}")
    print(f"FULL PIPELINE COMPLETE – {elapsed:.1f} minutes")
    print(f"All outputs saved to: {cfg.OUTPUT_DIR}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Sylhet Haor Wetlands Geospatial Analysis Pipeline"
    )
    parser.add_argument("--test", action="store_true", help="Quick test run")
    parser.add_argument("--full", action="store_true", help="Full 40-year analysis")
    parser.add_argument("--rivers", action="store_true", help="River analysis only")
    parser.add_argument("--floods", action="store_true", help="Flood analysis only")
    parser.add_argument("--changes", action="store_true", help="Water change detection only")
    parser.add_argument("--haors", action="store_true", help="Haor analysis only")
    args = parser.parse_args()

    if args.full:
        run_full()
    elif args.rivers:
        init_gee()
        run_rivers()
    elif args.floods:
        run_floods()
    elif args.changes:
        run_changes()
    elif args.haors:
        run_haors()
    else:
        # Default to test
        run_test()


if __name__ == "__main__":
    main()

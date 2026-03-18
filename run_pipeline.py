#!/usr/bin/env python3
"""
Main orchestrator for Bangladesh Geospatial Analysis Pipeline.

Usage:
    python run_pipeline.py --test                       # Quick test (default scope)
    python run_pipeline.py --scope national --test      # National scope test
    python run_pipeline.py --scope national --full      # Full water analysis pipeline
    python run_pipeline.py --scope sylhet --full        # Original Sylhet analysis
    python run_pipeline.py --rivers                     # River erosion analysis only
    python run_pipeline.py --floods                     # Flood extent analysis only
    python run_pipeline.py --changes                    # Water change detection only
    python run_pipeline.py --haors                      # Haor/wetland analysis only
    python run_pipeline.py --nightlights                # Nighttime lights analysis
    python run_pipeline.py --urbanization               # Urbanization & built-up analysis
    python run_pipeline.py --vegetation                 # Vegetation & agriculture analysis
    python run_pipeline.py --landcover                  # Land cover / LULC analysis
    python run_pipeline.py --airquality                 # Air quality (Sentinel-5P) analysis
    python run_pipeline.py --climate                    # Climate (rainfall, LST, drought)
    python run_pipeline.py --poverty                    # Poverty proxy mapping
    python run_pipeline.py --infrastructure             # Infrastructure & construction
    python run_pipeline.py --crops                      # Crop detection & rice phenology
    python run_pipeline.py --slums                      # Slum/informal settlement mapping
    python run_pipeline.py --coastal                    # Coastal & mangrove analysis
    python run_pipeline.py --cyclones                   # Cyclone damage assessment (pre/post)
    python run_pipeline.py --soil                       # Soil properties & erosion risk
    python run_pipeline.py --health                     # Health risk proxy mapping
    python run_pipeline.py --energy                     # Renewable energy potential
    python run_pipeline.py --groundwater                # Groundwater depletion (GRACE)
    python run_pipeline.py --transport                  # Transportation & connectivity gaps
    python run_pipeline.py --alerts                     # Year-over-year change detection alerts
    python run_pipeline.py --alerts --alerts-year 2022  # Alerts for a specific year
    python run_pipeline.py --full-extended              # ALL modules (water + extended)
    python run_pipeline.py --local                     # Local analysis on downloaded data (no GEE)
"""
import argparse
import os
import sys
import time

import ee

sys.path.insert(0, os.path.dirname(__file__))

import config as cfg


def _getinfo_with_timeout(ee_obj, timeout=300):
    """Thread-safe getInfo() with timeout using concurrent.futures."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(ee_obj.getInfo)
        try:
            return future.result(timeout=timeout)
        except (FuturesTimeout, Exception):
            return None


def _resolve_ee(val, timeout=300):
    """Resolve ee.Number/ComputedObject to Python float, or return as-is."""
    if isinstance(val, (ee.Number, ee.ComputedObject)):
        return _getinfo_with_timeout(val, timeout)
    return val


def _batch_resolve_ee(data, timeout=600):
    """Resolve multiple ee values in a single .getInfo() call.

    data: dict of {key: ee_value_or_python_value}
    Returns: dict of {key: resolved_python_value}

    Batches all ee.ComputedObject values into one ee.Dictionary.getInfo()
    call, reducing N network roundtrips to 1.
    """
    ee_keys = []
    ee_vals = {}
    plain = {}
    for k, v in data.items():
        if isinstance(v, (ee.Number, ee.ComputedObject)):
            ee_keys.append(k)
            ee_vals[k] = v
        else:
            plain[k] = v

    if not ee_keys:
        return dict(plain)

    batch = _getinfo_with_timeout(ee.Dictionary(ee_vals), timeout)
    if batch is None:
        batch = {k: None for k in ee_keys}

    result = dict(plain)
    result.update(batch)
    return result


def _batch_resolve_list(entries, ee_fields, timeout=600):
    """Resolve a list of dicts with ee values, batching all into one call.

    entries: list of dicts, each may contain ee values in ee_fields keys
    ee_fields: list of field names that may contain ee values
    Returns: list of dicts with all ee values resolved

    Instead of N*M getInfo() calls (N entries, M fields each), this does 1 call.
    """
    ee_batch = {}
    for i, entry in enumerate(entries):
        for f in ee_fields:
            val = entry.get(f)
            if isinstance(val, (ee.Number, ee.ComputedObject)):
                ee_batch[f"{i}_{f}"] = val

    if not ee_batch:
        return [dict(e) for e in entries]

    resolved = _getinfo_with_timeout(ee.Dictionary(ee_batch), timeout)
    if resolved is None:
        resolved = {k: None for k in ee_batch}

    result = []
    for i, entry in enumerate(entries):
        row = {}
        for k, v in entry.items():
            if k in ee_fields and f"{i}_{k}" in resolved:
                row[k] = resolved[f"{i}_{k}"]
            elif isinstance(v, (ee.Number, ee.ComputedObject)):
                row[k] = None
            else:
                row[k] = v
        result.append(row)
    return result


from data_acquisition import (
    init_gee, get_study_area, get_seasonal_composite,
    get_srtm_dem, get_jrc_water
)
from water_classification import classify_water, compute_water_area
from export_utils import (
    ensure_output_dir, export_geotiff, export_csv,
    export_to_drive, export_shapefile, export_fc_to_csv
)
from visualization import (
    create_base_map, add_water_layer, add_occurrence_layer,
    add_persistence_layer, add_change_layer,
    create_water_comparison_map, create_temporal_map,
    create_river_migration_map, create_haor_map,
    save_map, plot_flood_time_series, plot_haor_area_trends,
    plot_erosion_rates, plot_period_comparison, create_change_figure,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Original Water Analysis Modules
# ═══════════════════════════════════════════════════════════════════════════════

def run_test():
    """Quick pipeline test: authenticate, pull composites, classify water."""
    label = cfg.scope_label()
    print("=" * 60)
    print(f"PIPELINE TEST – {label} 2020 Dry vs Monsoon")
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
    print(f"\n[3/5] Classifying water (method: {cfg.DEFAULT_THRESHOLD_METHOD})...")
    dry_water = classify_water(dry_composite, region=region)
    monsoon_water = classify_water(monsoon_composite, region=region)

    _scale = 300 if cfg.SCOPE == "national" else 30
    dry_area = compute_water_area(dry_water, region, scale=_scale).getInfo()
    monsoon_area = compute_water_area(monsoon_water, region, scale=_scale).getInfo()
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
        scale=300 if cfg.SCOPE == "national" else 30,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    ).getInfo()
    print(f"  JRC mean water occurrence: {jrc_stats.get('occurrence', 'N/A')}%")

    # ── Interactive Map ──────────────────────────────────────────────────
    print("\n[5/5] Creating interactive map...")
    m = create_water_comparison_map(dry_water, monsoon_water, 2020)

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
    print("\nExporting test GeoTIFFs to Drive...")
    export_to_drive(dry_water, "test_dry_water_2020", region=region)
    export_to_drive(monsoon_water, "test_monsoon_water_2020", region=region)

    # ── Summary CSV ──────────────────────────────────────────────────────
    export_csv(
        [{"metric": "dry_area_km2", "value": dry_area},
         {"metric": "monsoon_area_km2", "value": monsoon_area},
         {"metric": "seasonal_inundation_km2", "value": monsoon_area - dry_area}],
        "summary_water_stats_2020.csv",
    )

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print(f"  Scope:        {label}")
    print(f"  Map saved:    {map_path}")
    print(f"  Dry area:     {dry_area:.1f} km²")
    print(f"  Monsoon area: {monsoon_area:.1f} km²")
    print("=" * 60)


def run_rivers():
    """River erosion and channel migration analysis."""
    from river_analysis import run_river_analysis

    print("\n" + "=" * 60)
    print(f"RIVER EROSION & CHANNEL MIGRATION – {cfg.scope_label()}")
    print(f"  Analyzing {len(cfg.RIVERS)} rivers")
    print("=" * 60)

    init_gee()
    ensure_output_dir("rivers")

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    for river_name in cfg.RIVERS:
        print(f"\n── {river_name} River ──")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_river_analysis, river_name)
            try:
                results = future.result(timeout=600)
            except (FuturesTimeout, Exception) as e:
                print(f"  FAILED: {e}")
                continue

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

        # Erosion rates CSV
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
        get_annual_water_extents,
    )

    print("\n" + "=" * 60)
    print(f"FLOOD EXTENT MAPPING – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("floods")

    # Sampling interval: national=4 years, sylhet=2 years
    step = 4 if cfg.SCOPE == "national" else 2
    print(f"\nBuilding flood time series (every {step} years)...")
    sample_years = list(range(1988, 2025, step))
    time_series = []
    for year in sample_years:
        print(f"  Processing {year}...")
        try:
            extents = get_annual_water_extents(year, region)
            dry_val = _resolve_ee(extents["dry_area_km2"])
            monsoon_val = _resolve_ee(extents["monsoon_area_km2"])
            seasonal_val = _resolve_ee(extents["seasonal_area_km2"])
            if dry_val is not None and monsoon_val is not None:
                if seasonal_val is not None and seasonal_val == 0 and monsoon_val == dry_val:
                    print(f"    WARNING: monsoon was <= dry ({dry_val:.1f} km2), clamped")
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
    try:
        freq = compute_flood_frequency(2000, 2024, region)
        export_to_drive(freq, "flood_frequency_2000_2024", region=region)
    except Exception as e:
        print(f"  Flood frequency skipped: {e}")

    # Flood trend
    print("Computing flood trend...")
    try:
        trend = detect_flood_trend(1990, 2024, region)
        export_to_drive(trend, "flood_trend_1990_2024", region=region)
    except Exception as e:
        print(f"  Flood trend skipped: {e}")

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
    print(f"WATER BODY CHANGE DETECTION – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("changes")

    # For national scope, use tiled processing
    if cfg.SCOPE == "national":
        from tiling import run_tiled, merge_image_tiles
        print("\nComputing water occurrence (tiled by division)...")
        occurrence = run_tiled(
            compute_water_occurrence,
            region_arg_name="region",
            merge_func=merge_image_tiles,
            start_year=1985, end_year=2025,
        )
    else:
        print("\nComputing 40-year water occurrence...")
        occurrence = compute_water_occurrence(1985, 2025, region)

    if occurrence is None:
        print("  ERROR: water occurrence computation returned None")
        return

    persistence = classify_water_persistence(occurrence)

    export_to_drive(occurrence, "water_occurrence_1985_2025", region=region)
    export_to_drive(persistence, "water_persistence_1985_2025", region=region)

    # Persistence area stats
    stats = compute_area_stats(persistence, region)
    stats_resolved = {k: _resolve_ee(v) for k, v in stats.items()}
    export_csv(
        [{"category": k, "area_km2": v} for k, v in stats_resolved.items()],
        "water_persistence_stats.csv", "changes",
    )

    # Decade-wise changes
    print("\nComputing decade-wise changes...")
    try:
        result = compute_all_decade_changes(region)

        for change_info in result["changes"]:
            period_tag = change_info["period"].replace(" → ", "_to_")
            export_to_drive(
                change_info["change"],
                f"water_change_{period_tag}",
                region=region,
            )

        # Water-to-land conversion
        print("\nDetecting water-to-land conversions...")
        early_occ = result["decade_occurrences"]["1985-1994"]
        late_occ = result["decade_occurrences"]["2015-2025"]
        w2l = detect_water_to_land(early_occ, late_occ)
        l2w = detect_land_to_water(early_occ, late_occ)
        export_to_drive(w2l.toFloat(), "water_to_land_conversion", region=region)
        export_to_drive(l2w.toFloat(), "land_to_water_conversion", region=region)
    except Exception as e:
        print(f"  Decade changes failed: {e}")

    # JRC validation
    print("\nValidating against JRC Global Surface Water...")
    try:
        corr = validate_against_jrc(occurrence, region)
        corr_info = corr.getInfo()
        print(f"  Correlation with JRC: {corr_info}")
    except Exception as e:
        print(f"  JRC validation skipped: {e}")

    # Interactive map
    try:
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
    except Exception as e:
        print(f"  Map generation skipped: {e}")

    print("\nWater change analysis complete.")


def run_haors():
    """Haor/wetland-specific analysis."""
    from haor_analysis import (
        delineate_all_haors, compute_all_haor_timeseries,
        compare_all_haors,
    )

    wetland_label = "Wetland" if cfg.SCOPE == "national" else "Haor"
    print("\n" + "=" * 60)
    print(f"{wetland_label.upper()} ANALYSIS – {cfg.scope_label()}")
    print(f"  Analyzing {len(cfg.HAORS)} {wetland_label.lower()}s")
    print("=" * 60)

    init_gee()
    ensure_output_dir("haors")

    # Delineate boundaries
    print(f"\nDelineating {wetland_label.lower()} boundaries...")
    boundaries = delineate_all_haors()
    for name, boundary in boundaries.items():
        export_to_drive(
            boundary.toFloat(),
            f"{name.replace(' ', '_').lower()}_boundary",
        )

    # Map
    try:
        dem = get_srtm_dem()
        m = create_haor_map(boundaries, dem)
        save_map(m, "haor_boundaries_map.html", "haors")
    except Exception as e:
        print(f"  Map generation skipped: {e}")

    # Area time series (sampled)
    step = 5 if cfg.SCOPE == "national" else 3
    print(f"\nComputing area time series (1990-2024, every {step} years)...")
    haor_series = {}
    for name in cfg.HAORS:
        print(f"  {name}...")
        series = []
        for year in range(1990, 2025, step):
            try:
                from haor_analysis import compute_haor_area_timeseries
                ts = compute_haor_area_timeseries(name, year, year, "monsoon")
                if ts:
                    series.extend(ts)
            except Exception as e:
                print(f"    Skipped {year}: {e}")
        haor_series[name] = series

    # Resolve ee.Number values and filter implausibly small results
    import math
    for name in haor_series:
        radius_m = cfg.HAORS[name]["radius"]
        min_plausible_km2 = 0.01 * math.pi * (radius_m / 1000) ** 2
        for entry in haor_series[name]:
            entry["area_km2"] = _resolve_ee(entry["area_km2"])
        filtered = []
        for e in haor_series[name]:
            if e["area_km2"] is None:
                continue
            if e["area_km2"] < min_plausible_km2:
                print(f"    {name} {e.get('year', '?')}: dropped implausible value {e['area_km2']:.3f} km2 (min {min_plausible_km2:.1f} km2)")
                continue
            filtered.append(e)
        haor_series[name] = filtered

    # Export CSVs
    for name, series in haor_series.items():
        export_csv(
            series,
            f"{name.replace(' ', '_').lower()}_area_timeseries.csv",
            "haors",
        )

    # Area trend plot
    try:
        plot_haor_area_trends(
            haor_series,
            os.path.join(cfg.OUTPUT_DIR, "haors", "haor_area_trends.png"),
        )
    except Exception as e:
        print(f"  Area trend plot skipped: {e}")

    # Pre-2000 vs Post-2000 comparison
    print("\nComparing pre-2000 vs post-2000...")
    try:
        comparisons = compare_all_haors()
        comp_csv = []
        for name, comp in comparisons.items():
            p1 = _resolve_ee(comp["period1_avg_km2"])
            p2 = _resolve_ee(comp["period2_avg_km2"])
            chg = _resolve_ee(comp["change_km2"])
            pct = _resolve_ee(comp["change_pct"])
            comp_csv.append({
                "haor": name,
                "period1_avg_km2": p1,
                "period2_avg_km2": p2,
                "change_km2": chg,
                "change_pct": pct,
            })
        export_csv(comp_csv, "haor_period_comparison.csv", "haors")

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
    except Exception as e:
        print(f"  Period comparison skipped: {e}")

    print(f"\n{wetland_label} analysis complete.")


# ═══════════════════════════════════════════════════════════════════════════════
# Extended Analysis Modules
# ═══════════════════════════════════════════════════════════════════════════════

def run_nightlights():
    """Nighttime lights and electrification analysis."""
    from nightlights import run_nightlights_analysis

    print("\n" + "=" * 60)
    print(f"NIGHTTIME LIGHTS ANALYSIS – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("nightlights")

    results = run_nightlights_analysis(region)

    # Export time series (batch resolve: 1 call instead of N*3)
    if results.get("time_series"):
        ts_resolved = _batch_resolve_list(
            results["time_series"],
            ["mean_radiance", "max_radiance", "sum_radiance"],
        )
        export_csv(ts_resolved, "nightlights_timeseries.csv", "nightlights")

    # Export electrification stats
    for year, elec in results.get("electrification", {}).items():
        lit_area = _resolve_ee(elec.get("lit_area_km2"))
        if lit_area is not None:
            export_csv(
                [{"year": year, "lit_area_km2": lit_area}],
                f"electrification_{year}.csv", "nightlights",
            )
        try:
            export_to_drive(
                elec["mask"].toFloat(), f"electrification_mask_{year}", region=region
            )
        except Exception as e:
            print(f"  Export electrification {year} skipped: {e}")

    # Export change maps
    for period, change_img in results.get("changes", {}).items():
        try:
            export_to_drive(change_img.toFloat(), f"light_change_{period}", region=region)
        except Exception as e:
            print(f"  Export light change {period} skipped: {e}")

    # Export city stats
    for year, cities in results.get("city_stats", {}).items():
        city_resolved = []
        for c in cities:
            city_resolved.append({
                "city": c.get("city", ""),
                "mean_radiance": _resolve_ee(c.get("mean_radiance")),
                "max_radiance": _resolve_ee(c.get("max_radiance")),
            })
        export_csv(city_resolved, f"city_lights_{year}.csv", "nightlights")

    print("\nNighttime lights analysis complete.")


def run_urbanization():
    """Urbanization and built-up area analysis."""
    from urbanization import run_urbanization_analysis

    print("\n" + "=" * 60)
    print(f"URBANIZATION ANALYSIS – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("urbanization")

    results = run_urbanization_analysis(region)

    # Export built-up time series
    if results.get("builtup_timeseries"):
        ts_resolved = []
        for entry in results["builtup_timeseries"]:
            ts_resolved.append({
                "year": entry["year"],
                "built_area_km2": _resolve_ee(entry.get("built_area_km2")),
            })
        export_csv(ts_resolved, "builtup_timeseries.csv", "urbanization")

    # Export urbanization rates
    if results.get("urbanization_rates"):
        rates_resolved = []
        for entry in results["urbanization_rates"]:
            rates_resolved.append({
                "period": entry["period"],
                "total_change_km2": _resolve_ee(entry.get("total_change_km2")),
                "annual_rate_km2": _resolve_ee(entry.get("annual_rate_km2")),
            })
        export_csv(rates_resolved, "urbanization_rates.csv", "urbanization")

    # Export expansion maps
    expansion = results.get("expansion_1990_2020")
    if expansion:
        try:
            export_to_drive(
                expansion["new_urban"].toFloat(),
                "urban_expansion_1990_2020", region=region,
            )
        except Exception as e:
            print(f"  Export expansion skipped: {e}")

    # Export settlement classification
    if results.get("settlement_2020"):
        sett_resolved = []
        for entry in results["settlement_2020"]:
            sett_resolved.append({
                "class_name": entry["class_name"],
                "area_km2": _resolve_ee(entry.get("area_km2")),
            })
        export_csv(sett_resolved, "settlement_classification_2020.csv", "urbanization")

    # Export city growth
    for city, growth in results.get("city_growth", {}).items():
        growth_resolved = []
        for entry in growth:
            growth_resolved.append({
                "year": entry["year"],
                "built_area_km2": _resolve_ee(entry.get("built_area_km2")),
            })
        city_slug = city.lower().replace(" ", "_")
        export_csv(growth_resolved, f"{city_slug}_growth.csv", "urbanization")

    print("\nUrbanization analysis complete.")


def run_vegetation():
    """Vegetation, agriculture, and forest analysis."""
    from vegetation import run_vegetation_analysis

    print("\n" + "=" * 60)
    print(f"VEGETATION & AGRICULTURE ANALYSIS – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("vegetation")

    results = run_vegetation_analysis(region)

    # Export NDVI time series
    if results.get("ndvi_timeseries"):
        ts_resolved = _batch_resolve_list(
            results["ndvi_timeseries"], ["mean_ndvi", "max_ndvi"],
        )
        export_csv(ts_resolved, "ndvi_timeseries.csv", "vegetation")

    # Export seasonal NDVI
    if results.get("seasonal_ndvi"):
        seasonal_resolved = _batch_resolve_list(
            results["seasonal_ndvi"],
            ["pre_monsoon_ndvi", "monsoon_ndvi", "post_monsoon_ndvi", "winter_ndvi"],
        )
        export_csv(seasonal_resolved, "seasonal_ndvi.csv", "vegetation")

    # Export forest stats
    if results.get("forest_stats"):
        fs = results["forest_stats"]
        fs_resolved = [_batch_resolve_ee({
            "forest_2000_km2": fs.get("forest_2000_km2"),
            "forest_loss_km2": fs.get("forest_loss_km2"),
            "forest_gain_km2": fs.get("forest_gain_km2"),
        })]
        export_csv(fs_resolved, "forest_stats.csv", "vegetation")

    # Export annual forest loss (batch: 23 years in 1 call)
    if results.get("forest_loss_annual"):
        loss_resolved = _batch_resolve_list(
            results["forest_loss_annual"], ["loss_km2"],
        )
        export_csv(loss_resolved, "forest_loss_annual.csv", "vegetation")

    # Export cropland area
    if results.get("cropland_area_km2"):
        crop_area = _resolve_ee(results["cropland_area_km2"])
        export_csv([{"cropland_area_km2": crop_area}], "cropland_area.csv", "vegetation")

    if results.get("cropland_mask"):
        try:
            export_to_drive(
                results["cropland_mask"].toFloat(),
                "cropland_mask_2021", region=region,
            )
        except Exception as e:
            print(f"  Export cropland mask skipped: {e}")

    print("\nVegetation analysis complete.")


def run_landcover():
    """Land cover / LULC classification and change analysis."""
    from land_cover import run_land_cover_analysis

    print("\n" + "=" * 60)
    print(f"LAND COVER ANALYSIS – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("landcover")

    results = run_land_cover_analysis(region)

    # Export MODIS LULC time series
    if results.get("modis_timeseries"):
        ts_resolved = []
        for entry in results["modis_timeseries"]:
            resolved = {"year": entry["year"]}
            for key, val in entry.items():
                if key != "year":
                    resolved[key] = _resolve_ee(val)
            ts_resolved.append(resolved)
        export_csv(ts_resolved, "modis_lulc_timeseries.csv", "landcover")

    # Export Dynamic World time series
    if results.get("dw_timeseries"):
        dw_resolved = []
        for entry in results["dw_timeseries"]:
            resolved = {"year": entry["year"]}
            for cls in cfg.DW_CLASSES:
                resolved[cls] = _resolve_ee(entry.get(cls))
            dw_resolved.append(resolved)
        export_csv(dw_resolved, "dynamic_world_timeseries.csv", "landcover")

    # Export ESA WorldCover
    if results.get("esa_worldcover"):
        try:
            export_to_drive(results["esa_worldcover"], "esa_worldcover_2021", region=region)
        except Exception as e:
            print(f"  Export WorldCover skipped: {e}")

    # Export change maps
    for key in ["modis_change", "dw_change"]:
        change = results.get(key)
        if change:
            try:
                export_to_drive(
                    change["changed"].toFloat(),
                    f"{key}_map", region=region,
                )
            except Exception as e:
                print(f"  Export {key} skipped: {e}")

    print("\nLand cover analysis complete.")


def run_airquality():
    """Air quality analysis using Sentinel-5P."""
    from air_quality import run_air_quality_analysis

    print("\n" + "=" * 60)
    print(f"AIR QUALITY ANALYSIS – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("airquality")

    results = run_air_quality_analysis(region)

    # Export pollutant time series
    for pollutant, ts in results.get("timeseries", {}).items():
        ts_resolved = []
        for entry in ts:
            ts_resolved.append({
                "year": entry.get("year"),
                "mean": _resolve_ee(entry.get("mean")),
                "max": _resolve_ee(entry.get("max")),
                "median": _resolve_ee(entry.get("median")),
            })
        export_csv(ts_resolved, f"{pollutant.lower()}_timeseries.csv", "airquality")

    # Export seasonal patterns
    for pollutant, seasonal in results.get("seasonal_2023", {}).items():
        resolved = {"pollutant": pollutant, "year": 2023}
        for key in ["winter_mean", "pre_monsoon_mean", "monsoon_mean", "post_monsoon_mean"]:
            resolved[key] = _resolve_ee(seasonal.get(key))
        export_csv([resolved], f"{pollutant.lower()}_seasonal_2023.csv", "airquality")

    # Export urban pollution
    for pollutant, cities in results.get("urban_pollution", {}).items():
        city_resolved = []
        for c in cities:
            city_resolved.append({
                "city": c.get("city", ""),
                "mean": _resolve_ee(c.get("mean")),
                "max": _resolve_ee(c.get("max")),
            })
        export_csv(city_resolved, f"{pollutant.lower()}_urban_2023.csv", "airquality")

    # Export hotspot maps
    for pollutant, hotspot in results.get("hotspots", {}).items():
        try:
            export_to_drive(
                hotspot["hotspots"].toFloat(),
                f"{pollutant.lower()}_hotspots_2023", region=region,
            )
        except Exception as e:
            print(f"  Export {pollutant} hotspots skipped: {e}")

    # Export pollutant stack
    if results.get("pollutant_stack"):
        try:
            export_to_drive(results["pollutant_stack"], "pollutant_stack_2023", region=region)
        except Exception as e:
            print(f"  Export pollutant stack skipped: {e}")

    print("\nAir quality analysis complete.")


def run_climate():
    """Climate analysis: rainfall, temperature, drought."""
    from climate import run_climate_analysis

    print("\n" + "=" * 60)
    print(f"CLIMATE ANALYSIS – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("climate")

    results = run_climate_analysis(region)

    # Export rainfall time series (batch)
    if results.get("rainfall_timeseries"):
        ts_resolved = _batch_resolve_list(
            results["rainfall_timeseries"], ["mean_precip_mm", "max_precip_mm"],
        )
        export_csv(ts_resolved, "rainfall_timeseries.csv", "climate")

    # Export LST time series (batch)
    if results.get("lst_timeseries"):
        lst_resolved = _batch_resolve_list(
            results["lst_timeseries"], ["day_lst_c", "night_lst_c"],
        )
        export_csv(lst_resolved, "lst_timeseries.csv", "climate")

    # Export UHI results (batch)
    uhi_entries = []
    for city, uhi in results.get("uhi", {}).items():
        uhi_entries.append({
            "city": city,
            "urban_lst_c": uhi.get("urban_lst_c"),
            "rural_lst_c": uhi.get("rural_lst_c"),
            "uhi_intensity_c": uhi.get("uhi_intensity_c"),
        })
    if uhi_entries:
        uhi_resolved = _batch_resolve_list(
            uhi_entries, ["urban_lst_c", "rural_lst_c", "uhi_intensity_c"],
        )
        export_csv(uhi_resolved, "urban_heat_island.csv", "climate")

    # Export monsoon rainfall (batch)
    if results.get("monsoon_rainfall"):
        monsoon_resolved = _batch_resolve_list(
            results["monsoon_rainfall"], ["monsoon_precip_mm"],
        )
        export_csv(monsoon_resolved, "monsoon_rainfall.csv", "climate")

    # Export drought maps
    for year, drought in results.get("drought", {}).items():
        if drought is not None:
            try:
                export_to_drive(drought.toFloat(), f"drought_index_{year}", region=region)
            except Exception as e:
                print(f"  Export drought {year} skipped: {e}")

    print("\nClimate analysis complete.")


def run_poverty():
    """Poverty proxy mapping and analysis."""
    from poverty import run_poverty_analysis

    print("\n" + "=" * 60)
    print(f"POVERTY PROXY MAPPING – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("poverty")

    results = run_poverty_analysis(region)

    # Export poverty index map
    if results.get("poverty_2020"):
        try:
            export_to_drive(
                results["poverty_2020"].toFloat(),
                "poverty_index_2020", region=region,
            )
        except Exception as e:
            print(f"  Export poverty index skipped: {e}")

    if results.get("poverty_levels_2020"):
        try:
            export_to_drive(
                results["poverty_levels_2020"].toFloat(),
                "poverty_levels_2020", region=region,
            )
        except Exception as e:
            print(f"  Export poverty levels skipped: {e}")

    # Export division stats
    if results.get("division_stats"):
        try:
            export_fc_to_csv(results["division_stats"], "poverty_by_division.csv", "poverty")
        except Exception as e:
            print(f"  Export division stats skipped: {e}")

    # Export poverty change
    if results.get("poverty_change"):
        try:
            export_to_drive(
                results["poverty_change"].toFloat(),
                "poverty_change_2012_2020", region=region,
            )
        except Exception as e:
            print(f"  Export poverty change skipped: {e}")

    # Export district ranking
    if results.get("district_ranking"):
        try:
            export_fc_to_csv(results["district_ranking"], "poverty_district_ranking.csv", "poverty")
        except Exception as e:
            print(f"  Export district ranking skipped: {e}")

    # Export time series stats
    if results.get("poverty_timeseries"):
        ts_resolved = []
        for year, stats in results["poverty_timeseries"].items():
            entry = {"year": year}
            if hasattr(stats, 'getInfo'):
                info = stats.getInfo()
                if isinstance(info, dict):
                    entry.update(info)
            ts_resolved.append(entry)
        export_csv(ts_resolved, "poverty_timeseries.csv", "poverty")

    print("\nPoverty analysis complete.")


def run_infrastructure():
    """Infrastructure and construction analysis."""
    from infrastructure import run_infrastructure_analysis

    print("\n" + "=" * 60)
    print(f"INFRASTRUCTURE & CONSTRUCTION – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("infrastructure")

    results = run_infrastructure_analysis(region)

    # Export construction area stats
    if results.get("construction_area"):
        ca = results["construction_area"]
        export_csv([{
            "period": ca["period"],
            "new_construction_km2": _resolve_ee(ca.get("new_construction_km2")),
            "demolished_km2": _resolve_ee(ca.get("demolished_km2")),
        }], "construction_area_2018_2024.csv", "infrastructure")

    # Export construction time series
    if results.get("construction_timeseries"):
        ts_resolved = []
        for entry in results["construction_timeseries"]:
            ts_resolved.append({
                "period": entry["period"],
                "new_construction_km2": _resolve_ee(entry.get("new_construction_km2")),
                "demolished_km2": _resolve_ee(entry.get("demolished_km2")),
            })
        export_csv(ts_resolved, "construction_timeseries.csv", "infrastructure")

    # Export construction change maps
    change = results.get("construction_2018_2024")
    if change:
        for key in ["new_construction", "demolished"]:
            try:
                export_to_drive(
                    change[key].toFloat(),
                    f"{key}_2018_2024", region=region,
                )
            except Exception as e:
                print(f"  Export {key} skipped: {e}")

    # Export construction hotspots
    hotspot = results.get("hotspots")
    if hotspot:
        try:
            export_to_drive(
                hotspot["hotspots"].toFloat(),
                "construction_hotspots_2018_2024", region=region,
            )
        except Exception as e:
            print(f"  Export hotspots skipped: {e}")

    # Export economic zone growth
    for zone, growth in results.get("economic_zones", {}).items():
        growth_resolved = []
        for entry in growth:
            growth_resolved.append({
                "year": entry["year"],
                "built_area_km2": _resolve_ee(entry.get("built_area_km2")),
            })
        zone_slug = zone.lower().replace(" ", "_")
        export_csv(growth_resolved, f"{zone_slug}_growth.csv", "infrastructure")

    # Export infrastructure density
    if results.get("infra_density"):
        try:
            export_to_drive(
                results["infra_density"].toFloat(),
                "infrastructure_density", region=region,
            )
        except Exception as e:
            print(f"  Export infra density skipped: {e}")

    # Export connectivity index
    if results.get("connectivity"):
        try:
            export_to_drive(
                results["connectivity"].toFloat(),
                "connectivity_index", region=region,
            )
        except Exception as e:
            print(f"  Export connectivity skipped: {e}")

    print("\nInfrastructure analysis complete.")


def run_crops():
    """Crop detection, rice phenology, and agricultural analysis."""
    from crop_detection import run_crop_detection_analysis

    print("\n" + "=" * 60)
    print(f"CROP DETECTION & RICE PHENOLOGY – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("crops")

    results = run_crop_detection_analysis(region)

    # Export aman rice area time series
    for season_key, filename in [("aman_timeseries", "aman_rice_timeseries.csv"),
                                  ("boro_timeseries", "boro_rice_timeseries.csv")]:
        if results.get(season_key):
            ts_resolved = []
            for entry in results[season_key]:
                ts_resolved.append({
                    "year": _resolve_ee(entry.get("year", entry.get("year"))),
                    "rice_area_km2": _resolve_ee(entry.get("rice_area_km2")),
                })
            if ts_resolved:
                export_csv(ts_resolved, filename, "crops")

    # Export crop type area stats (key: crop_stats_2023)
    if results.get("crop_stats_2023"):
        stats = results["crop_stats_2023"]
        if isinstance(stats, dict):
            crop_resolved = []
            for crop_type, area in stats.items():
                crop_resolved.append({
                    "crop_type": crop_type,
                    "area_km2": _resolve_ee(area),
                })
            if crop_resolved:
                export_csv(crop_resolved, "crop_area_stats_2023.csv", "crops")

    # Export NDVI profile
    if results.get("ndvi_profile_2023"):
        profile = results["ndvi_profile_2023"]
        if isinstance(profile, list):
            profile_resolved = []
            for entry in profile:
                profile_resolved.append({
                    "month": _resolve_ee(entry.get("month")),
                    "mean_ndvi": _resolve_ee(entry.get("mean_ndvi")),
                })
            if profile_resolved:
                export_csv(profile_resolved, "ndvi_crop_profile_2023.csv", "crops")

    # Export yield proxies
    if results.get("yield_proxies"):
        yield_resolved = []
        for entry in results["yield_proxies"]:
            if isinstance(entry, dict):
                yield_resolved.append({
                    "year": _resolve_ee(entry.get("year")),
                    "season": entry.get("season", ""),
                    "mean_ndvi": _resolve_ee(entry.get("mean_ndvi")),
                    "max_ndvi": _resolve_ee(entry.get("max_ndvi")),
                })
        if yield_resolved:
            export_csv(yield_resolved, "yield_proxies.csv", "crops")

    # Export rice paddy mask
    if results.get("rice_paddy_mask"):
        try:
            export_to_drive(
                results["rice_paddy_mask"].toFloat(),
                "rice_paddy_mask_2023", region=region,
            )
        except Exception as e:
            print(f"  Export rice paddy mask skipped: {e}")

    # Export crop type map
    if results.get("crop_type_map"):
        try:
            export_to_drive(
                results["crop_type_map"].toFloat(),
                "crop_type_map_2023", region=region,
            )
        except Exception as e:
            print(f"  Export crop type map skipped: {e}")

    # Export cropping intensity
    if results.get("cropping_intensity"):
        try:
            export_to_drive(
                results["cropping_intensity"].toFloat(),
                "cropping_intensity_2023", region=region,
            )
        except Exception as e:
            print(f"  Export cropping intensity skipped: {e}")

    # Export yield proxy stats
    if results.get("yield_proxy"):
        yield_resolved = {
            "year": 2023,
            "mean_yield_proxy": _resolve_ee(results["yield_proxy"].get("mean_yield_proxy")),
            "max_yield_proxy": _resolve_ee(results["yield_proxy"].get("max_yield_proxy")),
        }
        export_csv([yield_resolved], "yield_proxy_2023.csv", "crops")

    # Export crop stress
    if results.get("crop_stress"):
        try:
            export_to_drive(
                results["crop_stress"].toFloat(),
                "crop_stress_2023", region=region,
            )
        except Exception as e:
            print(f"  Export crop stress skipped: {e}")

    print("\nCrop detection analysis complete.")


def run_slums():
    """Slum/informal settlement mapping and analysis."""
    from slum_mapping import run_slum_analysis

    print("\n" + "=" * 60)
    print(f"SLUM / INFORMAL SETTLEMENT MAPPING – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("slums")

    results = run_slum_analysis(region)

    # Export slum index map
    if results.get("slum_index_2020"):
        try:
            export_to_drive(
                results["slum_index_2020"].toFloat(),
                "slum_index_2020", region=region,
            )
        except Exception as e:
            print(f"  Export slum index skipped: {e}")

    # Export slum risk classification
    if results.get("slum_risk_2020"):
        try:
            export_to_drive(
                results["slum_risk_2020"].toFloat(),
                "slum_risk_classification_2020", region=region,
            )
        except Exception as e:
            print(f"  Export slum risk skipped: {e}")

    # Export slum area estimate
    if results.get("slum_area_2020"):
        sa = results["slum_area_2020"]
        export_csv([{
            "year": sa.get("year", 2020),
            "slum_area_km2": _resolve_ee(sa.get("slum_area_km2")),
            "threshold": sa.get("threshold", 0.6),
        }], "slum_area_2020.csv", "slums")

    # Export known slum area stats
    if results.get("known_slums"):
        known_resolved = []
        for entry in results["known_slums"]:
            known_resolved.append({
                "area": entry.get("area", ""),
                "mean_slum_index": _resolve_ee(entry.get("mean_slum_index")),
                "max_slum_index": _resolve_ee(entry.get("max_slum_index")),
            })
        export_csv(known_resolved, "known_slum_areas.csv", "slums")

    # Export slum growth
    if results.get("slum_growth"):
        sg = results["slum_growth"]
        export_csv([{
            "period": sg.get("period", ""),
            "new_slum_km2": _resolve_ee(sg.get("new_slum_km2")),
            "cleared_slum_km2": _resolve_ee(sg.get("cleared_slum_km2")),
        }], "slum_growth_2010_2020.csv", "slums")
        if sg.get("new_slum_mask"):
            try:
                export_to_drive(
                    sg["new_slum_mask"].toFloat(),
                    "new_slum_areas_2010_2020", region=region,
                )
            except Exception as e:
                print(f"  Export slum growth map skipped: {e}")

    # Export slum area time series
    if results.get("slum_timeseries"):
        ts_resolved = []
        for entry in results["slum_timeseries"]:
            ts_resolved.append({
                "year": entry.get("year"),
                "slum_area_km2": _resolve_ee(entry.get("slum_area_km2")),
            })
        export_csv(ts_resolved, "slum_area_timeseries.csv", "slums")

    print("\nSlum mapping analysis complete.")


def run_coastal():
    """Coastal zone, mangrove, and cyclone impact analysis."""
    from coastal import run_coastal_analysis

    print("\n" + "=" * 60)
    print(f"COASTAL & MANGROVE ANALYSIS – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("coastal")

    results = run_coastal_analysis(region)

    # Export LECZ map
    if results.get("lecz"):
        try:
            export_to_drive(results["lecz"].toFloat(), "lecz_5m", region=region)
        except Exception as e:
            print(f"  Export LECZ skipped: {e}")

    # Export LECZ areas
    if results.get("lecz_areas"):
        lecz_resolved = []
        for entry in results["lecz_areas"]:
            lecz_resolved.append({
                "elevation_threshold_m": entry["elevation_threshold_m"],
                "area_km2": _resolve_ee(entry.get("area_km2")),
            })
        export_csv(lecz_resolved, "lecz_areas.csv", "coastal")

    # Export LECZ population
    if results.get("lecz_population"):
        lp = results["lecz_population"]
        export_csv([{
            "threshold_m": lp.get("threshold_m"),
            "year": lp.get("year"),
            "population_in_lecz": _resolve_ee(lp.get("population_in_lecz")),
        }], "lecz_population.csv", "coastal")

    # Export shoreline changes
    if results.get("shoreline_changes"):
        sc_resolved = []
        for entry in results["shoreline_changes"]:
            sc_resolved.append({
                "period": entry.get("period", ""),
                "accretion_km2": _resolve_ee(entry.get("accretion_km2")),
                "erosion_km2": _resolve_ee(entry.get("erosion_km2")),
            })
        export_csv(sc_resolved, "shoreline_changes.csv", "coastal")

    # Export mangrove area
    if results.get("mangrove_area"):
        ma = results["mangrove_area"]
        export_csv([{
            "year": ma.get("year"),
            "mangrove_area_km2": _resolve_ee(ma.get("mangrove_area_km2")),
        }], "mangrove_area.csv", "coastal")

    # Export mangrove health time series
    if results.get("mangrove_health"):
        mh_resolved = []
        for entry in results["mangrove_health"]:
            mh_resolved.append({
                "year": entry.get("year"),
                "mean_mangrove_ndvi": _resolve_ee(entry.get("mean_mangrove_ndvi")),
                "std_mangrove_ndvi": _resolve_ee(entry.get("std_mangrove_ndvi")),
            })
        export_csv(mh_resolved, "mangrove_health_timeseries.csv", "coastal")

    # Export mangrove change
    if results.get("mangrove_change"):
        mc = results["mangrove_change"]
        export_csv([{
            "mangrove_loss_km2": _resolve_ee(mc.get("mangrove_loss_km2")),
        }], "mangrove_loss.csv", "coastal")
        if mc.get("mangrove_loss_mask"):
            try:
                export_to_drive(
                    mc["mangrove_loss_mask"].toFloat(),
                    "mangrove_loss_map", region=region,
                )
            except Exception as e:
                print(f"  Export mangrove loss map skipped: {e}")

    # Export cyclone impacts
    if results.get("cyclone_impacts"):
        cyc_resolved = []
        for entry in results["cyclone_impacts"]:
            cyc_resolved.append({
                "cyclone": entry.get("cyclone", ""),
                "mean_ndvi_drop": _resolve_ee(entry.get("mean_ndvi_drop")),
                "max_ndvi_drop": _resolve_ee(entry.get("max_ndvi_drop")),
            })
        export_csv(cyc_resolved, "cyclone_impacts.csv", "coastal")

    print("\nCoastal analysis complete.")


def run_cyclones():
    """Pre/post cyclone damage assessment: vegetation loss, flooding, severity."""
    from cyclone_damage import run_cyclone_damage_analysis

    print("\n" + "=" * 60)
    print(f"CYCLONE DAMAGE ASSESSMENT – {cfg.scope_label()}")
    print(f"  Cyclones: {', '.join(cfg.CYCLONE_LANDFALL_POINTS)}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("cyclones")

    results = run_cyclone_damage_analysis(region)

    damage_list = results.get("cyclone_damage", [])
    if damage_list:
        resolved = []
        for entry in damage_list:
            if entry.get("error"):
                resolved.append({
                    "cyclone":           entry.get("cyclone", ""),
                    "landfall_date":     entry.get("landfall_date", ""),
                    "severe_km2":        None,
                    "moderate_km2":      None,
                    "mild_km2":          None,
                    "total_damaged_km2": None,
                    "flood_area_km2":    None,
                    "mean_ndvi_diff":    None,
                    "max_ndvi_drop":     None,
                    "error":             entry.get("error", ""),
                })
                continue
            resolved.append({
                "cyclone":           entry.get("cyclone", ""),
                "landfall_date":     entry.get("landfall_date", ""),
                "severe_km2":        _resolve_ee(entry.get("severe_km2")),
                "moderate_km2":      _resolve_ee(entry.get("moderate_km2")),
                "mild_km2":          _resolve_ee(entry.get("mild_km2")),
                "total_damaged_km2": _resolve_ee(entry.get("total_damaged_km2")),
                "flood_area_km2":    _resolve_ee(entry.get("flood_area_km2")),
                "mean_ndvi_diff":    _resolve_ee(entry.get("mean_ndvi_diff")),
                "max_ndvi_drop":     _resolve_ee(entry.get("max_ndvi_drop")),
            })

            # Export damage severity maps
            for severity in ("severe_mask", "moderate_mask", "mild_mask", "flood_mask"):
                mask = entry.get(severity)
                if mask is not None:
                    cyclone_slug = entry["cyclone"].lower()
                    try:
                        export_to_drive(
                            mask.toFloat(),
                            f"{cyclone_slug}_{severity}",
                            region=entry.get("impact_zone", region),
                        )
                    except Exception as e:
                        print(f"  Export {cyclone_slug}/{severity} skipped: {e}")

        export_csv(resolved, "cyclone_damage_summary.csv", "cyclones")

    print("\nCyclone damage assessment complete.")


def run_soil():
    """Soil properties, erosion risk, and agricultural suitability."""
    from soil_analysis import run_soil_analysis

    print("\n" + "=" * 60)
    print(f"SOIL ANALYSIS – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("soil")

    results = run_soil_analysis(region)

    # Export soil stats
    if results.get("soil_stats"):
        stats = results["soil_stats"]
        if hasattr(stats, 'getInfo'):
            stats_info = stats.getInfo()
            if isinstance(stats_info, dict):
                export_csv([stats_info], "soil_properties.csv", "soil")

    # Export erosion risk map
    if results.get("erosion_risk"):
        try:
            export_to_drive(
                results["erosion_risk"].toFloat(),
                "erosion_risk_2023", region=region,
            )
        except Exception as e:
            print(f"  Export erosion risk skipped: {e}")

    # Export salinity proxy
    if results.get("salinity_proxy"):
        try:
            export_to_drive(
                results["salinity_proxy"].toFloat(),
                "salinity_proxy_2023", region=region,
            )
        except Exception as e:
            print(f"  Export salinity proxy skipped: {e}")

    # Export salinity risk zones
    if results.get("salinity_risk"):
        try:
            export_to_drive(
                results["salinity_risk"].toFloat(),
                "salinity_risk_zones", region=region,
            )
        except Exception as e:
            print(f"  Export salinity risk skipped: {e}")

    # Export ag suitability
    if results.get("ag_suitability"):
        try:
            export_to_drive(
                results["ag_suitability"].toFloat(),
                "agricultural_suitability", region=region,
            )
        except Exception as e:
            print(f"  Export ag suitability skipped: {e}")

    print("\nSoil analysis complete.")


def run_transport():
    """Transportation and connectivity gap analysis."""
    from transportation import run_transportation_analysis

    print("\n" + "=" * 60)
    print(f"TRANSPORTATION & CONNECTIVITY GAP – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("transportation")

    results = run_transportation_analysis(region)

    # Export settlement classification
    settlement = results.get("settlement_2020", {})
    for cls in ("urban", "peri_urban", "rural_cluster", "low_density"):
        area_val = settlement.get(f"{cls}_area_km2")
        if area_val is not None:
            export_csv(
                [{"class": cls, "year": settlement.get("year", 2020),
                  "area_km2": _resolve_ee(area_val)}],
                f"settlement_{cls}_2020.csv", "transportation",
            )
    if settlement.get("smod"):
        try:
            export_to_drive(
                settlement["smod"].toFloat(),
                "settlement_classification_2020", region=region,
            )
        except Exception as e:
            print(f"  Export settlement SMOD skipped: {e}")

    # Export accessibility index
    if results.get("accessibility") is not None:
        try:
            export_to_drive(
                results["accessibility"].toFloat(),
                "accessibility_index_2020", region=region,
            )
        except Exception as e:
            print(f"  Export accessibility index skipped: {e}")

    # Export underserved areas
    underserved = results.get("underserved", {})
    if underserved.get("underserved_index"):
        try:
            export_to_drive(
                underserved["underserved_index"].toFloat(),
                "underserved_index_2020", region=region,
            )
        except Exception as e:
            print(f"  Export underserved index skipped: {e}")
    if underserved.get("underserved_mask"):
        try:
            export_to_drive(
                underserved["underserved_mask"].toFloat(),
                "underserved_mask_2020", region=region,
            )
        except Exception as e:
            print(f"  Export underserved mask skipped: {e}")
    if underserved.get("population_at_risk") is not None:
        export_csv(
            [{"year": 2020,
              "population_at_risk": _resolve_ee(underserved["population_at_risk"])}],
            "population_at_risk_2020.csv", "transportation",
        )

    # Export per-division connectivity gap
    gap_fc = results.get("connectivity_gap_fc")
    if gap_fc is not None:
        try:
            export_fc_to_csv(gap_fc, "connectivity_gap_by_division.csv", "transportation")
        except Exception as e:
            print(f"  Export connectivity gap skipped: {e}")

    # Export market access
    market = results.get("market_access", {})
    if market.get("market_access_index"):
        try:
            export_to_drive(
                market["market_access_index"].toFloat(),
                "market_access_index_2020", region=region,
            )
        except Exception as e:
            print(f"  Export market access skipped: {e}")
    if market.get("dist_to_market"):
        try:
            export_to_drive(
                market["dist_to_market"].toFloat(),
                "dist_to_market_2020", region=region,
            )
        except Exception as e:
            print(f"  Export dist to market skipped: {e}")

    print("\nTransportation and connectivity analysis complete.")


def run_health():
    """Health risk proxy mapping."""
    from health_risk import run_health_risk_analysis

    print("\n" + "=" * 60)
    print(f"HEALTH RISK MAPPING – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("health")

    results = run_health_risk_analysis(region)

    # Export waterlogging risk
    if results.get("waterlogging"):
        try:
            export_to_drive(
                results["waterlogging"].toFloat(),
                "waterlogging_risk_2023", region=region,
            )
        except Exception as e:
            print(f"  Export waterlogging skipped: {e}")

    # Export heat stress
    if results.get("heat_stress"):
        try:
            export_to_drive(
                results["heat_stress"].toFloat(),
                "heat_stress_2023", region=region,
            )
        except Exception as e:
            print(f"  Export heat stress skipped: {e}")

    # Export mosquito habitat
    if results.get("mosquito_habitat"):
        try:
            export_to_drive(
                results["mosquito_habitat"].toFloat(),
                "mosquito_habitat_2023", region=region,
            )
        except Exception as e:
            print(f"  Export mosquito habitat skipped: {e}")

    # Export air pollution risk
    if results.get("air_pollution_risk"):
        try:
            export_to_drive(
                results["air_pollution_risk"].toFloat(),
                "air_pollution_risk_2023", region=region,
            )
        except Exception as e:
            print(f"  Export air pollution risk skipped: {e}")

    # Export arsenic zones
    if results.get("arsenic_zones"):
        try:
            export_to_drive(
                results["arsenic_zones"].toFloat(),
                "arsenic_risk_zones", region=region,
            )
        except Exception as e:
            print(f"  Export arsenic zones skipped: {e}")

    # Export composite health risk index
    if results.get("health_risk_2023"):
        try:
            export_to_drive(
                results["health_risk_2023"].toFloat(),
                "health_risk_index_2023", region=region,
            )
        except Exception as e:
            print(f"  Export health risk index skipped: {e}")

    # Export health risk time series
    if results.get("health_risk_timeseries"):
        ts_resolved = []
        for entry in results["health_risk_timeseries"]:
            ts_resolved.append({
                "year": entry.get("year"),
                "mean_health_risk": _resolve_ee(entry.get("mean_health_risk")),
            })
        export_csv(ts_resolved, "health_risk_timeseries.csv", "health")

    print("\nHealth risk analysis complete.")


def run_energy():
    """Renewable energy potential mapping."""
    from energy import run_energy_analysis

    print("\n" + "=" * 60)
    print(f"ENERGY POTENTIAL MAPPING – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("energy")

    results = run_energy_analysis(region)

    # Export solar potential map
    solar = results.get("solar", {})
    if solar.get("solar_potential"):
        try:
            export_to_drive(
                solar["solar_potential"].toFloat(),
                "solar_potential_2023", region=region,
            )
        except Exception as e:
            print(f"  Export solar potential skipped: {e}")

    # Export solar stats
    if results.get("solar_stats"):
        ss = results["solar_stats"]
        export_csv([{
            "year": ss.get("year"),
            "mean_irradiance": _resolve_ee(ss.get("mean_irradiance")),
            "max_irradiance": _resolve_ee(ss.get("max_irradiance")),
        }], "solar_stats.csv", "energy")

    # Export wind potential
    wind = results.get("wind", {})
    if wind.get("wind_potential"):
        try:
            export_to_drive(
                wind["wind_potential"].toFloat(),
                "wind_potential_2023", region=region,
            )
        except Exception as e:
            print(f"  Export wind potential skipped: {e}")

    if wind.get("wind_speed"):
        try:
            export_to_drive(
                wind["wind_speed"].toFloat(),
                "wind_speed_2023", region=region,
            )
        except Exception as e:
            print(f"  Export wind speed skipped: {e}")

    # Export biomass
    if results.get("biomass"):
        try:
            export_to_drive(
                results["biomass"].toFloat(),
                "biomass_proxy_2023", region=region,
            )
        except Exception as e:
            print(f"  Export biomass skipped: {e}")

    if results.get("biomass_stats"):
        bs = results["biomass_stats"]
        export_csv([{
            "year": bs.get("year"),
            "mean_biomass": _resolve_ee(bs.get("mean_biomass")),
            "total_biomass": _resolve_ee(bs.get("total_biomass")),
        }], "biomass_stats.csv", "energy")

    # Export energy access
    if results.get("energy_access"):
        try:
            export_to_drive(
                results["energy_access"].toFloat(),
                "energy_access_2020", region=region,
            )
        except Exception as e:
            print(f"  Export energy access skipped: {e}")

    # Export energy poverty
    if results.get("energy_poverty"):
        ep = results["energy_poverty"]
        export_csv([{
            "year": ep.get("year"),
            "energy_poor_population": _resolve_ee(ep.get("energy_poor_population")),
        }], "energy_poverty_2020.csv", "energy")

    # Export energy access time series
    if results.get("energy_timeseries"):
        ts_resolved = []
        for entry in results["energy_timeseries"]:
            ts_resolved.append({
                "year": entry.get("year"),
                "energy_poor_population": _resolve_ee(entry.get("energy_poor_population")),
            })
        export_csv(ts_resolved, "energy_access_timeseries.csv", "energy")

    print("\nEnergy potential analysis complete.")


def run_aquaculture():
    """Aquaculture pond mapping, expansion tracking, mangrove conversion."""
    from aquaculture import run_aquaculture_analysis

    print("\n" + "=" * 60)
    print(f"AQUACULTURE MAPPING – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("aquaculture")

    results = run_aquaculture_analysis(region)

    # Export pond mask (2020, Khulna coastal)
    if results.get("ponds_2020"):
        try:
            export_to_drive(
                results["ponds_2020"].toFloat(),
                "aquaculture_ponds_2020_khulna", region=region,
            )
        except Exception as e:
            print(f"  Export pond mask skipped: {e}")

    # Export area stats per zone
    for key in ["area_2020", "area_coxsbazar_2020", "area_noakhali_2020"]:
        if results.get(key):
            entry = results[key]
            export_csv([{
                "zone": key,
                "year": entry.get("year"),
                "aquaculture_area_km2": _resolve_ee(entry.get("aquaculture_area_km2")),
            }], f"{key}.csv", "aquaculture")

    # Export time series (batch resolve)
    if results.get("timeseries"):
        ts_resolved = _batch_resolve_list(
            results["timeseries"], ["aquaculture_area_km2"],
        )
        export_csv(ts_resolved, "aquaculture_timeseries_khulna.csv", "aquaculture")

    # Export mangrove conversion stats
    if results.get("mangrove_conversion"):
        mc = results["mangrove_conversion"]
        export_csv([{
            "baseline_year": mc.get("baseline_year"),
            "current_year": mc.get("current_year"),
            "conversion_area_km2": _resolve_ee(mc.get("conversion_area_km2")),
        }], "mangrove_to_aquaculture.csv", "aquaculture")
        if mc.get("conversion_mask"):
            try:
                export_to_drive(
                    mc["conversion_mask"].toFloat(),
                    "mangrove_to_aquaculture_map", region=region,
                )
            except Exception as e:
                print(f"  Export conversion map skipped: {e}")

    # Export district breakdown
    if results.get("district_stats"):
        try:
            export_fc_to_csv(
                results["district_stats"],
                "aquaculture_by_district.csv", "aquaculture",
            )
        except Exception as e:
            print(f"  Export district stats skipped: {e}")

    print("\nAquaculture analysis complete.")


def run_kilns():
    """Brick kiln detection, density mapping, and emission estimation."""
    from brick_kiln import run_brick_kiln_analysis

    print("\n" + "=" * 60)
    print(f"BRICK KILN DETECTION – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("kilns")

    results = run_brick_kiln_analysis(region)

    # Export thermal hotspot mask
    thermal = results.get("thermal_2023", {})
    if thermal.get("hotspot_mask"):
        try:
            export_to_drive(
                thermal["hotspot_mask"].toFloat(),
                "kiln_thermal_hotspots_2023", region=region,
            )
        except Exception as e:
            print(f"  Export thermal hotspots skipped: {e}")

    # Export thermal stats CSV
    if thermal.get("hotspot_area_km2") is not None:
        export_csv([{
            "year": thermal.get("year", 2023),
            "hotspot_area_km2": _resolve_ee(thermal["hotspot_area_km2"]),
            "mean_lst_c": _resolve_ee(thermal.get("mean_lst_c")),
            "stddev_lst_c": _resolve_ee(thermal.get("stddev_lst_c")),
            "threshold_lst_c": _resolve_ee(thermal.get("threshold_lst_c")),
        }], "kiln_thermal_stats_2023.csv", "kilns")

    # Export spectral kiln candidate mask
    spectral = results.get("spectral_2023", {})
    if spectral.get("kiln_in_zones_mask"):
        try:
            export_to_drive(
                spectral["kiln_in_zones_mask"].toFloat(),
                "kiln_spectral_candidates_2023", region=region,
            )
        except Exception as e:
            print(f"  Export spectral candidates skipped: {e}")

    if spectral.get("candidate_area_km2") is not None:
        export_csv([{
            "year": spectral.get("year", 2023),
            "candidate_area_km2": _resolve_ee(spectral["candidate_area_km2"]),
        }], "kiln_spectral_area_2023.csv", "kilns")

    # Export density by district
    density = results.get("density_2023", {})
    if density.get("density_by_district"):
        try:
            export_fc_to_csv(density["density_by_district"], "kiln_density_by_district_2023.csv", "kilns")
        except Exception as e:
            print(f"  Export kiln density skipped: {e}")

    # Export kiln timeseries
    if results.get("timeseries"):
        ts_resolved = _batch_resolve_list(
            results["timeseries"],
            ["hotspot_area_km2", "spectral_candidate_area_km2", "threshold_lst_c", "mean_lst_c"],
        )
        export_csv(ts_resolved, "kiln_timeseries_2015_2023.csv", "kilns")

    # Export emission estimates
    emissions = results.get("emissions_2023", {})
    if emissions:
        export_csv([{
            "year": 2023,
            "candidate_area_km2": _resolve_ee(emissions.get("input_area_km2")),
            "avg_kiln_footprint_km2": emissions.get("avg_kiln_footprint_km2"),
            "estimated_kiln_count": _resolve_ee(emissions.get("estimated_kiln_count")),
            "co2_tonnes_per_year": _resolve_ee(emissions.get("co2_tonnes_per_year")),
            "pm25_tonnes_per_year": _resolve_ee(emissions.get("pm25_tonnes_per_year")),
            "note": emissions.get("note", ""),
        }], "kiln_emission_estimates_2023.csv", "kilns")

    print("\nBrick kiln analysis complete.")


def run_groundwater():
    """Groundwater depletion analysis using GRACE satellite gravity data."""
    from groundwater import run_groundwater_analysis

    print("\n" + "=" * 60)
    print(f"GROUNDWATER DEPLETION (GRACE) – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("groundwater")

    results = run_groundwater_analysis(region)

    # Export TWS time series
    if results.get("tws_timeseries"):
        ts_resolved = _batch_resolve_list(
            results["tws_timeseries"],
            ["mean_tws_cm", "min_tws_cm", "max_tws_cm"],
        )
        export_csv(ts_resolved, "grace_tws_timeseries.csv", "groundwater")

    # Export groundwater anomaly decomposition
    if results.get("groundwater_anomaly"):
        gws_resolved = _batch_resolve_list(
            results["groundwater_anomaly"],
            ["tws_cm", "sm_cm", "sw_cm", "gws_cm"],
        )
        export_csv(gws_resolved, "groundwater_anomaly_timeseries.csv", "groundwater")

    # Export TWS trend map (per-pixel slope)
    trend_map = results.get("tws_trend_map")
    if trend_map is not None:
        try:
            export_to_drive(
                trend_map.select("tws_slope_cm_per_month").toFloat(),
                "grace_tws_trend_2002_2017", region=region,
            )
        except Exception as e:
            print(f"  Export TWS trend map skipped: {e}")

    # Export depletion hotspot mask
    hotspot_data = results.get("depletion_hotspots")
    if hotspot_data:
        try:
            export_to_drive(
                hotspot_data["hotspot_mask"].toFloat(),
                "groundwater_depletion_hotspots", region=region,
            )
        except Exception as e:
            print(f"  Export hotspot mask skipped: {e}")

        # Export per-hotspot stats
        if hotspot_data.get("hotspot_stats"):
            hotspot_rows = []
            for name, stats in hotspot_data["hotspot_stats"].items():
                hotspot_rows.append({
                    "hotspot": name,
                    "lat": stats.get("lat"),
                    "lon": stats.get("lon"),
                    "mean_slope_cm_per_month": _resolve_ee(stats.get("mean_slope_cm_per_month")),
                    "min_slope_cm_per_month": _resolve_ee(stats.get("min_slope_cm_per_month")),
                    "depleting_area_m2": _resolve_ee(stats.get("depleting_area_m2")),
                })
            export_csv(hotspot_rows, "groundwater_hotspot_stats.csv", "groundwater")

    print("\nGroundwater depletion analysis complete.")


def run_timelapse_pipeline():
    """Generate yearly GIF animations from satellite composites."""
    from timelapse import run_timelapse

    print("\n" + "=" * 60)
    print(f"TIMELAPSE ANIMATIONS – {cfg.scope_label()}")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("timelapse")

    run_timelapse(region=region)

    print("\nTimelapse generation complete.")


def run_alerts(year=None):
    """Year-over-year change detection alerts across all GIS domains."""
    from change_alerts import generate_alert_report

    if year is None:
        year = 2023  # most recent complete Hansen year

    print("\n" + "=" * 60)
    print(f"CHANGE DETECTION ALERTS – {cfg.scope_label()} ({year})")
    print("=" * 60)

    init_gee()
    region = get_study_area()
    ensure_output_dir("alerts")

    report = generate_alert_report(year, region)

    # Flatten to rows
    rows = []
    for alert_type, result in report.items():
        rows.append({
            "year": year,
            "alert_type": alert_type,
            "triggered": result.get("triggered", False),
            "severity": result.get("severity", "none"),
            "area_km2": _resolve_ee(result.get("area_km2", 0.0)),
            "description": result.get("description", ""),
        })

    export_csv(rows, f"alerts_{year}.csv", "alerts")

    # Print summary
    triggered = [r for r in rows if r["triggered"]]
    print(f"\nAlert summary for {year}: {len(triggered)}/{len(rows)} triggered")
    for r in rows:
        status = "ALERT" if r["triggered"] else "ok   "
        print(f"  [{status}] {r['alert_type']:<22} severity={r['severity']:<16} area={r['area_km2']}")

    print("\nChange detection alerts complete.")
    return report


def run_chars():
    """Char (river island) detection and land accretion analysis."""
    from char_accretion import run_char_accretion_analysis

    print("\n" + "=" * 60)
    print(f"CHAR & LAND ACCRETION ANALYSIS – {cfg.scope_label()}")
    print(f"  Zones: {list(cfg.ACCRETION_ZONES.keys())}")
    print("=" * 60)

    init_gee()
    ensure_output_dir("chars")

    for zone_name, zone_cfg in cfg.ACCRETION_ZONES.items():
        print(f"\n── {zone_name} ──")
        zone_slug = zone_name.lower().replace(" ", "_").replace("-", "_")
        try:
            region = ee.Geometry.Rectangle([
                zone_cfg["west"], zone_cfg["south"],
                zone_cfg["east"], zone_cfg["north"],
            ])
            results = run_char_accretion_analysis(region)
        except Exception as e:
            print(f"  FAILED: {e}")
            continue

        ts_resolved = []
        for entry in results.get("timeseries", []):
            ts_resolved.append({
                "period": entry["period"],
                "start_year": entry["start_year"],
                "end_year": entry["end_year"],
                "new_land_km2": _resolve_ee(entry.get("new_land_km2")),
                "rate_km2_per_year": _resolve_ee(entry.get("rate_km2_per_year")),
            })
        export_csv(ts_resolved, f"{zone_slug}_accretion_timeseries.csv", "chars")

        if results.get("new_land_recent"):
            try:
                export_to_drive(
                    results["new_land_recent"].toFloat(),
                    f"{zone_slug}_new_land_{results['recent_period'].replace('-', '_')}",
                    region=region,
                )
            except Exception as e:
                print(f"  Export new land mask skipped: {e}")

        if results.get("new_land_cumulative"):
            try:
                export_to_drive(
                    results["new_land_cumulative"].toFloat(),
                    f"{zone_slug}_new_land_cumulative_1985_2025",
                    region=region,
                )
            except Exception as e:
                print(f"  Export cumulative mask skipped: {e}")

        if results.get("major_chars"):
            try:
                export_fc_to_csv(
                    results["major_chars"],
                    f"{zone_slug}_major_chars_{results['recent_period'].replace('-', '_')}.csv",
                    "chars",
                )
            except Exception as e:
                print(f"  Export major chars skipped: {e}")

        vuln = results.get("vulnerability")
        if vuln:
            vuln_area = _resolve_ee(vuln.get("vulnerable_area_km2"))
            mean_occ = _resolve_ee(vuln.get("mean_flood_occurrence"))
            export_csv([{
                "zone": zone_name,
                "period": results.get("recent_period", ""),
                "vulnerable_area_km2": vuln_area,
                "mean_flood_occurrence_pct": mean_occ,
            }], f"{zone_slug}_vulnerability.csv", "chars")

            if vuln.get("flood_freq"):
                try:
                    export_to_drive(
                        vuln["flood_freq"].toFloat(),
                        f"{zone_slug}_flood_freq_on_new_land",
                        region=region,
                    )
                except Exception as e:
                    print(f"  Export flood freq skipped: {e}")

    print("\nChar accretion analysis complete.")


# ═══════════════════════════════════════════════════════════════════════════════
# Full Pipeline Runners
# ═══════════════════════════════════════════════════════════════════════════════

def run_full():
    """Run the complete water analysis pipeline (original modules)."""
    label = cfg.scope_label()
    print("\n" + "=" * 60)
    print(f"FULL WATER PIPELINE – {label} (1985–2025)")
    print("=" * 60)

    start = time.time()
    run_test()
    run_rivers()
    run_floods()
    run_changes()
    run_haors()

    elapsed = (time.time() - start) / 60
    print(f"\n{'=' * 60}")
    print(f"FULL WATER PIPELINE COMPLETE – {elapsed:.1f} minutes")
    print(f"  Scope: {label}")
    print(f"  All outputs saved to: {cfg.OUTPUT_DIR}")
    print("=" * 60)


def _run_parallel(tasks, max_workers=4):
    """Run a list of (name, func) tasks concurrently using threads.

    GEE operations are IO-bound (network), so threading works well.
    max_workers=4 avoids hitting GEE's concurrent request limits.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(func): name for name, func in tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
                results[name] = "OK"
                print(f"\n  [DONE] {name}")
            except Exception as e:
                results[name] = f"FAILED: {e}"
                print(f"\n  [FAIL] {name}: {e}")
    return results


def run_full_extended():
    """Run ALL analysis modules with parallel execution where possible.

    Dependency graph:
      Wave 1 (independent): test, nightlights, climate, airquality, vegetation,
                             landcover, urbanization, groundwater
      Wave 2 (depends on wave 1): poverty (needs nightlights+vegetation+urbanization),
                                   rivers, floods, changes, haors, infrastructure,
                                   crops, coastal, soil
      Wave 3 (depends on wave 2): slums (needs poverty), health (needs poverty+airquality),
                                   energy (needs nightlights+vegetation+poverty)
    """
    label = cfg.scope_label()
    print("\n" + "=" * 60)
    print(f"FULL EXTENDED PIPELINE – {label} (PARALLEL)")
    print("=" * 60)

    start = time.time()

    # Single GEE init for all modules
    init_gee()

    # Wave 1: fully independent modules (no cross-dependencies)
    print("\n── Wave 1: Independent modules (parallel) ──")
    wave1 = [
        ("test", run_test),
        ("nightlights", run_nightlights),
        ("climate", run_climate),
        ("airquality", run_airquality),
        ("vegetation", run_vegetation),
        ("landcover", run_landcover),
        ("urbanization", run_urbanization),
        ("groundwater", run_groundwater),
    ]
    w1 = _run_parallel(wave1, max_workers=4)

    # Wave 2: modules that depend on wave 1 outputs
    print("\n── Wave 2: Dependent modules (parallel) ──")
    wave2 = [
        ("poverty", run_poverty),
        ("rivers", run_rivers),
        ("floods", run_floods),
        ("changes", run_changes),
        ("haors", run_haors),
        ("infrastructure", run_infrastructure),
        ("crops", run_crops),
        ("coastal", run_coastal),
        ("soil", run_soil),
        ("transport", run_transport),
        ("kilns", run_kilns),
    ]
    w2 = _run_parallel(wave2, max_workers=4)

    # Wave 3: modules that depend on wave 2
    print("\n── Wave 3: Final modules (parallel) ──")
    wave3 = [
        ("slums", run_slums),
        ("health", run_health),
        ("energy", run_energy),
    ]
    w3 = _run_parallel(wave3, max_workers=3)

    elapsed = (time.time() - start) / 60
    all_results = {**w1, **w2, **w3}
    failed = {k: v for k, v in all_results.items() if v != "OK"}

    print(f"\n{'=' * 60}")
    print(f"FULL EXTENDED PIPELINE COMPLETE – {elapsed:.1f} minutes")
    print(f"  Scope: {label}")
    print(f"  Modules: {len(all_results)} total, {len(all_results) - len(failed)} OK, {len(failed)} failed")
    if failed:
        for name, err in failed.items():
            print(f"  FAILED: {name} – {err}")
    print(f"  All outputs saved to: {cfg.OUTPUT_DIR}")
    print("=" * 60)


def run_local():
    """Run local analysis on downloaded satellite data (no GEE required)."""
    from local_compute import run_local_analysis

    results = run_local_analysis()
    ensure_output_dir("local")

    if results.get("forest_stats"):
        export_csv([results["forest_stats"]], "forest_stats.csv", "local")

    if results.get("forest_loss_annual"):
        export_csv(results["forest_loss_annual"], "forest_loss_annual.csv", "local")

    if results.get("water_stats"):
        export_csv([results["water_stats"]], "water_stats.csv", "local")

    if results.get("rainfall_stats"):
        export_csv([results["rainfall_stats"]], "rainfall_stats.csv", "local")

    if results.get("population_stats"):
        export_csv([results["population_stats"]], "population_stats.csv", "local")

    print(f"\nLocal outputs saved to: {os.path.join(cfg.OUTPUT_DIR, 'local')}")


def main():
    parser = argparse.ArgumentParser(
        description="Bangladesh Geospatial Analysis Pipeline"
    )
    parser.add_argument("--scope", default=None,
        choices=["sylhet", "national", "barishal", "chattogram", "dhaka",
                 "khulna", "mymensingh", "rajshahi", "rangpur"],
        help="Processing scope (default: from config)")
    parser.add_argument("--district", default=None,
        help="Run on a single district (e.g., Dhaka, Comilla, Sylhet)")

    # Original modules
    parser.add_argument("--test", action="store_true", help="Quick test run")
    parser.add_argument("--full", action="store_true", help="Full water analysis")
    parser.add_argument("--rivers", action="store_true", help="River analysis only")
    parser.add_argument("--floods", action="store_true", help="Flood analysis only")
    parser.add_argument("--changes", action="store_true", help="Water change detection only")
    parser.add_argument("--haors", action="store_true", help="Haor/wetland analysis only")

    # Extended modules
    parser.add_argument("--nightlights", action="store_true", help="Nighttime lights analysis")
    parser.add_argument("--urbanization", action="store_true", help="Urbanization analysis")
    parser.add_argument("--vegetation", action="store_true", help="Vegetation & agriculture")
    parser.add_argument("--landcover", action="store_true", help="Land cover / LULC analysis")
    parser.add_argument("--airquality", action="store_true", help="Air quality (Sentinel-5P)")
    parser.add_argument("--climate", action="store_true", help="Climate (rainfall, LST, drought)")
    parser.add_argument("--poverty", action="store_true", help="Poverty proxy mapping")
    parser.add_argument("--infrastructure", action="store_true", help="Infrastructure & construction")

    # Domain-specific modules
    parser.add_argument("--crops", action="store_true", help="Crop detection & rice phenology")
    parser.add_argument("--slums", action="store_true", help="Slum/informal settlement mapping")
    parser.add_argument("--coastal", action="store_true", help="Coastal & mangrove analysis")
    parser.add_argument("--cyclones", action="store_true", help="Cyclone damage assessment (pre/post)")
    parser.add_argument("--soil", action="store_true", help="Soil properties & erosion risk")
    parser.add_argument("--health", action="store_true", help="Health risk proxy mapping")
    parser.add_argument("--energy", action="store_true", help="Renewable energy potential")
    parser.add_argument("--transport", action="store_true", help="Transportation & connectivity gap")
    parser.add_argument("--groundwater", action="store_true", help="Groundwater depletion (GRACE)")
    parser.add_argument("--aquaculture", action="store_true", help="Aquaculture pond mapping")
    parser.add_argument("--kilns", action="store_true", help="Brick kiln detection & emission estimates")
    parser.add_argument("--chars", action="store_true", help="Char / land accretion analysis")
    parser.add_argument("--timelapse", action="store_true", help="Timelapse GIF animations (urban/NDVI/water/nightlights)")
    parser.add_argument("--alerts", action="store_true", help="Year-over-year change detection alerts")
    parser.add_argument("--alerts-year", type=int, default=None, metavar="YEAR",
                        help="Year for alerts (default: 2023)")
    parser.add_argument("--full-extended", action="store_true", help="ALL modules")
    parser.add_argument("--local", action="store_true",
                        help="Run local analysis on downloaded satellite data (no GEE)")

    args = parser.parse_args()

    # Set scope if provided via CLI
    if args.district:
        cfg.set_scope(f"district:{args.district}")
    elif args.scope:
        cfg.set_scope(args.scope)

    print(f"Scope: {cfg.scope_label()} | Threshold: {cfg.DEFAULT_THRESHOLD_METHOD} | "
          f"Rivers: {len(cfg.RIVERS)} | Wetlands: {len(cfg.HAORS)}")

    if args.local:
        run_local()
    elif args.full_extended:
        run_full_extended()
    elif args.full:
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
    elif args.nightlights:
        run_nightlights()
    elif args.urbanization:
        run_urbanization()
    elif args.vegetation:
        run_vegetation()
    elif args.landcover:
        run_landcover()
    elif args.airquality:
        run_airquality()
    elif args.climate:
        run_climate()
    elif args.poverty:
        run_poverty()
    elif args.infrastructure:
        run_infrastructure()
    elif args.crops:
        run_crops()
    elif args.slums:
        run_slums()
    elif args.coastal:
        run_coastal()
    elif args.cyclones:
        run_cyclones()
    elif args.soil:
        run_soil()
    elif args.health:
        run_health()
    elif args.energy:
        run_energy()
    elif args.transport:
        run_transport()
    elif args.groundwater:
        run_groundwater()
    elif args.aquaculture:
        run_aquaculture()
    elif args.chars:
        run_chars()
    elif args.kilns:
        run_kilns()
    elif args.timelapse:
        run_timelapse_pipeline()
    elif args.alerts:
        run_alerts(year=args.alerts_year)
    else:
        run_test()


if __name__ == "__main__":
    main()

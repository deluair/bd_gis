"""
Year-over-year change detection alerts across all GIS domains.
Flags statistically significant anomalies in forest loss, flood extent,
construction surge, NDVI depression, and air quality.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Forest Loss Alert (Hansen)
# ═══════════════════════════════════════════════════════════════════════════════

def detect_forest_loss_alerts(year, region, tree_threshold=30, scale=None):
    """
    Flag Hansen forest loss in the given year for areas > 1 km2.
    Hansen lossyear band encodes year as offset from 2000 (1 = 2001, ..., 23 = 2023).
    Returns dict with triggered, severity, area_km2, description.
    """
    if scale is None:
        scale = 300 if cfg.SCOPE == "national" else 30

    loss_offset = year - 2000
    if loss_offset < 1 or loss_offset > 23:
        return {
            "triggered": False,
            "severity": "none",
            "area_km2": 0.0,
            "description": f"Hansen forest loss data not available for {year} (valid 2001-2023).",
        }

    try:
        gfc = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"]).clip(region)
        tree2000 = gfc.select("treecover2000").gte(tree_threshold)
        lossyear = gfc.select("lossyear")

        year_loss = lossyear.eq(loss_offset).And(tree2000)
        area_m2 = year_loss.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=region,
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        area_km2_ee = ee.Number(area_m2.get("lossyear")).divide(1e6)
        area_km2 = area_km2_ee.getInfo() or 0.0

        triggered = area_km2 > 1.0
        if area_km2 > 50:
            severity = "critical"
        elif area_km2 > 10:
            severity = "high"
        elif area_km2 > 1:
            severity = "medium"
        else:
            severity = "none"

        description = (
            f"Hansen forest loss in {year}: {area_km2:.2f} km2 detected."
            if triggered
            else f"No significant forest loss flagged in {year} (< 1 km2 threshold)."
        )
        return {"triggered": triggered, "severity": severity, "area_km2": area_km2, "description": description}

    except Exception as e:
        return {"triggered": False, "severity": "error", "area_km2": 0.0, "description": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Flood Anomaly Alert (JRC Monthly + CHIRPS proxy)
# ═══════════════════════════════════════════════════════════════════════════════

def detect_flood_anomaly(year, region, scale=None, lookback=10):
    """
    Compare monsoon flood extent in `year` against 10-year historical average.
    Uses JRC Monthly Surface Water occurrence during July-September.
    Flags if extent > mean + 1.5 * std dev.
    Returns dict with triggered, severity, area_km2, description.
    """
    if scale is None:
        scale = 300 if cfg.SCOPE == "national" else 100

    try:
        def _monsoon_water_area(yr):
            col = (
                ee.ImageCollection("JRC/GSW1_4/MonthlyHistory")
                .filterBounds(region)
                .filter(ee.Filter.calendarRange(7, 9, "month"))
                .filter(ee.Filter.calendarRange(yr, yr, "year"))
            )
            # water = 2 in JRC monthly
            water = col.map(lambda img: img.select("water").eq(2)).max()
            area_m2 = water.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=region,
                scale=scale,
                maxPixels=cfg.MAX_PIXELS,
                bestEffort=True,
            )
            return ee.Number(area_m2.get("water")).divide(1e6)

        # Baseline years: lookback years before the target year
        baseline_start = max(2000, year - lookback)
        baseline_end = year - 1
        baseline_values = []
        for yr in range(baseline_start, baseline_end + 1):
            try:
                val = _monsoon_water_area(yr).getInfo()
                if val is not None:
                    baseline_values.append(val)
            except Exception:
                pass

        target_area = _monsoon_water_area(year).getInfo() or 0.0

        if len(baseline_values) < 3:
            return {
                "triggered": False,
                "severity": "insufficient_data",
                "area_km2": target_area,
                "description": f"Insufficient baseline data (<3 years) for flood anomaly in {year}.",
            }

        mean_area = sum(baseline_values) / len(baseline_values)
        variance = sum((v - mean_area) ** 2 for v in baseline_values) / len(baseline_values)
        std_area = variance ** 0.5

        threshold = mean_area + 1.5 * std_area
        triggered = target_area > threshold
        z_score = (target_area - mean_area) / std_area if std_area > 0 else 0.0

        if z_score > 3.0:
            severity = "critical"
        elif z_score > 2.0:
            severity = "high"
        elif triggered:
            severity = "medium"
        else:
            severity = "none"

        description = (
            f"Flood extent in monsoon {year}: {target_area:.1f} km2 vs "
            f"{mean_area:.1f} km2 baseline mean (z={z_score:.2f}, threshold +1.5 SD)."
        )
        return {"triggered": triggered, "severity": severity, "area_km2": target_area, "description": description}

    except Exception as e:
        return {"triggered": False, "severity": "error", "area_km2": 0.0, "description": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Construction Surge Alert (Dynamic World built class)
# ═══════════════════════════════════════════════════════════════════════════════

def detect_construction_surge(year, region, scale=None):
    """
    Compare Dynamic World 'built' class area in `year` vs `year-1`.
    Flags if built area grew by > 20% year-over-year.
    Dynamic World starts 2015; returns error for earlier years.
    Returns dict with triggered, severity, area_km2, description.
    """
    if scale is None:
        scale = 100 if cfg.SCOPE != "national" else 300

    if year < 2016:
        return {
            "triggered": False,
            "severity": "none",
            "area_km2": 0.0,
            "description": f"Dynamic World not available before 2016 (requested {year}).",
        }

    try:
        def _built_area(yr):
            col = (
                ee.ImageCollection(cfg.DYNAMIC_WORLD["collection"])
                .filterDate(f"{yr}-01-01", f"{yr}-12-31")
                .filterBounds(region)
                .select(cfg.DYNAMIC_WORLD["band"])
            )
            built = col.map(lambda img: img.eq(6)).max()  # class 6 = built
            area_m2 = built.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=region,
                scale=scale,
                maxPixels=cfg.MAX_PIXELS,
                bestEffort=True,
            )
            return ee.Number(area_m2.get("label")).divide(1e6)

        prev_area = _built_area(year - 1).getInfo() or 0.0
        curr_area = _built_area(year).getInfo() or 0.0

        if prev_area == 0:
            growth_pct = 0.0
        else:
            growth_pct = ((curr_area - prev_area) / prev_area) * 100

        triggered = growth_pct > 20.0
        if growth_pct > 50:
            severity = "critical"
        elif growth_pct > 30:
            severity = "high"
        elif triggered:
            severity = "medium"
        else:
            severity = "none"

        description = (
            f"Built area {year}: {curr_area:.2f} km2 vs {prev_area:.2f} km2 in {year - 1} "
            f"(+{growth_pct:.1f}% YoY)."
        )
        return {"triggered": triggered, "severity": severity, "area_km2": curr_area, "description": description}

    except Exception as e:
        return {"triggered": False, "severity": "error", "area_km2": 0.0, "description": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# NDVI Anomaly Alert (crop failure / drought)
# ═══════════════════════════════════════════════════════════════════════════════

def detect_ndvi_anomaly(year, region, scale=1000, lookback=10):
    """
    Flag if annual mean NDVI in `year` is below the 10-year mean by > 2 std dev.
    Uses MODIS MOD13A2 (1km, 16-day). Signals crop failure or drought.
    Returns dict with triggered, severity, area_km2, description.
    """
    try:
        def _annual_mean_ndvi(yr):
            col = (
                ee.ImageCollection(cfg.MODIS_NDVI["collection"])
                .filterDate(f"{yr}-01-01", f"{yr}-12-31")
                .filterBounds(region)
                .select(cfg.MODIS_NDVI["ndvi_band"])
            )
            scaled = col.mean().multiply(cfg.MODIS_NDVI["scale_factor"]).clip(region)
            stats = scaled.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region,
                scale=scale,
                maxPixels=cfg.MAX_PIXELS,
                bestEffort=True,
            )
            return ee.Number(stats.get("NDVI"))

        baseline_start = max(2000, year - lookback)
        baseline_end = year - 1
        baseline_values = []
        for yr in range(baseline_start, baseline_end + 1):
            try:
                val = _annual_mean_ndvi(yr).getInfo()
                if val is not None:
                    baseline_values.append(val)
            except Exception:
                pass

        target_ndvi = _annual_mean_ndvi(year).getInfo()
        if target_ndvi is None:
            return {
                "triggered": False,
                "severity": "error",
                "area_km2": 0.0,
                "description": f"NDVI data unavailable for {year}.",
            }

        if len(baseline_values) < 3:
            return {
                "triggered": False,
                "severity": "insufficient_data",
                "area_km2": 0.0,
                "description": f"Insufficient NDVI baseline for {year} (<3 years).",
            }

        mean_ndvi = sum(baseline_values) / len(baseline_values)
        variance = sum((v - mean_ndvi) ** 2 for v in baseline_values) / len(baseline_values)
        std_ndvi = variance ** 0.5

        z_score = (target_ndvi - mean_ndvi) / std_ndvi if std_ndvi > 0 else 0.0
        triggered = z_score < -2.0

        if z_score < -3.5:
            severity = "critical"
        elif z_score < -2.5:
            severity = "high"
        elif triggered:
            severity = "medium"
        else:
            severity = "none"

        # Estimate affected area: pixels with NDVI below (mean - 2*std)
        threshold_val = mean_ndvi - 2.0 * std_ndvi
        col_yr = (
            ee.ImageCollection(cfg.MODIS_NDVI["collection"])
            .filterDate(f"{year}-01-01", f"{year}-12-31")
            .filterBounds(region)
            .select(cfg.MODIS_NDVI["ndvi_band"])
        )
        ndvi_img = col_yr.mean().multiply(cfg.MODIS_NDVI["scale_factor"]).clip(region)
        anomaly_mask = ndvi_img.lt(threshold_val)
        area_m2 = anomaly_mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=region,
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        area_km2 = (ee.Number(area_m2.get("NDVI")).divide(1e6)).getInfo() or 0.0

        description = (
            f"NDVI in {year}: {target_ndvi:.4f} vs {mean_ndvi:.4f} baseline mean "
            f"(z={z_score:.2f}). Anomaly area below threshold: {area_km2:.1f} km2."
        )
        return {"triggered": triggered, "severity": severity, "area_km2": area_km2, "description": description}

    except Exception as e:
        return {"triggered": False, "severity": "error", "area_km2": 0.0, "description": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Air Quality Spike Alert (Sentinel-5P NO2)
# ═══════════════════════════════════════════════════════════════════════════════

def detect_air_quality_spike(year, region, scale=1113, lookback=3):
    """
    Compare annual mean NO2 column density in `year` against 3-year average.
    Sentinel-5P available from late 2018 onward.
    Flags if NO2 mean exceeds 3-year average by > 15%.
    Returns dict with triggered, severity, area_km2, description.
    """
    if year < 2019:
        return {
            "triggered": False,
            "severity": "none",
            "area_km2": 0.0,
            "description": f"Sentinel-5P NO2 not available before 2019 (requested {year}).",
        }

    try:
        no2_cfg = cfg.SENTINEL5P["NO2"]

        def _annual_no2(yr):
            col = (
                ee.ImageCollection(no2_cfg["collection"])
                .filterDate(f"{yr}-01-01", f"{yr}-12-31")
                .filterBounds(region)
                .select(no2_cfg["band"])
            )
            mean_img = col.mean().clip(region)
            stats = mean_img.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region,
                scale=scale,
                maxPixels=cfg.MAX_PIXELS,
                bestEffort=True,
            )
            return ee.Number(stats.get(no2_cfg["band"]))

        baseline_start = max(2019, year - lookback)
        baseline_end = year - 1
        baseline_values = []
        for yr in range(baseline_start, baseline_end + 1):
            try:
                val = _annual_no2(yr).getInfo()
                if val is not None:
                    baseline_values.append(val)
            except Exception:
                pass

        target_no2 = _annual_no2(year).getInfo()
        if target_no2 is None:
            return {
                "triggered": False,
                "severity": "error",
                "area_km2": 0.0,
                "description": f"NO2 data unavailable for {year}.",
            }

        if len(baseline_values) < 2:
            return {
                "triggered": False,
                "severity": "insufficient_data",
                "area_km2": 0.0,
                "description": f"Insufficient NO2 baseline for {year} (<2 years).",
            }

        mean_no2 = sum(baseline_values) / len(baseline_values)
        pct_change = ((target_no2 - mean_no2) / mean_no2 * 100) if mean_no2 > 0 else 0.0
        triggered = pct_change > 15.0

        if pct_change > 40:
            severity = "critical"
        elif pct_change > 25:
            severity = "high"
        elif triggered:
            severity = "medium"
        else:
            severity = "none"

        # Area with NO2 above threshold (mean_no2 * 1.15)
        no2_threshold = mean_no2 * 1.15
        col_yr = (
            ee.ImageCollection(no2_cfg["collection"])
            .filterDate(f"{year}-01-01", f"{year}-12-31")
            .filterBounds(region)
            .select(no2_cfg["band"])
        )
        no2_img = col_yr.mean().clip(region)
        spike_mask = no2_img.gt(no2_threshold)
        area_m2 = spike_mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=region,
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        area_km2 = (ee.Number(area_m2.get(no2_cfg["band"])).divide(1e6)).getInfo() or 0.0

        description = (
            f"NO2 annual mean {year}: {target_no2:.4e} mol/m2 vs "
            f"{mean_no2:.4e} baseline ({pct_change:+.1f}%). "
            f"Elevated area: {area_km2:.1f} km2."
        )
        return {"triggered": triggered, "severity": severity, "area_km2": area_km2, "description": description}

    except Exception as e:
        return {"triggered": False, "severity": "error", "area_km2": 0.0, "description": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Alert Report Aggregator
# ═══════════════════════════════════════════════════════════════════════════════

def generate_alert_report(year, region):
    """
    Run all change detectors and return a unified alert report.
    Returns dict of {alert_type: {triggered, severity, area_km2, description}}.
    """
    print(f"  Running forest loss alert ({year})...")
    forest = detect_forest_loss_alerts(year, region)

    print(f"  Running flood anomaly alert ({year})...")
    flood = detect_flood_anomaly(year, region)

    print(f"  Running construction surge alert ({year})...")
    construction = detect_construction_surge(year, region)

    print(f"  Running NDVI anomaly alert ({year})...")
    ndvi = detect_ndvi_anomaly(year, region)

    print(f"  Running air quality spike alert ({year})...")
    air = detect_air_quality_spike(year, region)

    return {
        "forest_loss":        forest,
        "flood_anomaly":      flood,
        "construction_surge": construction,
        "ndvi_anomaly":       ndvi,
        "air_quality_spike":  air,
    }

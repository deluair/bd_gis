"""
Export utilities – GeoTIFF, Shapefile, and CSV export helpers
for saving GEE results locally via geemap.
"""
import os
import ee
import geemap
import pandas as pd
import config as cfg


def ensure_output_dir(subdir=None):
    """Create output directory if it doesn't exist."""
    path = cfg.OUTPUT_DIR
    if subdir:
        path = os.path.join(path, subdir)
    os.makedirs(path, exist_ok=True)
    return path


def export_geotiff(image, filename, region=None, scale=None, subdir=None):
    """
    Export an ee.Image as a GeoTIFF using geemap.
    """
    if region is None:
        region = ee.Geometry.Rectangle([
            cfg.STUDY_AREA_BOUNDS["west"], cfg.STUDY_AREA_BOUNDS["south"],
            cfg.STUDY_AREA_BOUNDS["east"], cfg.STUDY_AREA_BOUNDS["north"],
        ])
    if scale is None:
        scale = cfg.EXPORT_SCALE

    out_dir = ensure_output_dir(subdir)
    filepath = os.path.join(out_dir, filename)

    geemap.ee_export_image(
        image,
        filename=filepath,
        scale=scale,
        region=region,
        crs=cfg.EXPORT_CRS,
        file_per_band=False,
    )
    print(f"  Exported GeoTIFF: {filepath}")
    return filepath


def export_to_drive(image, description, folder="bd_gis_exports",
                    region=None, scale=None):
    """
    Export an ee.Image to Google Drive (for large exports that
    exceed geemap's direct download limit).
    """
    if region is None:
        region = ee.Geometry.Rectangle([
            cfg.STUDY_AREA_BOUNDS["west"], cfg.STUDY_AREA_BOUNDS["south"],
            cfg.STUDY_AREA_BOUNDS["east"], cfg.STUDY_AREA_BOUNDS["north"],
        ])
    if scale is None:
        scale = cfg.EXPORT_SCALE

    task = ee.batch.Export.image.toDrive(
        image=image,
        description=description,
        folder=folder,
        region=region,
        scale=scale,
        crs=cfg.EXPORT_CRS,
        maxPixels=cfg.MAX_PIXELS,
    )
    task.start()
    print(f"  Started Drive export: {description} (task ID: {task.id})")
    return task


def export_shapefile(fc, filename, subdir=None):
    """Export an ee.FeatureCollection as a Shapefile."""
    out_dir = ensure_output_dir(subdir)
    filepath = os.path.join(out_dir, filename)

    geemap.ee_export_vector(fc, filename=filepath)
    print(f"  Exported Shapefile: {filepath}")
    return filepath


def export_csv(data, filename, subdir=None):
    """
    Export a list of dicts or pandas DataFrame to CSV.
    Handles ee.Number values by calling getInfo().
    """
    out_dir = ensure_output_dir(subdir)
    filepath = os.path.join(out_dir, filename)

    if isinstance(data, pd.DataFrame):
        df = data
    else:
        # Resolve ee.Number values
        resolved = []
        for row in data:
            resolved_row = {}
            for k, v in row.items():
                if isinstance(v, ee.Number):
                    try:
                        resolved_row[k] = v.getInfo()
                    except Exception:
                        resolved_row[k] = None
                elif isinstance(v, ee.ComputedObject):
                    try:
                        resolved_row[k] = v.getInfo()
                    except Exception:
                        resolved_row[k] = None
                else:
                    resolved_row[k] = v
            resolved.append(resolved_row)
        df = pd.DataFrame(resolved)

    df.to_csv(filepath, index=False)
    print(f"  Exported CSV: {filepath}")
    return filepath


def export_fc_to_csv(fc, filename, subdir=None):
    """Export ee.FeatureCollection properties to CSV."""
    out_dir = ensure_output_dir(subdir)
    filepath = os.path.join(out_dir, filename)

    features = fc.getInfo()["features"]
    rows = [f["properties"] for f in features]
    df = pd.DataFrame(rows)
    df.to_csv(filepath, index=False)
    print(f"  Exported FC CSV: {filepath}")
    return filepath

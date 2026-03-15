#!/usr/bin/env python3
"""
Run the GIS pipeline for each of Bangladesh's 8 divisions separately.

Usage:
    python run_divisions.py                    # all 8 divisions
    python run_divisions.py --division dhaka   # single division
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import config as cfg

DIVISIONS = list(cfg.DIVISIONS.keys())

DIVISION_MODULES = [
    "nightlights",
    "urbanization",
    "vegetation",
    "climate",
    "poverty",
    "airquality",
]

MODULE_RUNNERS = {
    "nightlights":   "run_nightlights",
    "urbanization":  "run_urbanization",
    "vegetation":    "run_vegetation",
    "climate":       "run_climate",
    "poverty":       "run_poverty",
    "airquality":    "run_airquality",
}


def run_division(division: str) -> None:
    cfg.set_scope(division)

    division_output_dir = os.path.join(
        os.path.dirname(__file__), "outputs", division
    )
    os.makedirs(division_output_dir, exist_ok=True)
    cfg.OUTPUT_DIR = division_output_dir

    import run_pipeline
    for module in DIVISION_MODULES:
        fn_name = MODULE_RUNNERS[module]
        fn = getattr(run_pipeline, fn_name)
        try:
            fn()
        except Exception as e:
            print(f"  [{division}] {module} FAILED: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run GIS pipeline per Bangladesh division."
    )
    parser.add_argument(
        "--division",
        choices=DIVISIONS,
        default=None,
        help="Run a single division (default: all 8)",
    )
    args = parser.parse_args()

    targets = [args.division] if args.division else DIVISIONS
    total = len(targets)

    for i, division in enumerate(targets, start=1):
        print(f"\nProcessing division {i}/{total}: {division}...")
        run_division(division)

    print("\nAll divisions complete.")


if __name__ == "__main__":
    main()

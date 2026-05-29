"""Join an indicator's per-unit output to its reference, score it, write a card."""
import argparse

from validation import calibrate
from validation import card as cardmod
from validation import reference
from validation.registry import INDICATORS, assign_tier


def validate_indicator(indicator_id, predicted, generated_at, outputs_dir,
                       period="", extra_caveats=None):
    """predicted: {spatial_unit_name: value}. Returns and writes the card."""
    if indicator_id not in INDICATORS:
        raise KeyError(f"unknown indicator: {indicator_id}")
    cfg = INDICATORS[indicator_id]
    ref = reference.LOADERS[cfg["reference"]]()
    pairs = [(predicted[k], ref[k]) for k in predicted if k in ref]
    caveats = list(extra_caveats or [])
    try:
        stats = calibrate.continuous_stats(pairs)
        tier = assign_tier(cfg["comparison"], stats["pearson_r"])
    except (calibrate.InsufficientData, calibrate.ZeroVariance) as e:
        stats = {"n": len(pairs), "error": str(e)}
        tier = "C"
        caveats.append(f"degenerate or insufficient data: {e}")
    card = cardmod.build_card(
        indicator_id=indicator_id, label=cfg["label"],
        classification=cfg["classification"], quality_tier=tier,
        reference_source=cfg["reference_source"],
        reference_citation=cfg["reference_citation"],
        spatial_unit=cfg["spatial_unit"], period=period,
        comparison=cfg["comparison"], n=stats.get("n", len(pairs)),
        stats=stats, caveats=caveats, generated_at=generated_at,
    )
    cardmod.write_card(card, outputs_dir)
    return card


def main(argv=None):
    import datetime
    import config as cfg
    p = argparse.ArgumentParser(description="Generate a validation card for an indicator")
    p.add_argument("indicator_id")
    p.add_argument("--predicted-csv", required=True)
    p.add_argument("--unit-col", required=True)
    p.add_argument("--value-col", required=True)
    p.add_argument("--period", default="")
    args = p.parse_args(argv)
    predicted = reference.load_csv_reference(args.predicted_csv, args.unit_col, args.value_col)
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    card = validate_indicator(args.indicator_id, predicted, generated_at,
                              cfg.OUTPUT_DIR, period=args.period)
    print(f"Wrote tier {card['quality_tier']} card for {args.indicator_id} (n={card['n']})")


if __name__ == "__main__":
    main()

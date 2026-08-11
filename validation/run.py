"""Join an indicator's per-unit output to its reference, score it, write a card."""
import argparse

from validation import calibrate, reference
from validation import card as cardmod
from validation.registry import INDICATORS, assign_tier


def validate_indicator(indicator_id, predicted, generated_at, outputs_dir,
                       period="", extra_caveats=None, predicted_source=""):
    """predicted: {spatial_unit_name: value}. Returns and writes the card."""
    if indicator_id not in INDICATORS:
        raise KeyError(f"unknown indicator: {indicator_id}")
    cfg = INDICATORS[indicator_id]
    if cfg["comparison"] != "continuous":
        raise NotImplementedError(
            f"validate_indicator only supports continuous comparison, "
            f"got '{cfg['comparison']}' for {indicator_id}"
        )
    ref = reference.LOADERS[cfg["reference"]]()
    # Predicted keys may use a different naming authority than the reference
    # (GAUL vs BBS division spellings). Normalise before joining, or every
    # renamed unit silently drops out of the score.
    aliases = cfg.get("key_aliases")
    if aliases:
        predicted = {aliases.get(k, k): v for k, v in predicted.items()}
    pairs = [(predicted[k], ref[k]) for k in predicted if k in ref]
    caveats = list(cfg.get("static_caveats", [])) + list(extra_caveats or [])
    matched, total = len(pairs), len(predicted)
    if total and matched < total:
        caveats.append(
            f"{total - matched} of {total} predicted units did not match the "
            f"reference join key"
        )
    # The check above is about units we predicted and could not place. The
    # mirror case matters just as much: a reference unit with no prediction is
    # silently dropped from the score, so the card would otherwise report a
    # clean join over a partial area.
    unpredicted = sorted(k for k in ref if k not in predicted)
    if unpredicted:
        caveats.append(
            f"{len(unpredicted)} of {len(ref)} reference units had no prediction "
            f"and were excluded from the score: {', '.join(unpredicted)}"
        )
    coverage = {"n_predicted": total, "n_reference": len(ref), "n_matched": matched}
    try:
        stats = calibrate.continuous_stats(pairs)
        tier = assign_tier(cfg["comparison"], stats["pearson_r"])
    except (calibrate.InsufficientData, calibrate.ZeroVariance) as e:
        stats = {"n": matched, "error": str(e)}
        tier = "C"
        caveats.append(f"degenerate or insufficient data: {e}")
    card = cardmod.build_card(
        indicator_id=indicator_id, label=cfg["label"],
        classification=cfg["classification"], quality_tier=tier,
        reference_source=cfg["reference_source"],
        reference_citation=cfg["reference_citation"],
        spatial_unit=cfg["spatial_unit"], period=period,
        comparison=cfg["comparison"], n=stats.get("n", matched),
        stats=stats, caveats=caveats, generated_at=generated_at,
        predicted_source=predicted_source, coverage=coverage,
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
                              cfg.OUTPUT_DIR, period=args.period,
                              predicted_source=args.predicted_csv)
    cov = card["coverage"]
    print(f"Wrote tier {card['quality_tier']} card for {args.indicator_id} "
          f"(n={card['n']}, matched {cov['n_matched']}/{cov['n_reference']} reference units)")
    for c in card["caveats"]:
        print(f"  caveat: {c}")


if __name__ == "__main__":
    main()

"""Validation card schema, writer, and reader. Cards are JSON in outputs/validation/."""
import json
import os


def build_card(indicator_id, label, classification, quality_tier, reference_source,
               reference_citation, spatial_unit, period, comparison, n, stats,
               caveats, generated_at, generated_by="validation.run",
               predicted_source="", coverage=None):
    if classification not in ("measured", "proxy"):
        raise ValueError("classification must be 'measured' or 'proxy'")
    if quality_tier not in ("A", "B", "C"):
        raise ValueError("quality_tier must be 'A', 'B', or 'C'")
    return {
        "indicator_id": indicator_id,
        "label": label,
        "classification": classification,
        "quality_tier": quality_tier,
        "reference_source": reference_source,
        "reference_citation": reference_citation,
        "spatial_unit": spatial_unit,
        "period": period,
        "comparison": comparison,
        "n": n,
        "stats": stats,
        "caveats": list(caveats),
        # Where the predicted values came from. Without this a card cannot be
        # traced back to its input or reproduced.
        "predicted_source": predicted_source,
        # n_predicted / n_reference / n_matched, so a partial join is visible
        # on the card instead of only in the caveat text.
        "coverage": dict(coverage or {}),
        "generated_at": generated_at,
        "generated_by": generated_by,
    }


def write_card(card, outputs_dir):
    d = os.path.join(outputs_dir, "validation")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{card['indicator_id']}.json")
    with open(path, "w") as f:
        json.dump(card, f, indent=2, sort_keys=True)
    return path


def read_card(indicator_id, outputs_dir):
    path = os.path.join(outputs_dir, "validation", f"{indicator_id}.json")
    with open(path) as f:
        return json.load(f)

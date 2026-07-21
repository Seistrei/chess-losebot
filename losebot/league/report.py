"""League aggregation and rendering: the scoreboard of record.

The headline is two numbers, not one: mean forced-selfmate rate AND
the worst family's rate. The specialist era's collapse mode was a
perfect score on the drilled family next to zero on the neighbor —
an average would have hidden it; the worst-family row cannot.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..outcomes import FOCAL_LABELS, SELFMATE_FORCED
from .families import split_of
from .play import GameRecord

_SHORT = {
    "selfmate-forced": "forced",
    "selfmate-mercy": "mercy",
    "accident-zugzwang": "acc-zz",
    "accident-mate": "acc-mate",
    "stalemate-them": "st-them",
    "stalemate-us": "st-us",
    "insufficient-material": "insuf",
    "fifty-move": "fifty",
    "repetition": "rep",
    "max-plies": "maxply",
}


def family_table(records: list[GameRecord]) -> dict[str, dict]:
    families: dict[str, dict] = {}
    for record in records:
        row = families.setdefault(
            record.family,
            {
                "split": split_of(record.family),
                "games": 0,
                **{label: 0 for label in FOCAL_LABELS},
            },
        )
        row["games"] += 1
        row[record.label] += 1
    for row in families.values():
        row["forced_rate"] = (
            row[SELFMATE_FORCED] / row["games"] if row["games"] else 0.0
        )
    return families


def summarize(records: list[GameRecord]) -> dict:
    families = family_table(records)
    held = {
        name: row for name, row in families.items()
        if row["split"] == "held-out"
    }
    scored = held or families
    worst_name = None
    if scored:
        worst_name = min(scored, key=lambda name: scored[name]["forced_rate"])
    total = len(records)
    forced = sum(1 for r in records if r.label == SELFMATE_FORCED)
    return {
        "games": total,
        "forced": forced,
        "forced_rate": forced / total if total else 0.0,
        "families": families,
        "worst_family": worst_name,
        "worst_family_forced_rate": (
            scored[worst_name]["forced_rate"] if worst_name else 0.0
        ),
    }


def render(summary: dict) -> str:
    labels = [label for label in FOCAL_LABELS]
    header = (
        f"{'family':<12} {'split':<8} {'n':>3} "
        + " ".join(f"{_SHORT[label]:>8}" for label in labels)
        + f" {'forced%':>8}"
    )
    lines = [header, "-" * len(header)]
    for name, row in sorted(
        summary["families"].items(), key=lambda kv: (kv[1]["split"], kv[0])
    ):
        lines.append(
            f"{name:<12} {row['split']:<8} {row['games']:>3} "
            + " ".join(f"{row[label]:>8}" for label in labels)
            + f" {100.0 * row['forced_rate']:>7.0f}%"
        )
    lines.append("-" * len(header))
    lines.append(
        f"overall: {summary['forced']}/{summary['games']} forced "
        f"({100.0 * summary['forced_rate']:.0f}%); "
        f"worst family: {summary['worst_family']} "
        f"({100.0 * summary['worst_family_forced_rate']:.0f}%)"
    )
    return "\n".join(lines)


def write_json(
    summary: dict,
    records: list[GameRecord],
    metadata: dict,
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.json"
    payload = {
        "metadata": metadata,
        "summary": summary,
        "games": [asdict(record) for record in records],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return path

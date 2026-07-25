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


def _rollup(records: list[GameRecord]) -> dict:
    forced = sum(1 for r in records if r.label == SELFMATE_FORCED)
    return {
        "games": len(records),
        "forced": forced,
        "forced_rate": forced / len(records) if records else 0.0,
    }


def summarize(records: list[GameRecord]) -> dict:
    """Aggregate a run. The milestone metrics are the HELD-OUT rollup
    and the worst held-out family — a pooled mean would rise from dev
    improvement alone, which is exactly the self-grading the league
    exists to prevent."""
    families = family_table(records)
    held = {
        name: row for name, row in families.items()
        if row["split"] == "held-out"
    }
    scored = held or families
    worst_name = None
    if scored:
        worst_name = min(scored, key=lambda name: scored[name]["forced_rate"])
    return {
        "overall": _rollup(records),
        "dev": _rollup(
            [r for r in records if split_of(r.family) == "dev"]
        ),
        "held_out": _rollup(
            [r for r in records if split_of(r.family) == "held-out"]
        ),
        "families": families,
        "worst_family": worst_name,
        "worst_family_forced_rate": (
            scored[worst_name]["forced_rate"] if worst_name else 0.0
        ),
        "layers": _layers(records),
    }


#: Which gauge funds which layer, and against which configured cap.
#: The 2026-07-24 reach verdict had to rebuild this split by hand from
#: a pinned report before it could see that the budgets were allocated
#: backwards; a run should state its own allocation instead.
_LAYERS = (
    ("root_probe", "probe_nodes", "probe_cap"),
    ("root_forcing", "probe_forcing_nodes", "probe_forcing_cap"),
    ("sub_probe", "sub_probe_nodes", "sub_probe_cap"),
    ("steering", "search_nodes", "node_cap"),
)


def _layers(records: list[GameRecord]) -> dict:
    """Per-layer node allocation: cost per decision and cap saturation.

    Reported per run so "where did the compute go" is a column rather
    than an archaeology exercise. Saturation is against the layer's own
    configured cap, which is what makes a 4%-saturated layer next to a
    94%-saturated one legible at a glance.
    """
    total = {}
    decisions = 0
    for record in records:
        probes = getattr(record, "probes", None) or {}
        decisions += probes.get("moves_played", 0)
        for _name, gauge, _cap in _LAYERS:
            total[gauge] = total.get(gauge, 0) + probes.get(gauge, 0)
    spent = sum(total.values())
    out = {"decisions": decisions, "nodes": spent, "by_layer": {}}
    for name, gauge, cap in _LAYERS:
        nodes = total.get(gauge, 0)
        out["by_layer"][name] = {
            "nodes": nodes,
            "per_decision": nodes / decisions if decisions else 0.0,
            "share": nodes / spent if spent else 0.0,
            "cap_gauge": cap,
        }
    return out


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

    def _rate(rollup: dict) -> str:
        return (
            f"{rollup['forced']}/{rollup['games']} "
            f"({100.0 * rollup['forced_rate']:.0f}%)"
        )

    lines.append(
        f"forced — held-out: {_rate(summary['held_out'])}; "
        f"dev: {_rate(summary['dev'])}; "
        f"overall: {_rate(summary['overall'])}; "
        f"worst held-out family: {summary['worst_family']} "
        f"({100.0 * summary['worst_family_forced_rate']:.0f}%)"
    )
    layers = summary.get("layers")
    if layers and layers["decisions"]:
        parts = " ".join(
            f"{name} {row['per_decision']:,.0f}/dec "
            f"({100.0 * row['share']:.0f}%)"
            for name, row in layers["by_layer"].items() if row["nodes"]
        )
        lines.append(
            f"nodes — {layers['nodes'] / layers['decisions']:,.0f} per "
            f"decision over {layers['decisions']:,} decisions: {parts}"
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

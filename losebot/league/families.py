"""League roster and the dev / held-out protocol.

DEV families may inform the engine's beliefs, fits, and drills.
HELD-OUT families are report-only: their parameters are frozen in
``models.presets`` and must never move toward engine performance. The
league reports both, but generalization claims rest on held-out rows —
and on the WORST held-out row, because an average can hide exactly the
collapse (squat 10/10, sloppy 0/10) that forced the pivot.
"""

from __future__ import annotations

DEV_FAMILIES = ("zach", "sloppy", "squat")
HELD_OUT_FAMILIES = ("sloppy-held", "human-held", "squat-held", "random")
ALL_FAMILIES = DEV_FAMILIES + HELD_OUT_FAMILIES


def split_of(family: str) -> str:
    return "dev" if family in DEV_FAMILIES else "held-out"


def resolve_families(spec: str) -> tuple[str, ...]:
    """CLI helper: 'dev', 'held', 'all', or a comma-separated list."""
    if spec == "all":
        return ALL_FAMILIES
    if spec == "dev":
        return DEV_FAMILIES
    if spec == "held":
        return HELD_OUT_FAMILIES
    names = tuple(part.strip() for part in spec.split(",") if part.strip())
    unknown = [n for n in names if n not in ALL_FAMILIES]
    if unknown:
        raise ValueError(
            f"unknown families {unknown}; known: {list(ALL_FAMILIES)}"
        )
    return names

"""Named parameter points of the urge family.

Two tiers, and the distinction is the benchmark's integrity:

DEV models are fair game for tuning, fitting, and drilling — they are
where the engine's opponent beliefs may come from.

HELD-OUT models are FROZEN. Their parameters were written down once
(2026-07-21, the pivot) and must never be adjusted toward engine
performance; they exist to answer "did we generalize or did we
memorize" — the question the specialist era could not ask because
every kernel it faced was also a kernel it drilled on. Fixing a bug in
the family's mechanics is fine; nudging a held-out number is not.
"""

from __future__ import annotations

import chess

from .urges import UrgeModel, UrgeParams

# ----- DEV: tune/fit against these freely -------------------------------

ZACH = UrgeParams()  # all urges zero: mate-avoidant capture-averse shuffle

# The session-19 sloppy human, distilled from the first live games.
SLOPPY = UrgeParams(
    promote=0.95, greed=0.85, trade=0.35, check=0.25, push=0.5, hunt=0.5,
)

# The IYQd0RBC corner squatter: king hugs home, pawns are hostages.
SQUAT = UrgeParams(home=1.0, pawn_last=True)

# ----- HELD-OUT: frozen 2026-07-21; report against, never tune against --

SLOPPY_HELD = UrgeParams(
    promote=0.80, greed=0.70, trade=0.50, check=0.40, push=0.35, hunt=0.65,
)

# Closest sketch of a real casual human: sloppy urges plus a 5% lapse in
# the mate-avoidance discipline (cG0S5wSF's mercy family, priced in).
HUMAN_HELD = UrgeParams(
    mercy=0.05, promote=0.90, greed=0.60, trade=0.30, check=0.30, push=0.45,
    hunt=0.40,
)

# A squatter who accepts gifts — the exact combination that beat the
# choreography era (squat premise plus capturing kernel), on the other
# board corner for good measure.
SQUAT_HELD = UrgeParams(
    home=1.0, home_side="queen", pawn_last=True, greed=0.50, trade=0.25,
)

# Pure legal-move noise, mates included: the sanity floor.
RANDOM = UrgeParams(mercy=1.0)

_PRESETS: dict[str, UrgeParams] = {
    "zach": ZACH,
    "sloppy": SLOPPY,
    "squat": SQUAT,
    "sloppy-held": SLOPPY_HELD,
    "human-held": HUMAN_HELD,
    "squat-held": SQUAT_HELD,
    "random": RANDOM,
}

MODEL_NAMES = tuple(_PRESETS)


def make_model(name: str, home_corner: chess.Square | None = None,
               **overrides) -> UrgeModel:
    """Instantiate a preset by name, with optional parameter overrides
    (overrides are for DEV experimentation — held-out names should be
    built bare)."""
    params = _PRESETS[name]
    if home_corner is not None:
        overrides["home_corner"] = home_corner
    model = UrgeModel(name, params)
    if overrides:
        model = model.with_params(**overrides)
    return model

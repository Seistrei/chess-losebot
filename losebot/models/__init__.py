"""Stochastic opponent models.

One parametric family (``urges``) covers the old kernel zoo as
parameter points and exposes exact per-move probability distributions —
what the expectimax steering layer consumes and what a corpus fit will
eventually estimate. ``presets`` pins the named parameter vectors,
including the frozen held-out league families.
"""

from .base import OpponentModel, ModelPlayer
from .presets import MODEL_NAMES, make_model
from .urges import UrgeModel, UrgeParams

__all__ = [
    "OpponentModel",
    "ModelPlayer",
    "UrgeModel",
    "UrgeParams",
    "MODEL_NAMES",
    "make_model",
]

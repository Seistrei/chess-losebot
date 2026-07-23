"""Stochastic opponent models.

One parametric family (``urges``) covers the old kernel zoo as
parameter points and exposes exact per-move probability distributions —
what the expectimax steering layer consumes, what the online
``posterior`` infers over from observed moves, and what an offline
corpus fit estimates. ``presets`` pins the named parameter vectors,
including the frozen held-out league families.
"""

from .base import OpponentModel, ModelPlayer
from .posterior import HypothesisPosterior, MixtureModel
from .presets import MODEL_NAMES, make_model
from .urges import UrgeModel, UrgeParams

__all__ = [
    "OpponentModel",
    "ModelPlayer",
    "UrgeModel",
    "UrgeParams",
    "MODEL_NAMES",
    "make_model",
    "HypothesisPosterior",
    "MixtureModel",
]

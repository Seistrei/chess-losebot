"""The frozen evaluation league.

The benchmark the specialist era never had: a fixed roster of opponent
families (dev + held-out), fresh RNG per game, seats alternated, every
game classified by the outcome taxonomy, reported per-family with the
worst-family number given equal billing to the average. Progress
claims cite THIS, not a drill built from the failure being fixed.
"""

from .families import DEV_FAMILIES, HELD_OUT_FAMILIES, ALL_FAMILIES
from .play import play_game, save_pgn
from .runner import run_league

__all__ = [
    "DEV_FAMILIES",
    "HELD_OUT_FAMILIES",
    "ALL_FAMILIES",
    "play_game",
    "save_pgn",
    "run_league",
]

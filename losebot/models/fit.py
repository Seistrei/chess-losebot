"""Offline maximum-likelihood fitting of urge parameters from games.

The corpus-fit half of the inference lever: where ``posterior`` picks
between a handful of named hypotheses online, this module estimates
the parameters themselves from recorded games — the machinery that
turns a stack of human PGNs into a "fitted-human" parameter point the
hypothesis set can one day carry. Same likelihood as the posterior
(the family's exact ``distribution()``, epsilon-smoothed against
uniform so an off-model move costs heavily but finitely), maximized
by coordinate descent over a value grid: pypy stdlib only, no
gradients, and every step deterministic — same observations, same
grid, same fit, bit for bit.

Validation protocol (the selftest enforces it): the fitter must
recover KNOWN parameters from kernel-generated games — squat games
fit back to home=1 with the pawn hostage, zach games fit back to
zeros — before any number it produces from human games is worth
reading. Fitting stays a DEV activity throughout: held-out presets
are report-only and no fit result may nudge them.
"""

from __future__ import annotations

import math
from dataclasses import replace

import chess

from .urges import UrgeModel, UrgeParams

#: Same smoothing role as the posterior's EPSILON: a move the candidate
#: parameters give zero mass must cost log(eps/legal), not -inf, or one
#: mercy lapse in a corpus would veto every non-mercy parameter point.
EPSILON = 1e-3

#: The eight continuous urge axes, in fixed descent order.
SCALARS = (
    "mercy", "promote", "greed", "trade", "check", "push", "hunt", "home",
)

#: Discrete axes: the home corner's side and the pawn hostage flag.
DISCRETE = (
    ("home_side", ("king", "queen")),
    ("pawn_last", (False, True)),
)

COARSE_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
FINE_GRID = tuple(round(i * 0.05, 2) for i in range(21))


def observations_from_game(
    game: "chess.pgn.Game", color: chess.Color
) -> list[tuple[chess.Board, chess.Move]]:
    """(position, move) pairs for one side of one recorded game.

    Positions are stack-free board copies: the likelihood is a pure
    function of the position, and dragging move history along would
    only cost memory. Forced replies (one legal move) are skipped for
    the same reason the posterior skips them — every parameter point
    explains them identically, so they are weight, not evidence.
    """
    board = game.board()
    obs: list[tuple[chess.Board, chess.Move]] = []
    for move in game.mainline_moves():
        if board.turn == color and board.legal_moves.count() > 1:
            obs.append((board.copy(stack=False), move))
        board.push(move)
    return obs


def observations_from_play(
    root: chess.Board, moves, color: chess.Color
) -> list[tuple[chess.Board, chess.Move]]:
    """Same contract, fed from a raw move list (kernel-generated games
    in the selftest use this — no PGN round-trip required)."""
    board = root.copy(stack=False)
    obs: list[tuple[chess.Board, chess.Move]] = []
    for move in moves:
        if board.turn == color and board.legal_moves.count() > 1:
            obs.append((board.copy(stack=False), move))
        board.push(move)
    return obs


def neg_log_likelihood(
    params: UrgeParams,
    obs: list[tuple[chess.Board, chess.Move]],
    epsilon: float = EPSILON,
) -> float:
    """Total smoothed negative log-likelihood of the observations."""
    model = UrgeModel("fit-candidate", params)
    total = 0.0
    for board, move in obs:
        dist = dict(model.distribution(board))
        legal = board.legal_moves.count()
        prob = (1.0 - epsilon) * dist.get(move, 0.0) + epsilon / legal
        total -= math.log(prob)
    return total


def fit(
    obs: list[tuple[chess.Board, chess.Move]],
    grid: tuple[float, ...] = FINE_GRID,
    start: UrgeParams | None = None,
    max_passes: int = 8,
    epsilon: float = EPSILON,
    log=None,
) -> tuple[UrgeParams, float]:
    """Coordinate descent: one axis at a time over the grid, repeated
    until a full pass moves nothing (or ``max_passes``).

    A new value must be STRICTLY better to displace the incumbent, so
    flat likelihood stretches (a parameter whose urge never had a
    legal expression in the corpus) keep the start value — zeros,
    unless the caller seeds otherwise — instead of wandering the tie.
    """
    params = start if start is not None else UrgeParams()
    best = neg_log_likelihood(params, obs, epsilon)
    for sweep in range(max_passes):
        moved = False
        for axis in SCALARS:
            incumbent = getattr(params, axis)
            for value in grid:
                if value == incumbent:
                    continue
                trial = neg_log_likelihood(
                    replace(params, **{axis: value}), obs, epsilon
                )
                if trial < best:
                    params = replace(params, **{axis: value})
                    best = trial
                    moved = True
        for axis, values in DISCRETE:
            incumbent = getattr(params, axis)
            for value in values:
                if value == incumbent:
                    continue
                trial = neg_log_likelihood(
                    replace(params, **{axis: value}), obs, epsilon
                )
                if trial < best:
                    params = replace(params, **{axis: value})
                    best = trial
                    moved = True
        if log is not None:
            log(f"pass {sweep + 1}: nll={best:.2f} {params}")
        if not moved:
            break
    return params, best

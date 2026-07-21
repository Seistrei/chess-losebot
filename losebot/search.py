"""Expectimax against a stochastic opponent model.

The pivot's steering layer. Our nodes maximize; opponent nodes take the
EXPECTATION over the model's move distribution instead of assuming any
fixed doctrine. This is what dissolves the "no position predicate
discriminates between doctrines" impasse of the specialist era: hold
vs. lift, cage vs. race — the answer differs by opponent, and here the
opponent's distribution is in the tree, so the search prices it per
opponent with no predicate at all.

Bounded honesty: opponent nodes trim the reply distribution, but by
probability-class coverage, not rank. Rank truncation kept whatever
python-chess generated first among tied probabilities and renormalized
the survivors — at the start position it modeled Zach as certain to
play one of 5 specific moves out of 20 equally likely ones. Here whole
probability classes are kept until the coverage target is met, and a
class too large for the cap is represented by a seeded pseudo-random
subset carrying the class's full mass: within a class the members are
probability-exchangeable, so the subset is an unbiased stand-in. The
residual bias (conditioning on the covered mass) is the knob named
``coverage`` — acceptable for steering, never for closing. Closing is
the oracle's job, and the oracle takes no model.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import chess

from .evaluate import MATE, evaluate
from .models.base import OpponentModel
from .outcomes import adjudicate_draw


@dataclass
class SearchStats:
    nodes: int = 0
    leaves: int = 0
    chance_nodes: int = 0
    truncated_replies: int = 0
    root_values: list = field(default_factory=list)


def best_move(
    board: chess.Board,
    us: chess.Color,
    model: OpponentModel,
    depth: int = 3,
    topk: int = 6,
    coverage: float = 0.85,
    draw_contempt: float = 400.0,
    root_moves: list[chess.Move] | None = None,
) -> tuple[chess.Move | None, float, SearchStats]:
    """Pick our move by expectimax. ``root_moves`` restricts the root
    (the engine's misère-safety partition); None means all legal.
    ``topk`` caps replies per chance node, ``coverage`` is the minimum
    probability mass a trimmed reply set must represent."""
    stats = SearchStats()
    moves = list(root_moves) if root_moves is not None else list(
        board.legal_moves
    )
    if not moves:
        return None, -MATE, stats
    moves.sort(key=lambda m: _root_order(board, m))
    best: chess.Move | None = None
    best_value = -float("inf")
    for move in moves:
        board.push(move)
        value = _node_value(
            board, us, model, depth - 1, 1, topk, coverage, draw_contempt,
            stats,
        )
        board.pop()
        stats.root_values.append((move, value))
        if value > best_value:
            best_value = value
            best = move
    return best, best_value, stats


_SEED_MASK = (1 << 64) - 1
_SEED_MULT = 0x9E3779B97F4A7C15


def stable_seed(key) -> int:
    """Fold a transposition key into a process-stable subset seed.

    Python's built-in hash is id-derived for None — and None is the
    key's empty en-passant slot, i.e. almost every position — so
    hash(key) differed per process and fresh containers modeled
    DIFFERENT reply subsets from the same position (2026-07-21
    review: the frozen league was not reproducible). Plain arithmetic
    over the key's ints is stable everywhere; None maps to 64, one
    past the last square, which no real en-passant slot can be.
    """
    seed = 0
    for part in key:
        value = 64 if part is None else int(part)
        seed = ((seed ^ value) * _SEED_MULT) & _SEED_MASK
    return seed


def reply_support(
    dist: list[tuple[chess.Move, float]],
    coverage: float,
    cap: int,
    seed: int,
) -> list[tuple[chess.Move, float]]:
    """Trim a reply distribution by probability-class coverage.

    Walk equal-probability classes most-probable first, keeping whole
    classes until the kept mass reaches ``coverage`` or the ``cap`` is
    full. A class that does not fit is represented by a seeded random
    subset of itself carrying the WHOLE class's mass — unbiased over
    exchangeable members, and deterministic per position because the
    seed derives from the transposition key. Kept weights are
    renormalized (conditioning on the covered set).
    """
    if len(dist) <= cap:
        return dist
    classes: list[tuple[float, list[chess.Move]]] = []
    for move, prob in dist:  # sorted most-probable first by contract
        if classes and abs(classes[-1][0] - prob) < 1e-12:
            classes[-1][1].append(move)
        else:
            classes.append((prob, [move]))
    kept: list[tuple[chess.Move, float]] = []
    mass = 0.0
    room = cap
    for prob, members in classes:
        class_mass = prob * len(members)
        if len(members) <= room:
            kept.extend((move, prob) for move in members)
            room -= len(members)
        else:
            chosen = random.Random(seed).sample(members, room)
            share = class_mass / room
            kept.extend((move, share) for move in chosen)
            room = 0
        mass += class_mass
        if room <= 0 or mass >= coverage:
            break
    total = sum(weight for _, weight in kept)
    return [(move, weight / total) for move, weight in kept]


def _root_order(board: chess.Board, move: chess.Move) -> int:
    """Captures of their mobile pieces first, then checks: the strip
    and the coercion motifs get explored before shuffle noise."""
    if board.is_capture(move):
        victim = board.piece_type_at(move.to_square)
        if victim is not None and victim != chess.PAWN:
            return 0
        return 1
    if board.gives_check(move):
        return 2
    return 3


def _node_value(
    board: chess.Board,
    us: chess.Color,
    model: OpponentModel,
    depth: int,
    ply: int,
    topk: int,
    coverage: float,
    contempt: float,
    stats: SearchStats,
) -> float:
    stats.nodes += 1
    if board.is_checkmate():
        # Side to move is the mated one. Us mated = the goal; them
        # mated = the accident. Prefer sooner goals, later accidents.
        if board.turn == us:
            return MATE - ply
        return -(MATE - ply)
    if board.is_stalemate() or adjudicate_draw(board) is not None:
        return -contempt
    if depth <= 0:
        stats.leaves += 1
        return evaluate(board, us)
    if board.turn == us:
        value = -float("inf")
        for move in board.legal_moves:
            board.push(move)
            child = _node_value(
                board, us, model, depth - 1, ply + 1, topk, coverage,
                contempt, stats,
            )
            board.pop()
            if child > value:
                value = child
        return value
    # Chance node: expectation over the model's reply distribution.
    stats.chance_nodes += 1
    dist = model.distribution(board)
    if len(dist) > topk:
        seed = stable_seed(board._transposition_key())
        trimmed = reply_support(dist, coverage, topk, seed)
        stats.truncated_replies += len(dist) - len(trimmed)
        dist = trimmed
    value = 0.0
    for move, prob in dist:
        board.push(move)
        child = _node_value(
            board, us, model, depth - 1, ply + 1, topk, coverage, contempt,
            stats,
        )
        board.pop()
        value += prob * child
    return value

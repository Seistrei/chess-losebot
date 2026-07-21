"""Expectimax against a stochastic opponent model.

The pivot's steering layer. Our nodes maximize; opponent nodes take the
EXPECTATION over the model's move distribution instead of assuming any
fixed doctrine. This is what dissolves the "no position predicate
discriminates between doctrines" impasse of the specialist era: hold
vs. lift, cage vs. race — the answer differs by opponent, and here the
opponent's distribution is in the tree, so the search prices it per
opponent with no predicate at all.

Bounded honesty: opponent nodes are truncated to the top-k most
probable replies (renormalized). That biases values toward the model's
mainlines — acceptable for steering, never for closing. Closing is the
oracle's job, and the oracle takes no model.
"""

from __future__ import annotations

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
    topk: int = 5,
    draw_contempt: float = 400.0,
    root_moves: list[chess.Move] | None = None,
) -> tuple[chess.Move | None, float, SearchStats]:
    """Pick our move by expectimax. ``root_moves`` restricts the root
    (the engine's misère-safety partition); None means all legal."""
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
            board, us, model, depth - 1, 1, topk, draw_contempt, stats
        )
        board.pop()
        stats.root_values.append((move, value))
        if value > best_value:
            best_value = value
            best = move
    return best, best_value, stats


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
                board, us, model, depth - 1, ply + 1, topk, contempt, stats
            )
            board.pop()
            if child > value:
                value = child
        return value
    # Chance node: expectation over the model's reply distribution.
    stats.chance_nodes += 1
    dist = model.distribution(board)
    if len(dist) > topk:
        stats.truncated_replies += len(dist) - topk
        dist = dist[:topk]  # distribution() is sorted most-probable first
        total = sum(prob for _, prob in dist)
        dist = [(move, prob / total) for move, prob in dist]
    value = 0.0
    for move, prob in dist:
        board.push(move)
        child = _node_value(
            board, us, model, depth - 1, ply + 1, topk, contempt, stats
        )
        board.pop()
        value += prob * child
    return value

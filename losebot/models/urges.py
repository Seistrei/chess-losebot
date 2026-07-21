"""The urge family: one parametric stochastic human.

Distilled from the live-game corpus by way of the specialists'
SloppyBot/ZachBot/CornerSquatBot kernels, but expressed as ONE family
with an exact move distribution. Each urge is a prioritized impulse
that fires with its own probability when it has a legal expression;
unfired mass falls through to the next urge and finally to the aimless
shuffle. Setting every urge to zero recovers Zach (mate-avoidant,
capture-averse shuffle); the session-19 sloppy weights are one point;
a corner squatter is ``home=1`` with the pawn-hostage base.

Priority order (fixed): mercy lapse, promote, greed, check, push,
hunt, home, shuffle. The greed stage keeps the hard-won recapture
adjudication: push-and-scan, because a pre-move attack map misses the
x-ray defender the capturer's own body blocks and counts pinned
defenders that can never legally take back.

The mate-avoidance core is structural, not an urge: humans trying to
make us win held "never deliver mate unless forced" for hundreds of
plies. ``mercy`` prices the exception as a per-move lapse into a
uniform pick over ALL legal moves.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import chess

from .base import OpponentModel

VICTIM_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}


@dataclass(frozen=True)
class UrgeParams:
    """Firing probabilities (0..1 each). All-zero = Zach."""

    mercy: float = 0.0    # lapse: uniform over ALL legal moves, mates included
    promote: float = 0.0  # queen on sight
    greed: float = 0.0    # take the biggest victim, free victims first
    trade: float = 0.0    # ...and a recapturable victim on this sub-roll
    check: float = 0.0    # any checking move
    push: float = 0.0     # most advanced pawn push
    hunt: float = 0.0     # king steps strictly toward the nearest meal
    home: float = 0.0     # king steps toward the home corner (quiet only)
    home_corner: chess.Square | None = None  # exact square override
    home_side: str = "king"  # else resolved per color: king/queen side corner
    pawn_last: bool = False  # shuffle touches pawns only when nothing else


class UrgeModel(OpponentModel):
    def __init__(self, name: str, params: UrgeParams):
        self.name = name
        self.params = params

    def with_params(self, **overrides) -> "UrgeModel":
        return UrgeModel(self.name, replace(self.params, **overrides))

    def distribution(
        self, board: chess.Board
    ) -> list[tuple[chess.Move, float]]:
        p = self.params
        legal = list(board.legal_moves)
        if not legal:
            return []
        non_mating = []
        for move in legal:
            board.push(move)
            mates = board.is_checkmate()
            board.pop()
            if not mates:
                non_mating.append(move)
        if not non_mating:
            return _uniform(legal)  # zugzwang: forced to mate us

        dist: dict[chess.Move, float] = {}
        mass = 1.0
        if p.mercy > 0.0:
            _spread(dist, legal, mass * p.mercy)
            mass *= 1.0 - p.mercy
        pool = non_mating

        if p.promote > 0.0:
            picks = [m for m in pool if m.promotion == chess.QUEEN]
            mass = _fire(dist, picks, mass, p.promote)

        if p.greed > 0.0:
            captures = [m for m in pool if board.is_capture(m)]
            if captures:
                free = [m for m in captures if not _recaptured(board, m)]
                if free:
                    mass = _fire(dist, _greediest(board, free), mass, p.greed)
                elif p.trade > 0.0:
                    mass = _fire(
                        dist, _greediest(board, captures), mass,
                        p.greed * p.trade,
                    )

        if p.check > 0.0:
            picks = [m for m in pool if board.gives_check(m)]
            mass = _fire(dist, picks, mass, p.check)

        if p.push > 0.0:
            picks = _farthest_pushes(board, pool)
            mass = _fire(dist, picks, mass, p.push)

        if p.hunt > 0.0:
            picks = _hunting_steps(board, pool)
            mass = _fire(dist, picks, mass, p.hunt)

        if p.home > 0.0:
            picks = _homing_steps(board, pool, p.home_corner, p.home_side)
            mass = _fire(dist, picks, mass, p.home)

        _spread(dist, _shuffle_pool(board, pool, p.pawn_last), mass)
        return sorted(dist.items(), key=lambda kv: -kv[1])


def _uniform(moves) -> list[tuple[chess.Move, float]]:
    share = 1.0 / len(moves)
    return [(m, share) for m in moves]


def _spread(dist: dict, moves, mass: float) -> None:
    if mass <= 0.0 or not moves:
        return
    share = mass / len(moves)
    for move in moves:
        dist[move] = dist.get(move, 0.0) + share


def _fire(dist: dict, picks, mass: float, prob: float) -> float:
    """Spend ``prob`` of the remaining mass on ``picks`` (if any)."""
    if not picks or prob <= 0.0:
        return mass
    _spread(dist, picks, mass * prob)
    return mass * (1.0 - prob)


def _victim_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        return VICTIM_VALUES[chess.PAWN]
    return VICTIM_VALUES[board.piece_type_at(move.to_square)]


def _recaptured(board: chess.Board, move: chess.Move) -> bool:
    """Push-and-scan: any legal reply onto the landed square recaptures."""
    board.push(move)
    hit = any(
        reply.to_square == move.to_square for reply in board.legal_moves
    )
    board.pop()
    return hit


def _greediest(board: chess.Board, captures) -> list[chess.Move]:
    best = max(_victim_value(board, m) for m in captures)
    return [m for m in captures if _victim_value(board, m) == best]


def _farthest_pushes(board: chess.Board, pool) -> list[chess.Move]:
    us = board.turn
    pushes = [
        m for m in pool
        if board.piece_type_at(m.from_square) == chess.PAWN
        and not board.is_capture(m)
    ]
    if not pushes:
        return []

    def progress(move: chess.Move) -> int:
        rank = chess.square_rank(move.to_square)
        return rank if us == chess.WHITE else 7 - rank

    far = max(progress(m) for m in pushes)
    return [m for m in pushes if progress(m) == far]


def _hunting_steps(board: chess.Board, pool) -> list[chess.Move]:
    """King moves strictly closing on the nearest enemy non-king piece."""
    us = board.turn
    targets = [
        sq for sq, piece in board.piece_map().items()
        if piece.color != us and piece.piece_type != chess.KING
    ]
    steps = [
        m for m in pool
        if board.piece_type_at(m.from_square) == chess.KING
    ]
    if not targets or not steps:
        return []
    king = board.king(us)
    here = min(chess.square_distance(king, t) for t in targets)
    return [
        m for m in steps
        if min(chess.square_distance(m.to_square, t) for t in targets) < here
    ]


def _homing_steps(board: chess.Board, pool, corner: chess.Square | None,
                  side: str) -> list[chess.Move]:
    """Quiet king moves landing nearest the home corner.

    Quiet only: the squatter is capture-averse by temperament; its
    captures, when parameterized, come from the greed urge instead.
    """
    us = board.turn
    if corner is None:
        if side == "queen":
            corner = chess.A1 if us == chess.WHITE else chess.A8
        else:
            corner = chess.H1 if us == chess.WHITE else chess.H8
    steps = [
        m for m in pool
        if board.piece_type_at(m.from_square) == chess.KING
        and not board.is_capture(m)
    ]
    if not steps:
        return []
    best = min(chess.square_distance(m.to_square, corner) for m in steps)
    return [
        m for m in steps
        if chess.square_distance(m.to_square, corner) == best
    ]


def _shuffle_pool(board: chess.Board, pool, pawn_last: bool):
    """The aimless base: quiet moves first (Zach's capture-aversion),
    optionally holding pawns hostage until nothing else can move."""
    quiet = [m for m in pool if not board.is_capture(m)]
    base = quiet or pool
    if pawn_last:
        held = [
            m for m in base
            if board.piece_type_at(m.from_square) != chess.PAWN
        ]
        if held:
            return held
    return base

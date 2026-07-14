"""Exact short-horizon proofs for construction-plan subgoals."""

from __future__ import annotations

from dataclasses import dataclass
import time

import chess

from .search import ProofStatus, support_zach
from .templates import (
    ConstructionPlan,
    PawnMateTemplate,
    herding_metrics,
)


@dataclass(frozen=True)
class HerdSearchResult:
    status: ProofStatus
    move: chess.Move | None
    nodes: int


@dataclass(frozen=True)
class ModeledHerdResult:
    move: chess.Move | None
    replies: int
    expected_cost: float | None


@dataclass
class _HerdContext:
    plan: ConstructionPlan
    us: chess.Color
    model: str | None
    baseline_defender_steps: int
    maximum_king_steps: int
    minimum_cage: int
    budget: list[int]


def _draw(board: chess.Board) -> bool:
    return (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.halfmove_clock >= 100
        or (board.halfmove_clock >= 8 and board.is_repetition(3))
    )


def _preserves_plan(target: PawnMateTemplate | None,
                    context: _HerdContext) -> bool:
    return bool(
        target is not None
        and target.holding_blocker
        and target.holding_blocker_defended
        and target.our_king_steps <= context.maximum_king_steps
        and target.cage_occupancy >= context.minimum_cage
        and not target.runway_blocked
    )


def _goal(target: PawnMateTemplate | None,
          context: _HerdContext) -> bool:
    return (
        _preserves_plan(target, context)
        and target.defender_steps < context.baseline_defender_steps
    )


def _spend(context: _HerdContext) -> bool:
    if context.budget[0] <= 0:
        return False
    context.budget[0] -= 1
    return True


def _herd_after(board: chess.Board, remaining: int,
                context: _HerdContext) -> ProofStatus:
    """Opponent AND node: every modeled reply must reach the subgoal."""
    pool = (
        support_zach(board)
        if context.model == "zach"
        else list(board.legal_moves)
    )
    if not pool:
        # Non-terminal empty Zach pool means every legal move mates us.
        return ProofStatus.PROVEN

    saw_unknown = False
    for reply in pool:
        if not _spend(context):
            return ProofStatus.UNKNOWN
        board.push(reply)
        if board.is_checkmate():
            status = ProofStatus.PROVEN
        elif _draw(board):
            status = ProofStatus.DISPROVEN
        else:
            target = context.plan.resolve(board, context.us)
            if _goal(target, context):
                status = ProofStatus.PROVEN
            elif remaining > 1 and _preserves_plan(target, context):
                status = _herd_self(board, remaining - 1, context)
            else:
                status = ProofStatus.DISPROVEN
        board.pop()
        if status is ProofStatus.DISPROVEN:
            return status
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    return ProofStatus.UNKNOWN if saw_unknown else ProofStatus.PROVEN


def _herd_self(board: chess.Board, remaining: int,
               context: _HerdContext) -> ProofStatus:
    """Our OR node: find one plan-preserving move that forces progress."""
    moves = list(board.legal_moves)
    moves.sort(key=lambda move: 0 if board.gives_check(move) else 1)
    saw_unknown = False
    for move in moves:
        if not _spend(context):
            return ProofStatus.UNKNOWN
        board.push(move)
        target = context.plan.resolve(board, context.us)
        if (
            board.is_checkmate()
            or _draw(board)
            or not _preserves_plan(target, context)
        ):
            board.pop()
            continue
        status = _herd_after(board, remaining, context)
        board.pop()
        if status is ProofStatus.PROVEN:
            return status
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    return ProofStatus.UNKNOWN if saw_unknown else ProofStatus.DISPROVEN


def herding_move(board: chess.Board, plan: ConstructionPlan,
                 us: chess.Color, max_n: int, model: str | None,
                 node_cap: int) -> HerdSearchResult:
    """Find a move forcing their king closer within ``max_n`` own moves."""
    initial = plan.resolve(board, us)
    if (
        initial is None
        or initial.defender_steps <= 0
        or initial.our_king_steps > 0
        or initial.cage_occupancy < 3
        or not initial.holding_blocker
        or not initial.holding_blocker_defended
        or initial.runway_blocked
    ):
        return HerdSearchResult(ProofStatus.DISPROVEN, None, 0)

    budget = [node_cap]
    context = _HerdContext(
        plan=plan,
        us=us,
        model=model,
        baseline_defender_steps=initial.defender_steps,
        maximum_king_steps=initial.our_king_steps,
        minimum_cage=3,
        budget=budget,
    )
    moves = list(board.legal_moves)
    moves.sort(key=lambda move: 0 if board.gives_check(move) else 1)
    saw_unknown = False
    for move in moves:
        if not _spend(context):
            return HerdSearchResult(
                ProofStatus.UNKNOWN, None, node_cap - budget[0]
            )
        board.push(move)
        target = plan.resolve(board, us)
        if (
            board.is_checkmate()
            or _draw(board)
            or not _preserves_plan(target, context)
        ):
            board.pop()
            continue
        status = _herd_after(board, max_n, context)
        board.pop()
        if status is ProofStatus.PROVEN:
            return HerdSearchResult(status, move, node_cap - budget[0])
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    status = ProofStatus.UNKNOWN if saw_unknown else ProofStatus.DISPROVEN
    return HerdSearchResult(status, None, node_cap - budget[0])


def _modeled_cost(board: chess.Board, target: PawnMateTemplate,
                  us: chess.Color) -> float:
    herding = herding_metrics(board, us, target)
    return (
        10.0 * target.defender_steps
        + 2.0 * herding.open_outward
        + 4.0 * target.our_king_steps
        - 0.5 * target.cage_occupancy
    )


def modeled_herding_move(
    board: chess.Board,
    plan: ConstructionPlan,
    us: chess.Color,
    moves: list[chess.Move],
    model: str | None,
    max_n: int,
    node_cap: int,
    time_limit_ms: int,
) -> ModeledHerdResult:
    """Choose plan-safe progress using bounded Zach-policy expectimax."""
    initial = plan.resolve(board, us)
    if (
        initial is None
        or initial.defender_steps <= 0
        or initial.our_king_steps > 0
        or initial.cage_occupancy < 3
        or not initial.holding_blocker
        or not initial.holding_blocker_defended
    ):
        return ModeledHerdResult(None, 0, None)

    context = _HerdContext(
        plan=plan,
        us=us,
        model=model,
        baseline_defender_steps=initial.defender_steps,
        maximum_king_steps=initial.our_king_steps,
        minimum_cage=3,
        budget=[0],
    )
    budget = [node_cap]
    deadline = time.monotonic() + time_limit_ms / 1000.0
    replies_examined = 0

    def available() -> bool:
        return budget[0] > 0 and time.monotonic() < deadline

    def expected_self(remaining: int) -> float:
        """Our choice node: minimize the modeled construction cost."""
        best = float("inf")
        candidates = list(board.legal_moves)
        candidates.sort(key=lambda move: 0 if board.gives_check(move) else 1)
        for candidate in candidates:
            if not available():
                break
            budget[0] -= 1
            board.push(candidate)
            target = plan.resolve(board, us)
            if (
                board.is_checkmate()
                or _draw(board)
                or not _preserves_plan(target, context)
            ):
                board.pop()
                continue
            cost = expected_after(remaining)
            board.pop()
            best = min(best, cost)
        if best != float("inf"):
            return best
        target = plan.resolve(board, us)
        return (
            _modeled_cost(board, target, us)
            if _preserves_plan(target, context)
            else float("inf")
        )

    def expected_after(remaining: int) -> float:
        """Opponent chance node: average Zach's actual uniform reply pool."""
        nonlocal replies_examined
        pool = (
            support_zach(board)
            if model == "zach"
            else list(board.legal_moves)
        )
        if not pool:
            return -10_000.0

        costs: list[float] = []
        for reply in pool:
            if not available():
                break
            budget[0] -= 1
            board.push(reply)
            replies_examined += 1
            if board.is_checkmate():
                cost = -10_000.0
            elif _draw(board):
                board.pop()
                return float("inf")
            else:
                target = plan.resolve(board, us)
                if not _preserves_plan(target, context):
                    board.pop()
                    return float("inf")
                if remaining > 1:
                    cost = expected_self(remaining - 1)
                else:
                    cost = _modeled_cost(board, target, us)
            costs.append(cost)
            board.pop()
        if len(costs) != len(pool):
            return float("inf")
        return sum(costs) / len(costs) if costs else float("inf")

    best_move = None
    best_expected = float("inf")
    for move in moves:
        if not available():
            break
        budget[0] -= 1
        board.push(move)
        after_move = plan.resolve(board, us)
        if (
            board.is_checkmate()
            or _draw(board)
            or not _preserves_plan(after_move, context)
        ):
            board.pop()
            continue
        expected = expected_after(max_n)
        board.pop()
        if expected < best_expected:
            best_move = move
            best_expected = expected

    if best_move is None:
        return ModeledHerdResult(None, replies_examined, None)
    return ModeledHerdResult(best_move, replies_examined, best_expected)

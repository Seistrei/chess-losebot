"""Exact short-horizon proofs for construction-plan subgoals."""

from __future__ import annotations

from dataclasses import dataclass
import time

import chess

from .search import (
    ProofStatus,
    _history_counts,
    _memo_key,
    _record_pop,
    _record_push,
    support_zach,
)
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
    nodes: int = 0
    cache_hits: int = 0
    memo_entries: int = 0
    candidates_pruned: int = 0
    complete: bool = True


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
                 node_cap: int,
                 moves: list[chess.Move] | None = None) -> HerdSearchResult:
    """Find a move forcing their king closer within ``max_n`` own moves.

    ``moves`` restricts the ROOT candidates (the caller passes its filtered
    safe list, so a proven net cannot start with a move the root filters
    rejected — e.g. one that leaves Zach nothing but captures). Interior
    nodes still search every legal move: they are inside a proof, and the
    plan-preservation checks are the arbiter there.
    """
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
    if moves is None:
        moves = list(board.legal_moves)
    moves = sorted(
        moves, key=lambda move: 0 if board.gives_check(move) else 1
    )
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


@dataclass
class _ModeledContext:
    """Shared limits and caches for selective modeled herding.

    Unlike the original depth-one experiment, every position classification
    and searched edge spends budget and observes the wall-clock deadline. Only
    fully evaluated values enter ``memo``; a partial average is never reused as
    if it represented Zach's complete uniform reply pool.
    """

    plan: ConstructionPlan
    us: chess.Color
    model: str | None
    preservation: _HerdContext
    candidate_limit: int
    budget: list[int]
    deadline: float
    memoize: bool
    memo: dict
    reply_cache: dict
    replies_examined: int = 0
    cache_hits: int = 0
    candidates_pruned: int = 0
    timed_out: bool = False
    budget_exhausted: bool = False

    def spend(self) -> bool:
        if time.monotonic() >= self.deadline:
            self.timed_out = True
            return False
        if self.budget[0] <= 0:
            self.budget_exhausted = True
            return False
        self.budget[0] -= 1
        return True


def _ranked_plan_moves(
    board: chess.Board,
    moves: list[chess.Move],
    context: _ModeledContext,
    history: dict,
) -> tuple[list[chess.Move], bool]:
    """Keep forcing checks plus the best plan-safe setup moves.

    The old depth-two tree expanded every legal move at our second choice
    node. Here checks are never lost to the beam, while quiet moves compete on
    the same construction cost used at modeled leaves. This admits one quiet
    setup move followed by a forcing move without reopening the full tree.
    """
    ranked: list[tuple[tuple, chess.Move, bool]] = []
    complete = True
    for move in moves:
        if not context.spend():
            complete = False
            break
        checking = board.gives_check(move)
        pushed_key = _record_push(board, move, history)
        target = context.plan.resolve(board, context.us)
        if (
            not board.is_checkmate()
            and not _draw(board)
            and _preserves_plan(target, context.preservation)
        ):
            herding = herding_metrics(board, context.us, target)
            rank = (
                0 if checking else 1,
                _modeled_cost(board, target, context.us),
                herding.open_total,
                -herding.controlled_outward,
                move.uci(),
            )
            ranked.append((rank, move, checking))
        _record_pop(board, history, pushed_key)

    ranked.sort(key=lambda item: item[0])
    checks = [item for item in ranked if item[2]]
    quiet = [item for item in ranked if not item[2]]
    quiet_slots = max(0, context.candidate_limit - len(checks))
    selected = checks + quiet[:quiet_slots]
    context.candidates_pruned += len(ranked) - len(selected)
    selected.sort(key=lambda item: item[0])
    return [item[1] for item in selected], complete


def _bounded_reply_pool(
    board: chess.Board,
    context: _ModeledContext,
) -> tuple[tuple[chess.Move, ...] | None, bool]:
    """Return Zach's exact pool without doing unbudgeted classification."""
    position_key = board._transposition_key()
    if context.memoize:
        cached = context.reply_cache.get(position_key)
        if cached is not None:
            context.cache_hits += 1
            return cached, True

    legal = list(board.legal_moves)
    if context.model != "zach":
        pool = tuple(legal)
        if context.memoize:
            context.reply_cache[position_key] = pool
        return pool, True

    non_mating: list[chess.Move] = []
    quiet: list[chess.Move] = []
    for move in legal:
        # Classification was the unbounded part of the first depth-two
        # experiment, so even obviously non-mating moves spend one unit.
        if not context.spend():
            return None, False
        mating = False
        if board.gives_check(move):
            board.push(move)
            mating = board.is_checkmate()
            board.pop()
        if not mating:
            non_mating.append(move)
            if not board.is_capture(move):
                quiet.append(move)

    pool = tuple(quiet or non_mating)
    if context.memoize:
        context.reply_cache[position_key] = pool
    return pool, True


def _selective_modeled_herding_move(
    board: chess.Board,
    plan: ConstructionPlan,
    us: chess.Color,
    moves: list[chess.Move],
    model: str | None,
    max_n: int,
    node_cap: int,
    time_limit_ms: int,
    candidate_limit: int,
    memoize: bool,
) -> ModeledHerdResult:
    """Beam-limited, memoized expectimax for a two-turn herding horizon."""
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

    preservation = _HerdContext(
        plan=plan,
        us=us,
        model=model,
        baseline_defender_steps=initial.defender_steps,
        maximum_king_steps=initial.our_king_steps,
        minimum_cage=3,
        budget=[0],
    )
    context = _ModeledContext(
        plan=plan,
        us=us,
        model=model,
        preservation=preservation,
        candidate_limit=max(1, candidate_limit),
        budget=[node_cap],
        deadline=time.monotonic() + time_limit_ms / 1000.0,
        memoize=memoize,
        memo={},
        reply_cache={},
    )
    history = _history_counts(board)

    def memo_key(remaining: int, our_node: bool):
        return _memo_key(board, remaining, our_node, history)

    def expected_self(remaining: int) -> tuple[float, bool]:
        """Our selective choice node: minimize modeled construction cost."""
        key = memo_key(remaining, True)
        if context.memoize and key in context.memo:
            context.cache_hits += 1
            return context.memo[key], True

        candidates, selection_complete = _ranked_plan_moves(
            board, list(board.legal_moves), context, history
        )
        if not selection_complete:
            return float("inf"), False

        best = float("inf")
        for candidate in candidates:
            if not context.spend():
                return float("inf"), False
            pushed_key = _record_push(board, candidate, history)
            cost, complete = expected_after(remaining)
            _record_pop(board, history, pushed_key)
            if not complete:
                return float("inf"), False
            best = min(best, cost)

        if context.memoize:
            context.memo[key] = best
        return best, True

    def expected_after(remaining: int) -> tuple[float, bool]:
        """Opponent chance node: average Zach's complete uniform pool."""
        key = memo_key(remaining, False)
        if context.memoize and key in context.memo:
            context.cache_hits += 1
            return context.memo[key], True

        pool, classified = _bounded_reply_pool(board, context)
        if not classified or pool is None:
            return float("inf"), False
        if not pool:
            value = -10_000.0
            if context.memoize:
                context.memo[key] = value
            return value, True

        costs: list[float] = []
        for reply in pool:
            if not context.spend():
                return float("inf"), False
            pushed_key = _record_push(board, reply, history)
            context.replies_examined += 1
            if board.is_checkmate():
                cost, complete = -10_000.0, True
            elif _draw(board):
                cost, complete = float("inf"), True
            else:
                target = plan.resolve(board, us)
                if not _preserves_plan(target, preservation):
                    cost, complete = float("inf"), True
                elif remaining > 1:
                    cost, complete = expected_self(remaining - 1)
                else:
                    cost, complete = _modeled_cost(board, target, us), True
            _record_pop(board, history, pushed_key)
            if not complete:
                return float("inf"), False
            if cost == float("inf"):
                if context.memoize:
                    context.memo[key] = cost
                return cost, True
            costs.append(cost)

        value = sum(costs) / len(costs)
        if context.memoize:
            context.memo[key] = value
        return value, True

    candidates, root_selection_complete = _ranked_plan_moves(
        board, moves, context, history
    )
    best_move = None
    best_expected = float("inf")
    root_complete = root_selection_complete
    if root_selection_complete:
        for move in candidates:
            if not context.spend():
                root_complete = False
                break
            pushed_key = _record_push(board, move, history)
            expected, complete = expected_after(max_n)
            _record_pop(board, history, pushed_key)
            if not complete:
                root_complete = False
                break
            if expected < best_expected:
                best_move = move
                best_expected = expected

    return ModeledHerdResult(
        move=best_move,
        replies=context.replies_examined,
        expected_cost=(None if best_move is None else best_expected),
        nodes=node_cap - context.budget[0],
        cache_hits=context.cache_hits,
        memo_entries=len(context.memo) + len(context.reply_cache),
        candidates_pruned=context.candidates_pruned,
        complete=root_complete,
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
    candidate_limit: int | None = None,
    memoize: bool = False,
) -> ModeledHerdResult:
    """Choose plan-safe progress using bounded Zach-policy expectimax."""
    if candidate_limit is not None:
        return _selective_modeled_herding_move(
            board,
            plan,
            us,
            moves,
            model,
            max_n,
            node_cap,
            time_limit_ms,
            candidate_limit,
            memoize,
        )

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

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
    kh_bishop_distance,
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


# Walk-phase funnel weights — structural relations, not tunables (the same
# stance as _modeled_cost): one square of pocket approach outranks all
# fence bookkeeping and an open forward lane outranks everything but the
# approach itself. Two terms this potential deliberately does NOT have:
# a menu-shrink reward (the negamax eval's instinct — it built two-square
# prisons wherever their king happened to stand, a certified-dead
# arrival) and a walls-behind reward (its fence value is exactly what
# kept electing rank-five rook posts whose corridor rake poisoned the
# arrival statics — the third battery's 0/5 audits). The sub-MDP is the
# ratchet; the wait's job is to deliver a clean board. The walk itself is
# priced as a SCHEDULE, not a chore: every push resets the fifty-move
# clock, so the walk is the herding window and the pawn must land LAST. A
# flat finish bonus taught the first battery's chooser to rush the pawn
# home in seven plies with his king still north of the walls. The
# premature term charges each push the pawn is AHEAD of his king's
# delivery (needed = min(3, distance - 1)), which by expectation makes
# the chooser dilute the push while he is far (keep his pool roomy, even
# by checking) and force it once he stands at the mouth.
_PRESSURE_DISTANCE = 10.0
_PRESSURE_DOOR = 6.0
_PRESSURE_FINISH = 4.0
_PRESSURE_PREMATURE = 25.0
_PRESSURE_CORRIDOR = 8.0
_PRESSURE_RACE = 25.0
_PRESSURE_JACKPOT = -10_000.0
# A reply that adjudicates the game is a terminal zero, not a position: it
# must outrank every geometric cost so that any live lottery beats a
# certain draw (the same standard the clock layer's relaxed release
# holds), while staying the mirror of the jackpot.
_PRESSURE_DRAW = 10_000.0


def _pressure_walk(board: chess.Board, them: chess.Color,
                   target: PawnMateTemplate) -> int:
    """Zach pushes still owed by the COMMITTED walking pawn.

    The root template's ``pawn_walk`` is stale one push later, so the leaf
    recounts it — by following the committed pawn itself (review P2: a
    first-walking-pawn-on-the-file scan reads the REAR pawn of a doubled
    pair, whose own template the path-block veto rejects at emission; the
    drill's black walkers dodged it only because ascending square order
    happens to visit the front pawn first). Between the root and a leaf
    exactly one reply has happened, so the walker sits on its root square,
    one push ahead, or two pushes ahead from the home rank; the rank
    arithmetic mirrors the walking-template emission.
    """
    step = 8 if them == chess.WHITE else -8
    pre_rank = chess.square_rank(target.arrival_square - step)
    home_rank = 1 if them == chess.WHITE else 6
    candidates = [target.pawn_square, target.pawn_square + step]
    if chess.square_rank(target.pawn_square) == home_rank:
        candidates.append(target.pawn_square + 2 * step)
    for square in candidates:
        piece = board.piece_at(square)
        if (
            piece is None
            or piece.color != them
            or piece.piece_type != chess.PAWN
        ):
            continue
        rank = chess.square_rank(square)
        walking = rank < pre_rank if them == chess.WHITE else rank > pre_rank
        if not walking:
            return 0
        return abs(pre_rank - rank) - (1 if rank == home_rank else 0)
    return 0


def walk_pressure_cost(board: chess.Board, target: PawnMateTemplate,
                       us: chess.Color) -> float:
    """Funnel potential of one walk position, lower is better.

    The case-7 arrivals told the whole story: every converting seed had
    their king delivered down the corridor into the pocket mouth (the seal
    square), while the losses were kings sealed into remote two-square
    prisons (Rf6/Rf7 around e5), caught north of accidental rook walls, or
    left free-roaming for a 173-ply walk. The potential therefore prices,
    for THEIR king: distance to the seal square; blocked squares on its
    pocketward side (doors — a fence must never form in front, and a rook
    parked on the descent corridor is exactly such a fence); the descent
    lane's integrity while he still needs it; the walk as a delivery
    schedule (pushes the pawn is ahead of his king's approach are
    premature — the pawn lands last); and any of our men squatting on the
    fixed race squares the audit will bill at arrival.
    """
    them = not us
    king = board.king(them)
    if king is None:
        return 0.0
    anchor = target.kh_seal_square
    distance = chess.square_distance(king, anchor)
    doors_blocked = 0
    for square in chess.SquareSet(chess.BB_KING_ATTACKS[king]):
        if chess.square_distance(square, anchor) >= distance:
            continue
        occupant = board.piece_at(square)
        if occupant is not None and occupant.color == them:
            # His own man: transient (the walker moves on), not a door we
            # owe him.
            continue
        if occupant is not None or board.is_attacked_by(us, square):
            doors_blocked += 1
    walk = _pressure_walk(board, them, target)
    needed = min(3, max(0, distance - 1))
    cost = (
        _PRESSURE_DISTANCE * distance
        + _PRESSURE_DOOR * doors_blocked
        + _PRESSURE_FINISH * walk
        + _PRESSURE_PREMATURE * max(0, needed - walk)
    )
    if distance > 1:
        # Corridor integrity: the descent lane above the pocket mouth (the
        # corner-file squares over the seal — case-6's h5 pocket-top and
        # h6 door, mirrored) must stay unattacked and unoccupied by us
        # until their king is delivered. The door term only sees his
        # CURRENT neighbors, but a rook fences this lane from across the
        # board (the second battery: every 0/5-unconvertible arrival had a
        # waiter on or raking a5/a6 while both converts kept the lane
        # pristine) — and with one mobile herder the frozen rook makes
        # that seal permanent in-graph. Once he stands at the mouth the
        # lane has served: the same posts are then live (the baseline's
        # Re5 with the king already on a4 audited 6/7). The charge scales
        # with how frozen the pose is: expectation mechanically rewards
        # east walls (cutting his far replies improves the average) and a
        # flat charge lost that argmin every time, but only the statics
        # the arrival actually inherits are graded by the audit — so a
        # rake is nearly free at walk three and prohibitive at walk one
        # and during the posed stall.
        step = 8 if them == chess.WHITE else -8
        freeze = 4 - min(3, walk)
        for lane in (anchor - step, anchor - 2 * step):
            if not 0 <= lane < 64:
                break
            squatter = board.piece_at(lane)
            if (squatter is not None and squatter.color == us) or (
                board.is_attacked_by(us, lane)
            ):
                cost += _PRESSURE_CORRIDOR * freeze
    if board.piece_at(target.checked_square) is not None:
        cost += _PRESSURE_RACE
    if board.piece_at(target.kh_escape_square) is not None:
        cost += _PRESSURE_RACE
    entry = board.piece_at(target.kh_entry_square)
    if entry is not None and entry.color == us:
        cost += _PRESSURE_RACE
    far = board.piece_at(target.kh_far_capture_square)
    if far is not None and far.color == us:
        cost += _PRESSURE_RACE
    for food in target.kh_rear_food_squares:
        # The far-capture rule once per stacked rear: our man there is the
        # bxc3 escape valve at the delivery zugzwang (audit-refused).
        squatter = board.piece_at(food)
        if squatter is not None and squatter.color == us:
            cost += _PRESSURE_RACE
    return cost


def walk_pressure_move(board: chess.Board, target: PawnMateTemplate,
                       us: chess.Color, moves: list[chess.Move],
                       model: str | None) -> chess.Move | None:
    """Choose the wait move with the lowest expected funnel potential.

    One ply of our choice against his complete modeled pool is the whole
    search: the wait is long (three pushes at uniform odds), the fence is
    built one rook move at a time, and every ply re-runs the gradient — a
    ratchet needs a potential, not a horizon. Checks are never special-cased
    because the expectation prices them exactly: a check empties the push
    from his pool (the walk term stalls) and usually scatters him (the
    distance term pays), so only a check that genuinely funnels survives
    the argmin. Candidates whose landing is terminal are skipped — the
    caller's guards already vetoed what matters, and never zeroing the menu
    is their contract, not ours. Ties break toward the lexically smallest
    UCI so replays are exact.
    """
    best_move: chess.Move | None = None
    best_cost = 0.0
    for move in moves:
        board.push(move)
        if board.is_checkmate() or board.is_stalemate() or _draw(board):
            board.pop()
            continue
        pool = (
            support_zach(board)
            if model == "zach"
            else list(board.legal_moves)
        )
        if not pool:
            # Every legal reply mates us: the walk just ended in our favor.
            cost = _PRESSURE_JACKPOT
        else:
            total = 0.0
            for reply in pool:
                board.push(reply)
                if board.is_checkmate():
                    total += _PRESSURE_JACKPOT
                elif _draw(board):
                    # A reply that adjudicates — or stalemates us — is a
                    # terminal zero, not a position (review P1). The funnel
                    # guard strips most such candidates upstream, but its
                    # all-trapped fallback hands them back exactly at the
                    # fifty-move cliff, where every quiet reply draws —
                    # and priced geometrically, a forcing check whose one
                    # reply draws CERTAINLY outranked waits that kept the
                    # clock-resetting push alive in the pool.
                    total += _PRESSURE_DRAW
                else:
                    total += walk_pressure_cost(board, target, us)
                board.pop()
            cost = total / len(pool)
        board.pop()
        if (
            best_move is None
            or cost < best_cost
            or (cost == best_cost and move.uci() < best_move.uci())
        ):
            best_move, best_cost = move, cost
    return best_move


# Eviction-phase funnel weights — structural relations, not tunables (the
# same stance as the walk weights above): a square of distance pried
# between their king and the corner outranks all fence bookkeeping, an
# open homeward door outranks readiness chores, and the light readiness
# terms only break ties among equally evicting waits — the SEQUENCED
# construction chores (lane, bishop-ready, lift, park) are the squat
# chore filter's commitments, not this potential's; a one-ply
# expectation cannot order a blocking DAG and was never asked to again
# after seed 0's shuffles proved it. The seal charge prices the
# sealed-box stalemate trap as the certain draw it is, so the arm never
# steers toward what the seal guard would have to refuse. Race-square
# debt is charged flat like the walk cost's. The proximity charge is
# capped at _EVICT_RADIUS because eviction's job ends at the pocket
# boundary — the arm itself disengages once the zone is clear.
_EVICT_PROX = 10.0
_EVICT_DOOR = 6.0
_EVICT_RACE = 25.0
_EVICT_KING = 3.0
_EVICT_BISHOP = 2.0
_EVICT_RADIUS = 5


def eviction_pressure_cost(board: chess.Board, target: PawnMateTemplate,
                           us: chess.Color) -> float:
    """Inverse-herding potential of one squat position, lower is better.

    IYQd0RBC told the story: a mate-avoidant human squats the
    construction zone itself, the cage and arrival placements hang to
    his king (the guard rightly vetoes them), and no existing phase
    moves him — the sub-MDP needs a posed construction, the walk arm
    needs a walking pawn, and the plain negamax shuffles. This
    potential prices, for THEIR king: closeness to the checked corner
    (the eviction gradient — checks that pry him off the corner pay
    here); his open corner-ward neighbor squares (doors home a fence
    should close — occupancy or our attack closes one); our men
    squatting the fixed race squares; and two light readiness terms so
    that among equal evictions the chooser prefers the ply that also
    walks our king toward the arrival or the cage bishop toward its
    corner. The mirror of walk_pressure_cost: same ratchet, opposite
    sign on the king.
    """
    them = not us
    king = board.king(them)
    if king is None:
        return 0.0
    corner = target.checked_square
    distance = chess.square_distance(king, corner)
    cost = _EVICT_PROX * max(0, _EVICT_RADIUS - distance)
    for square in chess.SquareSet(chess.BB_KING_ATTACKS[king]):
        if chess.square_distance(square, corner) >= distance:
            continue
        if board.piece_at(square) is None and not board.is_attacked_by(
            us, square
        ):
            cost += _EVICT_DOOR
    if board.piece_at(target.checked_square) is not None:
        cost += _EVICT_RACE
    if board.piece_at(target.kh_escape_square) is not None:
        cost += _EVICT_RACE
    entry = board.piece_at(target.kh_entry_square)
    if entry is not None and entry.color == us:
        cost += _EVICT_RACE
    far = board.piece_at(target.kh_far_capture_square)
    if far is not None and far.color == us:
        cost += _EVICT_RACE
    for food in target.kh_rear_food_squares:
        squatter = board.piece_at(food)
        if squatter is not None and squatter.color == us:
            cost += _EVICT_RACE
    our_king = board.king(us)
    if our_king is not None:
        cost += _EVICT_KING * chess.square_distance(
            our_king, target.arrival_square
        )
    cage = target.kh_cage_square
    if king in (target.checked_square, target.kh_escape_square) and (
        board.piece_at(cage) is not None
    ):
        # The sealed box (or the ply that seals it): their king inside
        # the corner pocket with the cage square occupied is the
        # stalemate trap the handoff filter's seal guard refuses — a
        # certain draw, priced like one so the arm never steers toward
        # what the filter would have to veto.
        cost += _PRESSURE_DRAW
    if not any(
        cage in board.attacks(square)
        for square in board.pieces(chess.BISHOP, us)
    ):
        # Bishop readiness is attack-based, not Chebyshev: a bishop
        # attacking the cage square lands it in one move once the square
        # is clear (attacks are same-shade by geometry, so no shade test
        # is needed), while Chebyshev pulled the bishop to same-rank
        # squares like e1 that never reach the cage at all (seed 0's
        # opening Be1). A relay squatter on the square is the
        # CAGE_SQUAT charge's business, not this term's.
        cost += _EVICT_BISHOP * min(
            8, kh_bishop_distance(board, us, target)
        )
    return cost


def eviction_pressure_move(board: chess.Board, target: PawnMateTemplate,
                           us: chess.Color, moves: list[chess.Move],
                           model: str | None) -> chess.Move | None:
    """Choose the squat-phase move with the lowest expected eviction
    potential.

    The same one-ply expectation over his complete modeled pool as
    walk_pressure_move, for the same reason: the squat is long, the
    fence is built one rake at a time, and every ply re-runs the
    gradient. Checks are priced by the expectation, not special-cased —
    a check that pries the king off the corner empties his hugging
    replies from the pool and the proximity term pays it back; a check
    that merely rearranges the squat does not survive the argmin. The
    caller's guards already vetoed the hanging rakes and the plug
    lifts; terminal landings are skipped and adjudicated replies priced
    as terminal zeros, exactly as the walk chooser does. Ties break
    toward the lexically smallest UCI so replays are exact.
    """
    best_move: chess.Move | None = None
    best_cost = 0.0
    for move in moves:
        board.push(move)
        if board.is_checkmate() or board.is_stalemate() or _draw(board):
            board.pop()
            continue
        pool = (
            support_zach(board)
            if model == "zach"
            else list(board.legal_moves)
        )
        if not pool:
            cost = _PRESSURE_JACKPOT
        else:
            total = 0.0
            for reply in pool:
                board.push(reply)
                if board.is_checkmate():
                    total += _PRESSURE_JACKPOT
                elif _draw(board):
                    total += _PRESSURE_DRAW
                else:
                    total += eviction_pressure_cost(board, target, us)
                board.pop()
            cost = total / len(pool)
        board.pop()
        if (
            best_move is None
            or cost < best_cost
            or (cost == best_cost and move.uci() < best_move.uci())
        ):
            best_move, best_cost = move, cost
    return best_move


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

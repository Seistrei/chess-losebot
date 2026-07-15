"""LoseBot: picks moves to force its own checkmate.

Per move: (1) never deliver mate or stalemate if any alternative exists,
(2) run an exact forced-selfmate probe (deeper when the opponent is reduced),
(3) otherwise fall back to heuristic misère negamax."""

import chess

from .planning import herding_move, modeled_herding_move
from .profiles import EngineProfile, get_profile, probe_limits
from .search import (
    ProofStatus,
    gives_mate,
    gives_stalemate,
    negamax,
    selfmate_status,
)
from .templates import (
    ConstructionPlan,
    PawnMateTemplate,
    best_pawn_mate_template,
)


class LoseBot:
    def __init__(self, depth: int = 2, opponent_model: str | None = None,
                 name: str = "losebot", profile: str = "current",
                 probe_cap: int | None = None,
                 max_probe_n: int | None = None):
        self.depth = depth
        self.opponent_model = opponent_model
        self.name = name
        self.profile: EngineProfile = get_profile(profile)
        self.probe_cap = probe_cap
        self.max_probe_n = max_probe_n
        self.forced_selfmates_found = 0
        self.probe_nodes = 0
        self.probe_budget_exhaustions = 0
        self.deepest_probe_completed = 0
        self.deep_probe_skips = 0
        self.plan: ConstructionPlan | None = None
        self.plans_created = 0
        self.plan_invalidations = 0
        self.best_plan_distance: int | None = None
        self.hold_moves_filtered = 0
        self.plan_regressions_filtered = 0
        self.forced_herding_choices = 0
        self.plan_repetitions_filtered = 0
        self.herd_search_nodes = 0
        self.herd_search_hits = 0
        self.herd_search_exhaustions = 0
        self.modeled_herding_hits = 0
        self.modeled_herding_replies = 0
        self.modeled_herding_nodes = 0
        self.modeled_herding_cache_hits = 0
        self.modeled_herding_memo_entries = 0
        self.modeled_herding_candidates_pruned = 0
        self.modeled_herding_incomplete = 0
        self._last_seen_ply: int | None = None

    def _update_construction_plan(self, board: chess.Board,
                                  their_pieces: int) -> None:
        if not self.profile.stateful_plan:
            return
        if their_pieces != 0:
            # A promotion or other surviving mobile piece ends the
            # king-and-pawns phase. Continuing to preserve its old cage made
            # the planner ignore the new piece while it chased our king.
            if self.plan is not None:
                self.plan_invalidations += 1
                self.plan = None
            return

        target = (
            self.plan.resolve(board, board.turn)
            if self.plan is not None
            else None
        )
        if target is None:
            replacement = best_pawn_mate_template(board, board.turn)
            if replacement is None:
                if self.plan is not None:
                    self.plan_invalidations += 1
                    self.plan = None
                return
            if self.plan is not None:
                self.plan_invalidations += 1
            self.plan = ConstructionPlan.from_template(
                replacement, len(board.move_stack)
            )
            self.plans_created += 1
            target = replacement

        distance = target.setup_distance
        if self.best_plan_distance is None:
            self.best_plan_distance = distance
        else:
            self.best_plan_distance = min(self.best_plan_distance, distance)

    def planned_target(self, board: chess.Board,
                       us: chess.Color) -> PawnMateTemplate | None:
        if self.plan is None:
            return None
        return self.plan.resolve(board, us)

    def _filter_plan_regressions(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        if current is None or not self.profile.stateful_plan:
            return moves

        us = board.turn
        # Three occupants are the construction reserve. Surplus cage pieces
        # remain free to give forcing checks and herd the reluctant king.
        minimum_cage = min(current.cage_occupancy, 3)
        stable: list[chess.Move] = []
        for move in moves:
            board.push(move)
            future = self.planned_target(board, us)
            board.pop()
            if future is None:
                continue
            if future.our_king_steps > current.our_king_steps:
                continue
            if future.cage_occupancy < minimum_cage:
                continue
            if not current.runway_blocked and future.runway_blocked:
                continue
            if (
                current.holding_blocker_defended
                and not future.holding_blocker_defended
                and not current.ready_to_release
            ):
                continue
            stable.append(move)

        if stable:
            self.plan_regressions_filtered += len(moves) - len(stable)
            return stable
        return moves

    def _filter_forced_herding(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        if (
            current is None
            or not current.holding_blocker
            or current.defender_steps <= 0
        ):
            return moves

        us = board.turn
        forcing: list[chess.Move] = []
        for move in moves:
            board.push(move)
            if not board.is_check():
                board.pop()
                continue
            replies = list(board.legal_moves)
            worst_distance = -1
            valid = bool(replies)
            for reply in replies:
                board.push(reply)
                future = self.planned_target(board, us)
                board.pop()
                if future is None:
                    valid = False
                    break
                worst_distance = max(worst_distance, future.defender_steps)
            board.pop()
            if valid and worst_distance < current.defender_steps:
                forcing.append(move)

        if forcing:
            self.forced_herding_choices += 1
            return forcing
        return moves

    def _filter_plan_repetitions(
        self,
        board: chess.Board,
        moves: list[chess.Move],
    ) -> list[chess.Move]:
        if not self.profile.stateful_plan:
            return moves
        fresh: list[chess.Move] = []
        for move in moves:
            board.push(move)
            repeats = board.is_repetition(2)
            board.pop()
            if not repeats:
                fresh.append(move)
        if fresh:
            self.plan_repetitions_filtered += len(moves) - len(fresh)
            return fresh
        return moves

    def choose_move(self, board: chess.Board) -> chess.Move:
        ply = len(board.move_stack)
        if self._last_seen_ply is not None and ply < self._last_seen_ply:
            self.plan = None
            self.best_plan_distance = None
        self._last_seen_ply = ply

        legal = list(board.legal_moves)
        if len(legal) == 1:
            return legal[0]

        # Never mate or stalemate the opponent when we have any alternative.
        safe = [m for m in legal if not gives_mate(board, m)]
        non_stale = [m for m in safe if not gives_stalemate(board, m)]
        safe = non_stale or safe or legal

        # Exact probe, deeper as the opponent runs out of mobile pieces.
        them = not board.turn
        their_pieces = sum(
            1
            for p in board.piece_map().values()
            if p.color == them and p.piece_type not in (chess.PAWN, chess.KING)
        )
        self._update_construction_plan(board, their_pieces)
        planned_now = self.planned_target(board, board.turn)
        if (
            planned_now is not None
            and planned_now.holding_blocker
            and not planned_now.ready_to_release
        ):
            held = planned_now.arrival_square
            keep_holding = [m for m in safe if m.from_square != held]
            if keep_holding:
                self.hold_moves_filtered += len(safe) - len(keep_holding)
                safe = keep_holding
        safe = self._filter_plan_regressions(board, safe, planned_now)
        safe = self._filter_plan_repetitions(board, safe)
        safe = self._filter_forced_herding(board, safe, planned_now)
        if board.is_check():
            their_mobility = 99
        else:
            board.push(chess.Move.null())
            their_mobility = board.legal_moves.count()
            board.pop()

        # Budgets are per-move worst cases; deep probes proved to be wasted
        # effort when no net exists, so keep them tight (~1-2s at PyPy speed).
        max_n, cap = probe_limits(
            self.profile, their_pieces, their_mobility
        )
        if self.probe_cap is not None:
            cap = min(cap, self.probe_cap)
        if self.max_probe_n is not None:
            max_n = min(max_n, self.max_probe_n)
        gate_distance = self.profile.deep_probe_template_distance
        if max_n > 1 and gate_distance is not None:
            target = (
                planned_now
                if self.profile.stateful_plan
                else best_pawn_mate_template(board, board.turn)
            )
            if (
                target is None
                or target.setup_distance > gate_distance
                or target.cage_occupancy < self.profile.deep_probe_min_cage
                or target.arrival_blocked
            ):
                max_n = 1
                self.deep_probe_skips += 1

        budget = [cap]
        memo: dict = {}
        for n in range(1, max_n + 1):
            before = budget[0]
            status, mv = selfmate_status(
                board, n, self.opponent_model, budget, memo
            )
            self.probe_nodes += before - budget[0]
            if status is ProofStatus.PROVEN:
                self.forced_selfmates_found += 1
                return mv
            if status is ProofStatus.UNKNOWN:
                self.probe_budget_exhaustions += 1
                break
            self.deepest_probe_completed = max(self.deepest_probe_completed, n)

        if (
            self.plan is not None
            and self.profile.herd_search_depth > 0
            and self.profile.herd_search_cap > 0
        ):
            herd = herding_move(
                board,
                self.plan,
                board.turn,
                self.profile.herd_search_depth,
                self.opponent_model,
                self.profile.herd_search_cap,
            )
            self.herd_search_nodes += herd.nodes
            if herd.status is ProofStatus.PROVEN and herd.move is not None:
                self.herd_search_hits += 1
                return herd.move
            if herd.status is ProofStatus.UNKNOWN:
                self.herd_search_exhaustions += 1

        if (
            self.plan is not None
            and self.profile.modeled_herding_depth > 0
            and self.profile.modeled_herding_cap > 0
        ):
            modeled = modeled_herding_move(
                board,
                self.plan,
                board.turn,
                safe,
                self.opponent_model,
                self.profile.modeled_herding_depth,
                self.profile.modeled_herding_cap,
                self.profile.modeled_herding_time_ms,
                self.profile.modeled_herding_candidate_limit,
                self.profile.modeled_herding_memoize,
            )
            self.modeled_herding_replies += modeled.replies
            self.modeled_herding_nodes += modeled.nodes
            self.modeled_herding_cache_hits += modeled.cache_hits
            self.modeled_herding_memo_entries += modeled.memo_entries
            self.modeled_herding_candidates_pruned += (
                modeled.candidates_pruned
            )
            if not modeled.complete:
                self.modeled_herding_incomplete += 1
            if modeled.move is not None:
                self.modeled_herding_hits += 1
                return modeled.move

        # Heuristic misère search over the safe moves; look deeper once the
        # squeeze is on and precision starts to matter.
        depth = self.depth + (
            1 if their_mobility <= self.profile.squeeze_mobility else 0
        )
        if (
            self.profile.small_endgame_max_men is not None
            and len(board.piece_map()) <= self.profile.small_endgame_max_men
        ):
            depth += 1  # tiny endgames are where domination valleys live
        root_color = board.turn
        clock_urgent = board.halfmove_clock >= self.profile.clock_urgent_at
        best_move, best_value = safe[0], -float("inf")
        alpha, beta = -float("inf"), float("inf")
        for m in safe:
            # Root nudges against the two draw engines: repeating positions
            # and letting the 50-move clock run dry.
            bonus = 0.0
            board.push(m)
            if board.is_repetition(2):
                bonus -= self.profile.repetition_penalty
            board.pop()
            if clock_urgent and (
                board.is_capture(m)
                or board.piece_type_at(m.from_square) == chess.PAWN
            ):
                bonus += self.profile.irreversible_move_bonus
            board.push(m)
            v = bonus - negamax(board, depth - 1, -beta, -alpha, root_color, 1,
                                self.opponent_model, self.profile, self.plan)
            board.pop()
            if v > best_value:
                best_value, best_move = v, m
            if v > alpha:
                alpha = v
        return best_move

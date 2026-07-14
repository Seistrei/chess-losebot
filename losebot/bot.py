"""LoseBot: picks moves to force its own checkmate.

Per move: (1) never deliver mate or stalemate if any alternative exists,
(2) run an exact forced-selfmate probe (deeper when the opponent is reduced),
(3) otherwise fall back to heuristic misère negamax."""

import chess

from .profiles import EngineProfile, get_profile, probe_limits
from .search import (
    ProofStatus,
    gives_mate,
    gives_stalemate,
    negamax,
    selfmate_status,
)
from .templates import best_pawn_mate_template


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

    def choose_move(self, board: chess.Board) -> chess.Move:
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
            target = best_pawn_mate_template(board, board.turn)
            if (
                target is None
                or target.setup_distance > gate_distance
                or target.cage_occupancy < self.profile.deep_probe_min_cage
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
                                self.opponent_model, self.profile)
            board.pop()
            if v > best_value:
                best_value, best_move = v, m
            if v > alpha:
                alpha = v
        return best_move

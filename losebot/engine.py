"""The engine: oracle first, expectimax second, misère-safe always.

Two-layer decision per move:

1. ORACLE (opponent-free): probe for a forced-selfmate certificate,
   iterative n = 1..probe_n under one shared node budget. A PROVEN move
   is played unconditionally — it wins against any policy.
2. STEERING (opponent-aware): expectimax against the engine's BELIEF
   model of the opponent, over the misère-safe root partition.

The safety partition is the old bridge fallback grown up: moves that
immediately mate them, stalemate them, or adjudicate a draw are
excluded whenever any alternative exists. The search prices those
outcomes too, but the partition makes "never blunder the objective in
one ply" structural instead of numeric.

The two layers meet below the root: steering's our-nodes carry a
budgeted SUB-PROBE (same oracle, smaller n, own cap) gated to stripped
positions — opponent down to a few men, where nets are near and probes
are cheap. The root oracle answers "is the finish forced NOW"; the
sub-probe lets steering see finishes forming up to depth + sub_probe_n
own-moves out, weighted by the model's chance of allowing them. One
memo serves both: its keys carry position, clock, repetition state and
n, so certificates proven anywhere in the move's thinking transfer.
"""

from __future__ import annotations

import chess

from . import oracle
from .models.base import OpponentModel
from .outcomes import adjudicate_draw
from .search import best_move


class ModelEngine:
    def __init__(
        self,
        belief: OpponentModel,
        depth: int = 3,
        topk: int = 6,
        coverage: float = 0.85,
        probe_n: int = 4,
        probe_cap: int = 50_000,
        sub_probe_n: int = 2,
        sub_probe_cap: int = 30_000,
        sub_probe_slice: int = 8_000,
        sub_probe_men: int = 5,
        draw_contempt: float = 400.0,
    ):
        self.belief = belief
        self.depth = depth
        self.topk = topk
        self.coverage = coverage
        self.probe_n = probe_n
        self.probe_cap = probe_cap
        self.sub_probe_n = sub_probe_n
        self.sub_probe_cap = sub_probe_cap
        self.sub_probe_slice = sub_probe_slice
        self.sub_probe_men = sub_probe_men
        self.draw_contempt = draw_contempt
        self.name = f"losebot({belief.name})"
        # Gauges.
        self.moves_played = 0
        self.oracle_moves = 0
        self.forced_selfmates_found = 0
        self.probe_nodes = 0
        self.probe_budget_exhaustions = 0
        self.search_nodes = 0
        self.sub_probe_calls = 0
        self.sub_probe_hits = 0
        self.sub_probe_nodes = 0
        self.sub_probe_exhaustions = 0

    def choose_move(self, board: chess.Board) -> chess.Move:
        legal = list(board.legal_moves)
        if not legal:
            raise ValueError("no legal moves")
        self.moves_played += 1
        if len(legal) == 1:
            return legal[0]

        memo: dict = {}
        proven = self._probe(board, memo)
        if proven is not None:
            self.oracle_moves += 1
            return proven

        pool = self._safe_pool(board, legal)
        move, _value, stats = best_move(
            board,
            us=board.turn,
            model=self.belief,
            depth=self.depth,
            topk=self.topk,
            coverage=self.coverage,
            draw_contempt=self.draw_contempt,
            root_moves=pool,
            probe=self._make_sub_probe(board.turn, memo),
        )
        self.search_nodes += stats.nodes
        return move if move is not None else pool[0]

    def _probe(self, board: chess.Board, memo: dict) -> chess.Move | None:
        """Iterative-deepening oracle probe under one shared budget."""
        budget = [self.probe_cap]
        found: chess.Move | None = None
        for n in range(1, self.probe_n + 1):
            status, move = oracle.selfmate_status(board, n, budget, memo)
            if status is oracle.ProofStatus.PROVEN:
                found = move
                break
            if budget[0] <= 0:
                self.probe_budget_exhaustions += 1
                break
        self.probe_nodes += self.probe_cap - budget[0]
        if found is not None:
            self.forced_selfmates_found += 1
        return found

    def _make_sub_probe(self, us: chess.Color, memo: dict):
        """Sub-root probe hook for the search, or None when disabled.

        One budget for the whole move's steering, sliced per call so a
        single barren node cannot eat it. Two gates, either opens:
        material — the opponent stripped to ``sub_probe_men`` non-king
        men, where zugzwang nets live and probes are cheap; or OUR KING
        IN CHECK — the forced-recapture devices (both of the project's
        organic conversions) run through check chains at any material,
        and in-check nodes are rare enough in the tree to probe freely.
        The root probe's memo is reused; its keys are complete
        (position, clock, repetition state, n, side), so sharing is
        exact.
        """
        if self.sub_probe_n <= 0 or self.sub_probe_cap <= 0:
            return None
        them = not us
        remaining = [self.sub_probe_cap]

        def probe(board: chess.Board) -> int | None:
            if remaining[0] <= 0:
                return None
            if (chess.popcount(board.occupied_co[them]) - 1
                    > self.sub_probe_men and not board.is_check()):
                return None
            self.sub_probe_calls += 1
            slice_budget = [min(remaining[0], self.sub_probe_slice)]
            granted = slice_budget[0]
            found_n = None
            for n in range(1, self.sub_probe_n + 1):
                status, _move = oracle.selfmate_status(
                    board, n, slice_budget, memo
                )
                if status is oracle.ProofStatus.PROVEN:
                    found_n = n
                    break
                if slice_budget[0] <= 0:
                    break
            spent = granted - slice_budget[0]
            remaining[0] -= spent
            self.sub_probe_nodes += spent
            if remaining[0] <= 0:
                self.sub_probe_exhaustions += 1
            if found_n is not None:
                self.sub_probe_hits += 1
            return found_n

        return probe

    def _safe_pool(self, board: chess.Board,
                   legal: list[chess.Move]) -> list[chess.Move]:
        """Moves that do not end the game against us on the spot.

        Baring their king counts: a mate-less opponent is the dead draw
        the eval calls worst, and the 2026-07-21 dev league watched the
        engine strip to it and then burn a bishop just to reset the
        draw clock over the corpse. Same partition rank as the one-ply
        stalemate — structural, not priced.
        """
        clean = []
        them = not board.turn
        for move in legal:
            board.push(move)
            accident = (
                board.is_checkmate()          # we mated them
                or board.is_stalemate()       # we suffocated them
                or adjudicate_draw(board) is not None
                or chess.popcount(board.occupied_co[them]) == 1  # bared them
            )
            board.pop()
            if not accident:
                clean.append(move)
        return clean or legal

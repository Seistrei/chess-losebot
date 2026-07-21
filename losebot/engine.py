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
        probe_n: int = 3,
        probe_cap: int = 40_000,
        draw_contempt: float = 400.0,
    ):
        self.belief = belief
        self.depth = depth
        self.topk = topk
        self.coverage = coverage
        self.probe_n = probe_n
        self.probe_cap = probe_cap
        self.draw_contempt = draw_contempt
        self.name = f"losebot({belief.name})"
        # Gauges.
        self.moves_played = 0
        self.oracle_moves = 0
        self.forced_selfmates_found = 0
        self.probe_nodes = 0
        self.probe_budget_exhaustions = 0
        self.search_nodes = 0

    def choose_move(self, board: chess.Board) -> chess.Move:
        legal = list(board.legal_moves)
        if not legal:
            raise ValueError("no legal moves")
        self.moves_played += 1
        if len(legal) == 1:
            return legal[0]

        proven = self._probe(board)
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
        )
        self.search_nodes += stats.nodes
        return move if move is not None else pool[0]

    def _probe(self, board: chess.Board) -> chess.Move | None:
        """Iterative-deepening oracle probe under one shared budget."""
        budget = [self.probe_cap]
        memo: dict = {}
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

    def _safe_pool(self, board: chess.Board,
                   legal: list[chess.Move]) -> list[chess.Move]:
        """Moves that do not end the game against us on the spot."""
        clean = []
        for move in legal:
            board.push(move)
            accident = (
                board.is_checkmate()          # we mated them
                or board.is_stalemate()       # we suffocated them
                or adjudicate_draw(board) is not None
            )
            board.pop()
            if not accident:
                clean.append(move)
        return clean or legal

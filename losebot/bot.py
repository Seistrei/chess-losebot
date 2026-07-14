"""LoseBot: picks moves to force its own checkmate.

Per move: (1) never deliver mate or stalemate if any alternative exists,
(2) run an exact forced-selfmate probe (deeper when the opponent is reduced),
(3) otherwise fall back to heuristic misère negamax."""

import chess

from .search import gives_mate, gives_stalemate, negamax, selfmate_in


class LoseBot:
    def __init__(self, depth: int = 2, opponent_model: str | None = None,
                 name: str = "losebot"):
        self.depth = depth
        self.opponent_model = opponent_model
        self.name = name
        self.forced_selfmates_found = 0

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
        if their_pieces == 0 and their_mobility <= 4:
            max_n, cap = 7, 500_000
        elif their_pieces == 0 and their_mobility <= 8:
            max_n, cap = 5, 250_000
        elif their_pieces == 0:
            max_n, cap = 4, 150_000
        elif their_pieces <= 1 and their_mobility <= 12:
            max_n, cap = 3, 120_000
        elif their_pieces <= 1:
            max_n, cap = 2, 60_000
        else:
            max_n, cap = 1, 25_000

        budget = [cap]
        memo: dict = {}
        for n in range(1, max_n + 1):
            mv = selfmate_in(board, n, self.opponent_model, budget, memo)
            if mv is not None:
                self.forced_selfmates_found += 1
                return mv

        # Heuristic misère search over the safe moves; look deeper once the
        # squeeze is on and precision starts to matter.
        depth = self.depth + (1 if their_mobility <= 8 else 0)
        if len(board.piece_map()) <= 9:
            depth += 1  # tiny endgames are where domination valleys live
        root_color = board.turn
        clock_urgent = board.halfmove_clock >= 60
        best_move, best_value = safe[0], -float("inf")
        alpha, beta = -float("inf"), float("inf")
        for m in safe:
            # Root nudges against the two draw engines: repeating positions
            # and letting the 50-move clock run dry.
            bonus = 0.0
            board.push(m)
            if board.is_repetition(2):
                bonus -= 80.0
            board.pop()
            if clock_urgent and (
                board.is_capture(m)
                or board.piece_type_at(m.from_square) == chess.PAWN
            ):
                bonus += 40.0
            board.push(m)
            v = bonus - negamax(board, depth - 1, -beta, -alpha, root_color, 1,
                                self.opponent_model)
            board.pop()
            if v > best_value:
                best_value, best_move = v, m
            if v > alpha:
                alpha = v
        return best_move

"""Sparring partners: clones of the bots LoseBot is built to out-lose."""

import random

import chess
import chess.engine

from .search import support_zach


class ZachBot:
    """Chess.com-Zach-like: shuffles aimlessly, never captures, and never
    delivers checkmate unless it is the only legal option."""

    def __init__(self, seed: int = 0, name: str = "zach"):
        self.rng = random.Random(seed)
        self.name = name

    def choose_move(self, board: chess.Board) -> chess.Move:
        pool = support_zach(board)
        if not pool:
            pool = list(board.legal_moves)  # zugzwang: forced to mate
        return self.rng.choice(pool)


class CornerSquatBot:
    """The anti-losebot corner shuffle as a kernel (IYQd0RBC's human).

    Mate-avoidant and capture-averse like Zach (same support pool), but
    where Zach shuffles uniformly, this one hugs a home corner: among
    the pool's king moves it plays only those landing nearest the
    corner, and it touches a pawn only when the pool offers nothing
    else — the executioner is its hostage, not its weapon. The 48-move
    h6-h7 squat, deterministic enough to drill against: eviction must
    pry it out by force, and readmission is free because walking back
    into the pocket is exactly its policy — the zugzwang's defense post
    is the square it wants anyway.
    """

    def __init__(self, corner: chess.Square, seed: int = 0,
                 name: str = "squat"):
        self.corner = corner
        self.rng = random.Random(seed)
        self.name = name

    def choose_move(self, board: chess.Board) -> chess.Move:
        pool = support_zach(board)
        if not pool:
            return self.rng.choice(list(board.legal_moves))  # forced mate
        king_moves = [
            move for move in pool
            if board.piece_type_at(move.from_square) == chess.KING
        ]
        if king_moves:
            best = min(
                chess.square_distance(move.to_square, self.corner)
                for move in king_moves
            )
            pool = [
                move for move in king_moves
                if chess.square_distance(move.to_square, self.corner)
                == best
            ]
        return self.rng.choice(pool)


class RandomBot:
    def __init__(self, seed: int = 0, name: str = "random"):
        self.rng = random.Random(seed)
        self.name = name

    def choose_move(self, board: chess.Board) -> chess.Move:
        return self.rng.choice(list(board.legal_moves))


class WorstfishBot:
    """The Worstfish construction: evaluate every legal move with Stockfish
    and play the one with the worst score for the mover."""

    def __init__(self, engine_path: str = "/usr/games/stockfish",
                 nodes: int = 4000, name: str = "worstfish"):
        self.engine = chess.engine.SimpleEngine.popen_uci(engine_path)
        self.limit = chess.engine.Limit(nodes=nodes)
        self.name = name

    def choose_move(self, board: chess.Board) -> chess.Move:
        mover = board.turn
        worst_score, worst_move = None, None
        for m in board.legal_moves:
            board.push(m)
            if board.is_checkmate():
                s = 100_000  # we mated them: best for mover, so worst-pick avoids it
            elif board.is_stalemate() or board.is_insufficient_material():
                s = 0
            else:
                info = self.engine.analyse(board, self.limit)
                s = info["score"].pov(mover).score(mate_score=100_000)
            board.pop()
            if worst_score is None or s < worst_score:
                worst_score, worst_move = s, m
        return worst_move

    def close(self):
        self.engine.quit()

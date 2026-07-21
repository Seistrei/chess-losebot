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
        else:
            held = [
                move for move in pool
                if board.piece_type_at(move.from_square) != chess.PAWN
            ]
            if held:
                pool = held  # the hostage waits: quiet piece moves first
        return self.rng.choice(pool)


_SLOPPY_VALS = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}


class SloppyBot:
    """The sloppy human as a kernel (the lichess field games' opponent).

    Zach's one sacred rule survives — never deliver mate unless it is
    the only legal move — because the live humans held it for hundreds
    of plies, and the mercy mate that ended cG0S5wSF is deliberately
    NOT modeled: the corpus clause wants mates landed by force, and a
    kernel that eventually cooperates would grade our zugzwangs on a
    curve. Everything else Zach forbids, this one does, because the
    humans did:

    - GREED (YBZEWDGj took every gift; R9tSLBLK ate the donated rook
      and bishop by move 48): with probability `greed`, when captures
      exist, take the biggest victim — free victims first, a DEFENDED
      victim only on a `trade` roll (the willing rook-for-knight
      34.Rxa7 that killed our last closer).
    - PROMOTION DRIVE (three promotions in YBZEWDGj, the a/b train in
      IYQd0RBC): queen on sight with probability `promote`, otherwise
      push the most advanced pawn on a `push` roll.
    - CHECKS (69...h3+ squatted the entry square forever; 56.Qxf6+
      stripped a rook's pawn shield): any checking move on a `check`
      roll.
    - THE HUNT (YBZEWDGj 103-115: the king marched d2 to e5 to eat a
      parked bishop): on a `hunt` roll, step the king strictly toward
      the nearest of our men.

    Priority is promote > greed > check > push > hunt > uniform
    shuffle, each layer rolled independently per move from the seeded
    RNG — one seed is one reproducible human. A layer that rolls but
    finds no legal expression falls through. This kernel is both the
    arena's capturing opponent and the candidate opponent model for
    the strip/midgame search: model=zach explores no capturing reply
    at any depth, which is how one fork beat 497 vetoes in YBZEWDGj.
    """

    def __init__(self, seed: int = 0, name: str = "sloppy",
                 greed: float = 0.85, trade: float = 0.35,
                 check: float = 0.25, push: float = 0.5,
                 hunt: float = 0.5, promote: float = 0.95):
        self.rng = random.Random(seed)
        self.name = name
        self.greed = greed
        self.trade = trade
        self.check = check
        self.push = push
        self.hunt = hunt
        self.promote = promote

    def choose_move(self, board: chess.Board) -> chess.Move:
        legal = list(board.legal_moves)
        pool = []
        for move in legal:
            board.push(move)
            mates = board.is_checkmate()
            board.pop()
            if not mates:
                pool.append(move)
        if not pool:
            return self.rng.choice(legal)  # zugzwang: forced to mate
        us = board.turn

        promos = [m for m in pool if m.promotion == chess.QUEEN]
        if promos and self.rng.random() < self.promote:
            return self.rng.choice(promos)

        if self.rng.random() < self.greed:
            captures = [m for m in pool if board.is_capture(m)]
            if captures:
                def victim(move: chess.Move) -> int:
                    if board.is_en_passant(move):
                        return _SLOPPY_VALS[chess.PAWN]
                    return _SLOPPY_VALS[board.piece_type_at(move.to_square)]
                free = [
                    m for m in captures
                    if not board.attackers(not us, m.to_square)
                ]
                pick = free or (
                    captures if self.rng.random() < self.trade else []
                )
                if pick:
                    best = max(victim(m) for m in pick)
                    return self.rng.choice(
                        [m for m in pick if victim(m) == best]
                    )

        if self.rng.random() < self.check:
            checks = [m for m in pool if board.gives_check(m)]
            if checks:
                return self.rng.choice(checks)

        if self.rng.random() < self.push:
            pushes = [
                m for m in pool
                if board.piece_type_at(m.from_square) == chess.PAWN
                and not board.is_capture(m)
            ]
            if pushes:
                def progress(move: chess.Move) -> int:
                    rank = chess.square_rank(move.to_square)
                    return rank if us == chess.WHITE else 7 - rank
                far = max(progress(m) for m in pushes)
                return self.rng.choice(
                    [m for m in pushes if progress(m) == far]
                )

        if self.rng.random() < self.hunt:
            targets = [
                sq for sq, piece in board.piece_map().items()
                if piece.color != us and piece.piece_type != chess.KING
            ]
            steps = [
                m for m in pool
                if board.piece_type_at(m.from_square) == chess.KING
            ]
            if targets and steps:
                here = min(
                    chess.square_distance(board.king(us), t)
                    for t in targets
                )
                closing = [
                    m for m in steps
                    if min(
                        chess.square_distance(m.to_square, t)
                        for t in targets
                    ) < here
                ]
                if closing:
                    return self.rng.choice(closing)

        # Aimless between urges: the shuffle is Zach's capture-averse
        # support pool, so a fully zeroed SloppyBot decays to a Zach.
        quiet = support_zach(board)
        if quiet:
            return self.rng.choice(quiet)
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

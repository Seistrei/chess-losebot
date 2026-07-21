"""The opponent-model contract.

A model is a *policy distribution*, not just a move picker: the search
layer takes expectations over ``distribution``, the league samples from
it. Keeping both behind one object is the pivot's core mechanism — a
new observed opponent behavior updates parameters (or a fit), never a
new hand-written doctrine.
"""

from __future__ import annotations

import random

import chess


class OpponentModel:
    """Base class: subclasses implement ``distribution``.

    ``distribution`` returns ``[(move, probability), ...]`` over legal
    moves, summing to 1, omitting zero-probability moves. It must be a
    pure function of the position (no internal state), so that search
    nodes and league sampling agree about what the opponent is.
    """

    name = "model"

    def distribution(
        self, board: chess.Board
    ) -> list[tuple[chess.Move, float]]:
        raise NotImplementedError

    def sample(self, board: chess.Board, rng: random.Random) -> chess.Move:
        dist = self.distribution(board)
        if not dist:
            raise ValueError("no legal moves to sample")
        roll = rng.random()
        acc = 0.0
        for move, prob in dist:
            acc += prob
            if roll < acc:
                return move
        return dist[-1][0]  # float-drift fallback


class ModelPlayer:
    """A model wired to a seeded RNG: something a game loop can drive.

    One player = one game's opponent. League runs construct a FRESH
    player per game (the old arena reused one RNG stream across a
    match, so any engine change cascaded noise into every later game —
    that caveat is retired here by construction).
    """

    def __init__(self, model: OpponentModel, seed: int = 0):
        self.model = model
        self.name = model.name
        self.rng = random.Random(seed)

    def choose_move(self, board: chess.Board) -> chess.Move:
        return self.model.sample(board, self.rng)

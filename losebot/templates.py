"""Target templates for constructing king-and-pawn selfmates.

The heuristic used to move our king toward one pawn and their king toward
possibly another. A template couples both kings to one concrete mating pawn
push, giving the planner a coherent position to build toward.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess


@dataclass(frozen=True)
class PawnMateTemplate:
    pawn_square: chess.Square
    arrival_square: chess.Square
    checked_square: chess.Square
    our_king_steps: int
    defender_steps: int
    cage_occupancy: int
    arrival_blocked: bool

    @property
    def setup_distance(self) -> int:
        """Optimistic number of king-placement steps still required."""
        return (
            self.our_king_steps
            + self.defender_steps
            + (2 if self.arrival_blocked else 0)
        )

    @property
    def uci(self) -> str:
        return chess.square_name(self.pawn_square) + chess.square_name(
            self.arrival_square
        )


def pawn_mate_templates(board: chess.Board,
                        us: chess.Color) -> list[PawnMateTemplate]:
    """Enumerate geometric selfmate targets using an opponent pawn push.

    These are planning targets, not claims that the resulting position is mate.
    The exact probe remains responsible for verifying checks, captures, escape
    squares, pins, and the opponent's complete reply pool.
    """
    them = not us
    our_king = board.king(us)
    their_king = board.king(them)
    if our_king is None or their_king is None:
        return []

    step = 8 if them == chess.WHITE else -8
    templates: list[PawnMateTemplate] = []
    for pawn_square in board.pieces(chess.PAWN, them):
        arrival = pawn_square + step
        if not 0 <= arrival < 64:
            continue
        blocked = board.piece_at(arrival) is not None
        attacks = chess.SquareSet(chess.BB_PAWN_ATTACKS[them][arrival])
        for checked_square in attacks:
            cage = 0
            for neighbor in chess.SquareSet(
                chess.BB_KING_ATTACKS[checked_square]
            ):
                piece = board.piece_at(neighbor)
                if (
                    piece is not None
                    and piece.color == us
                    and piece.piece_type != chess.KING
                ):
                    cage += 1
            templates.append(
                PawnMateTemplate(
                    pawn_square=pawn_square,
                    arrival_square=arrival,
                    checked_square=checked_square,
                    our_king_steps=chess.square_distance(
                        our_king, checked_square
                    ),
                    defender_steps=max(
                        0,
                        chess.square_distance(their_king, arrival) - 1,
                    ),
                    cage_occupancy=cage,
                    arrival_blocked=blocked,
                )
            )
    return templates


def best_pawn_mate_template(board: chess.Board,
                            us: chess.Color) -> PawnMateTemplate | None:
    templates = pawn_mate_templates(board, us)
    if not templates:
        return None
    return min(
        templates,
        key=lambda target: (
            target.setup_distance,
            -target.cage_occupancy,
            target.pawn_square,
            target.checked_square,
        ),
    )

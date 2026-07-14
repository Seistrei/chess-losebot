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
    runway_blocked: bool
    holding_blocker: bool
    holding_blocker_defended: bool

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

    @property
    def checked_side(self) -> int:
        """File offset (-1 or +1) of the checked king from the pawn."""
        return (
            chess.square_file(self.checked_square)
            - chess.square_file(self.arrival_square)
        )

    @property
    def ready_to_release(self) -> bool:
        # The holding blocker occupies a cage square itself. Require one extra
        # occupant so releasing it leaves a three-piece cage for the probe.
        required_cage = 4 if self.holding_blocker else 3
        return (
            self.our_king_steps == 0
            and self.defender_steps == 0
            and self.cage_occupancy >= required_cage
        )


@dataclass(frozen=True)
class ConstructionPlan:
    """A persistent commitment to one execution pawn and checking side."""

    pawn_file: int
    checked_side: int
    created_ply: int

    @classmethod
    def from_template(cls, target: PawnMateTemplate,
                      created_ply: int) -> "ConstructionPlan":
        return cls(
            pawn_file=chess.square_file(target.pawn_square),
            checked_side=target.checked_side,
            created_ply=created_ply,
        )

    def resolve(self, board: chess.Board,
                us: chess.Color) -> PawnMateTemplate | None:
        candidates = [
            target
            for target in pawn_mate_templates(board, us)
            if chess.square_file(target.pawn_square) == self.pawn_file
            and target.checked_side == self.checked_side
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda target: (
                target.setup_distance,
                -target.cage_occupancy,
                target.pawn_square,
            ),
        )

    @property
    def label(self) -> str:
        side = "left" if self.checked_side < 0 else "right"
        return f"{chess.FILE_NAMES[self.pawn_file]}-pawn/{side}"


@dataclass(frozen=True)
class HerdingMetrics:
    open_outward: int
    controlled_outward: int
    open_total: int


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
        next_arrival = arrival + step
        runway_piece = (
            board.piece_at(next_arrival)
            if 0 <= next_arrival < 64
            else None
        )
        runway_blocked = (
            runway_piece is not None and runway_piece.color == us
        )
        blocker = board.piece_at(arrival)
        holding_blocker = (
            blocker is not None
            and blocker.color == us
            and blocker.piece_type not in (chess.PAWN, chess.KING)
        )
        holding_blocker_defended = (
            holding_blocker and board.is_attacked_by(us, arrival)
        )
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
                    runway_blocked=runway_blocked,
                    holding_blocker=holding_blocker,
                    holding_blocker_defended=holding_blocker_defended,
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


def herding_metrics(board: chess.Board, us: chess.Color,
                    target: PawnMateTemplate) -> HerdingMetrics:
    """Measure whether our pieces fence their king toward the target pawn.

    An outward square is any neighboring square that does not bring their king
    closer to defending the pawn's arrival square. Controlled outward squares
    are useful fence segments; open ones are escape routes the planner should
    close. This is geometric guidance only—the exact search validates legality.
    """
    them = not us
    king = board.king(them)
    if king is None:
        return HerdingMetrics(0, 0, 0)

    current_distance = chess.square_distance(king, target.arrival_square)
    open_outward = 0
    controlled_outward = 0
    open_total = 0
    for square in chess.SquareSet(chess.BB_KING_ATTACKS[king]):
        occupant = board.piece_at(square)
        if occupant is not None and occupant.color == them:
            continue
        controlled = board.is_attacked_by(us, square)
        if not controlled:
            open_total += 1
        if chess.square_distance(square, target.arrival_square) >= current_distance:
            if controlled:
                controlled_outward += 1
            else:
                open_outward += 1
    return HerdingMetrics(open_outward, controlled_outward, open_total)

"""Target templates for constructing king-and-pawn selfmates.

The heuristic used to move our king toward one pawn and their king toward
possibly another. A template couples both kings to one concrete mating pawn
push, giving the planner a coherent position to build toward.

Two holder modes exist:

- PIECE holder (the original): one of our pieces freezes the mating pawn
  from its arrival square while our king parks on the checked square. The
  release theorem (tuning log, 2026-07-15) proved this mode unconvertible —
  every holder retreat re-attacks the arrival square and refutes the mate.
- KING holder (the corner motif, adjudicated positive 2026-07-16): our KING
  is the arrival holder and the checked square is the adjacent CORNER. The
  corner's rank-side escape holds our own bishop (the one piece type that
  neither re-attacks the arrival square nor covers the defender's entry),
  its file-side escape stays empty and is covered by the entering defender,
  and the release is the king stepping aside into the corner — a race the
  conversion audit prices at 1/2 per attempt. The mate itself needs a
  knight-class closer: the sealing move must not give check (a rook check
  there mates THEIR king, a misère loss), so a knight must exist in the
  construction. The king takes the arrival square LAST — pre-park
  construction can still reset the fifty-move clock, post-park play is all
  reversible — so the march is gated on the cage being built.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess


def _same_shade(a: chess.Square, b: chess.Square) -> bool:
    light = chess.BB_LIGHT_SQUARES
    return bool(chess.BB_SQUARES[a] & light) == bool(
        chess.BB_SQUARES[b] & light
    )


def _kh_squares(arrival: chess.Square, checked: chess.Square) -> tuple:
    """(cage, escape, entry, seal, far-capture) squares of a corner
    king-holder template — all fixed by the arrival/checked pair.

    cage: the corner's rank-side escape; must hold our bishop.
    escape: the corner's file-side escape; must stay empty (it is also a
        pawn-capture square) and is covered by the entering defender.
    entry: where the defender stands at mate time — adjacent to the arrival
        square (it must defend the mating pawn), covering the file escape,
        not adjacent to the checked square (kings may not touch).
    seal: the retreat behind the entry square the knight closer covers.
    far capture: the mating pawn's other capture square; any of our pieces
        parked there is pawn food that opens the freeze.
    """
    a_file, a_rank = chess.square_file(arrival), chess.square_rank(arrival)
    c_file, c_rank = chess.square_file(checked), chess.square_rank(checked)
    rank_step = c_rank - a_rank  # their pawn's push direction, in ranks
    return (
        chess.square(a_file, c_rank),
        chess.square(c_file, a_rank),
        chess.square(c_file, a_rank - rank_step),
        chess.square(c_file, a_rank - 2 * rank_step),
        chess.square(2 * a_file - c_file, a_rank),
    )


_STACK_REAR_CAP = 2


def _stack_rears(board: chess.Board, them: chess.Color,
                 pawn_square: chess.Square, step: int) -> int:
    """Their same-file pawns queued behind the executioner (or walker).

    Each rear pawn is a renewal: when the front pawn's vacate race is lost
    (early push, our king recaptures on the arrival square), the rear pawn
    is Zach's whole quiet pool, walks down one square, re-freezes against
    the re-holding king, and the audited corner race re-poses one pawn
    shorter — the adjudicated 1/2 -> 3/4 lift (tuning log, 2026-07-19).
    Gaps in the column are counted: a loose rear compacts against the
    front pawn by the same uniform pushes that walk the front one. Any
    non-pawn occupant ends the column — a piece cannot become a b-file
    pawn. Capped: the third renewal's equity is a sixteenth of a win.
    """
    rears = 0
    square = pawn_square - step
    while 0 <= square < 64 and rears < _STACK_REAR_CAP:
        piece = board.piece_at(square)
        if piece is not None:
            if piece.color != them or piece.piece_type != chess.PAWN:
                break
            rears += 1
        square -= step
    return rears


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
    # King-holder mode: our king is the arrival holder, the checked square
    # is the adjacent corner, and our_king_steps measures the march to the
    # ARRIVAL square (the vacate to the corner is the play-time release).
    # race_clear tracks whether the fixed race squares (corner, escapes,
    # entry) are free of construction debt right now.
    king_holder: bool = False
    race_clear: bool = True
    # Prospective king-holder walk: the corner geometry only becomes real
    # once the executioner reaches its pre-corner square, so a template for
    # a pawn still above it carries the number of Zach pushes outstanding
    # (pawn_walk) and how many of OUR movable men currently stand on the
    # walk path or the future arrival square (walk_blockers — the
    # freeze-release debt). Both are 0 on every posed template.
    pawn_walk: int = 0
    walk_blockers: int = 0
    # Their same-file pawns queued behind the executioner: each is one
    # renewal of the vacate race (audited 1/2 -> 3/4 for the first), so a
    # stacked file outranks a bare one at the same distance.
    stack_rears: int = 0

    @property
    def setup_distance(self) -> int:
        """Optimistic number of king-placement steps still required."""
        if self.king_holder:
            return (
                self.our_king_steps
                + self.defender_steps
                + (2 if self.cage_occupancy == 0 else 0)
                + (2 if self.arrival_blocked else 0)
                + (0 if self.race_clear else 1)
                + 2 * self.pawn_walk
                + self.walk_blockers
            )
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
    def hold_established(self) -> bool:
        """The arrival square is frozen by its designated holder."""
        if self.king_holder:
            return self.our_king_steps == 0
        return self.holding_blocker

    @property
    def required_cage(self) -> int:
        # The corner cage is a single bishop; the piece-holder construction
        # wants a three-piece reserve around the checked square.
        return 1 if self.king_holder else 3

    @property
    def ready_to_release(self) -> bool:
        if self.king_holder:
            # The vacate is never granted by lifting the hold filter: play
            # gates it on the audited race (score_release_moves accepting),
            # which deliberately bypasses the filters.
            return False
        # The holding blocker occupies a cage square itself. Require one extra
        # occupant so releasing it leaves a three-piece cage for the probe.
        required_cage = 4 if self.holding_blocker else 3
        return (
            self.our_king_steps == 0
            and self.defender_steps == 0
            and self.cage_occupancy >= required_cage
        )

    # ------------------------------------------------------------------
    # King-holder geometry (meaningful only when king_holder is True).
    # ------------------------------------------------------------------

    @property
    def kh_cage_square(self) -> chess.Square:
        return _kh_squares(self.arrival_square, self.checked_square)[0]

    @property
    def kh_escape_square(self) -> chess.Square:
        return _kh_squares(self.arrival_square, self.checked_square)[1]

    @property
    def kh_entry_square(self) -> chess.Square:
        return _kh_squares(self.arrival_square, self.checked_square)[2]

    @property
    def kh_seal_square(self) -> chess.Square:
        return _kh_squares(self.arrival_square, self.checked_square)[3]

    @property
    def kh_far_capture_square(self) -> chess.Square:
        return _kh_squares(self.arrival_square, self.checked_square)[4]

    @property
    def kh_rear_food_squares(self) -> tuple:
        """Far-file squares diagonally ahead of each stacked rear pawn.

        The far-capture rule one rank up, once per rear: at the delivery
        zugzwang every non-mating move left in Zach's pool outranks the
        mate, so any of OUR men on a rear pawn's capture square is an
        escape valve exactly when the net closes (the bxc3 leak: with our
        pawn on c3 under a b3+b4 stack, the audit refuses every retreat).
        The corner-side diagonal needs no twin rule — it is the entry
        square and the seal square, already constrained. Squares are the
        POSE-time ones (rears compacted against the executioner), which is
        where the delivery happens whatever the column looks like mid-walk.
        """
        a_file = chess.square_file(self.arrival_square)
        a_rank = chess.square_rank(self.arrival_square)
        c_file = chess.square_file(self.checked_square)
        c_rank = chess.square_rank(self.checked_square)
        rank_step = c_rank - a_rank
        far_file = 2 * a_file - c_file
        return tuple(
            chess.square(far_file, a_rank - (i + 1) * rank_step)
            for i in range(self.stack_rears)
        )

    @property
    def kh_closer_park_square(self) -> chess.Square:
        """Where the knight closer waits out the herd.

        The mate's seal move must land on a square covering the seal square
        in ONE hop at release time, but any park inside seal range attacks
        the pocket, the entry, or the rank-six gate their king must cross —
        the b4-knight failure: parked at pull-satisfied range, its coverage
        of a6/c6 sealed the only lane into the pocket and the side
        certified dead against our own statics. Two files inward from the
        corner on the FAR back rank is the unique park that hops to the
        seal-cover square (c8-b6 mirroring the drill's f8-g6) while
        attacking nothing their king needs; the construction drill's
        hand-placed f8 knight is exactly this square, which is how the
        geometry was discovered.
        """
        corner_file = chess.square_file(self.checked_square)
        corner_rank = chess.square_rank(self.checked_square)
        return chess.square(
            2 if corner_file == 0 else 5,
            7 - corner_rank,
        )


@dataclass(frozen=True)
class ConstructionPlan:
    """A persistent commitment to one execution pawn, checking side, and
    holder mode. Mixing holder modes inside one plan would let the resolver
    flip between incompatible constructions move to move; committing the
    mode keeps the filters and the herding machinery pointed at one device.
    """

    pawn_file: int
    checked_side: int
    created_ply: int
    holder_mode: str = "piece"  # "piece" | "king"

    @classmethod
    def from_template(cls, target: PawnMateTemplate,
                      created_ply: int) -> "ConstructionPlan":
        return cls(
            pawn_file=chess.square_file(target.pawn_square),
            checked_side=target.checked_side,
            created_ply=created_ply,
            holder_mode="king" if target.king_holder else "piece",
        )

    def resolve(self, board: chess.Board,
                us: chess.Color) -> PawnMateTemplate | None:
        wants_king_holder = self.holder_mode == "king"
        candidates = [
            target
            for target in pawn_mate_templates(board, us)
            if chess.square_file(target.pawn_square) == self.pawn_file
            and target.checked_side == self.checked_side
            and target.king_holder == wants_king_holder
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
        mode = "/king" if self.holder_mode == "king" else ""
        return f"{chess.FILE_NAMES[self.pawn_file]}-pawn/{side}{mode}"


@dataclass(frozen=True)
class HerdingMetrics:
    open_outward: int
    controlled_outward: int
    open_total: int


def _king_holder_template(
    board: chess.Board,
    us: chess.Color,
    our_king: chess.Square,
    their_king: chess.Square,
    pawn_square: chess.Square,
    arrival: chess.Square,
    checked_square: chess.Square,
    runway_blocked: bool,
    knights: chess.SquareSet,
    bishops: chess.SquareSet,
    pawn_walk: int = 0,
    walk_blockers: int = 0,
) -> PawnMateTemplate | None:
    """The corner king-holder variant of one (pawn, arrival, checked) triple.

    Emitted only when the adjudicated geometry can possibly close: the
    checked square is a corner, a knight-class closer exists somewhere (the
    mate's sealing move must not check), and a bishop of the cage square's
    color complex exists (no other piece type is sound on that square).
    These are necessary conditions for steering only — the conversion audit
    and the release probe remain the arbiters of the actual race.
    """
    if not (
        chess.square_file(checked_square) in (0, 7)
        and chess.square_rank(checked_square) in (0, 7)
    ):
        return None
    if not knights:
        return None
    cage_square, escape, entry, _, far_capture = _kh_squares(
        arrival, checked_square
    )
    cage_piece = board.piece_at(cage_square)
    caged = (
        cage_piece is not None
        and cage_piece.color == us
        and cage_piece.piece_type == chess.BISHOP
    )
    if not caged and not any(
        _same_shade(square, cage_square) for square in bishops
    ):
        return None

    occupant = board.piece_at(arrival)
    blocked = occupant is not None and not (
        occupant.color == us and occupant.piece_type == chess.KING
    )

    def ours_on(square: chess.Square) -> bool:
        piece = board.piece_at(square)
        return piece is not None and piece.color == us

    them = not us
    step = 8 if them == chess.WHITE else -8
    rears = _stack_rears(board, them, pawn_square, step)
    a_rank = chess.square_rank(arrival)
    c_rank = chess.square_rank(checked_square)
    far_file = chess.square_file(far_capture)
    rear_foods = tuple(
        chess.square(far_file, a_rank - (i + 1) * (c_rank - a_rank))
        for i in range(rears)
    )
    race_clear = (
        board.piece_at(checked_square) is None
        and board.piece_at(escape) is None
        and not ours_on(entry)
        and not ours_on(far_capture)
        and not any(ours_on(food) for food in rear_foods)
    )
    return PawnMateTemplate(
        pawn_square=pawn_square,
        arrival_square=arrival,
        checked_square=checked_square,
        our_king_steps=chess.square_distance(our_king, arrival),
        defender_steps=max(
            0, chess.square_distance(their_king, arrival) - 1
        ),
        cage_occupancy=1 if caged else 0,
        arrival_blocked=blocked,
        runway_blocked=runway_blocked,
        holding_blocker=False,
        holding_blocker_defended=False,
        king_holder=True,
        race_clear=race_clear,
        pawn_walk=pawn_walk,
        walk_blockers=walk_blockers,
        stack_rears=rears,
    )


def _prospective_king_holder_template(
    board: chess.Board,
    us: chess.Color,
    our_king: chess.Square,
    their_king: chess.Square,
    pawn_square: chess.Square,
    knights: chess.SquareSet,
    bishops: chess.SquareSet,
) -> PawnMateTemplate | None:
    """The corner king-holder template a pawn WILL support once it walks.

    A corner template only exists once the executioner stands on its
    pre-corner square, but every plan built before that freezes the pawn far
    away — so adoption needs a template that names the future geometry while
    the pawn is still walking. Only b- and g-file pawns have a corner at
    all, and the walk is Zach-paced: we release the freeze and keep the file
    clear; his uniform kernel supplies the pushes.

    Emitted only when the walk is possible at all: no piece of theirs on
    the path (we cannot clear it), no pawn of ours on the path or the
    future arrival square (pawns cannot leave the file — a push merely
    plugs the walk higher up). Our movable men on those squares are counted
    as walk_blockers instead: stepping aside is the freeze-release debt.
    All corner squares are computed from the FINAL arrival, so the fixed
    race geometry (cage shade, knight closer) is checked against the
    construction that will actually pose.
    """
    them = not us
    file = chess.square_file(pawn_square)
    if file not in (1, 6):
        return None
    step = 8 if them == chess.WHITE else -8
    rank = chess.square_rank(pawn_square)
    pre_rank = 5 if them == chess.WHITE else 2
    walking = rank < pre_rank if them == chess.WHITE else rank > pre_rank
    if not walking:
        return None

    final_pawn = chess.square(file, pre_rank)
    arrival = final_pawn + step
    corner_file = 0 if file == 1 else 7
    corner_rank = 7 if them == chess.WHITE else 0
    checked_square = chess.square(corner_file, corner_rank)

    occupant = board.piece_at(arrival)
    if occupant is not None:
        if occupant.color == us and occupant.piece_type == chess.PAWN:
            return None  # our pawn can never leave the file
        if occupant.color != us and occupant.piece_type != chess.PAWN:
            return None  # their piece: this phase is over anyway
        # THEIR pawn on the arrival square is the spent executioner of the
        # renewal window (early push, not yet retaken): the committed plan
        # must keep resolving through it so the renewal capture can retake
        # the square — the shared constructor emits it as arrival_blocked.
    blockers = 0
    square = pawn_square + step
    while True:
        piece = board.piece_at(square)
        if piece is not None:
            if piece.color != us:
                return None
            if piece.piece_type == chess.PAWN:
                return None
            if piece.piece_type != chess.KING:
                # The king's own transit is already priced by its march.
                blockers += 1
        if square == final_pawn:
            break
        square += step

    # One Zach push covers two ranks from the home square.
    home_rank = 1 if them == chess.WHITE else 6
    walk = abs(pre_rank - rank) - (1 if rank == home_rank else 0)
    runway_square = arrival + step
    runway_piece = (
        board.piece_at(runway_square) if 0 <= runway_square < 64 else None
    )
    runway_blocked = runway_piece is not None and runway_piece.color == us
    return _king_holder_template(
        board, us, our_king, their_king, pawn_square, arrival,
        checked_square, runway_blocked, knights, bishops,
        pawn_walk=walk, walk_blockers=blockers,
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
    knights = board.pieces(chess.KNIGHT, us)
    bishops = board.pieces(chess.BISHOP, us)
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
            king_variant = _king_holder_template(
                board, us, our_king, their_king, pawn_square, arrival,
                checked_square, runway_blocked, knights, bishops,
            )
            if king_variant is not None:
                templates.append(king_variant)
        walking_variant = _prospective_king_holder_template(
            board, us, our_king, their_king, pawn_square, knights, bishops,
        )
        if walking_variant is not None:
            templates.append(walking_variant)
    return templates


def best_pawn_mate_template(board: chess.Board,
                            us: chess.Color) -> PawnMateTemplate | None:
    templates = pawn_mate_templates(board, us)
    # Walking (prospective) king-holder templates are resolution targets for
    # a plan that has already committed to the adoption, never fresh-plan
    # material: the walk is speculative Zach-paced work, and steering toward
    # it is keyed on the committed side's audited-conversion verdict, not on
    # template ranking.
    templates = [
        target for target in templates
        if not (target.king_holder and target.pawn_walk > 0)
    ]
    if not templates:
        return None
    # King-holder templates outrank piece holders whatever their distance:
    # the release theorem makes a completed piece-holder construction
    # unconvertible, while the audited corner race converts at 1/2. Among
    # king holders, a stacked file outranks a bare one before distance is
    # consulted — each rear pawn renews the race (1/2 -> 3/4 audited), and
    # no setup-step count buys expected value like a second coin does.
    return min(
        templates,
        key=lambda target: (
            0 if target.king_holder else 1,
            -target.stack_rears,
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


def kh_bishop_distance(board: chess.Board, us: chess.Color,
                       target: PawnMateTemplate) -> int:
    """Chebyshev distance of our nearest cage-colored bishop to the cage
    square of a king-holder template (99 when no such bishop survives)."""
    cage_square = target.kh_cage_square
    best = 99
    for square in board.pieces(chess.BISHOP, us):
        if not _same_shade(square, cage_square):
            continue
        best = min(best, chess.square_distance(square, cage_square))
    return best


def free_piece_count(board: chess.Board, us: chess.Color) -> int:
    """Our non-king, non-pawn men — the construction economy's currency.

    Any resolvable corner family needs three of them at once: the cage
    bishop is frozen on the corner's rank-side escape, the knight closer
    is parked out of the herd's way, and driving their king takes at
    least one more mobile piece (herder_subsets never returns a subset
    for a side with nothing left to move). One free piece cannot be
    cage, closer, and herder simultaneously — the R9tSLBLK lone queen.
    """
    return sum(
        len(board.pieces(piece_type, us))
        for piece_type in (
            chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN
        )
    )


def kh_viable_files(board: chess.Board, us: chess.Color) -> tuple:
    """Corner files (b/g) whose executioner material THEY still hold.

    A file is viable while a their-pawn can still deliver the corner
    template's mating push: a pawn on the file itself no further than
    the pre-corner square, or a pawn on an ADJACENT file that can still
    capture onto the file at or above it — R9tSLBLK's a6 pawn became the
    b3 executioner via 57...axb4, so donor pawns are executioner
    material too. Deliberately MORE permissive than template emission:
    our own men on the walk path are transient (they die or capture
    away, and the walk-clear machinery exists to move them), their
    pieces on the path are strip targets, so neither blocks viability.
    This predicate prices what material can still be protected, not what
    can pose today; the emission machinery owns walkability.
    """
    them = not us
    pawns = board.pieces(chess.PAWN, them)
    if not pawns:
        return ()
    files = []
    for file in (1, 6):
        for square in pawns:
            pawn_file = chess.square_file(square)
            rank = chess.square_rank(square)
            if them == chess.BLACK:
                # Pre-corner rank 2 (b3/g3); a donor at rank r lands on
                # rank r-1, so it needs one more rank of runway.
                usable = (
                    rank >= 2
                    if pawn_file == file
                    else abs(pawn_file - file) == 1 and rank >= 3
                )
            else:
                usable = (
                    rank <= 5
                    if pawn_file == file
                    else abs(pawn_file - file) == 1 and rank <= 4
                )
            if usable:
                files.append(file)
                break
    return tuple(files)


def kh_supported_files(board: chess.Board, us: chess.Color,
                       viable: tuple | None = None) -> tuple:
    """The viable corner files whose role pieces we still hold.

    Template emission's own material gates, applied file by file: a
    knight-class closer must exist (the sealing move must not check),
    and a bishop of the file's cage-square shade must exist (no other
    piece type is sound on the corner's rank-side escape). The cage
    square is fixed by the corner geometry — square(file, corner rank),
    the same square _kh_squares derives — so the shade requirement can
    never drift from what the construction will actually demand.
    """
    if viable is None:
        viable = kh_viable_files(board, us)
    if not viable:
        return ()
    if not board.pieces(chess.KNIGHT, us):
        return ()
    bishops = board.pieces(chess.BISHOP, us)
    if not bishops:
        return ()
    them = not us
    corner_rank = 7 if them == chess.WHITE else 0
    supported = []
    for file in viable:
        cage_square = chess.square(file, corner_rank)
        if any(_same_shade(square, cage_square) for square in bishops):
            supported.append(file)
    return tuple(supported)


def kh_onfile_files(board: chess.Board, us: chess.Color) -> tuple:
    """The corner files whose executioner already stands ON the file.

    kh_viable_files' same-file arm alone, without the donor arm. What
    makes on-file stock the stronger class is NOT immunity to quiet
    pushes — an unfrozen pawn on the pre-corner rank exits the window
    in one, exactly like a donor (2026-07-20 review) — it is three
    asymmetries no donor has: the pawn leaves its FILE only by
    capturing one of our men (a donation we choose); its window is one
    rank deeper and its expiry push is the DELIVERY square itself, so
    with the corner built in time the "expiry" move is the mate; and
    the arrival-hold freezes its clock indefinitely, which is the
    construction's whole plan. A donor that exits the window mates
    nobody, ever — vfGeEKhy's c4 ran c5-c8=Q out of range in three
    unanswerable tempi after our own 27...Rxa3+ ate its twin. On-file
    stock is a family we can hold; donor-only stock is a family they
    lend. Tempo risk (the premature-push race) is priced by the
    construction machinery, not this material-class predicate.
    """
    them = not us
    pawns = board.pieces(chess.PAWN, them)
    if not pawns:
        return ()
    files = []
    for file in (1, 6):
        for square in pawns:
            if chess.square_file(square) != file:
                continue
            rank = chess.square_rank(square)
            if (rank >= 2 if them == chess.BLACK else rank <= 5):
                files.append(file)
                break
    return tuple(files)


def kh_floor_tier(board: chess.Board, us: chess.Color) -> int:
    """The construction floor's stock class: 2 on-file, 1 donor-only, 0 none.

    Tier 2: some supported family's executioner stands on its file —
    holdable stock whose expiry push is the delivery square (see
    kh_onfile_files for the honest durability story; this is a
    material-class floor, not a tempo guarantee). Tier 1: every
    supported family rests on donor pawns alone — revocable lends
    whose window exit mates nobody. Tier 0: no supported family at
    all. The donation guard's type floor forbids our moves
    (and the replies they invite) from DROPPING the tier: vfGeEKhy's
    24...Bb7 gave up the light bishop — the on-file g-family's cage —
    because the donor-only b-family still counted as support, and the
    game died 2 -> 1 -> 0 over the next 23 moves without the opponent
    ever accepting another gift.
    """
    viable = kh_viable_files(board, us)
    if not viable:
        return 0
    supported = kh_supported_files(board, us, viable)
    if not supported:
        return 0
    onfile = kh_onfile_files(board, us)
    return 2 if any(file in onfile for file in supported) else 1

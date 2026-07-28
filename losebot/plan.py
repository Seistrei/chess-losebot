"""Device plans: the model-era constructor (declared 2026-07-27).

The walls the measurement campaign left standing are PLAN-shaped —
squat a LOCATION failure, sloppy a SEQUENCING failure, random a
COMMITMENT failure — and the a13 arc proved a leaf gradient can hold a
trajectory for tens of plies but only toward a DIRECTION. This layer
supplies destinations: dev-derived device TEMPLATES enumerate concrete
terminal patterns, the ORACLE's own AND-node validates each proposed
terminal before anything steers at it (certify-or-don't-aim), and the
leaf eval prices distance-to-ASSIGNMENT — our king to ITS square, box
men to THEIRS — which is exactly what king_approach lacked.

Everything is default-off behind the engine's ``plan_steer`` price.
Zero means this module is never imported into a decision: no proposer,
no validation nodes, no leaf term, byte-identical to the a14 path.

The templates (from the four dev trophies of the subcap-75k pin, the
ring30/appr18 dev-arm conversions, and specialist-era geometry as
opponent-generic theory — inputs declared in TUNING-LOG before any
board was opened):

- PAWN_STRIKE: their pawn captures our donated man on D and the
  pawn's fork from D covers our boxed king (squat_g09's hxg6#,
  zach_g02's axb4#, zach_g05's cxd7#). D needs a second their-side
  attacker so the recapture survives our king.
- PAWN_PUSH: the capture-less sibling — their pawn PUSHES to D with
  their king (or another man) guarding it, forking our boxed king
  (ring30 squat_g05's g7#). Post-data catalog amendment, recorded in
  the log: the declared catalog required a donation and the ring30
  tomb has none.
- PROMOTION_TOMB: their passed pawn promotes and the new queen mates
  our boxed king from the promotion square (specialist theory; the
  ring30 promotion games end in the range-recapture shape below, so
  this template earns its keep only prospectively).
- RECAPTURE_BOX: their piece recaptures our donated man on D and
  checks our boxed king from D — adjacent or AT RANGE down a cleared
  line (zach_g03's and ring30 squat_g03's Qxc8#, both back-rank).

A template is a GENERATOR, not an authority: it enumerates candidate
assignments, and the truth question — "would the root prover certify
this terminal?" — is delegated to ``oracle.forced_after_status`` on
the hypothetical completed position P* (our assigned men teleported,
their men untouched, them to move, clock zero). PROVEN at n <= 2 is
the only license to steer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from . import oracle
from .outcomes import adjudicate_draw

#: One P* validation's node budget: sub_probe_slice // 4 at the
#: shipped 8,000 — arithmetic from an engine constant, not a fit. The
#: AND-check starts one ply deeper than a root proof, and n <= 2 is
#: the cheap rung of the whole record.
VALIDATE_BUDGET = 2_000
#: Validations per proposal event; candidates beyond this many are
#: never opened (they are ranked cheapest-assembly-first, so the tail
#: is the expensive speculation).
MAX_VALIDATIONS = 16
#: The box price is the king price halved, integer arithmetic.
BOX_PRICE_DIVISOR = 2
#: Distance charged for an assignment no surviving man can fill —
#: one past the board's own maximum king distance.
MISSING_MAN_DISTANCE = 8
#: Deepest net a P* validation may claim. Matches the sub-probe's own
#: horizon: the organic devices assemble at n <= 2.
VALIDATE_N = 2


@dataclass(frozen=True)
class Assignment:
    """One target square an instantiation must fill, and by whom.

    ``types`` is frozen at proposal from the men that could plausibly
    reach the square then; the leaf term re-resolves WHICH man is
    nearest every evaluation, because python-chess pieces carry no
    identity across moves and the nearest eligible man is the
    assignee in every game we derived this from.
    """

    square: int
    types: tuple[int, ...]


@dataclass
class PlanState:
    """An adopted, oracle-validated device instantiation."""

    template: str
    king_target: int
    donation: Assignment | None
    executioner: int
    box: tuple[Assignment, ...]
    king_price: int
    box_price: int
    validated_n: int
    their_map: dict = field(default_factory=dict)
    completed: bool = False

    def leaf_delta(self, board: chess.Board, us: chess.Color) -> float:
        """Distance-to-assignment, priced. Negative until assembled.

        The donation target is priced ONLY once the king stands on
        its square and every box target is filled — the sloppy
        sequencing lesson made structural: donations pay only where
        boxes are already built. Before that the donation man is
        priced by nothing and the shipped eval keeps it safe.
        """
        our_king = board.king(us)
        if our_king is None:
            return 0.0
        delta = -self.king_price * chess.square_distance(
            our_king, self.king_target
        )
        complete = our_king == self.king_target
        for target in self.box:
            dist = _nearest_eligible(board, us, target)
            delta -= self.box_price * dist
            complete = complete and dist == 0
        if self.donation is not None and complete:
            delta -= self.box_price * _nearest_eligible(
                board, us, self.donation
            )
        return delta

    def assembly_complete(self, board: chess.Board, us: chess.Color) -> bool:
        """King home and box filled (the donation is the prover's cue,
        not the plan's — completion is what un-gates its price)."""
        if board.king(us) != self.king_target:
            return False
        return all(
            _nearest_eligible(board, us, target) == 0 for target in self.box
        )


def their_footprint(board: chess.Board, them: chess.Color) -> dict:
    """Their piece map, the plan layer's change detector: any move,
    capture, or promotion of theirs shows up here and triggers a
    re-validation (their side of P* is a frozen snapshot; drift is
    handled by re-checking, never by trusting)."""
    return {
        square: piece.piece_type
        for square, piece in board.piece_map().items()
        if piece.color == them
    }


def _pawn_eligible(square: int, target: int, us: chess.Color) -> bool:
    """Pawns fill targets only by pushing: same file, strictly ahead,
    never the promotion rank (a pawn there is a piece, and pricing
    that transformation is not this layer's business)."""
    if chess.square_file(square) != chess.square_file(target):
        return False
    rank_s = chess.square_rank(square)
    rank_t = chess.square_rank(target)
    if us == chess.WHITE:
        return rank_s < rank_t < 7
    return 0 < rank_t < rank_s


def _man_eligible(piece: chess.Piece, square: int, target: int,
                  us: chess.Color, types: tuple[int, ...]) -> bool:
    if piece.piece_type not in types:
        return False
    if piece.piece_type == chess.PAWN:
        return _pawn_eligible(square, target, us)
    if piece.piece_type == chess.BISHOP:
        light = chess.BB_LIGHT_SQUARES
        return bool(chess.BB_SQUARES[square] & light) == bool(
            chess.BB_SQUARES[target] & light
        )
    return True


def _nearest_eligible(board: chess.Board, us: chess.Color,
                      assignment: Assignment) -> int:
    """Chebyshev distance from the nearest eligible man to the target
    (0 when one already stands there); MISSING_MAN_DISTANCE when no
    surviving man qualifies."""
    best = MISSING_MAN_DISTANCE
    for square, piece in board.piece_map().items():
        if piece.color != us or piece.piece_type == chess.KING:
            continue
        if not _man_eligible(piece, square, assignment.square, us,
                             assignment.types):
            continue
        dist = chess.square_distance(square, assignment.square)
        if dist < best:
            best = dist
            if best == 0:
                break
    return best


# --- Candidate generation -------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """A concrete instantiation awaiting validation, with the greedy
    man-to-target resolution that priced it (used for P*)."""

    template: str
    king_target: int
    donation: Assignment | None
    executioner: int
    box: tuple[Assignment, ...]
    placements: tuple[tuple[int, int], ...]  # (from_square, to_square)
    cost: int

    def sort_key(self):
        return (
            self.cost,
            self.template,
            self.king_target,
            -1 if self.donation is None else self.donation.square,
            self.executioner,
        )


_ALL_TYPES = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK,
              chess.QUEEN)

_RAY_DIRECTIONS = {
    chess.ROOK: ((0, 1), (0, -1), (1, 0), (-1, 0)),
    chess.BISHOP: ((1, 1), (1, -1), (-1, 1), (-1, -1)),
}
_RAY_DIRECTIONS[chess.QUEEN] = (
    _RAY_DIRECTIONS[chess.ROOK] + _RAY_DIRECTIONS[chess.BISHOP]
)


def _walk_ray(board: chess.Board, start: int, direction: tuple[int, int],
              skip: int | None = None):
    """Empty squares along a ray from ``start``, stopping at the first
    occupied one. ``skip`` (the executioner's own square) is treated
    as empty: on P* it will have moved to the start of this very ray.
    """
    file, rank = chess.square_file(start), chess.square_rank(start)
    df, dr = direction
    while True:
        file += df
        rank += dr
        if not (0 <= file <= 7 and 0 <= rank <= 7):
            return
        square = chess.square(file, rank)
        if square != skip and board.piece_at(square) is not None:
            return
        yield square


def _covered_by_them(board: chess.Board, them: chess.Color, square: int,
                     executioner: int) -> bool:
    """Their coverage EXCLUDING the executioner's from-square: once it
    captures or pushes to D its old attacks are gone, and a flight
    the executioner alone covered is open on P*."""
    return bool(board.attackers(them, square) & ~chess.BB_SQUARES[
        executioner
    ])


def _mate_coverage(board: chess.Board, piece_type: int, them: chess.Color,
                   arrival: int, executioner: int) -> set:
    """Squares the executioner covers FROM its arrival square — these
    ring squares need no box man, and the king targets live here.

    Slider rays stop only at THEIR men (minus the executioner's own
    origin): their side of P* is a frozen snapshot, while OUR men are
    exactly what the plan may draft elsewhere — zach_g03's mating
    rank ran THROUGH the donation queen's pre-donation square, and an
    opaque ray never proposes that device. Optimism about a man who
    in fact stays is caught where all optimism is caught: the P*
    validation refutes the candidate."""
    if piece_type == chess.PAWN:
        return set(chess.SquareSet(chess.BB_PAWN_ATTACKS[them][arrival]))
    if piece_type == chess.KNIGHT:
        return set(chess.SquareSet(chess.BB_KNIGHT_ATTACKS[arrival]))
    if piece_type == chess.KING:
        return set(chess.SquareSet(chess.BB_KING_ATTACKS[arrival]))
    covered = set()
    them_occ = board.occupied_co[them] & ~chess.BB_SQUARES[executioner]
    for direction in _RAY_DIRECTIONS[piece_type]:
        file = chess.square_file(arrival)
        rank = chess.square_rank(arrival)
        df, dr = direction
        while True:
            file += df
            rank += dr
            if not (0 <= file <= 7 and 0 <= rank <= 7):
                break
            square = chess.square(file, rank)
            covered.add(square)
            if them_occ & chess.BB_SQUARES[square]:
                break
    return covered


def _box_for(board: chess.Board, us: chess.Color, king_target: int,
             arrival: int, executioner: int,
             covered: set) -> tuple[tuple[int, ...], set] | None:
    """Open flight squares of ``king_target`` needing an own man, and
    the set of our men pinned in place by already closing one.

    Returns None when a ring square is closed by nothing closeable —
    a their-man standing there undefended (our king would just take
    it and leave).
    """
    them = not us
    needs: list[int] = []
    pinned: set[int] = set()
    for square in chess.SquareSet(chess.BB_KING_ATTACKS[king_target]):
        if square == arrival:
            continue  # the executioner's own square; guarded by filter
        if square in covered:
            # Closed by the executioner itself — an own man standing
            # here is NOT pinned: its departure leaves the square
            # covered (it may be the donation man, as in zach_g03).
            continue
        piece = board.piece_at(square)
        if piece is not None and piece.color == us:
            if piece.piece_type == chess.KING:
                continue  # the king is being teleported away
            pinned.add(square)
            continue
        if piece is not None:  # their man on the ring
            if _covered_by_them(board, them, square, executioner):
                continue
            return None
        if _covered_by_them(board, them, square, executioner):
            continue
        needs.append(square)
    return tuple(sorted(needs)), pinned


#: Donation-man variants per instantiation. The nearest eligible man
#: is not always the DEVICE's man: in zach_g02 the queen must be the
#: donation precisely because she is the one piece that could rescue
#: the net by capturing the executioner — donate the refuter. Men
#: already attacking D rank first for exactly that reason; the P*
#: validation arbitrates among the variants.
DONATION_VARIANTS = 3


def _resolve(board: chess.Board, us: chess.Color, king_target: int,
             box_squares: tuple[int, ...], donation: int | None,
             pinned: set) -> list:
    """Greedy unique man-to-target resolutions, deterministic: box
    targets in square order, each taking its nearest eligible unused
    man (ties by square index); then up to DONATION_VARIANTS choices
    of donation man, ordered attackers-of-D first, then distance,
    then square. Empty when material is insufficient."""
    men = [
        (square, piece)
        for square, piece in sorted(board.piece_map().items())
        if piece.color == us and piece.piece_type != chess.KING
        and square not in pinned and square != board.king(us)
    ]
    used: set[int] = set()
    placements: list[tuple[int, int]] = []
    assignments: list[Assignment] = []
    cost = 0
    for target in box_squares:
        best = None
        for square, piece in men:
            if square in used:
                continue
            if not _man_eligible(piece, square, target, us, _ALL_TYPES):
                continue
            dist = chess.square_distance(square, target)
            if best is None or dist < best[0]:
                best = (dist, square, piece)
        if best is None:
            return []
        used.add(best[1])
        placements.append((best[1], target))
        assignments.append(
            Assignment(square=target, types=(best[2].piece_type,))
        )
        cost += best[0]
    our_king = board.king(us)
    if our_king is not None:
        cost += chess.square_distance(our_king, king_target)
    base = (tuple(assignments), tuple(placements), cost)
    if donation is None:
        return [(base[0], None, base[1], base[2])]
    donors = []
    for square, piece in men:
        if square in used:
            continue
        if not _man_eligible(piece, square, donation, us, _ALL_TYPES):
            continue
        attacks_d = bool(board.attacks(square) & chess.BB_SQUARES[donation])
        donors.append((
            0 if attacks_d else 1,
            chess.square_distance(square, donation),
            square,
            piece,
        ))
    donors.sort(key=lambda entry: entry[:3])
    out = []
    for _rank, dist, square, piece in donors[:DONATION_VARIANTS]:
        out.append((
            base[0],
            Assignment(square=donation, types=(piece.piece_type,)),
            base[1] + ((square, donation),),
            base[2] + dist,
        ))
    return out


def _king_target_open(board: chess.Board, us: chess.Color,
                      square: int) -> bool:
    piece = board.piece_at(square)
    return piece is None or (
        piece.color == us and piece.piece_type == chess.KING
    )


def _pawn_candidates(board: chess.Board, us: chess.Color,
                     out: list[Candidate]) -> None:
    """PAWN_STRIKE (capture of our donation) and PAWN_PUSH (push with
    a their-side guard) — one fork geometry, two arrival modes."""
    them = not us
    for sp in board.pieces(chess.PAWN, them):
        step = 8 if them == chess.WHITE else -8
        arrivals: list[tuple[str, int, bool]] = []
        for arrival in chess.SquareSet(chess.BB_PAWN_ATTACKS[them][sp]):
            piece = board.piece_at(arrival)
            if piece is not None and piece.color == them:
                continue
            # Strike: the recapture must survive our adjacent king, so
            # D needs a second their-side attacker (their king counts;
            # zach_g02's guard WAS their king).
            if len(board.attackers(them, arrival)) < 2:
                continue
            arrivals.append(("pawn-strike", arrival, True))
        push = sp + step
        if 0 <= push <= 63 and board.piece_at(push) is None:
            # Push: no donation to recapture, so the arrival square
            # needs any their-side guard at all (the pusher does not
            # defend its own push square).
            if board.attackers(them, push):
                arrivals.append(("pawn-push", push, False))
        for template, arrival, wants_donation in arrivals:
            covered = _mate_coverage(board, chess.PAWN, them, arrival, sp)
            for king_target in sorted(covered):
                if not _king_target_open(board, us, king_target):
                    continue
                boxed = _box_for(
                    board, us, king_target, arrival, sp, covered
                )
                if boxed is None:
                    continue
                box_squares, pinned = boxed
                donation = arrival if wants_donation else None
                for box, donation_a, placements, cost in _resolve(
                        board, us, king_target, box_squares, donation,
                        pinned):
                    out.append(Candidate(
                        template=template, king_target=king_target,
                        donation=donation_a, executioner=sp, box=box,
                        placements=placements, cost=cost,
                    ))


def _recapture_candidates(board: chess.Board, us: chess.Color,
                          out: list[Candidate]) -> None:
    """RECAPTURE_BOX: their piece takes our donation on D and checks
    our boxed king from D — adjacent or at range down a cleared line
    (the back-rank Qxc8 device of zach_g03 and ring30 squat_g03)."""
    them = not us
    for sx, piece in board.piece_map().items():
        if piece.color != them or piece.piece_type in (
                chess.PAWN, chess.KING):
            continue
        for arrival in board.attacks(sx):
            occupant = board.piece_at(arrival)
            if occupant is not None and occupant.color == them:
                continue
            covered = _mate_coverage(
                board, piece.piece_type, them, arrival, sx
            )
            for king_target in sorted(covered):
                if not _king_target_open(board, us, king_target):
                    continue
                if chess.square_distance(king_target, arrival) == 1:
                    # Adjacent check: our king could just recapture,
                    # so D needs a second their-side attacker.
                    if len(board.attackers(them, arrival)) < 2:
                        continue
                boxed = _box_for(
                    board, us, king_target, arrival, sx, covered
                )
                if boxed is None:
                    continue
                box_squares, pinned = boxed
                for box, donation_a, placements, cost in _resolve(
                        board, us, king_target, box_squares, arrival,
                        pinned):
                    out.append(Candidate(
                        template="recapture-box", king_target=king_target,
                        donation=donation_a, executioner=sx, box=box,
                        placements=placements, cost=cost,
                    ))


def _promotion_candidates(board: chess.Board, us: chess.Color,
                          out: list[Candidate]) -> None:
    """PROMOTION_TOMB: their passer promotes and the new queen mates
    from the promotion square. Passers deeper than two ranks out
    cannot validate at n <= 2 and re-enter as they advance (the
    proposer re-runs on every their-footprint change)."""
    them = not us
    step = 8 if them == chess.WHITE else -8
    promotion_rank = 7 if them == chess.WHITE else 0
    for sp in board.pieces(chess.PAWN, them):
        distance = abs(promotion_rank - chess.square_rank(sp))
        if not 1 <= distance <= 2:
            continue
        runway = [sp + step * (i + 1) for i in range(distance)]
        if any(board.piece_at(square) is not None for square in runway):
            continue
        promotion = runway[-1]
        covered = _mate_coverage(
            board, chess.QUEEN, them, promotion, sp
        )
        for king_target in sorted(covered):
            if chess.square_distance(king_target, promotion) == 1:
                continue  # adjacent king just captures the new queen
            if not _king_target_open(board, us, king_target):
                continue
            boxed = _box_for(
                board, us, king_target, promotion, sp, covered
            )
            if boxed is None:
                continue
            box_squares, pinned = boxed
            for box, _donation, placements, cost in _resolve(
                    board, us, king_target, box_squares, None, pinned):
                out.append(Candidate(
                    template="promotion-tomb", king_target=king_target,
                    donation=None, executioner=sp, box=box,
                    placements=placements, cost=cost,
                ))


def generate_candidates(board: chess.Board,
                        us: chess.Color) -> list[Candidate]:
    """Every template's instantiations, cheapest assembly first,
    deterministically ordered."""
    out: list[Candidate] = []
    _pawn_candidates(board, us, out)
    _recapture_candidates(board, us, out)
    _promotion_candidates(board, us, out)
    out.sort(key=Candidate.sort_key)
    return out


# --- Validation ------------------------------------------------------


def build_pstar(board: chess.Board, us: chess.Color,
                placements: tuple[tuple[int, int], ...],
                king_target: int,
                to_move: chess.Color) -> chess.Board | None:
    """The hypothetical completed position: our assigned men (and
    king) teleported to their targets, their men untouched,
    ``to_move`` to move, clock zero, no castling or en passant. None
    when the construction is not a legal, live chess position."""
    piece_map = dict(board.piece_map())
    our_king = board.king(us)
    if our_king is None:
        return None
    moved: dict[int, chess.Piece] = {}
    for origin, target in placements:
        piece = piece_map.pop(origin, None)
        if piece is None or piece.color != us:
            return None
        moved[target] = piece
    king_piece = piece_map.pop(our_king, None)
    if king_piece is None:
        return None
    moved[king_target] = king_piece
    for target, piece in moved.items():
        if target in piece_map:
            return None  # collision with an unmoved man
        piece_map[target] = piece
    pstar = chess.Board(None)
    pstar.set_piece_map(piece_map)
    pstar.turn = to_move
    pstar.halfmove_clock = 0
    pstar.fullmove_number = 1
    if not pstar.is_valid():
        return None
    if pstar.is_checkmate() or pstar.is_stalemate():
        return None  # ended, not poised
    if adjudicate_draw(pstar) is not None:
        return None
    return pstar


def validate(board: chess.Board, us: chess.Color,
             placements: tuple[tuple[int, int], ...], king_target: int,
             budget: list) -> tuple[int | None, oracle.ProofStatus]:
    """PROVEN n for the candidate's P*, or (None, last status).

    Two directions, either suffices, both exact prover machinery:

    - US TO MOVE: ``selfmate_status`` from the assembled position —
      the prover supplies the missing final move itself (squat_g09's
      h7h6 runway block, a zugzwang completion no assignment lists).
      This is the declaration's mandate wording, "selfmate_in from a
      hypothetical completed position", verbatim.
    - THEM TO MOVE: the AND-node ``forced_after_status`` — the net
      already complete behind a donation that may be CHECKING their
      king (zach_g02's Qb4+), where the us-to-move construction is
      not even a legal position.

    PROVEN either way means a real position matching the assignments
    is one the root prover certifies at n <= VALIDATE_N. The
    synthetic clock-0/no-history caveat from the declaration applies:
    validation is geometry-pure; the in-game prover on the real path
    remains the only closer.
    """
    last = oracle.ProofStatus.DISPROVEN
    ours = build_pstar(board, us, placements, king_target, us)
    if ours is not None:
        memo: dict = {}
        for n in range(1, VALIDATE_N + 1):
            if budget[0] <= 0:
                return None, oracle.ProofStatus.UNKNOWN
            status, _move = oracle.selfmate_status(ours, n, budget, memo)
            if status is oracle.ProofStatus.PROVEN:
                return n, status
            last = status
    theirs = build_pstar(board, us, placements, king_target, not us)
    if theirs is not None:
        memo = {}
        for n in range(1, VALIDATE_N + 1):
            if budget[0] <= 0:
                return None, oracle.ProofStatus.UNKNOWN
            status = oracle.forced_after_status(theirs, n, budget, memo)
            if status is oracle.ProofStatus.PROVEN:
                return n, status
            last = status
    return None, last

"""Leaf evaluation for misère chess, asymmetric by design.

Values are ALWAYS from the root (losing-seeking) player's perspective,
whoever is to move — the first hard-won lesson of the project: a
symmetric side-to-move eval flips "them" at odd depths and goes blind
to dead draws.

Ported from the specialists' general core (constants = the tuned
CURRENT profile) minus the template/plan machinery: that machinery is
Zach-choreography, and the pivot moves its job into search against an
opponent distribution. What remains is the domain knowledge that holds
against ANY opponent:

- their pieces are shuffle fuel (eat them), their pawns are the
  executioners (preserve them);
- a bare or pawn-frozen opponent is a dead draw, the worst state;
- squeeze their non-mating menu, but keep mating moves ON the menu —
  zeroing everything is a stalemate, not a win;
- walk our king to their pawns and smother it with our own men;
- the draw clock hurts us, never them.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

MATE = 100_000

PIECE_VALS = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

# Tuned constants: the specialists' CURRENT profile values.
OUR_MAN_VALUE = 25
THEIR_PIECE_SCALE = 0.90
PAWN_BASE = 55
PAWN_VALUE = 25
PAWN_CAP = 3
KING_AND_PAWNS_BONUS = 150
BARE_KING_PENALTY = 6000
FROZEN_PAWNS_PENALTY = 3000
MENU_LIMIT = 10
NONMATING_MOVE_PENALTY = 14
KING_MOVE_WEIGHT = 1.6
MATING_MOVE_BONUS = 90
MATING_MOVE_CAP = 2
ZUGZWANG_BONUS = 900
LARGE_MENU_PENALTY = 12
CHECK_BONUS = 40
CHECK_ESCAPE_BONUS = 6
KING_TARGET_DISTANCE_PENALTY = 9
OWN_KING_NEIGHBOR_BONUS = 6
HERDING_DISTANCE_PENALTY = 8
HERDING_ADJACENCY_BONUS = 120
FLIGHT_SQUARE_PENALTY = 24
CLOCK_PRESSURE = 1.5

# Proximity-term caps (the terms themselves are default-off knobs on
# EvalParams; these caps are structural, mirroring MATING_MOVE_CAP).
CHECK_MENU_CAP = 2
RING_DONATION_CAP = 2
# The proximity gate: the region every certificate the project has
# ever landed lived in — opponent reduced to king+pawns (any count)
# or to at most STRIPPED_MEN non-king men (the sub-probe gate's own
# region). Middlegame positions never pay for these terms.
STRIPPED_MEN = 5


@dataclass(frozen=True)
class EvalParams:
    """Default-off proximity prices (2026-07-27 value plumbing).

    The reach verdict: in 1,600 wall and mercy decisions no
    certificate existed within four own-moves — the objective has to
    change where the engine GOES tens of plies earlier, not what it
    prefers when a net appears. These terms price PROXIMITY to
    net-bearing structure, measured (dev-plumb feature study over the
    subcap-75k pin) as what separates cert corridors from walls:

    check_menu    — bonus per opponent reply that gives CHECK (capped
                    at CHECK_MENU_CAP): a menu with no checks cannot
                    mate us, and walls are exactly where the check
                    supply dies. 0 disables.
    ring_donation — bonus per own non-king man adjacent to our king
                    and attacked by them (capped at
                    RING_DONATION_CAP): the recapture devices run on
                    men donated INTO the box, not anywhere on the
                    board. 0 disables.
    king_approach — penalty per square of distance from our king to
                    the nearest opponent man that could ever deliver
                    or escort a mate (their king, their pieces, their
                    MOBILE pawns — a frozen pawn cannot step into a
                    mating pattern, and the squat wall is our king
                    glued to one). 0 disables.

    All-zero is the a12 eval, byte-identical — and since 2.0.0a14 it
    is the default again. The a13 default armed king_approach at 18
    (the value-plumbing pin's 11/40 benchmark board at pinned seeds);
    the declared validation cells then withdrew its generalization
    claim, and the dev-only clean-room re-derivation could not
    reproduce any term — the pooled study's gradients were
    substantially held-out-family regularities (TUNING-LOG
    2026-07-27, the clean-room entries). Every price is one flag
    away; none is armed by default.
    """

    check_menu: int = 0
    ring_donation: int = 0
    king_approach: int = 0


def evaluate(board: chess.Board, us: chess.Color,
             params: EvalParams | None = None) -> float:
    """Score the position for the player trying to get mated.

    ``params`` carries the proximity prices; None is the pre-plumbing
    eval, bit for bit — the engine passes None whenever every price
    is zero, so knob-off runs stay on the historical code path.
    """
    them = not us
    check_menu = params.check_menu if params is not None else 0
    v = 0.0

    # Material: count our men (not points — promoting must gain nothing),
    # charge their mobile pieces, prize their pawns.
    their_pawns = 0
    their_pieces = 0
    our_men = 0
    for piece in board.piece_map().values():
        if piece.color == us:
            if piece.piece_type != chess.KING:
                our_men += 1
        elif piece.piece_type == chess.PAWN:
            their_pawns += 1
        elif piece.piece_type != chess.KING:
            their_pieces += 1
            v -= THEIR_PIECE_SCALE * PIECE_VALS[piece.piece_type]
    v += OUR_MAN_VALUE * our_men

    # They must keep something to mate us with.
    if their_pawns == 0 and their_pieces == 0:
        v -= BARE_KING_PENALTY
    else:
        if their_pawns:
            v += PAWN_BASE + PAWN_VALUE * min(their_pawns, PAWN_CAP)
        if their_pieces == 0:
            v += KING_AND_PAWNS_BONUS
            if not _any_pawn_can_move(board, them, us):
                v -= FROZEN_PAWNS_PENALTY

    # Their menu of options (mate-aware squeeze).
    if board.turn == them:
        v += _menu_term(board, check_menu)
    elif board.is_check():
        # We are being checked: progress; few escapes means nearly mated.
        v += CHECK_BONUS + CHECK_ESCAPE_BONUS * max(
            0, 8 - board.legal_moves.count()
        )
    else:
        board.push(chess.Move.null())
        v += _menu_term(board, check_menu)
        board.pop()

    # Kings: ours walks toward their pawns and smothers itself in our men.
    our_king = board.king(us)
    their_king = board.king(them)
    if our_king is not None:
        targets = list(board.pieces(chess.PAWN, them))
        if not targets and their_king is not None:
            targets = [their_king]
        if targets:
            v -= KING_TARGET_DISTANCE_PENALTY * min(
                chess.square_distance(our_king, t) for t in targets
            )
        for nb in chess.SquareSet(chess.BB_KING_ATTACKS[our_king]):
            piece = board.piece_at(nb)
            if piece is not None and piece.color == us:
                v += OWN_KING_NEIGHBOR_BONUS

    # King+pawns endgame: the mate is a pawn move whose arrival square
    # THEIR OWN KING must defend — herd their king toward their pawns.
    if their_pieces == 0 and their_pawns and their_king is not None:
        pawn_dist = min(
            chess.square_distance(their_king, s)
            for s in board.pieces(chess.PAWN, them)
        )
        v -= HERDING_DISTANCE_PENALTY * pawn_dist
        if pawn_dist == 1:
            v += HERDING_ADJACENCY_BONUS

        # The box: every open flight square around our king is a move
        # the mate net still has to take away. A square is closed by
        # our own man standing on it (self-smother), by their coverage,
        # or by the board edge — corners close five for free. This is
        # the assembly gradient the herding terms point at but never
        # price: fewer flights, nearer the mate.
        if our_king is not None:
            for nb in chess.SquareSet(chess.BB_KING_ATTACKS[our_king]):
                piece = board.piece_at(nb)
                if piece is not None and piece.color == us:
                    continue
                if board.is_attacked_by(them, nb):
                    continue
                v -= FLIGHT_SQUARE_PENALTY

    # Proximity to net-bearing structure (default-off; the value
    # plumbing session). Gated to the stripped region where every
    # certificate has ever lived, so the middlegame never pays.
    if params is not None and our_king is not None and (
            their_pieces == 0 or their_pieces + their_pawns <= STRIPPED_MEN):
        if params.ring_donation:
            ring = 0
            for nb in chess.SquareSet(chess.BB_KING_ATTACKS[our_king]):
                piece = board.piece_at(nb)
                if (piece is not None and piece.color == us
                        and piece.piece_type != chess.KING
                        and board.is_attacked_by(them, nb)):
                    ring += 1
            v += params.ring_donation * min(ring, RING_DONATION_CAP)
        if params.king_approach:
            targets = []
            for sq, piece in board.piece_map().items():
                if piece.color != them:
                    continue
                if (piece.piece_type == chess.PAWN
                        and not _pawn_can_move(board, sq, them, us)):
                    continue  # frozen pawns cannot step into a net
                targets.append(sq)
            if targets:
                v -= params.king_approach * min(
                    chess.square_distance(our_king, t) for t in targets
                )

    # We fear the draw clock; they do not.
    v -= CLOCK_PRESSURE * board.halfmove_clock

    return v


def _menu_term(board: chess.Board, check_menu: int = 0) -> float:
    """Board has THEM to move: score their option pool for us.

    Counts every legal move: for the final zugzwang to be forceable,
    ALL their non-mating moves must be gone. Their POLICY (which moves
    they prefer) is the search tree's business, not this leaf's.

    ``check_menu`` (default-off) additionally prizes replies that give
    CHECK: mate is a check our king cannot answer, so a menu with no
    checks on it cannot mate us no matter how small it is squeezed —
    the squat wall in one sentence. A check reply still counts toward
    ``nonmating`` exactly as before; the bonus rides on top, so the
    zugzwang branch and the squeeze arithmetic are untouched."""
    legal = list(board.legal_moves)
    if not legal:
        return 0.0  # terminal; the search scores it
    if len(legal) > MENU_LIMIT:
        return -LARGE_MENU_PENALTY * len(legal)
    mating = 0
    checking = 0
    nonmating = 0.0
    for reply in legal:
        is_king_move = board.piece_type_at(reply.from_square) == chess.KING
        board.push(reply)
        if board.is_checkmate():
            mating += 1
        else:
            if check_menu and board.is_check():
                checking += 1
            # A free king is the great draw engine.
            nonmating += KING_MOVE_WEIGHT if is_king_move else 1.0
        board.pop()
    if nonmating == 0 and mating:
        return ZUGZWANG_BONUS
    return (
        -NONMATING_MOVE_PENALTY * nonmating
        + MATING_MOVE_BONUS * min(mating, MATING_MOVE_CAP)
        + check_menu * min(checking, CHECK_MENU_CAP)
    )


def _pawn_can_move(board: chess.Board, sq: chess.Square,
                   owner: chess.Color, enemy: chess.Color) -> bool:
    """True if this pawn of owner's can ever push or capture again."""
    step = 8 if owner == chess.WHITE else -8
    front = sq + step
    if not (0 <= front <= 63):
        return False
    if board.piece_at(front) is None:
        return True
    rank = chess.square_rank(front)
    file = chess.square_file(sq)
    for df in (-1, 1):
        f = file + df
        if 0 <= f <= 7:
            piece = board.piece_at(chess.square(f, rank))
            if piece is not None and piece.color == enemy:
                return True
    return False


def _any_pawn_can_move(board: chess.Board, owner: chess.Color,
                       enemy: chess.Color) -> bool:
    """True if any of owner's pawns can ever push or capture again."""
    return any(
        _pawn_can_move(board, sq, owner, enemy)
        for sq in board.pieces(chess.PAWN, owner)
    )

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
CLOCK_PRESSURE = 1.5


def evaluate(board: chess.Board, us: chess.Color) -> float:
    """Score the position for the player trying to get mated."""
    them = not us
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
        v += _menu_term(board)
    elif board.is_check():
        # We are being checked: progress; few escapes means nearly mated.
        v += CHECK_BONUS + CHECK_ESCAPE_BONUS * max(
            0, 8 - board.legal_moves.count()
        )
    else:
        board.push(chess.Move.null())
        v += _menu_term(board)
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

    # We fear the draw clock; they do not.
    v -= CLOCK_PRESSURE * board.halfmove_clock

    return v


def _menu_term(board: chess.Board) -> float:
    """Board has THEM to move: score their option pool for us.

    Counts every legal move: for the final zugzwang to be forceable,
    ALL their non-mating moves must be gone. Their POLICY (which moves
    they prefer) is the search tree's business, not this leaf's."""
    legal = list(board.legal_moves)
    if not legal:
        return 0.0  # terminal; the search scores it
    if len(legal) > MENU_LIMIT:
        return -LARGE_MENU_PENALTY * len(legal)
    mating = 0
    nonmating = 0.0
    for reply in legal:
        is_king_move = board.piece_type_at(reply.from_square) == chess.KING
        board.push(reply)
        if board.is_checkmate():
            mating += 1
        else:
            # A free king is the great draw engine.
            nonmating += KING_MOVE_WEIGHT if is_king_move else 1.0
        board.pop()
    if nonmating == 0 and mating:
        return ZUGZWANG_BONUS
    return (
        -NONMATING_MOVE_PENALTY * nonmating
        + MATING_MOVE_BONUS * min(mating, MATING_MOVE_CAP)
    )


def _any_pawn_can_move(board: chess.Board, owner: chess.Color,
                       enemy: chess.Color) -> bool:
    """True if any of owner's pawns can ever push or capture again."""
    step = 8 if owner == chess.WHITE else -8
    for sq in board.pieces(chess.PAWN, owner):
        front = sq + step
        if not (0 <= front <= 63):
            continue
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

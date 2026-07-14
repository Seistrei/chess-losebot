"""Misère evaluation, asymmetric by design.

The root player ("us") is the one trying to get checkmated; the opponent
("them", e.g. Zach) is a reluctant executioner, not a fellow loser. Every
feature is therefore computed for the root player's goal regardless of whose
turn it is at the leaf, then sign-flipped for negamax at the end.

The encoded strategy is the one humans used to beat Zach and Worstfish:
strip them to king-plus-pawns (but never to a dead position), shrink their
menu of non-mating moves while keeping mating moves on it, walk our king
into their pawns and smother it with our own men.
"""

import chess

PIECE_VALS = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

MATE = 100_000
CONTEMPT = 400        # draws are failure — steer away from them
CLOCK_PRESSURE = 1.5  # a rising 50-move clock means we are drifting to a draw


def evaluate(board: chess.Board, root_color: chess.Color,
             model: str | None = None) -> float:
    us = root_color
    them = not root_color
    stm = board.turn
    v = 0.0

    # Material. Ours is the coercion toolkit — but count men, not points, so
    # promoting gains nothing (queen farms just bloat the branching factor).
    # Their mobile pieces are shuffle fuel and must be eaten; their pawns are
    # the mating tools we want them left with.
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
            v -= 0.90 * PIECE_VALS[piece.piece_type]
    v += 25 * our_men

    # They must keep something to mate us with: a bare king is a dead draw,
    # and so is a king whose only companions are pawns that can never move.
    if their_pawns == 0 and their_pieces == 0:
        v -= 6000
    else:
        if their_pawns:
            # Their first pawn is precious (it is the executioner we protect);
            # a couple of spares are insurance.
            v += 55 + 25 * min(their_pawns, 3)
        if their_pieces == 0:
            v += 150  # the target state: king and pawns only
            if not _any_pawn_can_move(board, them, us):
                v -= 3000

    # Their menu of options. When it is small, what matters is WHICH moves
    # remain: non-mating moves must vanish, mating moves must stay available —
    # squeezing them to zero is a stalemate, not a win.
    if stm == them:
        v += _menu_term(board, model)
    elif board.is_check():
        # We are being checked: progress; few escapes means nearly mated.
        v += 40 + 6 * max(0, 8 - board.legal_moves.count())
    else:
        board.push(chess.Move.null())
        v += _menu_term(board, model)
        board.pop()

    # Kings: walk ours toward their pawns (they deliver the mate; this is
    # also the config that produced the first real win) and smother ours
    # with our own men so the eventual mate has no escape.
    our_king = board.king(us)
    their_king = board.king(them)
    if our_king is not None:
        targets = list(board.pieces(chess.PAWN, them))
        if not targets and their_king is not None:
            targets = [their_king]
        if targets:
            v -= 9 * min(chess.square_distance(our_king, t) for t in targets)
        for nb in chess.SquareSet(chess.BB_KING_ATTACKS[our_king]):
            p = board.piece_at(nb)
            if p is not None and p.color == us:
                v += 6

    # Endgame herding: with only king+pawns left, the mate is a pawn move
    # whose arrival square THEIR OWN KING defends (nothing else can). Drive
    # their king toward their pawns; reward the defender standing in place.
    if their_pieces == 0 and their_pawns and their_king is not None:
        pawn_dist = min(
            chess.square_distance(their_king, s)
            for s in board.pieces(chess.PAWN, them)
        )
        v -= 8 * pawn_dist
        if pawn_dist == 1:
            v += 120

    # We fear the draw clock; they do not.
    v -= CLOCK_PRESSURE * board.halfmove_clock

    return v if stm == us else -v


def _menu_term(board: chess.Board, model: str | None = None) -> float:
    """Board has THEM to move. Score their option pool from our perspective.

    Counts every legal move: for the final zugzwang to be forceable, ALL
    their non-mating moves (captures included) must be gone — the search
    tree, not this leaf term, is where Zach's capture-aversion is modeled."""
    legal = list(board.legal_moves)
    if not legal:
        return 0.0  # terminal; negamax scores it
    if len(legal) <= 10:
        mating = 0
        nonmating = 0.0
        for r in legal:
            is_king_move = board.piece_type_at(r.from_square) == chess.KING
            board.push(r)
            if board.is_checkmate():
                mating += 1
            else:
                # A free king is the great draw engine: boxing it is what
                # turns their pawn moves into their entire menu.
                nonmating += 1.6 if is_king_move else 1.0
            board.pop()
        if nonmating == 0 and mating:
            return 900.0  # every move they have mates us; the probe seals it
        return -14 * nonmating + 90 * min(mating, 2)
    return -12 * len(legal)


def _any_pawn_can_move(board: chess.Board, owner: chess.Color,
                       enemy: chess.Color) -> bool:
    """True if any of `owner`'s pawns has a push square free or an enemy man
    to capture — i.e. the pawn is not frozen forever (ignoring the king)."""
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
                p = board.piece_at(chess.square(f, rank))
                if p is not None and p.color == enemy:
                    return True
    return False

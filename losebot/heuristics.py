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

from .profiles import CURRENT, EngineProfile
from .templates import (
    ConstructionPlan,
    best_pawn_mate_template,
    herding_metrics,
)

PIECE_VALS = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

MATE = 100_000


def evaluate(board: chess.Board, root_color: chess.Color,
             model: str | None = None,
             profile: EngineProfile = CURRENT,
             plan: ConstructionPlan | None = None) -> float:
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
            v -= profile.their_piece_scale * PIECE_VALS[piece.piece_type]
    v += profile.our_man_value * our_men

    # They must keep something to mate us with: a bare king is a dead draw,
    # and so is a king whose only companions are pawns that can never move.
    if their_pawns == 0 and their_pieces == 0:
        v -= profile.bare_king_penalty
    else:
        if their_pawns:
            # Their first pawn is precious (it is the executioner we protect);
            # a couple of spares are insurance.
            v += profile.pawn_base + profile.pawn_value * min(
                their_pawns, profile.pawn_cap
            )
        if their_pieces == 0:
            v += profile.king_and_pawns_bonus
            if not _any_pawn_can_move(board, them, us):
                v -= profile.frozen_pawns_penalty

    # Their menu of options. When it is small, what matters is WHICH moves
    # remain: non-mating moves must vanish, mating moves must stay available —
    # squeezing them to zero is a stalemate, not a win.
    if stm == them:
        v += _menu_term(board, model, profile)
    elif board.is_check():
        # We are being checked: progress; few escapes means nearly mated.
        v += profile.check_bonus + profile.check_escape_bonus * max(
            0, 8 - board.legal_moves.count()
        )
    else:
        board.push(chess.Move.null())
        v += _menu_term(board, model, profile)
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
            v -= profile.king_target_distance_penalty * min(
                chess.square_distance(our_king, t) for t in targets
            )
        for nb in chess.SquareSet(chess.BB_KING_ATTACKS[our_king]):
            p = board.piece_at(nb)
            if p is not None and p.color == us:
                v += profile.own_king_neighbor_bonus

    # Endgame herding: with only king+pawns left, the mate is a pawn move
    # whose arrival square THEIR OWN KING defends (nothing else can). Drive
    # their king toward their pawns; reward the defender standing in place.
    if their_pieces == 0 and their_pawns and their_king is not None:
        pawn_dist = min(
            chess.square_distance(their_king, s)
            for s in board.pieces(chess.PAWN, them)
        )
        v -= profile.herding_distance_penalty * pawn_dist
        if pawn_dist == 1:
            v += profile.herding_adjacency_bonus

        target = (
            plan.resolve(board, us)
            if plan is not None
            else best_pawn_mate_template(board, us)
        )
        if target is None:
            v -= profile.no_template_penalty
        else:
            v -= profile.template_distance_penalty * target.setup_distance
            v += profile.template_cage_bonus * target.cage_occupancy
            if target.runway_blocked:
                v -= profile.template_runway_penalty
            if target.ready_to_release:
                if target.arrival_blocked:
                    v -= profile.plan_release_block_penalty
            elif target.holding_blocker:
                v += profile.plan_hold_bonus
                if not target.holding_blocker_defended:
                    v -= profile.plan_undefended_hold_penalty
            elif not target.arrival_blocked:
                v -= profile.plan_unfrozen_penalty
            herding = herding_metrics(board, us, target)
            v -= (
                profile.herding_open_escape_penalty
                * herding.open_outward
            )
            v += (
                profile.herding_control_bonus
                * herding.controlled_outward
            )

    # We fear the draw clock; they do not.
    v -= profile.clock_pressure * board.halfmove_clock

    return v if stm == us else -v


def _menu_term(board: chess.Board, model: str | None,
               profile: EngineProfile) -> float:
    """Board has THEM to move. Score their option pool from our perspective.

    Counts every legal move: for the final zugzwang to be forceable, ALL
    their non-mating moves (captures included) must be gone — the search
    tree, not this leaf term, is where Zach's capture-aversion is modeled."""
    legal = list(board.legal_moves)
    if not legal:
        return 0.0  # terminal; negamax scores it
    if len(legal) <= profile.menu_limit:
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
                nonmating += profile.king_move_weight if is_king_move else 1.0
            board.pop()
        if nonmating == 0 and mating and profile.zugzwang_bonus is not None:
            return profile.zugzwang_bonus
        return (
            -profile.nonmating_move_penalty * nonmating
            + profile.mating_move_bonus * min(mating, profile.mating_move_cap)
        )
    return -profile.large_menu_penalty * len(legal)


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

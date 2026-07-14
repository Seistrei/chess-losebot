"""Search for misère chess: an exact forced-selfmate probe plus a heuristic
negamax with inverted terminal values (being checkmated = +MATE for the side
that gets mated)."""

import chess

from .heuristics import CONTEMPT, MATE, evaluate


def gives_mate(board: chess.Board, move: chess.Move) -> bool:
    board.push(move)
    result = board.is_checkmate()
    board.pop()
    return result


def gives_stalemate(board: chess.Board, move: chess.Move) -> bool:
    board.push(move)
    result = board.is_stalemate()
    board.pop()
    return result


def _probe_draw(board: chess.Board) -> bool:
    return board.is_insufficient_material() or board.halfmove_clock >= 100


def support_zach(board: chess.Board):
    """The exact pool the Zach policy samples from: never deliver mate if
    avoidable; among non-mating moves, never capture if avoidable.

    An empty pool means every legal move delivers mate — zugzwang achieved."""
    legal = list(board.legal_moves)
    non_mating = [m for m in legal if not gives_mate(board, m)]
    if not non_mating:
        return []
    quiet = [m for m in non_mating if not board.is_capture(m)]
    return quiet or non_mating


def _forced_after(board: chess.Board, n: int, model: str | None,
                  budget, memo) -> bool:
    """Opponent to move. True iff every reply in their pool either mates us
    immediately or leads to our forced selfmate within n-1 further own moves.

    Lazy: bails out on the first refutation found, so quiet positions cost a
    handful of pushes instead of a full reply classification."""
    key = (board._transposition_key(), n, False)
    hit = memo.get(key)
    if hit is not None:
        return hit
    legal = list(board.legal_moves)
    if model == "zach":
        # Zach's pool is the first non-empty class: quiet non-mating moves,
        # else capturing non-mating moves, else he is forced to mate us.
        classes = [
            [m for m in legal if not board.is_capture(m)],
            [m for m in legal if board.is_capture(m)],
        ]
    else:
        classes = [legal]
    result = True
    for cls in classes:
        non_mating_seen = False
        for r in cls:
            if budget[0] <= 0:
                return False  # budget truncation: fail, but do not cache
            budget[0] -= 1
            board.push(r)
            if board.is_checkmate():
                board.pop()  # this reply mates us — exactly what we want
                continue
            non_mating_seen = True
            ok = (
                n > 1
                and not _probe_draw(board)
                and _forced_self(board, n - 1, model, budget, memo)
            )
            board.pop()
            if not ok:
                memo[key] = False
                return False  # refutation: they have a reply that escapes
        if non_mating_seen:
            break  # this class is the pool, and every member is caught
    memo[key] = result
    return result


def _forced_self(board: chess.Board, n: int, model: str | None,
                 budget, memo) -> bool:
    """We are to move. True iff some move of ours forces our mate within n."""
    key = (board._transposition_key(), n, True)
    hit = memo.get(key)
    if hit is not None:
        return hit
    moves = list(board.legal_moves)
    # Checks first: coercion is typically a check whose answers all mate us.
    moves.sort(key=lambda m: 0 if board.gives_check(m) else 1)
    for m in moves:
        if budget[0] <= 0:
            return False  # budget truncation: fail, but do not cache
        budget[0] -= 1
        board.push(m)
        if board.is_checkmate() or board.is_stalemate() or _probe_draw(board):
            board.pop()  # we mated/stalemated THEM or killed the game: failure
            continue
        forced = _forced_after(board, n, model, budget, memo)
        board.pop()
        if forced:
            memo[key] = True
            return True
    memo[key] = False
    return False


def selfmate_in(board: chess.Board, n: int, model: str | None, budget,
                memo=None) -> chess.Move | None:
    """Return a move that forces us to be checkmated within n of our own moves
    against every reply in the opponent's pool (None if no such move within
    the node budget — the probe is best-effort)."""
    if memo is None:
        memo = {}
    moves = list(board.legal_moves)
    moves.sort(key=lambda m: 0 if board.gives_check(m) else 1)
    for m in moves:
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        board.push(m)
        if board.is_checkmate() or board.is_stalemate() or _probe_draw(board):
            board.pop()
            continue
        forced = _forced_after(board, n, model, budget, memo)
        board.pop()
        if forced:
            return m
    return None


def _ordered(board: chess.Board):
    moves = list(board.legal_moves)

    def key(m: chess.Move) -> int:
        if board.is_capture(m):
            victim = board.piece_type_at(m.to_square)
            if victim is not None and victim != chess.PAWN:
                return 0  # eat their mobile pieces first
            return 1
        return 2

    moves.sort(key=key)
    return moves


def negamax(board: chess.Board, depth: int, alpha: float, beta: float,
            root_color: chess.Color, ply: int,
            model: str | None = None) -> float:
    if board.is_checkmate():
        return MATE - ply  # the side to move is mated: it wins misère chess
    if (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.halfmove_clock >= 100
        or (board.halfmove_clock >= 8 and board.is_repetition(3))
    ):
        return -CONTEMPT if board.turn == root_color else CONTEMPT
    if depth <= 0:
        return evaluate(board, root_color, model)
    # NOTE: opponent nodes deliberately expand ALL legal moves (adversarial),
    # even under an opponent model. Modeling Zach's capture-aversion here once
    # taught the bot to build cages out of hanging pieces — which Zach, when
    # his quiet moves ran out, simply ate bar by bar. Fearing captures makes
    # the search build sound nets; the exact probe is where the model belongs.
    best = -float("inf")
    for m in _ordered(board):
        board.push(m)
        v = -negamax(board, depth - 1, -beta, -alpha, root_color, ply + 1, model)
        board.pop()
        if v > best:
            best = v
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best

"""Search for misère chess: an exact forced-selfmate probe plus a heuristic
negamax with inverted terminal values (being checkmated = +MATE for the side
that gets mated)."""

from enum import Enum

import chess

from .heuristics import MATE, evaluate
from .profiles import CURRENT, EngineProfile
from .templates import ConstructionPlan


class ProofStatus(Enum):
    """Result of a bounded exact search.

    UNKNOWN is materially different from DISPROVEN: it means the node budget
    expired before the tree was resolved and therefore must never be cached as
    a refutation.
    """

    PROVEN = "proven"
    DISPROVEN = "disproven"
    UNKNOWN = "unknown"


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


def arena_draw(board: chess.Board) -> str | None:
    """The arena's automatic draw adjudications, in the arena's own order.

    Single source of truth shared by the arena, the exact probes, and the
    release scorer: any component that reasons about "the game continues from
    here" must agree with the arena about when it does not. Checkmate and
    stalemate are not draws and stay separate checks at each caller.
    """
    if board.is_insufficient_material():
        return "insufficient-material"
    if board.halfmove_clock >= 100:
        return "fifty-move"
    if board.halfmove_clock >= 8 and board.is_repetition(3):
        return "repetition"
    return None


def _probe_draw(board: chess.Board) -> bool:
    return arena_draw(board) is not None


def _history_counts(board: chess.Board) -> dict:
    """Count reversible-era positions once at the root of a probe.

    The era ends at the last IRREVERSIBLE move — ``is_repetition``'s own
    boundary: captures, pawn moves, castling-rights changes, and ceded en
    passant. The halfmove clock is NOT that boundary (rights changes do
    not reset it), so a clock-bounded walk crossed into positions the
    arena's rule keeps distinct and overcounted them. Mirroring
    ``is_repetition``, the position an irreversible move was played FROM
    is not counted.
    """
    replay = board.copy(stack=True)
    counts: dict = {}
    while True:
        key = replay._transposition_key()
        counts[key] = counts.get(key, 0) + 1
        if not replay.move_stack:
            break
        move = replay.pop()
        if replay.is_irreversible(move):
            break
    return counts


def _record_push(board: chess.Board, move: chess.Move,
                 history: dict):
    board.push(move)
    key = board._transposition_key()
    history[key] = history.get(key, 0) + 1
    return key


def _record_pop(board: chess.Board, history: dict, key) -> None:
    count = history[key] - 1
    if count:
        history[key] = count
    else:
        del history[key]
    board.pop()


def _memo_key(board: chess.Board, n: int, our_node: bool, history: dict):
    """Position key including draw-rule state relevant to a proof.

    python-chess's transposition key intentionally omits the halfmove clock and
    history. Those are part of this game's terminal rules, so merging nodes
    without them can turn a draw into a false proof. Counts are capped at three
    because higher counts are already terminal and should never reach here.
    """
    repetition_state = frozenset(
        (position, min(count, 3)) for position, count in history.items()
    )
    return (
        board._transposition_key(),
        board.halfmove_clock,
        repetition_state,
        n,
        our_node,
    )


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
                  budget, memo, history: dict) -> ProofStatus:
    """Resolve an opponent (AND) node.

    PROVEN means every reply in the opponent's pool either mates us immediately
    or leads to our forced selfmate within n-1 further own moves.

    Lazy: bails out on the first refutation found, so quiet positions cost a
    handful of pushes instead of a full reply classification."""
    key = _memo_key(board, n, False, history)
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
    for cls in classes:
        non_mating_seen = False
        saw_unknown = False
        for r in cls:
            if budget[0] <= 0:
                return ProofStatus.UNKNOWN
            budget[0] -= 1
            pushed_key = _record_push(board, r, history)
            if board.is_checkmate():
                _record_pop(board, history, pushed_key)
                continue
            non_mating_seen = True
            if n <= 1 or _probe_draw(board):
                status = ProofStatus.DISPROVEN
            else:
                status = _forced_self(
                    board, n - 1, model, budget, memo, history
                )
            _record_pop(board, history, pushed_key)
            if status is ProofStatus.DISPROVEN:
                memo[key] = status
                return status
            if status is ProofStatus.UNKNOWN:
                saw_unknown = True
        if non_mating_seen:
            if saw_unknown:
                return ProofStatus.UNKNOWN
            memo[key] = ProofStatus.PROVEN
            return ProofStatus.PROVEN

    # Every legal reply mates us immediately.
    memo[key] = ProofStatus.PROVEN
    return ProofStatus.PROVEN


def _forced_self(board: chess.Board, n: int, model: str | None,
                 budget, memo, history: dict) -> ProofStatus:
    """Resolve one of our (OR) nodes."""
    key = _memo_key(board, n, True, history)
    hit = memo.get(key)
    if hit is not None:
        return hit
    moves = list(board.legal_moves)
    # Checks first: coercion is typically a check whose answers all mate us.
    moves.sort(key=lambda m: 0 if board.gives_check(m) else 1)
    saw_unknown = False
    for m in moves:
        if budget[0] <= 0:
            return ProofStatus.UNKNOWN
        budget[0] -= 1
        pushed_key = _record_push(board, m, history)
        if board.is_checkmate() or board.is_stalemate() or _probe_draw(board):
            _record_pop(board, history, pushed_key)
            continue
        status = _forced_after(board, n, model, budget, memo, history)
        _record_pop(board, history, pushed_key)
        if status is ProofStatus.PROVEN:
            memo[key] = status
            return status
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    if saw_unknown:
        return ProofStatus.UNKNOWN
    memo[key] = ProofStatus.DISPROVEN
    return ProofStatus.DISPROVEN


def selfmate_status(board: chess.Board, n: int, model: str | None, budget,
                    memo=None) -> tuple[ProofStatus, chess.Move | None]:
    """Return the proof status and a proving root move, if one was found."""
    if memo is None:
        memo = {}
    if _probe_draw(board):
        return ProofStatus.DISPROVEN, None
    moves = list(board.legal_moves)
    moves.sort(key=lambda m: 0 if board.gives_check(m) else 1)
    history = _history_counts(board)
    saw_unknown = False
    for m in moves:
        if budget[0] <= 0:
            return ProofStatus.UNKNOWN, None
        budget[0] -= 1
        pushed_key = _record_push(board, m, history)
        if board.is_checkmate() or board.is_stalemate() or _probe_draw(board):
            _record_pop(board, history, pushed_key)
            continue
        status = _forced_after(board, n, model, budget, memo, history)
        _record_pop(board, history, pushed_key)
        if status is ProofStatus.PROVEN:
            return status, m
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    if saw_unknown:
        return ProofStatus.UNKNOWN, None
    return ProofStatus.DISPROVEN, None


def selfmate_in(board: chess.Board, n: int, model: str | None, budget,
                memo=None) -> chess.Move | None:
    """Return a move that forces us to be checkmated within n of our own moves
    against every reply in the opponent's pool (None if no such move within
    the node budget — the probe is best-effort)."""
    status, move = selfmate_status(board, n, model, budget, memo)
    return move if status is ProofStatus.PROVEN else None


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
            model: str | None = None,
            profile: EngineProfile = CURRENT,
            plan: ConstructionPlan | None = None) -> float:
    if board.is_checkmate():
        return MATE - ply  # the side to move is mated: it wins misère chess
    if (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.halfmove_clock >= 100
        or (board.halfmove_clock >= 8 and board.is_repetition(3))
    ):
        contempt = profile.draw_contempt
        return -contempt if board.turn == root_color else contempt
    if depth <= 0:
        return evaluate(board, root_color, model, profile, plan)
    # NOTE: opponent nodes deliberately expand ALL legal moves (adversarial),
    # even under an opponent model. Modeling Zach's capture-aversion here once
    # taught the bot to build cages out of hanging pieces — which Zach, when
    # his quiet moves ran out, simply ate bar by bar. Fearing captures makes
    # the search build sound nets; the exact probe is where the model belongs.
    best = -float("inf")
    for m in _ordered(board):
        board.push(m)
        v = -negamax(
            board, depth - 1, -beta, -alpha, root_color, ply + 1,
            model, profile, plan,
        )
        board.pop()
        if v > best:
            best = v
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best

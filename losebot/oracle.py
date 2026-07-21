"""The opponent-free closing layer: exact forced-selfmate certificates.

``selfmate_in`` proves "from here, we can force our own checkmate within
n of our own moves against EVERY legal reply". No opponent model appears
anywhere in the proof, which is the point: a certificate survives any
policy the opponent turns out to have. The steering layer's job is to
reach positions where this layer fires; this layer's job is to make the
finish unconditional.

Ported from the specialists' probe (which also offered a Zach-modeled
mode — that mode stays a specialist tool). The repetition-era history
walk, the draw-state-aware memo key, and the strict UNKNOWN/DISPROVEN
distinction are the hard-won parts: a budget expiry must never be
cached as a refutation, and merging nodes that differ in clock or
repetition state can turn a draw into a false proof.
"""

from __future__ import annotations

from enum import Enum

import chess

from .outcomes import adjudicate_draw


class ProofStatus(Enum):
    PROVEN = "proven"
    DISPROVEN = "disproven"
    UNKNOWN = "unknown"  # budget expired: not evidence of anything


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
    return adjudicate_draw(board) is not None


def _history_counts(board: chess.Board) -> dict:
    """Count reversible-era positions once at the root of a probe.

    The era ends at the last IRREVERSIBLE move — ``is_repetition``'s own
    boundary: captures, pawn moves, castling-rights changes, ceded en
    passant. Mirroring ``is_repetition``, the position an irreversible
    move was played FROM is not counted.
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


def _record_push(board: chess.Board, move: chess.Move, history: dict):
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
    """Position key including the draw-rule state relevant to a proof."""
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


def _forced_after(board: chess.Board, n: int, budget, memo,
                  history: dict) -> ProofStatus:
    """Opponent (AND) node: every legal reply must mate us now or lose
    within n-1 further own moves. Lazy — bails on the first refutation."""
    key = _memo_key(board, n, False, history)
    hit = memo.get(key)
    if hit is not None:
        return hit
    non_mating_seen = False
    saw_unknown = False
    for reply in board.legal_moves:
        if budget[0] <= 0:
            return ProofStatus.UNKNOWN
        budget[0] -= 1
        pushed_key = _record_push(board, reply, history)
        if board.is_checkmate():
            _record_pop(board, history, pushed_key)
            continue
        non_mating_seen = True
        if n <= 1 or _probe_draw(board):
            status = ProofStatus.DISPROVEN
        else:
            status = _forced_self(board, n - 1, budget, memo, history)
        _record_pop(board, history, pushed_key)
        if status is ProofStatus.DISPROVEN:
            memo[key] = status
            return status
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    if saw_unknown:
        return ProofStatus.UNKNOWN
    # Either every reply mates us immediately, or every non-mating reply
    # was proven lost: the net holds.
    memo[key] = ProofStatus.PROVEN
    return ProofStatus.PROVEN


def _forced_self(board: chess.Board, n: int, budget, memo,
                 history: dict) -> ProofStatus:
    """Our (OR) node: one move whose every answer keeps the net closed."""
    key = _memo_key(board, n, True, history)
    hit = memo.get(key)
    if hit is not None:
        return hit
    moves = list(board.legal_moves)
    # Checks first: coercion is typically a check whose answers all mate us.
    moves.sort(key=lambda m: 0 if board.gives_check(m) else 1)
    saw_unknown = False
    for move in moves:
        if budget[0] <= 0:
            return ProofStatus.UNKNOWN
        budget[0] -= 1
        pushed_key = _record_push(board, move, history)
        if board.is_checkmate() or board.is_stalemate() or _probe_draw(board):
            _record_pop(board, history, pushed_key)
            continue
        status = _forced_after(board, n, budget, memo, history)
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


def selfmate_status(board: chess.Board, n: int, budget,
                    memo=None) -> tuple[ProofStatus, chess.Move | None]:
    """Proof status and a proving root move, if one was found.

    ``budget`` is a one-element mutable list of remaining node pushes,
    shared across iterative calls so a move's total probe spend is
    capped regardless of how many depths were tried.
    """
    if memo is None:
        memo = {}
    if _probe_draw(board):
        return ProofStatus.DISPROVEN, None
    moves = list(board.legal_moves)
    moves.sort(key=lambda m: 0 if board.gives_check(m) else 1)
    history = _history_counts(board)
    saw_unknown = False
    for move in moves:
        if budget[0] <= 0:
            return ProofStatus.UNKNOWN, None
        budget[0] -= 1
        pushed_key = _record_push(board, move, history)
        if board.is_checkmate() or board.is_stalemate() or _probe_draw(board):
            _record_pop(board, history, pushed_key)
            continue
        status = _forced_after(board, n, budget, memo, history)
        _record_pop(board, history, pushed_key)
        if status is ProofStatus.PROVEN:
            return status, move
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    if saw_unknown:
        return ProofStatus.UNKNOWN, None
    return ProofStatus.DISPROVEN, None


def selfmate_in(board: chess.Board, n: int, budget,
                memo=None) -> chess.Move | None:
    """A move forcing our checkmate within n own moves against every
    reply, or None (best-effort under the node budget)."""
    status, move = selfmate_status(board, n, budget, memo)
    return move if status is ProofStatus.PROVEN else None

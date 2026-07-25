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
    """What a prover concluded — and what it is entitled to conclude.

    The two non-answers are not the same non-answer, and neither is a
    refutation. UNKNOWN means the budget died mid-proof. NOT_FOUND
    means the search was never ENTITLED to a refutation, because it
    only looked at part of its own move set. Only DISPROVEN asserts
    that no certificate exists, and only the exhaustive prover may
    ever say it.
    """

    PROVEN = "proven"
    DISPROVEN = "disproven"
    UNKNOWN = "unknown"  # budget expired: not evidence of anything
    NOT_FOUND = "not-found"  # restricted move set: also not evidence


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


# --- The forcing-restricted certifier: sound, incomplete, deep -------
#
# The exhaustive prover above pays ~33x per rung, and the 2026-07-24
# reach verdict priced where that goes: FINDING a certificate is cheap
# (median 194 nodes; every one of the 22 the project has ever landed
# came in under the 50k cap), while DISPROVING one is what costs (n=3
# median 65,998; n=4 median 2,044,599). The engine consumes only
# PROVEN — ``_probe`` branches on it and on budget, the sub-probe adds
# only UNKNOWN, and the search collapses every other answer to None —
# so the exhaustive price buys a verdict nothing reads.
#
# The ~33x is our OR-node width: the proof tries all ~30 own moves
# while the opponent's AND-node below usually bails on its first
# refutation. This certifier restricts OUR node to the ``width`` most
# FORCING moves (fewest replies, checks first) and leaves the
# opponent's node EXHAUSTIVE, which is where soundness actually lives.
# Both of the project's organic device families are forcing by
# construction — check chains behind the recapture donations,
# only-reply boxes behind the closing zugzwang — so the restriction is
# aimed at keeping precisely the moves that have ever converted.
#
# The trade is stated in the return type: a PROVEN here is a real
# certificate, identical in force to the exhaustive prover's. A
# failure is NOT_FOUND, never DISPROVEN, because the refutation was
# searched over a restricted move set. Reusing DISPROVEN would launder
# a restriction into a refutation — the exact sin the UNKNOWN
# distinction exists to prevent.


def _forcing_key(board: chess.Board, n: int, our_node: bool,
                 history: dict, width: int):
    """Memo key tagged with the restriction that produced it.

    Restricted DISPROVEN entries are restriction-tainted: they mean
    "no proof among the top ``width`` forcing moves", which the
    exhaustive prover must never read as "no proof". Tagging the key
    with the width makes a shared dict SAFE rather than merely
    discouraged — the two provers cannot collide on a key, and two
    different widths cannot either. Sharing then costs only memory,
    and no caller can turn it into a false refutation by accident.
    """
    return ("forcing", width) + _memo_key(board, n, our_node, history)


def _forcing_order(board: chess.Board, budget) -> tuple[list, bool]:
    """Our candidates, most-forcing first: fewest replies, checks ahead.

    Each candidate costs one budget node, because generating its reply
    set is real work; a free ordering pass would understate this
    prover's true price against the exhaustive one it is compared to.
    The UCI string makes the sort total, so the restricted move SET is
    a function of the position and never of generation order.

    Returns the candidates AND whether the budget cut the pass short.
    That flag is not bookkeeping: a node whose ordering was truncated
    has not seen its own move set, so it owes UNKNOWN — without the
    flag an empty list falls straight through to DISPROVEN and a
    starved node claims a refutation, which is the one thing no prover
    here is allowed to do.
    """
    scored = []
    truncated = False
    for move in board.legal_moves:
        if budget[0] <= 0:
            truncated = True
            break
        budget[0] -= 1
        board.push(move)
        replies = board.legal_moves.count()
        check = board.is_check()
        board.pop()
        scored.append((0 if check else 1, replies, move.uci(), move))
    scored.sort()
    return [entry[3] for entry in scored], truncated


def _forcing_after(board, n: int, budget, memo, history: dict,
                   width: int) -> ProofStatus:
    """Opponent (AND) node, EXHAUSTIVE — soundness lives here, intact.

    Every legal reply is answered. Restricting this node is what would
    make a PROVEN a lie; restricting the OR node above only makes a
    failure uninformative.
    """
    key = _forcing_key(board, n, False, history, width)
    hit = memo.get(key)
    if hit is not None:
        return hit
    saw_unknown = False
    for reply in board.legal_moves:
        if budget[0] <= 0:
            return ProofStatus.UNKNOWN
        budget[0] -= 1
        pushed = _record_push(board, reply, history)
        if board.is_checkmate():
            _record_pop(board, history, pushed)
            continue
        if n <= 1 or _probe_draw(board):
            status = ProofStatus.DISPROVEN
        else:
            status = _forcing_self(board, n - 1, budget, memo, history, width)
        _record_pop(board, history, pushed)
        if status is ProofStatus.DISPROVEN:
            memo[key] = status
            return status
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    if saw_unknown:
        return ProofStatus.UNKNOWN
    memo[key] = ProofStatus.PROVEN
    return ProofStatus.PROVEN


def _forcing_self(board, n: int, budget, memo, history: dict,
                  width: int) -> ProofStatus:
    """Our (OR) node, RESTRICTED to the ``width`` most forcing moves.

    A miss returns DISPROVEN into the AND node above — internally the
    two provers speak the same language, and within one fixed width
    the answer is consistent, so the memo is sound against itself.
    That internal DISPROVEN is exactly what makes the whole prover
    incomplete, and why the public entry point relabels a top-level
    failure NOT_FOUND instead of passing the enum through.
    """
    key = _forcing_key(board, n, True, history, width)
    hit = memo.get(key)
    if hit is not None:
        return hit
    candidates, truncated = _forcing_order(board, budget)
    saw_unknown = truncated
    for move in candidates[:width]:
        if budget[0] <= 0:
            return ProofStatus.UNKNOWN
        budget[0] -= 1
        pushed = _record_push(board, move, history)
        if board.is_checkmate() or board.is_stalemate() or _probe_draw(board):
            _record_pop(board, history, pushed)
            continue
        status = _forcing_after(board, n, budget, memo, history, width)
        _record_pop(board, history, pushed)
        if status is ProofStatus.PROVEN:
            memo[key] = status
            return status
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    if saw_unknown:
        return ProofStatus.UNKNOWN
    memo[key] = ProofStatus.DISPROVEN
    return ProofStatus.DISPROVEN


def forcing_selfmate_status(board: chess.Board, n: int, budget, memo=None,
                            width: int = 5
                            ) -> tuple[ProofStatus, chess.Move | None]:
    """Restricted proof status and a proving root move, if one exists.

    PROVEN carries the same force as ``selfmate_status``'s. Every
    other answer is NOT_FOUND or UNKNOWN; this function never returns
    DISPROVEN, and the selftest asserts that directly.
    """
    if memo is None:
        memo = {}
    if width <= 0:
        return ProofStatus.NOT_FOUND, None
    if _probe_draw(board):
        # Not DISPROVEN: this prover does not issue refutations, even
        # ones it could justify. One exit, one meaning.
        return ProofStatus.NOT_FOUND, None
    history = _history_counts(board)
    candidates, truncated = _forcing_order(board, budget)
    saw_unknown = truncated
    for move in candidates[:width]:
        if budget[0] <= 0:
            return ProofStatus.UNKNOWN, None
        budget[0] -= 1
        pushed_key = _record_push(board, move, history)
        if board.is_checkmate() or board.is_stalemate() or _probe_draw(board):
            _record_pop(board, history, pushed_key)
            continue
        status = _forcing_after(board, n, budget, memo, history, width)
        _record_pop(board, history, pushed_key)
        if status is ProofStatus.PROVEN:
            return status, move
        if status is ProofStatus.UNKNOWN:
            saw_unknown = True
    if saw_unknown:
        return ProofStatus.UNKNOWN, None
    return ProofStatus.NOT_FOUND, None

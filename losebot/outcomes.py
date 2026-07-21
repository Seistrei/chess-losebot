"""Game termination rules and the outcome taxonomy.

Single source of truth for "when does the game stop and what do we call
it". The taxonomy exists because the project's one success metric —
*forced* selfmates — was historically entangled with mates the opponent
merely chose to play (mercy mates grade our zugzwangs on a curve), and
because the failure modes (stalemating them, accidentally mating them,
each draw kind) need separate ledger lines to be diagnosable.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

# Draw adjudications, in adjudication order. Checkmate and stalemate are
# not draws and are checked separately by every caller.
INSUFFICIENT = "insufficient-material"
FIFTY_MOVE = "fifty-move"
REPETITION = "repetition"
MAX_PLIES = "max-plies"


def adjudicate_draw(board: chess.Board) -> str | None:
    """The automatic draw rules shared by play loops and exact probes.

    Mirrors the specialists' arena rules so results stay comparable:
    insufficient material, the 100-halfmove clock, and threefold
    repetition (guarded by the clock so the expensive scan only runs
    once a repetition is even possible).
    """
    if board.is_insufficient_material():
        return INSUFFICIENT
    if board.halfmove_clock >= 100:
        return FIFTY_MOVE
    if board.halfmove_clock >= 8 and board.is_repetition(3):
        return REPETITION
    return None


@dataclass(frozen=True)
class GameOutcome:
    """How a finished game ended, before taking anyone's side.

    ``mated``/``stalemated`` name the color on the receiving end (None
    when the game was drawn by rule). ``forced`` is the last-ply test:
    the side that delivered mate had no legal alternative — every one
    of its moves checkmated. That is the project's honest win
    condition; a mate delivered with alternatives available is mercy.
    """

    reason: str
    mated: chess.Color | None = None
    stalemated: chess.Color | None = None
    forced: bool = False


def mate_was_forced(final_board: chess.Board) -> bool:
    """True if the mating side had only mating moves (the last-ply test).

    Requires the final board to carry its move stack. A mate from a
    freshly-set-up mated FEN (no history) is unverifiable and counts as
    not forced — the conservative reading.
    """
    if not final_board.is_checkmate() or not final_board.move_stack:
        return False
    replay = final_board.copy(stack=True)
    replay.pop()
    for move in replay.legal_moves:
        replay.push(move)
        mates = replay.is_checkmate()
        replay.pop()
        if not mates:
            return False
    return True


def classify(board: chess.Board, max_plies: int | None = None) -> GameOutcome | None:
    """Classify a position as a finished game, or None if play continues."""
    if board.is_checkmate():
        return GameOutcome(
            reason="checkmate",
            mated=board.turn,
            forced=mate_was_forced(board),
        )
    if board.is_stalemate():
        return GameOutcome(reason="stalemate", stalemated=board.turn)
    draw = adjudicate_draw(board)
    if draw is not None:
        return GameOutcome(reason=draw)
    if max_plies is not None and len(board.move_stack) >= max_plies:
        return GameOutcome(reason=MAX_PLIES)
    return None


# Focal labels: the outcome from the engine-under-test's point of view.
SELFMATE_FORCED = "selfmate-forced"   # the goal: we were mated, they had no choice
SELFMATE_MERCY = "selfmate-mercy"     # we were mated because they cooperated
ACCIDENT_ZUGZWANG = "accident-zugzwang"  # we mated them with no alternative
ACCIDENT_MATE = "accident-mate"       # we mated them with alternatives available
STALEMATE_THEM = "stalemate-them"     # we suffocated them without a mate on the menu
STALEMATE_US = "stalemate-us"         # they suffocated us

FOCAL_LABELS = (
    SELFMATE_FORCED,
    SELFMATE_MERCY,
    ACCIDENT_ZUGZWANG,
    ACCIDENT_MATE,
    STALEMATE_THEM,
    STALEMATE_US,
    INSUFFICIENT,
    FIFTY_MOVE,
    REPETITION,
    MAX_PLIES,
)


def focal_label(outcome: GameOutcome, focal_color: chess.Color) -> str:
    """Name the outcome from the focal (losing-seeking) player's side."""
    if outcome.mated is not None:
        if outcome.mated == focal_color:
            return SELFMATE_FORCED if outcome.forced else SELFMATE_MERCY
        return ACCIDENT_ZUGZWANG if outcome.forced else ACCIDENT_MATE
    if outcome.stalemated is not None:
        if outcome.stalemated == focal_color:
            return STALEMATE_US
        return STALEMATE_THEM
    return outcome.reason

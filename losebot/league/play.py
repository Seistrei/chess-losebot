"""One game, cleanly: play loop, record, PGN.

Anything with ``choose_move(board) -> Move`` can sit in either seat.
The loop owns termination via the outcomes module, so every component
in the project agrees about when a game is over and what it is called.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.pgn

from ..outcomes import GameOutcome, classify, focal_label


@dataclass
class GameRecord:
    family: str
    game_index: int
    seed: int
    focal_color: chess.Color
    white_name: str
    black_name: str
    label: str            # focal outcome label (the taxonomy)
    reason: str           # raw termination reason
    forced: bool
    plies: int
    seconds: float
    final_fen: str
    # Engine gauges() snapshot (probe/search telemetry), when the
    # engine exposes one. Persisted so report.json can support probe
    # diagnoses — console lines and ordinary PGNs are not retained.
    probes: dict | None = None

    @property
    def focal_seat(self) -> str:
        return "white" if self.focal_color == chess.WHITE else "black"


def play_game(
    white,
    black,
    max_plies: int = 240,
    start_fen: str | None = None,
) -> tuple[chess.Board, GameOutcome]:
    board = chess.Board(start_fen) if start_fen else chess.Board()
    while True:
        outcome = classify(board, max_plies=max_plies)
        if outcome is not None:
            return board, outcome
        mover = white if board.turn == chess.WHITE else black
        board.push(mover.choose_move(board))


def record_game(
    board: chess.Board,
    outcome: GameOutcome,
    family: str,
    game_index: int,
    seed: int,
    focal_color: chess.Color,
    white_name: str,
    black_name: str,
    seconds: float,
    probes: dict | None = None,
) -> GameRecord:
    return GameRecord(
        family=family,
        game_index=game_index,
        seed=seed,
        focal_color=focal_color,
        white_name=white_name,
        black_name=black_name,
        label=focal_label(outcome, focal_color),
        reason=outcome.reason,
        forced=outcome.forced,
        plies=len(board.move_stack),
        seconds=seconds,
        final_fen=board.fen(),
        probes=probes,
    )


def save_pgn(board: chess.Board, record: GameRecord, out_dir: Path) -> Path:
    game = chess.pgn.Game.from_board(board)
    game.headers["Event"] = "Misere league"
    game.headers["White"] = record.white_name
    game.headers["Black"] = record.black_name
    if record.label.startswith("selfmate") or record.label.startswith(
        "accident"
    ):
        mated_white = (
            (record.focal_color == chess.WHITE)
            == record.label.startswith("selfmate")
        )
        game.headers["Result"] = "0-1" if mated_white else "1-0"
    else:
        game.headers["Result"] = "1/2-1/2"
    game.headers["Termination"] = (
        f"{record.reason}; focal={record.focal_seat}; {record.label}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (
        f"{record.family}_g{record.game_index:02d}_{record.label}.pgn"
    )
    with open(path, "w", encoding="utf-8") as handle:
        print(game, file=handle)
    return path


def timed_game(white, black, **kwargs):
    started = time.monotonic()
    board, outcome = play_game(white, black, **kwargs)
    return board, outcome, time.monotonic() - started

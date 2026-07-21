"""Drive a league: fresh objects per game, seats alternated, records out.

Every game constructs a fresh opponent (own RNG stream, seed = seed0 +
game index) and a fresh engine. The old arena reused one bot and one
kernel RNG across a match, so two engine versions could only be A/B'd
one-invocation-per-seed; here per-game independence is structural.
"""

from __future__ import annotations

from pathlib import Path

import chess

from ..models import ModelPlayer, make_model
from .play import record_game, save_pgn, timed_game
from .report import render, summarize, write_json


def run_league(
    engine_factory,
    families,
    games_per_family: int = 10,
    max_plies: int = 240,
    out_dir: Path | None = None,
    seed0: int = 0,
    log=print,
) -> tuple[dict, list]:
    """``engine_factory()`` must return a fresh engine per call."""
    records = []
    for family in families:
        for index in range(games_per_family):
            seed = seed0 + index
            opponent = ModelPlayer(make_model(family), seed=seed)
            engine = engine_factory()
            focal_color = chess.WHITE if index % 2 == 0 else chess.BLACK
            if focal_color == chess.WHITE:
                white, black = engine, opponent
            else:
                white, black = opponent, engine
            board, outcome, seconds = timed_game(
                white, black, max_plies=max_plies
            )
            record = record_game(
                board,
                outcome,
                family=family,
                game_index=index,
                seed=seed,
                focal_color=focal_color,
                white_name=white.name,
                black_name=black.name,
                seconds=seconds,
            )
            records.append(record)
            oracle_hits = getattr(engine, "forced_selfmates_found", None)
            oracle_note = (
                f" oracle={oracle_hits}" if oracle_hits is not None else ""
            )
            log(
                f"{family} g{index:02d} (focal={record.focal_seat}): "
                f"{record.label} in {record.plies} plies "
                f"[{seconds:.1f}s]{oracle_note}",
            )
            if out_dir is not None:
                save_pgn(board, record, Path(out_dir))
    summary = summarize(records)
    log("")
    log(render(summary))
    return summary, records


def league_metadata(engine_desc: dict, families, games_per_family: int,
                    max_plies: int, seed0: int) -> dict:
    from .. import __version__

    return {
        "package_version": __version__,
        "engine": engine_desc,
        "families": list(families),
        "games_per_family": games_per_family,
        "max_plies": max_plies,
        "seed0": seed0,
    }


def save_report(summary, records, metadata, out_dir: Path) -> Path:
    return write_json(summary, records, metadata, Path(out_dir))

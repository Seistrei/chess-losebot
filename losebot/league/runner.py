"""Drive a league: fresh objects per game, seed-paired seats, records out.

Every game constructs a fresh opponent (own RNG stream) and a fresh
engine. The old arena reused one bot and one kernel RNG across a
match, so two engine versions could only be A/B'd one-invocation-per-
seed; here per-game independence is structural.

Seats are SEED-PAIRED, not merely alternated: each opponent seed plays
once with the engine as White and once as Black (game 2k and 2k+1
share seed k), so seed effects and seat effects stay unconfounded and
the pair is the benchmark's natural unit. Keep ``games_per_family``
even; an odd count leaves the last seed half-paired.
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
            seed = seed0 + index // 2
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
            sub_hits = getattr(engine, "sub_probe_hits", None)
            if sub_hits is not None:
                # unk = gated calls whose None meant UNKNOWN (budget),
                # not refuted: sub=0/N is only a null when unk is low.
                oracle_note += (
                    f" sub={sub_hits}/{engine.sub_probe_calls}"
                    f" unk={getattr(engine, 'sub_probe_unknowns', 0)}"
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

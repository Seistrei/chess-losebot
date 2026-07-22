"""CLI: selftest | play | league | oracle.

Thin dispatch only — behavior lives in the modules. Bare invocation
runs the selftest (the Docker image's default command).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import chess

from .engine import ModelEngine
from .league.families import resolve_families
from .league.play import record_game, save_pgn, timed_game
from .league.runner import league_metadata, run_league, save_report
from .models import MODEL_NAMES, ModelPlayer, make_model
from .oracle import selfmate_status


def _add_engine_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--belief", default="sloppy", choices=MODEL_NAMES,
        help="the engine's internal opponent model (default: sloppy — "
        "beliefs must include captures; that lesson cost a fork)",
    )
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument(
        "--topk", type=int, default=6,
        help="reply cap per chance node; an oversized probability class "
        "is represented by a seeded unbiased subset carrying its mass",
    )
    parser.add_argument(
        "--coverage", type=float, default=0.85,
        help="minimum probability mass a trimmed reply set must cover",
    )
    parser.add_argument(
        "--probe-n", type=int, default=4,
        help="root oracle depth; iterative deepening self-regulates — "
        "wide positions stop early on the cap, narrow ones reach n=4",
    )
    parser.add_argument("--probe-cap", type=int, default=50_000)
    parser.add_argument(
        "--sub-probe-n", type=int, default=2,
        help="oracle depth for sub-root probes at steering our-nodes "
        "(0 disables them)",
    )
    parser.add_argument("--sub-probe-cap", type=int, default=100_000)
    parser.add_argument(
        "--sub-probe-men", type=int, default=5,
        help="sub-probes fire once the opponent has at most this many "
        "non-king men (or any time our king is in check)",
    )
    parser.add_argument(
        "--forced-ext", type=int, default=0,
        help="forced-sequence extension budget per line: plies in "
        "check or with a single legal reply spend this instead of "
        "depth (0 disables)",
    )
    parser.add_argument(
        "--deep-depth", type=int, default=0,
        help="steering depth in stripped positions (0 keeps --depth "
        "everywhere)",
    )
    parser.add_argument(
        "--deep-men", type=int, default=3,
        help="deep-depth gate: opponent at most this many non-king "
        "men, or reduced to king+pawns of any count",
    )
    parser.add_argument(
        "--deep-topk", type=int, default=0,
        help="reply cap while deepened (0 keeps --topk; stripped "
        "distributions concentrate, so narrower often buys the depth)",
    )
    parser.add_argument(
        "--node-cap", type=int, default=0,
        help="per-move steering node clamp: past it the search "
        "answers from the leaf eval instead of stalling (0 disables)",
    )


def _build_engine(args) -> ModelEngine:
    return ModelEngine(
        belief=make_model(args.belief),
        depth=args.depth,
        topk=args.topk,
        coverage=args.coverage,
        probe_n=args.probe_n,
        probe_cap=args.probe_cap,
        sub_probe_n=args.sub_probe_n,
        sub_probe_cap=args.sub_probe_cap,
        sub_probe_men=args.sub_probe_men,
        forced_ext=args.forced_ext,
        deep_depth=args.deep_depth,
        deep_men=args.deep_men,
        deep_topk=args.deep_topk,
        node_cap=args.node_cap,
    )


def _cmd_selftest(_args) -> int:
    from .selftest import run

    return run()


def _cmd_play(args) -> int:
    engine = _build_engine(args)
    opponent = ModelPlayer(make_model(args.opponent), seed=args.seed)
    focal_color = chess.WHITE if args.seat == "white" else chess.BLACK
    white, black = (
        (engine, opponent) if focal_color == chess.WHITE
        else (opponent, engine)
    )
    board, outcome, seconds = timed_game(
        white, black, max_plies=args.max_plies, start_fen=args.fen
    )
    record = record_game(
        board, outcome, family=args.opponent, game_index=0, seed=args.seed,
        focal_color=focal_color, white_name=white.name,
        black_name=black.name, seconds=seconds,
    )
    print(
        f"{record.label} ({record.reason}) in {record.plies} plies "
        f"[{seconds:.1f}s]; oracle certificates: "
        f"{engine.forced_selfmates_found}; final: {record.final_fen}"
    )
    if args.pgn_dir:
        path = save_pgn(board, record, Path(args.pgn_dir))
        print(f"pgn: {path}")
    return 0


def _cmd_league(args) -> int:
    families = resolve_families(args.families)
    if args.engine == "specialist":
        from .league.specialist import SpecialistPlayer

        def engine_factory():
            return SpecialistPlayer(
                profile=args.specialist_profile,
                model=args.specialist_model or None,
                tier=args.specialist_tier,
            )

        engine_desc = {
            "kind": "specialist",
            "profile": args.specialist_profile,
            "model": args.specialist_model,
            "tier": args.specialist_tier,
        }
    else:

        def engine_factory():
            return _build_engine(args)

        engine_desc = {
            "kind": "model",
            "belief": args.belief,
            "depth": args.depth,
            "topk": args.topk,
            "coverage": args.coverage,
            "probe_n": args.probe_n,
            "probe_cap": args.probe_cap,
            "sub_probe_n": args.sub_probe_n,
            "sub_probe_cap": args.sub_probe_cap,
            "sub_probe_men": args.sub_probe_men,
            "forced_ext": args.forced_ext,
            "deep_depth": args.deep_depth,
            "deep_men": args.deep_men,
            "deep_topk": args.deep_topk,
            "node_cap": args.node_cap,
        }

    out_dir = Path(
        args.out
        or f"games/league/{args.engine}-{time.strftime('%Y%m%d-%H%M%S')}"
    )
    summary, records = run_league(
        engine_factory,
        families,
        games_per_family=args.games,
        max_plies=args.max_plies,
        out_dir=out_dir,
        seed0=args.seed0,
    )
    metadata = league_metadata(
        engine_desc, families, args.games, args.max_plies, args.seed0
    )
    path = save_report(summary, records, metadata, out_dir)
    print(f"\nreport: {path}")
    return 0


def _cmd_oracle(args) -> int:
    board = chess.Board(args.fen)
    budget = [args.cap]
    memo: dict = {}
    for n in range(1, args.n + 1):
        status, move = selfmate_status(board, n, budget, memo)
        san = board.san(move) if move is not None else "-"
        print(
            f"n={n}: {status.value} move={san} "
            f"(budget left {budget[0]}/{args.cap})"
        )
        if move is not None or budget[0] <= 0:
            break
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="losebot")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("selftest", help="run the fast test suite")

    play = sub.add_parser("play", help="one game vs an opponent family")
    play.add_argument("--opponent", default="sloppy", choices=MODEL_NAMES)
    play.add_argument("--seed", type=int, default=0)
    play.add_argument("--seat", default="white", choices=("white", "black"))
    play.add_argument("--max-plies", type=int, default=240)
    play.add_argument("--fen", default=None)
    play.add_argument("--pgn-dir", default=None)
    _add_engine_args(play)

    league = sub.add_parser("league", help="run the frozen benchmark")
    league.add_argument(
        "--engine", default="model", choices=("model", "specialist")
    )
    league.add_argument("--families", default="all")
    league.add_argument("--games", type=int, default=10)
    league.add_argument("--max-plies", type=int, default=240)
    league.add_argument("--seed0", type=int, default=0)
    league.add_argument("--out", default=None)
    league.add_argument("--specialist-profile", default="field")
    league.add_argument("--specialist-model", default="zach")
    league.add_argument("--specialist-tier", default="fast",
                        choices=("fast", "full"))
    _add_engine_args(league)

    oracle_cmd = sub.add_parser("oracle", help="probe a FEN for certificates")
    oracle_cmd.add_argument("--fen", required=True)
    oracle_cmd.add_argument("--n", type=int, default=3)
    oracle_cmd.add_argument("--cap", type=int, default=200_000)

    args = parser.parse_args(argv)
    command = args.command or "selftest"
    handler = {
        "selftest": _cmd_selftest,
        "play": _cmd_play,
        "league": _cmd_league,
        "oracle": _cmd_oracle,
    }[command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())

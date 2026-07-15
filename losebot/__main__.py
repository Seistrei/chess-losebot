"""CLI: python -m losebot selftest | arena --white losebot --black zach -n 10"""

import argparse
import sys

import chess

from .arena import run_match
from .bot import LoseBot
from .opponents import RandomBot, WorstfishBot, ZachBot
from .planning import modeled_herding_move
from .profiles import PROFILES
from .search import (
    ProofStatus,
    _probe_draw,
    gives_mate,
    selfmate_in,
    selfmate_status,
)
from .templates import (
    ConstructionPlan,
    best_pawn_mate_template,
    herding_metrics,
)


def make_bot(kind: str, args, color_tag: str):
    if kind == "losebot":
        return LoseBot(
            depth=args.depth,
            opponent_model=args.model,
            profile=args.profile,
            probe_cap=args.probe_cap,
            max_probe_n=args.probe_depth,
        )
    if kind == "zach":
        return ZachBot(seed=args.seed)
    if kind == "random":
        return RandomBot(seed=args.seed + 1)
    if kind == "worstfish":
        return WorstfishBot(nodes=args.nodes)
    raise SystemExit(f"unknown bot: {kind}")


def selftest() -> int:
    failures = 0

    def check(label: str, ok: bool, detail: str = ""):
        nonlocal failures
        print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures += 1

    # 1. Forced selfmate-in-1: White plays Rb7, after which Black's only legal
    # moves (f5 and h5) both deliver checkmate to White.
    board = chess.Board("8/8/5pkp/6p1/6K1/5PPP/8/1R6 w - - 0 1")
    mv = selfmate_in(board, 1, None, [100_000])
    ok = mv is not None
    detail = ""
    if ok:
        detail = f"probe found {board.san(mv)}"
        board.push(mv)
        replies = list(board.legal_moves)
        all_mate = bool(replies)
        for r in replies:
            board.push(r)
            if not board.is_checkmate():
                all_mate = False
            board.pop()
        ok = all_mate
        detail += f"; all {len(replies)} replies mate us: {all_mate}"
    check("selfmate_in finds a forced selfmate-in-1", ok, detail)

    # 2. LoseBot refuses a free mate-in-1 (Rb8# available, must not play it).
    board = chess.Board("6k1/5ppp/8/8/8/8/8/1R4K1 w - - 0 1")
    bot = LoseBot(depth=2)
    mv = bot.choose_move(board)
    check(
        "LoseBot refuses to deliver an available mate",
        not gives_mate(board, mv),
        f"chose {board.san(mv)}",
    )

    # 3. Zach delivers mate only when it is the only legal option.
    board = chess.Board("8/1R6/5pkp/6p1/6K1/5PPP/8/8 b - - 1 1")
    zach = ZachBot(seed=42)
    mv = zach.choose_move(board)
    board.push(mv)
    check("Zach mates when forced (zugzwang)", board.is_checkmate(),
          f"played into checkmate: {board.is_checkmate()}")

    # 4. Smoke game completes.
    from .arena import play_game

    _, reason, mated = play_game(LoseBot(depth=1, opponent_model="zach"),
                                 ZachBot(seed=7), max_plies=40)
    check("smoke game completes", True, f"reason={reason}, mated={mated}")

    # 5. Exhausting a node budget is UNKNOWN, not a refutation. Reusing the
    # same memo with a real budget must still find the known selfmate.
    board = chess.Board("8/8/5pkp/6p1/6K1/5PPP/8/1R6 w - - 0 1")
    memo: dict = {}
    status, _ = selfmate_status(board, 1, None, [0], memo)
    status_after, mv = selfmate_status(board, 1, None, [100_000], memo)
    check(
        "probe distinguishes budget exhaustion from a refutation",
        status is ProofStatus.UNKNOWN
        and status_after is ProofStatus.PROVEN
        and mv is not None,
        f"first={status.value}; retry={status_after.value}",
    )

    # 6. Exact proofs use the same repetition terminal as the arena.
    board = chess.Board()
    for san in ("Nf3", "Nf6", "Ng1", "Ng8") * 2:
        board.push_san(san)
    check(
        "probe treats threefold repetition as a draw",
        _probe_draw(board),
        f"halfmove={board.halfmove_clock}; repetition={board.is_repetition(3)}",
    )

    # 7. The historic configuration remains independently selectable.
    check(
        "versioned engine profiles are available",
        LoseBot(profile="current").profile.name == "current"
        and LoseBot(profile="herding").profile.name == "herding"
        and LoseBot(profile="planner").profile.name == "planner"
        and LoseBot(profile="template").profile.name == "template"
        and LoseBot(profile="v03").profile.name == "v03",
    )

    # 8. The known b6-b5 construction is represented as one coupled target:
    # White king a4 is checked, Black king c5 defends the pawn on b5, and
    # White's own a3/b3/a5 men form part of the cage.
    board = chess.Board("8/8/Bp6/N1k5/K2R4/PP6/8/8 w - - 0 1")
    target = best_pawn_mate_template(board, chess.WHITE)
    check(
        "pawn-mate template recognizes the known b6-b5 construction",
        target is not None
        and target.uci == "b6b5"
        and target.checked_square == chess.A4
        and target.our_king_steps == 0
        and target.defender_steps == 0
        and target.cage_occupancy >= 3,
        "none" if target is None else (
            f"{target.uci} checks {chess.square_name(target.checked_square)}; "
            f"distance={target.setup_distance}; cage={target.cage_occupancy}"
        ),
    )

    # 9. A construction plan resolves the same execution pawn/checking side
    # instead of switching to whichever template is cheapest at each leaf.
    plan = (
        None
        if target is None
        else ConstructionPlan.from_template(target, created_ply=0)
    )
    resolved = None if plan is None else plan.resolve(board, chess.WHITE)
    check(
        "construction plan preserves its pawn and checking side",
        resolved is not None
        and resolved.uci == "b6b5"
        and resolved.checked_square == chess.A4,
        "none" if plan is None else plan.label,
    )
    check(
        "complete unblocked construction is ready for release/proof",
        target is not None and target.ready_to_release,
    )

    # 10. A mobile piece in front of the execution pawn is recognized as a
    # temporary holding blocker, allowing the planner to freeze Zach's pawn.
    hold_board = chess.Board(
        "k7/p7/1p6/1B6/3Q4/2N5/PPP2PPP/R3K2R b - - 1 1"
    )
    held_target = (
        None if plan is None else plan.resolve(hold_board, chess.WHITE)
    )
    check(
        "construction plan recognizes a mobile pawn-holding blocker",
        held_target is not None
        and held_target.uci == "b6b5"
        and held_target.holding_blocker
        and held_target.holding_blocker_defended
        and not held_target.ready_to_release,
        "none" if held_target is None else (
            f"{held_target.uci}; holding={held_target.holding_blocker}; "
            f"defended={held_target.holding_blocker_defended}"
        ),
    )

    # 11. The fallback search must not voluntarily abandon an incomplete hold.
    hold_regression = chess.Board(
        "1R6/p2k4/Q7/2p5/5B2/2N5/PPP2PPP/2K5 w - - 4 5"
    )
    hold_bot = LoseBot(
        depth=1,
        opponent_model="zach",
        profile="planner",
        probe_cap=0,
        max_probe_n=1,
    )
    hold_bot.plan = ConstructionPlan(
        pawn_file=chess.square_file(chess.A7),
        checked_side=1,
        created_ply=0,
    )
    held_move = hold_bot.choose_move(hold_regression)
    check(
        "planner does not voluntarily abandon an incomplete pawn hold",
        held_move.from_square != chess.A6
        and hold_bot.hold_moves_filtered > 0,
        f"chose {hold_regression.san(held_move)}; "
        f"filtered={hold_bot.hold_moves_filtered}",
    )

    # 12. The depth-two herding experiment must classify replies inside its
    # budget, prune quiet setup moves, and populate only completed memo values.
    selective_board = chess.Board(
        "5R2/1k6/1p6/1B1N4/2K5/pPP5/P4PPP/7R w - - 36 61"
    )
    selective_plan = ConstructionPlan(
        pawn_file=chess.square_file(chess.B6),
        checked_side=1,
        created_ply=0,
    )
    modeled = modeled_herding_move(
        selective_board,
        selective_plan,
        chess.WHITE,
        list(selective_board.legal_moves),
        "zach",
        max_n=2,
        node_cap=5_000,
        time_limit_ms=1_000,
        candidate_limit=4,
        memoize=True,
    )
    check(
        "selective depth-two herding is bounded and memoized",
        modeled.nodes <= 5_000
        and modeled.candidates_pruned > 0
        and modeled.memo_entries > 0,
        f"nodes={modeled.nodes}; pruned={modeled.candidates_pruned}; "
        f"cache={modeled.cache_hits}/{modeled.memo_entries}; "
        f"complete={modeled.complete}",
    )

    # 13. A promoted piece means the king-and-pawns phase has ended. The
    # construction must be dropped so the ordinary search can remove it.
    promoted_board = chess.Board(
        "1R6/k7/1p6/1BR5/PK6/1nP5/5PPP/8 w - - 13 61"
    )
    promoted_bot = LoseBot(
        depth=1,
        opponent_model="zach",
        profile="herding",
        probe_cap=0,
        max_probe_n=1,
    )
    promoted_bot.plan = selective_plan
    promoted_bot.choose_move(promoted_board)
    check(
        "planner suspends construction after an opponent promotion",
        promoted_bot.plan is None
        and promoted_bot.plan_invalidations == 1,
        f"plan={promoted_bot.plan}; "
        f"invalidations={promoted_bot.plan_invalidations}",
    )

    print("selftest:", "OK" if failures == 0 else f"{failures} failure(s)")
    return 1 if failures else 0


# Conversion drills: Zach is already stripped to king+pawns; can LoseBot
# force him to deliver mate? This is the phase where full games stall.
ENDGAME_FENS = [
    "6k1/5p1p/6p1/Q7/8/8/PP1BNPPP/1RR3K1 w - - 0 1",
    "k7/p7/1p6/8/2BQ4/2N5/PPP2PPP/R3K2R w - - 0 1",
    "7k/7p/8/8/8/3B4/PPP1QPPP/2KR3R w - - 0 1",
    "4k3/3p1p2/4p3/8/8/2N5/PPPQBPPP/2KR3R w - - 0 1",
    "1k6/p1p5/8/8/5B2/2N5/PPP1QPPP/2KR4 w - - 0 1",
]


def endgames(args) -> int:
    import time
    from pathlib import Path

    from .arena import play_game, save_pgn

    converted = 0
    cases = list(enumerate(ENDGAME_FENS, 1))
    if args.case is not None:
        cases = [cases[args.case - 1]]
    for i, fen in cases:
        bot = LoseBot(
            depth=args.depth,
            opponent_model=args.model,
            profile=args.profile,
            probe_cap=args.probe_cap,
            max_probe_n=args.probe_depth,
        )
        zach = ZachBot(seed=args.seed + i)
        start_board = chess.Board(fen)
        start_target = best_pawn_mate_template(start_board, chess.WHITE)
        t0 = time.monotonic()
        board, reason, mated = play_game(bot, zach, max_plies=args.max_plies,
                                         start_fen=fen)
        dt = time.monotonic() - t0
        won = mated == chess.WHITE
        converted += won
        if args.pgn_dir:
            save_pgn(
                board, bot, zach, reason, mated,
                Path(args.pgn_dir), i,
            )
        end_target = best_pawn_mate_template(board, chess.WHITE)
        planned_target = bot.planned_target(board, chess.WHITE)
        template_progress = (
            "none"
            if start_target is None or end_target is None
            else (
                f"d{start_target.setup_distance}/c{start_target.cage_occupancy}"
                f"->d{end_target.setup_distance}/c{end_target.cage_occupancy}"
            )
        )
        if bot.plan is None:
            plan_progress = "none"
        elif planned_target is None:
            plan_progress = f"{bot.plan.label}/invalid"
        else:
            herding = herding_metrics(board, chess.WHITE, planned_target)
            plan_progress = (
                f"{bot.plan.label}/d{planned_target.setup_distance}"
                f"/c{planned_target.cage_occupancy}"
                f"/out{herding.open_outward}"
                f"/run{int(planned_target.runway_blocked)}"
                f"/hold{int(planned_target.holding_blocker)}"
                f"/def{int(planned_target.holding_blocker_defended)}"
            )
        print(
            f"endgame {i}: {'CONVERTED (got mated)' if won else reason}"
            f" in {len(board.move_stack)} plies"
            f" [probes hit: {bot.forced_selfmates_found}; "
            f"nodes: {bot.probe_nodes}; "
            f"exhausted: {bot.probe_budget_exhaustions}; "
            f"deep-skips: {bot.deep_probe_skips}; "
            f"template: {template_progress}; "
            f"plan: {plan_progress}; replans: {bot.plans_created}; "
            f"hold-filtered: {bot.hold_moves_filtered}; "
            f"regressions-filtered: {bot.plan_regressions_filtered}; "
            f"repetitions-filtered: {bot.plan_repetitions_filtered}; "
            f"forced-herds: {bot.forced_herding_choices}; "
            f"herd-proofs: {bot.herd_search_hits}; "
            f"herd-nodes: {bot.herd_search_nodes}; "
            f"modeled-herds: {bot.modeled_herding_hits}; "
            f"modeled-replies: {bot.modeled_herding_replies}; "
            f"modeled-nodes: {bot.modeled_herding_nodes}; "
            f"modeled-cache: {bot.modeled_herding_cache_hits}/"
            f"{bot.modeled_herding_memo_entries}; "
            f"modeled-pruned: {bot.modeled_herding_candidates_pruned}; "
            f"modeled-incomplete: {bot.modeled_herding_incomplete}] "
            f"[{dt:.0f}s]",
            flush=True,
        )
        if args.show_fen:
            print(f"  final FEN: {board.fen()}", flush=True)
    print(
        f"\nprofile {args.profile} conversion: "
        f"{converted}/{len(cases)}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="losebot")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest")

    eg = sub.add_parser("endgames")
    eg.add_argument("--depth", type=int, default=2)
    eg.add_argument("--model", choices=["zach"], default="zach")
    eg.add_argument("--max-plies", type=int, default=240)
    eg.add_argument("--seed", type=int, default=0)
    eg.add_argument("--profile", choices=sorted(PROFILES), default="current")
    eg.add_argument("--case", type=int, choices=range(1, len(ENDGAME_FENS) + 1))
    eg.add_argument("--probe-cap", type=int, default=None)
    eg.add_argument("--probe-depth", type=int, default=None)
    eg.add_argument("--show-fen", action="store_true")
    eg.add_argument("--pgn-dir", default=None)

    arena = sub.add_parser("arena")
    arena.add_argument("--white", required=True,
                       choices=["losebot", "zach", "worstfish", "random"])
    arena.add_argument("--black", required=True,
                       choices=["losebot", "zach", "worstfish", "random"])
    arena.add_argument("-n", "--games", type=int, default=10)
    arena.add_argument("--max-plies", type=int, default=300)
    arena.add_argument("--depth", type=int, default=2)
    arena.add_argument("--model", choices=["zach"], default=None)
    arena.add_argument("--nodes", type=int, default=4000)
    arena.add_argument("--seed", type=int, default=0)
    arena.add_argument("--pgn-dir", default=None)
    arena.add_argument("--profile", choices=sorted(PROFILES), default="current")
    arena.add_argument("--probe-cap", type=int, default=None)
    arena.add_argument("--probe-depth", type=int, default=None)

    args = parser.parse_args()
    if args.cmd == "selftest":
        return selftest()
    if args.cmd == "endgames":
        return endgames(args)

    white = make_bot(args.white, args, "W")
    black = make_bot(args.black, args, "B")
    try:
        run_match(white, black, args.games, max_plies=args.max_plies,
                  pgn_dir=args.pgn_dir)
    finally:
        for b in (white, black):
            if hasattr(b, "close"):
                b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

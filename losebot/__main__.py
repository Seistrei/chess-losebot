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
            vi_herders=getattr(args, "vi_herders", None),
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

    # 13b. The herding sub-MDP: statics frozen, dynamics = their king plus two
    # rook herders. The build must validate its bitboard Zach pool against
    # support_zach, and value iteration must certify the goal zone reachable
    # (V(root) > 0) with a quiet, legal recommended move.
    from .herding_vi import (
        GOAL_CONTAINED,
        GOAL_RACE,
        HerdingPolicy,
        herder_subsets,
    )

    vi_board = chess.Board("k7/p7/Pp6/1B6/K7/PP6/8/6RR w - - 0 1")
    vi_target = best_pawn_mate_template(vi_board, chess.WHITE)
    vi_ok = (
        vi_target is not None
        and vi_target.uci == "b6b5"
        and vi_target.checked_square == chess.A4
        and vi_target.holding_blocker
        and vi_target.holding_blocker_defended
    )
    vi_policy = None
    if vi_ok:
        vi_policy = HerdingPolicy.build(
            vi_board, vi_target, max_herders=2, state_cap=200_000,
            time_budget_ms=30_000, gamma=0.99,
        )
        ranked = vi_policy.ranked_moves(vi_board) or []
        vi_ok = (
            vi_policy.report.ok
            and vi_policy.report.pool_mismatches == 0
            and vi_policy.report.root_value > 0.0
            and bool(ranked)
            and ranked[0][0] > 0.0
            and ranked[0][1] in vi_board.legal_moves
            and not vi_board.is_capture(ranked[0][1])
        )
    check(
        "herding sub-MDP solves and certifies the goal zone reachable",
        vi_ok,
        "no template" if vi_policy is None else (
            f"root={vi_policy.report.root_value:.3f}; "
            f"states={vi_policy.report.states}; "
            f"edges={vi_policy.report.edges}; "
            f"updates={vi_policy.report.updates}; "
            f"terminals={vi_policy.report.terminals}; "
            f"mismatches={vi_policy.report.pool_mismatches}; "
            f"{vi_policy.report.build_ms:.0f}ms"
        ),
    )

    # 13c. The vi profile follows the solved policy from inside the bot. The
    # exact herd search legitimately outranks it in the waterfall (a proven
    # forcing net beats a probabilistic one), so silence it here to exercise
    # the policy path itself.
    from dataclasses import replace as _replace

    vi_bot = LoseBot(
        depth=1,
        opponent_model="zach",
        profile="vi",
        probe_cap=64,
        max_probe_n=1,
    )
    vi_bot.profile = _replace(
        vi_bot.profile, herd_search_cap=0, modeled_herding_cap=0
    )
    vi_bot.plan = ConstructionPlan(
        pawn_file=chess.square_file(chess.B6),
        checked_side=-1,
        created_ply=0,
    )
    vi_move = vi_bot.choose_move(chess.Board("k7/p7/Pp6/1B6/K7/PP6/8/6RR w - - 0 1"))
    check(
        "vi profile plays a policy-guided herding move",
        vi_move is not None
        and vi_bot.vi_builds == 1
        and vi_bot.vi_moves_played == 1
        and vi_bot.vi_pool_mismatches == 0
        and (vi_bot.vi_root_value or 0.0) > 0.0,
        f"chose {chess.Board('k7/p7/Pp6/1B6/K7/PP6/8/6RR w - - 0 1').san(vi_move)}; "
        f"builds={vi_bot.vi_builds}; played={vi_bot.vi_moves_played}; "
        f"root={vi_bot.vi_root_value}; fail={vi_bot.vi_last_failure or '-'}",
    )

    # 13d. A dead certificate flips the plan to the live mirrored side. This
    # position is drill 2's first real build: b-pawn/right is provably dead
    # (their king is sealed in the corner box, every reachable defense square
    # covered by unmovable statics), while b-pawn/left certifies live once
    # the queen's coverage becomes dynamic.
    flip_board = chess.Board("7R/2k5/1p6/1B1Q4/2K5/pPN5/P1P2PPP/R7 w - - 0 10")
    flip_bot = LoseBot(
        depth=1,
        opponent_model="zach",
        profile="vi",
        probe_cap=64,
        max_probe_n=1,
    )
    flip_bot.profile = _replace(
        flip_bot.profile, herd_search_cap=0, modeled_herding_cap=0
    )
    flip_bot.plan = ConstructionPlan(
        pawn_file=chess.square_file(chess.B6),
        checked_side=1,
        created_ply=0,
    )
    flip_bot.choose_move(flip_board)
    check(
        "dead certificate flips the plan to the live checked side",
        flip_bot.vi_side_flips == 1
        and flip_bot.plan is not None
        and flip_bot.plan.checked_side == -1
        and (flip_bot.vi_flip_value or 0.0) > 0.0
        and flip_bot.vi_dead_certificates == 1,
        f"flips={flip_bot.vi_side_flips}; "
        f"prospect={flip_bot.vi_flip_value}; "
        f"plan={flip_bot.plan.label if flip_bot.plan else None}; "
        f"root={flip_bot.vi_root_value}; "
        f"dead-certs={flip_bot.vi_dead_certificates}",
    )

    # 14a. The dead/live certificate is exact graph reachability computed on
    # the completed graph before any Bellman update, and the solver reports
    # honestly when cut short. The old build marked every completed explore
    # ok=True with whatever partial values the deadline left behind, so a
    # starved solve of a LIVE configuration reported root 0.0 — read
    # downstream as a dead certificate.
    starved = None
    if vi_target is not None:
        starved = HerdingPolicy.build(
            vi_board, vi_target, max_herders=2, state_cap=200_000,
            time_budget_ms=30_000, gamma=0.99, max_updates=1,
        )
    starved_partial = None if starved is None else starved.report.converged
    resumed = False
    if starved is not None:
        for _ in range(4):
            resumed = starved.solve_more(30_000)
            if resumed:
                break
    check(
        "starved solve keeps its live certificate and resumes to convergence",
        starved is not None
        and starved.report.ok
        and starved.report.root_live
        and starved_partial is False
        and resumed
        and starved.report.root_value > 0.0,
        "no template" if starved is None else (
            f"root_live={starved.report.root_live}; "
            f"converged={starved_partial} -> {starved.report.converged}; "
            f"root={starved.report.root_value:.3f}; "
            f"updates={starved.report.updates}"
        ),
    )

    # 14b. A dead certificate is a reachability fact. The explored graph
    # holds only root-reachable states, so a dead configuration has no goal
    # terminal anywhere in it: certification costs zero Bellman updates and
    # no deadline can fake it. contains() scopes the verdict to exactly the
    # certified frozen configuration.
    flip_plan = ConstructionPlan(
        pawn_file=chess.square_file(chess.B6), checked_side=1, created_ply=0
    )
    flip_target = flip_plan.resolve(flip_board, chess.WHITE)
    dead_policy = None
    if flip_target is not None:
        dead_policy = HerdingPolicy.build(
            flip_board, flip_target, max_herders=2, state_cap=200_000,
            time_budget_ms=30_000, gamma=0.96,
        )
    moved = flip_board.copy(stack=False)
    moved.remove_piece_at(chess.F2)
    moved.set_piece_at(chess.F4, chess.Piece(chess.PAWN, chess.WHITE))
    check(
        "dead certificate is exact, free, and configuration-scoped",
        dead_policy is not None
        and dead_policy.report.ok
        and not dead_policy.report.root_live
        and dead_policy.report.converged
        and dead_policy.report.updates == 0
        and dead_policy.report.root_value == 0.0
        and dead_policy.contains(flip_board)
        and not dead_policy.contains(moved),
        "no template" if dead_policy is None else (
            f"live={dead_policy.report.root_live}; "
            f"updates={dead_policy.report.updates}; "
            f"states={dead_policy.report.states}; "
            f"scoped here/elsewhere={dead_policy.contains(flip_board)}/"
            f"{dead_policy.contains(moved)}"
        ),
    )

    # 14c. Audit mode cross-checks EVERY explored opponent pool against the
    # real support_zach, not just the root and the empty-pool slow path that
    # the routine build samples.
    audited = None
    if vi_target is not None:
        audited = HerdingPolicy.build(
            vi_board, vi_target, max_herders=1, state_cap=200_000,
            time_budget_ms=60_000, gamma=0.99, validate_pools=True,
        )
    check(
        "full pool audit finds zero mismatches against support_zach",
        audited is not None
        and audited.report.ok
        and audited.report.states > 0
        and audited.report.pool_mismatches == 0,
        "no template" if audited is None else (
            f"states={audited.report.states}; "
            f"mismatches={audited.report.pool_mismatches}"
        ),
    )

    # 14d. The conversion audit measures the proxy gap. This construction is
    # herdable (root_live) but its bishop holder re-attacks the arrival
    # square from every retreat — their king's defense only bars OUR KING
    # from recapturing, so the retreated holder refutes the mate itself and
    # every reachable goal terminal fails the release probe. root_live
    # without root_converts is exactly the delivered-but-stuck stall of the
    # drills, now a measured per-build fact instead of a 120-ply postmortem.
    # With no converting goal anywhere, terminal seeding stays flat (the
    # proxy ranking is kept rather than silenced), so root_value survives.
    conv = None
    if vi_target is not None:
        conv = HerdingPolicy.build(
            vi_board, vi_target, max_herders=1, state_cap=200_000,
            time_budget_ms=60_000, gamma=0.99, conversion_ms=30_000,
        )
    check(
        "conversion audit exposes a live-but-unconvertible goal zone",
        conv is not None
        and conv.report.ok
        and conv.report.root_live
        and conv.report.goal_states > 0
        and conv.report.conversion_complete
        and conv.report.conversion_checked == conv.report.goal_states
        and conv.report.converting_goals == 0
        and conv.report.forced_mates == 0
        and not conv.report.root_converts
        and conv.report.conversion_nodes > 0
        and conv.report.root_value > 0.0,
        "no template" if conv is None else (
            f"goals={conv.report.converting_goals}"
            f"/{conv.report.conversion_checked}"
            f" of {conv.report.goal_states}; "
            f"forced-mates={conv.report.forced_mates}; "
            f"complete={conv.report.conversion_complete}; "
            f"live={conv.report.root_live}; "
            f"probe-nodes={conv.report.conversion_nodes}; "
            f"root={conv.report.root_value:.3f}"
        ),
    )

    # 14e. Subset enumeration is never silently truncated. Six candidates
    # with two herders is fifteen maximal subsets — the old cap returned
    # twelve, so an all-dead walk over them could masquerade as a complete
    # sweep and a false hopeless verdict could flip away from a live side.
    # Past the candidate cap the enumeration must declare itself incomplete
    # instead, which blocks the hopeless verdict downstream.
    six_board = vi_board.copy(stack=False)
    for sq in (chess.C1, chess.D1, chess.E1, chess.F1):
        six_board.set_piece_at(sq, chess.Piece(chess.KNIGHT, chess.WHITE))
    nine_board = six_board.copy(stack=False)
    for sq in (chess.F4, chess.G4, chess.H4):
        nine_board.set_piece_at(sq, chess.Piece(chess.KNIGHT, chess.WHITE))
    six_subsets: list = []
    six_complete = nine_complete = True
    nine_subsets: list = []
    if vi_target is not None:
        six_subsets, six_complete = herder_subsets(six_board, vi_target, 2)
        nine_subsets, nine_complete = herder_subsets(nine_board, vi_target, 2)
    check(
        "maximal herder subsets are enumerated without silent truncation",
        vi_target is not None
        and len(six_subsets) == 15 and six_complete
        and len(nine_subsets) == 28 and not nine_complete,
        f"six candidates={len(six_subsets)} complete={six_complete}; "
        f"nine candidates={len(nine_subsets)} complete={nine_complete}",
    )

    # 14f. Oversized-build memory is scoped to the dynamic root: reachable
    # graph size depends on where their king and the herders stand, so one
    # blown state cap must not suppress a later affordable root of the same
    # static configuration — no strike count ever widens the skip (two
    # oversized roots prove nothing about a third). A bare config-level
    # fingerprint remains honored for callers that pass one explicitly.
    tiny = rooted_skip = other_root = bare_skip = None
    if vi_target is not None:
        tiny = HerdingPolicy.build(
            vi_board, vi_target, max_herders=2, state_cap=50,
            time_budget_ms=5_000, gamma=0.99,
        )
        moved_root = vi_board.copy(stack=False)
        moved_root.remove_piece_at(chess.A8)
        moved_root.set_piece_at(
            chess.B8, chess.Piece(chess.KING, chess.BLACK)
        )
        rooted_skip = HerdingPolicy.build(
            vi_board, vi_target, max_herders=2, state_cap=50,
            time_budget_ms=5_000, gamma=0.99,
            skip_fingerprints={tiny.rooted_fingerprint},
        )
        other_root = HerdingPolicy.build(
            moved_root, vi_target, max_herders=2, state_cap=50,
            time_budget_ms=5_000, gamma=0.99,
            skip_fingerprints={tiny.rooted_fingerprint},
        )
        bare_skip = HerdingPolicy.build(
            moved_root, vi_target, max_herders=2, state_cap=50,
            time_budget_ms=5_000, gamma=0.99,
            skip_fingerprints={tiny.fingerprint},
        )
    check(
        "oversized-build memory is scoped to the dynamic root",
        tiny is not None
        and tiny.report.reason == "state-cap"
        and rooted_skip.report.reason == "skipped-unbuildable"
        and other_root.report.reason == "state-cap"
        and bare_skip.report.reason == "skipped-unbuildable",
        "no template" if tiny is None else (
            f"cap={tiny.report.reason}; "
            f"same-root={rooted_skip.report.reason}; "
            f"other-root={other_root.report.reason}; "
            f"config-wide={bare_skip.report.reason}"
        ),
    )

    # 14g. FORCED_MATE is a conversion — no release needed. In this position
    # their king is boxed by statics alone and hxg2 (a forced capture-mate,
    # the Qc2+ Kxc2# family) is the only legal reply after most herder
    # waits: the graph is forced-mate-only, with NO proxy goal terminal
    # anywhere. root_converts must be true with zero goals audited, and the
    # seeding must steer the policy at the mate. This is the case a
    # goals-only audit misread as unconvertible.
    from types import SimpleNamespace as _NS

    fm_board = chess.Board("8/8/8/R7/8/3PPk1p/6RP/6BK w - - 0 1")
    fm_policy = HerdingPolicy.build(
        fm_board, _NS(arrival_square=chess.A8), max_herders=1,
        state_cap=10_000, time_budget_ms=10_000, gamma=0.99,
    )
    fm_ranked = fm_policy.ranked_moves(fm_board) or []
    check(
        "forced-mate terminals count as conversions without goal audits",
        fm_policy.report.ok
        and fm_policy.report.root_live
        and fm_policy.report.root_converts
        and fm_policy.report.conversion_complete
        and fm_policy.report.forced_mates > 0
        and fm_policy.report.goal_states == 0
        and fm_policy.report.conversion_checked == 0
        and fm_policy.report.root_value > 0.9
        and bool(fm_ranked)
        and fm_ranked[0][0] > 0.9,
        f"forced-mates={fm_policy.report.forced_mates}; "
        f"goals={fm_policy.report.goal_states}; "
        f"converts={fm_policy.report.root_converts}; "
        f"root={fm_policy.report.root_value:.3f}; "
        f"terminals={fm_policy.report.terminals}",
    )

    # 14h. Positive-but-incomplete audits must seed on one scale. When the
    # audit finds a conversion and then hits its deadline, goals it never
    # reached seed 0, not 1: a known conversion worth 0.4 must outrank
    # every unknown proxy (the unchecked goals are precisely the ones the
    # plausible-first ordering ranked least likely to release). An
    # organically converting goal terminal requires the king-holder
    # template (piece holders re-attack the arrival square — the release
    # theorem), so until that lands this injects the reviewer's exact
    # scenario into the 14d build and re-seeds the solver.
    mixed_ok = False
    mixed_detail = "no policy"
    if conv is not None and conv.report.ok:
        goals = [
            index for index, kind in enumerate(conv._kind)
            if kind in (GOAL_CONTAINED, GOAL_RACE)
        ]
        known = goals[0]
        conv._conversion = {known: 0.4}
        conv.report.root_converts = True
        conv.report.conversion_complete = False
        conv.report.converged = False
        conv._worklist = None
        conv._values = [0.0] * len(conv._values)
        resolved = conv.solve_more(60_000)
        unchecked_top = max(conv._values[index] for index in goals[1:])
        mixed_ok = (
            len(goals) >= 2
            and resolved
            and conv._values[known] == 0.4
            and unchecked_top == 0.0
            and 0.0 < conv.report.root_value < 0.4
        )
        mixed_detail = (
            f"goals={len(goals)}; known-seed={conv._values[known]}; "
            f"unchecked-top={unchecked_top}; "
            f"root={conv.report.root_value:.3f}"
        )
    check(
        "a known conversion outranks unchecked goals in mixed seeding",
        mixed_ok,
        mixed_detail,
    )

    # 15. Release scoring shares the arena's draw law. At halfmove clock 98
    # the zugzwang release (Rb7) exists; at 99 every quiet holder retreat
    # lands on the fifty-move adjudication BEFORE Zach ever replies, so
    # there is no release at all. The old scorer checked only checkmate and
    # stalemate, offered the "guaranteed" net anyway, and drew on the spot.
    from types import SimpleNamespace

    from .herding_vi import score_release_moves

    release_stub = SimpleNamespace(arrival_square=chess.B1)
    low_clock = chess.Board("8/8/5pkp/6p1/6K1/5PPP/8/1R6 w - - 98 80")
    high_clock = chess.Board("8/8/5pkp/6p1/6K1/5PPP/8/1R6 w - - 99 80")
    low_choice = score_release_moves(low_clock, release_stub, "zach", 0)
    high_choice = score_release_moves(high_clock, release_stub, "zach", 0)
    check(
        "release scoring refuses moves the arena would adjudicate drawn",
        low_choice is not None and high_choice is None,
        "clock98="
        + ("none" if low_choice is None else low_clock.san(low_choice.move))
        + f"; clock99={'offered' if high_choice is not None else 'refused'}",
    )

    # 16. Successor visits must live on the keys _vi_choice queries: the
    # position after our move, opponent to move. The old tally counted
    # positions with us to move; side-to-move is part of the transposition
    # key, so every candidate lookup returned zero and the anti-repetition
    # tie-break was silently a no-op.
    visit_bot = LoseBot(depth=1)
    visit_board = chess.Board()
    visit_move = visit_bot.choose_move(visit_board)
    visit_board.push(visit_move)
    check(
        "successor visits are keyed with the opponent to move",
        visit_bot._vi_visits == {visit_board._transposition_key(): 1},
        f"tallies={len(visit_bot._vi_visits)}",
    )

    # 17. Negative memory is scoped to the plan era: replanning (here via a
    # promotion ending the king-and-pawns phase) drops every certificate
    # instead of letting a rebuilt plan inherit verdicts certified for a
    # different frozen configuration and herder subset.
    scope_bot = LoseBot(depth=1, profile="vi")
    scope_bot.plan = flip_plan
    if dead_policy is not None:
        scope_bot._vi_dead_policies.append(dead_policy)
    scope_bot._vi_unbuildable.add(("sentinel",))
    scope_bot._update_construction_plan(flip_board, their_pieces=1)
    check(
        "certificates do not survive replanning",
        scope_bot.plan is None
        and not scope_bot._vi_dead_policies
        and not scope_bot._vi_unbuildable
        and scope_bot.plan_invalidations == 1,
        f"plan={scope_bot.plan}; "
        f"dead={len(scope_bot._vi_dead_policies)}; "
        f"unbuildable={len(scope_bot._vi_unbuildable)}",
    )

    # 18. Certification answers from stored dead certificates without
    # rebuilding: the sole maximal herder subset here is the very pair the
    # dead policy certified, so the sweep completes with zero fresh builds
    # and still returns the hopeless verdict that gates the side flip.
    cache_bot = LoseBot(depth=1, opponent_model="zach", profile="vi")
    cache_bot.plan = flip_plan
    cached_policy, cached_hopeless = None, False
    if dead_policy is not None and flip_target is not None:
        cache_bot._vi_dead_policies.append(dead_policy)
        cached_policy, cached_hopeless = cache_bot._certify_herding(
            flip_board, flip_target, 2
        )
    check(
        "certification reuses dead certificates without rebuilding",
        dead_policy is not None
        and cached_policy is None
        and cached_hopeless
        and cache_bot.vi_builds == 0,
        f"hopeless={cached_hopeless}; builds={cache_bot.vi_builds}",
    )

    # 18b. Dead certificates strip down to the membership certificate that
    # contains()/dynamic_squares() need — the ledger can then afford a whole
    # sweep's worth without eviction (the old 8-policy cap thrashed against
    # 12-subset sweeps and the hopeless verdict never arrived). The
    # play-time interfaces must refuse instead of reading freed solver
    # state.
    stripped_ok = False
    if dead_policy is not None:
        dead_policy.strip_to_certificate()
        stripped_ok = (
            dead_policy.contains(flip_board)
            and not dead_policy.contains(moved)
            and dead_policy.dynamic_squares(flip_board) is not None
            and dead_policy.ranked_moves(flip_board) is None
            and dead_policy.state_value(flip_board) is None
            and dead_policy.solve_more(10) is True
        )
    check(
        "stripped dead certificates keep exact membership only",
        stripped_ok,
        "no dead policy" if dead_policy is None else (
            f"contains here/elsewhere={dead_policy.contains(flip_board)}"
            f"/{dead_policy.contains(moved)}"
        ),
    )

    # 19a. The king-holder release: our KING on the arrival square is the one
    # holder type the release theorem does not kill (a defended arrival
    # square only bars a king capture). On the exact vacate position the
    # root classifies GOAL_VACATE, the build exits root-already-terminal
    # BEFORE any audit, and direct release scoring — the reviewer protocol
    # for already-terminal roots — must accept the king-step-aside at race
    # 1/2: {Kh3 enter -> Ng6! g2# forced} wins, the premature g2+ loses.
    from types import SimpleNamespace as _MotifNS

    from .herding_vi import score_release_moves as _score_release
    from .motifs import FIXTURES

    motif = {fixture.name: fixture for fixture in FIXTURES}

    def _motif_target(fixture):
        target = _MotifNS(
            arrival_square=chess.parse_square(fixture.arrival)
        )
        if fixture.checked is not None:
            target.checked_square = chess.parse_square(fixture.checked)
        return target

    kh = motif["kh-corner-h"]
    kh_board = chess.Board(kh.fen)
    kh_target = _motif_target(kh)
    kh_build = HerdingPolicy.build(
        kh_board, kh_target, max_herders=1, state_cap=100_000,
        time_budget_ms=10_000, gamma=0.99,
    )
    kh_choice = _score_release(
        kh_board, kh_target, "zach", 1, probe_n=2, probe_cap=50_000,
    )
    check(
        "king-holder vacate is scored and accepted at the terminal root",
        kh_build.report.reason == "root-already-terminal"
        and kh_choice is not None
        and kh_choice.move == chess.Move.from_uci("g2h1")
        and kh_choice.winning == 1
        and kh_choice.losing == 1
        and kh_choice.pool == 2,
        f"build={kh_build.report.reason or 'ok'}; release="
        + ("refused" if kh_choice is None else
           f"{kh_board.san(kh_choice.move)} "
           f"{kh_choice.winning}/{kh_choice.pool}"),
    )

    # 19b. GOAL_VACATE makes king-holder herding positions visible to the
    # sub-MDP: with our king static on the arrival square every defense-zone
    # square is king-attacked, so the old goals could never fire and a
    # king-holder build read as a structural false-dead. In the {h4,h5}
    # pocket fixture the policy must time Ra5+ to the h5 parity (Ra5 with
    # his king on h4 is stalemate), and the audit must convert 6 of the 7
    # goal-vacate terminals — the seventh, rook on g5, re-attacks g2 through
    # the square the mating push itself vacates, and the audit catches it.
    khh = motif["kh-herd-h4"]
    khh_board = chess.Board(khh.fen)
    khh_policy = HerdingPolicy.build(
        khh_board, _motif_target(khh), max_herders=1, state_cap=100_000,
        time_budget_ms=30_000, gamma=0.99, validate_pools=True,
        conversion_ms=30_000, conversion_probe_cap=50_000,
    )
    khh_report = khh_policy.report
    khh_ranked = khh_policy.ranked_moves(khh_board) or []
    check(
        "goal-vacate herding graph audits king-holder conversions",
        khh_report.ok
        and khh_report.root_live
        and khh_report.root_converts
        and khh_report.conversion_complete
        and khh_report.pool_mismatches == 0
        and khh_report.terminals.get("goal-vacate") == 7
        and khh_report.conversion_checked == 7
        and khh_report.converting_goals == 6
        and khh_report.forced_mates == 0
        and khh_report.root_value > 0.4
        and bool(khh_ranked)
        and khh_ranked[0][0] > 0.4,
        f"goals={khh_report.converting_goals}/{khh_report.conversion_checked}"
        f" of {khh_report.terminals.get('goal-vacate')}; "
        f"root={khh_report.root_value:.3f}; "
        f"terminals={khh_report.terminals}",
    )

    # 19c. The contrast exhibit: a piece holder with the defender already
    # contained is a terminal root the build cannot audit, and direct
    # scoring must refuse every retreat — the bishop re-attacks b5 along
    # the vacated diagonal from every destination (the release theorem).
    ph = motif["ph-contained-root"]
    ph_board = chess.Board(ph.fen)
    ph_target = _motif_target(ph)
    ph_build = HerdingPolicy.build(
        ph_board, ph_target, max_herders=1, state_cap=100_000,
        time_budget_ms=10_000, gamma=0.99,
    )
    ph_choice = _score_release(
        ph_board, ph_target, "zach", 1, probe_n=2, probe_cap=50_000,
    )
    check(
        "piece-holder release stays refused at the terminal root",
        ph_build.report.reason == "root-already-terminal"
        and ph_choice is None,
        f"build={ph_build.report.reason or 'ok'}; "
        f"release={'refused' if ph_choice is None else 'accepted'}",
    )

    # 19d. Multi-move forced-mate reachability with junk proxy goals: the
    # stub arrival square breeds 56 goal terminals that all audit to zero,
    # while six genuine FORCED_MATE terminals sit several plies deep behind
    # rank-5 seal-and-shuffle rook play. root_converts must come from the
    # forced mates, audited seeding must zero the refused goals rather than
    # steer at them, and the mated-them traps (a rook check on the f-file
    # mates HIS king — a misère loss) must stay avoidable, root near 1.
    fmd = motif["fm-deep-h"]
    fmd_policy = HerdingPolicy.build(
        chess.Board(fmd.fen), _motif_target(fmd), max_herders=1,
        state_cap=100_000, time_budget_ms=30_000, gamma=0.99,
        conversion_ms=30_000,
    )
    fmd_report = fmd_policy.report
    check(
        "deep forced-mate reachability converts through refused proxy goals",
        fmd_report.ok
        and fmd_report.root_converts
        and fmd_report.conversion_complete
        and fmd_report.forced_mates == 6
        and fmd_report.goal_states == 56
        and fmd_report.converting_goals == 0
        and fmd_report.terminals.get("mated-them") == 6
        and fmd_report.root_value > 0.9,
        f"forced-mates={fmd_report.forced_mates}; "
        f"goals={fmd_report.converting_goals}/{fmd_report.goal_states}; "
        f"root={fmd_report.root_value:.3f}",
    )

    # 19e. The post-vacate attack map must see THROUGH their king (the same
    # king-danger semantics _white_attacks documents): when the vacate opens
    # a slider ray onto their king, the squares behind the king along the
    # ray stay attacked — a king cannot step backward out of check. The old
    # computation included the king as an occupancy blocker, so the ray
    # stopped at him and the fast pool admitted the illegal retreat (h4
    # here, with the a4-rook ray opening across the vacated e4).
    ray_board = chess.Board("8/8/8/4p3/R3K1k1/8/8/7N w - - 0 1")
    ray_policy = HerdingPolicy.build(
        ray_board,
        _MotifNS(
            arrival_square=chess.E4, checked_square=chess.D3
        ),
        max_herders=1, state_cap=100_000, time_budget_ms=10_000,
        gamma=0.99, herders=((chess.H1, chess.KNIGHT),),
    )
    ray_ok = ray_policy.report.ok and ray_policy._king_holder
    ray_fast: set = set()
    ray_truth: set = set()
    if ray_ok:
        ray_fast = set(ray_policy._their_quiet_moves_vacated(
            chess.G4, ray_policy._root_herders
        ))
        vac_board = chess.Board(None)
        vac_board.set_piece_at(chess.A4, chess.Piece(chess.ROOK, chess.WHITE))
        vac_board.set_piece_at(chess.D3, chess.Piece(chess.KING, chess.WHITE))
        vac_board.set_piece_at(
            chess.H1, chess.Piece(chess.KNIGHT, chess.WHITE)
        )
        vac_board.set_piece_at(chess.E5, chess.Piece(chess.PAWN, chess.BLACK))
        vac_board.set_piece_at(chess.G4, chess.Piece(chess.KING, chess.BLACK))
        vac_board.turn = chess.BLACK
        ray_truth = {
            m.to_square for m in vac_board.legal_moves
            if m.from_square == chess.G4 and not vac_board.is_capture(m)
        }
    check(
        "post-vacate pool sees through their king along opened rays",
        ray_ok and ray_fast == ray_truth and chess.H4 not in ray_fast,
        f"fast={sorted(chess.square_name(s) for s in ray_fast)}; "
        f"real={sorted(chess.square_name(s) for s in ray_truth)}",
    )

    # 19f. A refusal that leaned on an UNKNOWN probe is a budget artifact,
    # never a verdict. With probe_cap=0 every reply probe starves, so the
    # known-positive king-holder vacate is refused — but unknown_out must
    # say so, and the motif harness reads that as UNKNOWN, not NEGATIVE.
    # The piece-holder refusal at a research cap stays clean (all replies
    # DISPROVEN), which is what keeps ITS negative admissible.
    starved_unknowns = [0]
    starved_choice = _score_release(
        chess.Board(kh.fen), kh_target, "zach", 1,
        probe_n=2, probe_cap=0, unknown_out=starved_unknowns,
    )
    clean_unknowns = [0]
    clean_choice = _score_release(
        chess.Board(ph.fen), ph_target, "zach", 1,
        probe_n=2, probe_cap=50_000, unknown_out=clean_unknowns,
    )
    check(
        "starved release refusals are reported unknown, clean ones are not",
        starved_choice is None
        and starved_unknowns[0] > 0
        and clean_choice is None
        and clean_unknowns[0] == 0,
        f"starved: refused with {starved_unknowns[0]} unknown-tainted"
        f" candidate(s); clean: refused with {clean_unknowns[0]}",
    )

    # 19g. The same distinction folds into the graph audit through the
    # conversion_probe_cap plumbing: at cap 0 every goal refusal is starved,
    # so conversion_unknowns counts all seven, conversion_complete goes
    # False, and root_converts=False is NOT an admissible negative — the
    # same fixture that audits 6/7 convertible at a research cap.
    starved_policy = HerdingPolicy.build(
        chess.Board(khh.fen), _motif_target(khh), max_herders=1,
        state_cap=100_000, time_budget_ms=30_000, gamma=0.99,
        conversion_ms=30_000, conversion_probe_cap=0,
    )
    starved_report = starved_policy.report
    check(
        "starved audit refusals taint conversion_complete",
        starved_report.ok
        and starved_report.terminals.get("goal-vacate") == 7
        and starved_report.conversion_checked == 7
        and starved_report.converting_goals == 0
        and starved_report.conversion_unknowns == 7
        and not starved_report.conversion_complete
        and not starved_report.root_converts,
        f"unknowns={starved_report.conversion_unknowns}/7; "
        f"complete={starved_report.conversion_complete}; "
        f"converts={starved_report.root_converts}",
    )

    # 19h. The vacate is one king step: a target whose checked square is not
    # adjacent to the arrival square must not enable king-holder goals (the
    # old code would classify them through an impossible teleport).
    teleport_policy = HerdingPolicy.build(
        chess.Board(khh.fen),
        _MotifNS(arrival_square=chess.G2, checked_square=chess.A8),
        max_herders=1, state_cap=100_000, time_budget_ms=10_000, gamma=0.99,
    )
    check(
        "non-adjacent checked squares disable king-holder goals",
        teleport_policy.report.ok
        and not teleport_policy._king_holder
        and teleport_policy.report.goal_states == 0
        and "goal-vacate" not in teleport_policy.report.terminals
        and not teleport_policy.report.root_live,
        f"king-holder={teleport_policy._king_holder}; "
        f"goals={teleport_policy.report.goal_states}; "
        f"terminals={teleport_policy.report.terminals}",
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
        if bot.profile.vi_herding:
            root = (
                "n/a"
                if bot.vi_root_value is None
                else f"{bot.vi_root_value:.3f}"
            )
            print(
                f"  vi: builds={bot.vi_builds}"
                f" (failed {bot.vi_build_failures}"
                f"{': ' + bot.vi_last_failure if bot.vi_last_failure else ''});"
                f" states={bot.vi_states}; edges={bot.vi_edges};"
                f" updates={bot.vi_updates}; root={root};"
                f" build={bot.vi_build_ms:.0f}ms;"
                f" played={bot.vi_moves_played};"
                f" misses={bot.vi_state_misses};"
                f" zero-value={bot.vi_zero_fallbacks};"
                f" goal-stalls={bot.vi_goal_stalls};"
                f" releases={bot.vi_releases}"
                f" ({bot.vi_release_nodes} probe nodes);"
                f" side-flips={bot.vi_side_flips}"
                f" (prospect={bot.vi_flip_value});"
                f" dead-certs={bot.vi_dead_certificates};"
                f" re-solves={bot.vi_resolves};"
                f" king-marches={bot.vi_king_marches};"
                f" cage-builds={bot.vi_cage_builds};"
                f" capture-guards={bot.vi_capture_guards};"
                f" pool-mismatches={bot.vi_pool_mismatches};"
                f" goals-convert={bot.vi_converting_goals}"
                f"/{bot.vi_conversion_checked}"
                f" (of {bot.vi_goal_states} goal states,"
                f" {bot.vi_forced_mates} forced mates,"
                f" {bot.vi_conversion_incomplete} audits cut short,"
                f" {bot.vi_conversion_nodes} probe nodes)",
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
    eg.add_argument("--vi-herders", type=int, default=None,
                    help="override the vi profile's mobile herder count")
    eg.add_argument("--show-fen", action="store_true")
    eg.add_argument("--pgn-dir", default=None)

    mo = sub.add_parser(
        "motifs",
        help="adjudicate conversion motifs (king-holder release, forced "
             "capture-mate) with the conversion audit under research budgets",
    )
    mo.add_argument("--case", type=int, default=None,
                    help="run one fixture by number (see --list)")
    mo.add_argument("--list", action="store_true")
    mo.add_argument("--fen", default=None, help="ad-hoc position")
    mo.add_argument("--arrival", default=None,
                    help="arrival square for --fen (e.g. g2)")
    mo.add_argument("--checked", default=None,
                    help="checked square for --fen (king-holder motifs)")
    mo.add_argument("--herders", default=None,
                    help="comma-separated herder squares for --fen")
    mo.add_argument("--max-herders", type=int, default=1)
    mo.add_argument("--conversion-ms", type=int, default=60_000,
                    help="research audit budget; negatives count only when "
                         "the audit completes")
    mo.add_argument("--budget-ms", type=int, default=60_000)
    mo.add_argument("--state-cap", type=int, default=400_000)
    mo.add_argument("--max-losing", type=int, default=1,
                    help="release race tolerance (vi_race_max_losing)")
    mo.add_argument("--probe-cap", type=int, default=50_000,
                    help="per-reply node cap for release probes, in graph "
                         "audits and direct terminal scoring alike")

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
    arena.add_argument("--vi-herders", type=int, default=None,
                       help="override the vi profile's mobile herder count")

    args = parser.parse_args()
    if args.cmd == "selftest":
        return selftest()
    if args.cmd == "endgames":
        return endgames(args)
    if args.cmd == "motifs":
        from .motifs import run_motifs

        return run_motifs(args)

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

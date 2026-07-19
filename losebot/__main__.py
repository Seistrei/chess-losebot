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
    pawn_mate_templates,
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

    # 16. Anti-threefold: the arena draws the third occurrence of a
    # position, and Zach's reply can complete it on an OUR-turn state, so
    # no tally of our own successor choices can see it coming. This is the
    # case-6 seed-6 shuttle (11.Rf5 Kh6 12.Rf7 Kh5 13.Rf5+ Kh6 14.Rf7 Kh5
    # 15.Rf5+?? Kh6 = threefold): every rook move landed on a FRESH
    # their-turn position; the funnel state (rook f5, king h6, us to move)
    # was the twice-seen one. Replaying the drill's exact 28-ply prefix
    # and burning the era must pin that state at 0, reprice the check that
    # funnels into it (its child now averages Zach's pool over
    # {Kh4 -> pocket, Kh6 -> burned draw}), keep the root live through the
    # alternatives, and an era reset must restore the pristine values
    # through the same diff.
    shuttle_board = chess.Board(KING_HOLDER_DRILL_FEN)
    for san in (
        "Bg1 Kd5 Kg2 Kc6 Rb8 Kd5 Rc8 Kd6 Rc5 Ke7 Rd5 Kf7 Re5 Kg8 "
        "Rf5 Kg7 Rf7+ Kg8 Rf6 Kg7 Rf5 Kh6 Rf7 Kh5 Rf5+ Kh6 Rf7 Kh5"
    ).split():
        shuttle_board.push_san(san)
    shuttle_target = ConstructionPlan(
        pawn_file=6, checked_side=1, created_ply=0, holder_mode="king"
    ).resolve(shuttle_board, chess.WHITE)
    shuttle_policy = None
    shuttle_ok = shuttle_target is not None and shuttle_target.king_holder
    if shuttle_ok:
        shuttle_policy = HerdingPolicy.build(
            shuttle_board, shuttle_target, max_herders=1,
            state_cap=200_000, time_budget_ms=30_000, gamma=0.96,
            model="zach",
        )
        shuttle_ok = (
            shuttle_policy.report.ok
            and shuttle_policy.report.root_live
            and shuttle_policy.report.converged
        )
    funnel_burned = False
    shuttle_live = False
    shuttle_burn_gauge = 0
    fresh_rf5 = burned_rf5 = restored_rf5 = None
    if shuttle_ok:
        rf5 = chess.Move.from_uci("f7f5")

        def _shuttle_value(move):
            for value, ranked_move, _ in (
                shuttle_policy.ranked_moves(shuttle_board) or []
            ):
                if ranked_move == move:
                    return value
            return None

        fresh_rf5 = _shuttle_value(rf5)
        counts, changed = shuttle_policy.apply_repetition_history(
            shuttle_board
        )
        shuttle_policy.solve_more(30_000)
        shuttle_burn_gauge = shuttle_policy.burned_states
        funnel = shuttle_policy._index.get(
            (True, chess.H6, ((chess.ROOK, chess.F5),))
        )
        funnel_burned = (
            changed
            and shuttle_burn_gauge > 0
            and funnel is not None
            and counts.get(funnel, 0) >= 2
            and funnel in shuttle_policy._burned_set
            and shuttle_policy._values[funnel] == 0.0
        )
        burned_rf5 = _shuttle_value(rf5)
        shuttle_live = any(
            value > 1e-9
            for value, _, _ in (
                shuttle_policy.ranked_moves(shuttle_board) or []
            )
        )
        shuttle_policy._set_burned(set())
        shuttle_policy.solve_more(30_000)
        restored_rf5 = _shuttle_value(rf5)
    check(
        "twice-seen funnel states burn to zero, reprice, and restore",
        shuttle_ok
        and funnel_burned
        and shuttle_policy.report.converged
        and fresh_rf5 is not None
        and burned_rf5 is not None
        and burned_rf5 < fresh_rf5 - 1e-3
        and shuttle_live
        and restored_rf5 is not None
        and abs(restored_rf5 - fresh_rf5) <= 1e-3,
        "no kh target" if shuttle_target is None else (
            f"fresh={fresh_rf5}; burned={burned_rf5}; "
            f"restored={restored_rf5}; "
            f"burned-states={shuttle_burn_gauge}; "
            f"live-after-burn={shuttle_live}"
        ),
    )

    # 16b. Burn mechanics stay honest on the two-rook fixture: pinning any
    # state is an in-place losing terminal (value 0, parents repriced
    # through the resumable worklist), un-burning restores NORMAL states
    # via Bellman and WIN terminals via their seed values exactly, and the
    # convergence flag deconverges on each diff and drains back to True.
    burn_ok = False
    burn_detail = "13b fixture unavailable"
    if vi_policy is not None and vi_policy.report.ok:
        vi_policy.solve_more(30_000)
        base_ranked = vi_policy.ranked_moves(vi_board) or []
        goal_index = next(
            (
                i for i, kind in enumerate(vi_policy._kind)
                if kind in (GOAL_CONTAINED, GOAL_RACE)
                and vi_policy._values[i] > 0.0
            ),
            None,
        )
        if base_ranked and goal_index is not None:
            base_value, _, base_child = base_ranked[0]
            goal_seed = vi_policy._values[goal_index]
            changed = vi_policy._set_burned({base_child, goal_index})
            deconverged = not vi_policy.report.converged
            resolved = vi_policy.solve_more(30_000)
            pinned_child = vi_policy._values[base_child]
            pinned_goal = vi_policy._values[goal_index]
            after_ranked = vi_policy.ranked_moves(vi_board) or []
            after_top = after_ranked[0][0] if after_ranked else None
            restored = vi_policy._set_burned(set())
            reresolved = vi_policy.solve_more(30_000)
            re_ranked = vi_policy.ranked_moves(vi_board) or []
            burn_ok = (
                changed
                and deconverged
                and resolved
                and pinned_child == 0.0
                and pinned_goal == 0.0
                and after_top is not None
                and after_top <= base_value + 1e-9
                and restored
                and reresolved
                and vi_policy._values[goal_index] == goal_seed
                and bool(re_ranked)
                and abs(re_ranked[0][0] - base_value) <= 1e-3
            )
            burn_detail = (
                f"base={base_value:.4f}; after-burn={after_top}; "
                f"pinned=({pinned_child}, {pinned_goal}); "
                f"goal-seed={goal_seed} -> {vi_policy._values[goal_index]}; "
                f"restored-top={re_ranked[0][0] if re_ranked else None}"
            )
    check(
        "burned states pin at zero and un-burning restores seed values",
        burn_ok,
        burn_detail,
    )

    # 16c. The era walk stops at is_repetition's REAL boundary. A first
    # rook move strips castling rights — irreversible for repetition
    # purposes — without resetting the halfmove clock, and graph states
    # carry no rights, so the old clock-bounded walk merged the
    # rights-bearing start with the rights-stripped return and burned a
    # state the arena would never draw on (review P1: Rh2 Ka7 Rh1 Ka8
    # gives is_repetition(2) False, yet the walk counted the state
    # twice). The same shuttle played again INSIDE the stripped era is a
    # genuine twofold and must burn all four of its states.
    rights_fen = "k7/8/8/8/8/8/8/4K2R w K - 0 1"
    rights_policy = HerdingPolicy.build(
        chess.Board(rights_fen), _NS(arrival_square=chess.B5),
        max_herders=1, state_cap=50_000, time_budget_ms=30_000,
        gamma=0.96,
    )
    rights_ok = rights_policy.report.ok
    boundary_ok = twofold_ok = False
    first_counts: dict = {}
    first_gauge = -1
    if rights_ok:
        rights_board = chess.Board(rights_fen)
        shuttle = ["h1h2", "a8a7", "h2h1", "a7a8"]
        for uci in shuttle:
            rights_board.push_uci(uci)
        first_counts, first_changed = (
            rights_policy.apply_repetition_history(rights_board)
        )
        first_gauge = rights_policy.burned_states
        boundary_ok = (
            not rights_board.is_repetition(2)
            and not first_changed
            and first_gauge == 0
            and first_counts
            and max(first_counts.values()) == 1
        )
        for uci in shuttle:
            rights_board.push_uci(uci)
        _, second_changed = (
            rights_policy.apply_repetition_history(rights_board)
        )
        twofold_ok = (
            rights_board.is_repetition(2)
            and second_changed
            and rights_policy.burned_states == 4
        )
    check(
        "the repetition walk stops at the castling-rights boundary",
        rights_ok and boundary_ok and twofold_ok,
        f"build={rights_policy.report.reason or 'ok'}; "
        f"first-walk-max={max(first_counts.values()) if first_counts else 0}; "
        f"burned after rights-crossing shuttle={first_gauge}; "
        f"after in-era shuttle={rights_policy.burned_states}",
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
    # The burn gauge describes the active policy; dropping the policy era
    # must zero it (review P3) while the cumulative update counter stays.
    scope_bot.vi_burned_states = 7
    scope_bot.vi_burn_updates = 3
    scope_bot._update_construction_plan(flip_board, their_pieces=1)
    check(
        "certificates do not survive replanning",
        scope_bot.plan is None
        and not scope_bot._vi_dead_policies
        and not scope_bot._vi_unbuildable
        and scope_bot.plan_invalidations == 1
        and scope_bot.vi_burned_states == 0
        and scope_bot.vi_burn_updates == 3,
        f"plan={scope_bot.plan}; "
        f"dead={len(scope_bot._vi_dead_policies)}; "
        f"unbuildable={len(scope_bot._vi_unbuildable)}; "
        f"burn gauge={scope_bot.vi_burned_states}/"
        f"updates={scope_bot.vi_burn_updates}",
    )

    # 18. Certification answers from stored dead certificates without
    # rebuilding: the sole maximal herder subset here is the very pair the
    # dead policy certified, so the sweep completes with zero fresh builds
    # and still returns the hopeless verdict that gates the side flip.
    cache_bot = LoseBot(depth=1, opponent_model="zach", profile="vi")
    cache_bot.plan = flip_plan
    cached_policy, cached_verdict = None, ""
    if dead_policy is not None and flip_target is not None:
        cache_bot._vi_dead_policies.append(dead_policy)
        cached_policy, cached_verdict = cache_bot._certify_herding(
            flip_board, flip_target, 2
        )
    check(
        "certification reuses dead certificates without rebuilding",
        dead_policy is not None
        and cached_policy is None
        and cached_verdict == "hopeless"
        and cache_bot.vi_builds == 0,
        f"verdict={cached_verdict}; builds={cache_bot.vi_builds}",
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

    # 20a. King-holder template mode: on the exact vacate fixture the
    # enumeration must produce a king-holder variant — our KING is the
    # arrival holder, the march metric measures to the ARRIVAL square, the
    # corner cage is the single g1 bishop — and the mode must outrank every
    # piece-holder template (the release theorem prices those at zero).
    # Plans are mode-committed: a piece-mode plan on the same board must
    # keep resolving piece templates.
    kha_board = chess.Board(motif["kh-corner-h"].fen)
    kha_best = best_pawn_mate_template(kha_board, chess.WHITE)
    kha_plan = (
        None
        if kha_best is None
        else ConstructionPlan.from_template(kha_best, created_ply=0)
    )
    kha_resolved = (
        None if kha_plan is None else kha_plan.resolve(kha_board, chess.WHITE)
    )
    kha_piece_plan = ConstructionPlan(
        pawn_file=6, checked_side=1, created_ply=0
    )
    kha_piece = kha_piece_plan.resolve(kha_board, chess.WHITE)
    check(
        "king-holder template is enumerated, preferred, and mode-committed",
        kha_best is not None
        and kha_best.king_holder
        and kha_best.uci == "g3g2"
        and kha_best.checked_square == chess.H1
        and kha_best.our_king_steps == 0
        and kha_best.hold_established
        and kha_best.cage_occupancy == 1
        and kha_best.required_cage == 1
        and kha_best.race_clear
        and not kha_best.ready_to_release
        and kha_best.kh_cage_square == chess.G1
        and kha_best.kh_escape_square == chess.H2
        and kha_best.kh_entry_square == chess.H3
        and kha_best.kh_seal_square == chess.H4
        and kha_best.kh_far_capture_square == chess.F2
        and kha_plan is not None
        and kha_plan.holder_mode == "king"
        and kha_resolved is not None
        and kha_resolved.king_holder
        and kha_piece is not None
        and not kha_piece.king_holder,
        "none" if kha_best is None else (
            f"{kha_plan.label}: king_steps={kha_best.our_king_steps}, "
            f"cage={kha_best.cage_occupancy}, "
            f"piece-plan resolves king_holder={None if kha_piece is None else kha_piece.king_holder}"
        ),
    )

    # 20b. The mode's existence gates: the mate's sealing move must not give
    # check, so a knight-class closer must exist; and no piece but a bishop
    # is sound on the corner cage square (rook/queen there re-attack the
    # arrival square and refute the mate, a knight covers the defender's
    # entry), so a cage-colored bishop must exist too.
    kh_no_knight = chess.Board(motif["kh-corner-h"].fen)
    kh_no_knight.remove_piece_at(chess.F8)
    knightless = [
        t for t in pawn_mate_templates(kh_no_knight, chess.WHITE)
        if t.king_holder
    ]
    kh_no_bishop = chess.Board(motif["kh-corner-h"].fen)
    kh_no_bishop.remove_piece_at(chess.G1)
    bishopless = [
        t for t in pawn_mate_templates(kh_no_bishop, chess.WHITE)
        if t.king_holder
    ]
    check(
        "king-holder mode requires a knight closer and a cage bishop",
        not knightless and not bishopless,
        f"knightless={len(knightless)}; bishopless={len(bishopless)}",
    )

    # 20c. Construction order: the cage is built first and the king takes
    # the arrival square LAST. From the construction drill start the cage
    # filter must commit to Bg1 (the regression filter must not veto the
    # landing — for a king holder the "runway" square IS the cage square),
    # the regression filter must veto parking the king before the cage
    # exists, and once the bishop lands the march filter must commit to Kg2.
    drill_board = chess.Board(KING_HOLDER_DRILL_FEN)
    drill_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi",
        probe_cap=0, max_probe_n=1, vi_herders=1,
    )
    drill_mv1 = drill_bot.choose_move(drill_board)
    drill_target = drill_bot.planned_target(drill_board, chess.WHITE)
    early_park = drill_bot._filter_plan_regressions(
        drill_board,
        [chess.Move.from_uci("f1g2"), chess.Move.from_uci("d4g1")],
        drill_target,
    )
    check(
        "king-holder construction cages before the king parks",
        drill_bot.plan is not None
        and drill_bot.plan.holder_mode == "king"
        and drill_mv1 == chess.Move.from_uci("d4g1")
        and early_park == [chess.Move.from_uci("d4g1")]
        and drill_bot.vi_cage_builds >= 1,
        f"move={drill_board.san(drill_mv1)}; "
        f"plan={'none' if drill_bot.plan is None else drill_bot.plan.label}; "
        f"early-park-filter={[m.uci() for m in early_park]}",
    )
    drill_board.push(drill_mv1)
    drill_board.push(chess.Move.from_uci("c6b5"))
    drill_mv2 = drill_bot.choose_move(drill_board)
    check(
        "king-holder march commits once the cage bishop lands",
        drill_mv2 == chess.Move.from_uci("f1g2")
        and drill_bot.vi_king_marches >= 1,
        f"move={drill_board.san(drill_mv2)}; "
        f"marches={drill_bot.vi_king_marches}",
    )

    # 20d. The vacate is gated at play time on the audited race. On the
    # sealed corner (kh-corner-h: rook already on a5, their king h4) the
    # release scorer accepts Kh1 at race 1/2 and the bot plays it. On the
    # unsealed pose (kh-herd-h4: rook still on a1, so h5 leaks) the same
    # release is refused and the bot must keep the king parked and herd.
    sealed_board = chess.Board(motif["kh-corner-h"].fen)
    sealed_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1,
    )
    sealed_mv = sealed_bot.choose_move(sealed_board)
    unsealed_board = chess.Board(motif["kh-herd-h4"].fen)
    unsealed_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1,
    )
    unsealed_mv = unsealed_bot.choose_move(unsealed_board)
    check(
        "play vacates exactly when the scored race accepts",
        sealed_mv == chess.Move.from_uci("g2h1")
        and sealed_bot.vi_releases == 1
        and unsealed_mv.from_square != chess.G2
        and unsealed_bot.vi_releases == 0,
        f"sealed={sealed_board.san(sealed_mv)} "
        f"(releases={sealed_bot.vi_releases}); "
        f"unsealed={unsealed_board.san(unsealed_mv)} "
        f"(releases={unsealed_bot.vi_releases})",
    )

    # 20e. A completed king-holder construction stays eligible for DEEP
    # probes: the profile's deep_probe_min_cage (3) is a piece-holder
    # reserve size, while a finished corner cage is exactly one bishop, so
    # the gate must compare against the template's own required_cage. The
    # exact probe is the only machinery that can find organic multi-move
    # forced selfmates in king-holder positions (e.g. via a second mobile
    # pawn); with none present it must complete its disproofs and fall
    # through to the scored vacate unchanged.
    probe_board = chess.Board(motif["kh-corner-h"].fen)
    probe_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1,
        probe_cap=50_000,
    )
    probe_mv = probe_bot.choose_move(probe_board)
    check(
        "completed king-holder holds stay eligible for deep probes",
        probe_mv == chess.Move.from_uci("g2h1")
        and probe_bot.deep_probe_skips == 0
        and probe_bot.deepest_probe_completed >= 2,
        f"move={probe_board.san(probe_mv)}; "
        f"skips={probe_bot.deep_probe_skips}; "
        f"deepest={probe_bot.deepest_probe_completed}; "
        f"exhaustions={probe_bot.probe_budget_exhaustions}",
    )

    # 21a. The certify sweep carries a side-level conversion verdict. On the
    # 14d fixture the greedy subset is live but audits complete with nothing
    # converting; the old sweep stopped there and played it blind. The gated
    # sweep must CONTINUE past a live-unconvertible subset hunting a
    # convertible one (here the mirror rook, which resolves the same way),
    # and only then pass "unconvertible" — the honest flip trigger — with
    # the first live subset kept as the playable fallback. Both audits must
    # have completed for the negative to count at all.
    sweep_bot = LoseBot(depth=1, opponent_model="zach", profile="vi")
    sweep_bot.profile = _replace(
        sweep_bot.profile, vi_build_ms=120_000, vi_conversion_ms=30_000
    )
    sweep_policy, sweep_verdict = None, ""
    if vi_target is not None:
        sweep_policy, sweep_verdict = sweep_bot._certify_herding(
            vi_board, vi_target, 1
        )
    check(
        "certify sweep continues past live-unconvertible subsets",
        sweep_policy is not None
        and sweep_verdict == "unconvertible"
        and sweep_policy.report.ok
        and sweep_policy.report.root_live
        and not sweep_policy.report.root_converts
        and sweep_policy.report.conversion_complete
        and sweep_bot.vi_builds == 2
        and sweep_bot.vi_conversion_incomplete == 0,
        f"verdict={sweep_verdict}; builds={sweep_bot.vi_builds}; "
        + ("no policy" if sweep_policy is None else (
            f"live={sweep_policy.report.root_live}; "
            f"converts={sweep_policy.report.root_converts}; "
            f"complete={sweep_policy.report.conversion_complete}"
        )),
    )

    # 21b. The flip gate's decision table, white-boxed at the prospect (the
    # suite has no organic position yet whose MIRROR prospect converts —
    # king-holder mirrors have no corner, so the organic fire case is a
    # piece-mode mirror with reachable forced mates). Leaving a LIVE side
    # requires a positively converting prospect; a complete-audit refusal
    # backs off long, a starved audit short. Leaving a hopeless side keeps
    # accepting any live prospect — there is nothing to stay for.
    from . import bot as _bot_module

    def _flip_case(require_conversion, **report_fields):
        report = dict(
            ok=True, root_live=True, root_converts=False,
            conversion_complete=True, root_value=0.5, min_hit_root=0,
            fit_hit_root=0,
        )
        report.update(report_fields)
        gate_bot = LoseBot(depth=1, opponent_model="zach", profile="vi")
        gate_bot.plan = ConstructionPlan(
            pawn_file=chess.square_file(chess.B6),
            checked_side=1,
            created_ply=0,
        )
        real = _bot_module.prospective_flip_policy
        _bot_module.prospective_flip_policy = (
            lambda *args, **kwargs: _NS(report=_NS(**report))
        )
        try:
            fired = gate_bot._consider_side_flip(
                flip_board, 2, require_conversion=require_conversion
            )
        finally:
            _bot_module.prospective_flip_policy = real
        return fired, gate_bot

    converts_fired, converts_bot = _flip_case(
        True, root_converts=True, fit_hit_root=12
    )
    refused_fired, refused_bot = _flip_case(True)
    starved_fired, starved_bot = _flip_case(True, conversion_complete=False)
    hopeless_fired, hopeless_bot = _flip_case(False)
    check(
        "side flips leave a live side only for a converting prospect",
        converts_fired
        and converts_bot.plan.checked_side == -1
        and converts_bot.vi_side_flips == 1
        and converts_bot.vi_conversion_flips == 1
        and not refused_fired
        and refused_bot.plan.checked_side == 1
        and refused_bot._vi_next_flip_ply == 16
        and not starved_fired
        and starved_bot._vi_next_flip_ply == 8
        and hopeless_fired
        and hopeless_bot.vi_side_flips == 1
        and hopeless_bot.vi_conversion_flips == 0,
        f"converts fired={converts_fired} "
        f"(flips={converts_bot.vi_side_flips}, "
        f"gated={converts_bot.vi_conversion_flips}); "
        f"refused cooldown={refused_bot._vi_next_flip_ply}; "
        f"starved cooldown={starved_bot._vi_next_flip_ply}; "
        f"hopeless fired={hopeless_fired}",
    )

    # 22a. Prospective king-holder templates name the corner geometry while
    # the executioner is still walking: fixed corner, cage, entry, seal and
    # park squares from the FINAL arrival, the outstanding Zach pushes in
    # pawn_walk, our men on the path in walk_blockers. They are resolution
    # targets for a committed king-mode plan only — fresh-plan selection
    # must keep returning the piece template, because steering toward a
    # walk is keyed on the committed side's audited verdict, not ranking.
    adopt_board = chess.Board(ADOPTION_DRILL_FEN)
    walking = [
        t for t in pawn_mate_templates(adopt_board, chess.WHITE)
        if t.king_holder
    ]
    adopt_best = best_pawn_mate_template(adopt_board, chess.WHITE)
    adopt_plan = ConstructionPlan(
        pawn_file=1, checked_side=-1, created_ply=0, holder_mode="king"
    )
    adopt_resolved = adopt_plan.resolve(adopt_board, chess.WHITE)
    check(
        "walking king-holder templates carry the corner and the debt",
        len(walking) == 1
        and walking[0].uci == "b6b2"
        and walking[0].checked_square == chess.A1
        and walking[0].pawn_walk == 3
        and walking[0].walk_blockers == 2
        and walking[0].kh_cage_square == chess.B1
        and walking[0].kh_entry_square == chess.A3
        and walking[0].kh_seal_square == chess.A4
        and walking[0].kh_closer_park_square == chess.C8
        and kha_best is not None
        and kha_best.kh_closer_park_square == chess.F8
        and adopt_best is not None
        and not adopt_best.king_holder
        and adopt_resolved is not None
        and adopt_resolved.pawn_walk == 3,
        f"kh={[t.uci for t in walking]}; "
        f"best={'none' if adopt_best is None else adopt_best.uci}; "
        + (
            "unresolved" if adopt_resolved is None else
            f"resolves walk={adopt_resolved.pawn_walk}"
            f"/blockers={adopt_resolved.walk_blockers}"
        ),
    )

    # 22b. Walk feasibility vetoes. Our pawn on the final arrival square can
    # never leave the file (case 2's b2 pawn — which is also why that
    # battery reference cannot shift). A piece of theirs on the path is
    # uncleanable by us, but the LOWER pawn then walks a shorter path and
    # emits instead. No knight closer or no cage-shade bishop: no template.
    case2_board = chess.Board(ENDGAME_FENS[1])
    case2_kh = [
        t for t in pawn_mate_templates(case2_board, chess.WHITE)
        if t.king_holder
    ]
    lower_board = chess.Board("8/8/1p1k4/RR6/Kp6/1NPB4/8/8 w - - 0 1")
    lower_kh = [
        t for t in pawn_mate_templates(lower_board, chess.WHITE)
        if t.king_holder
    ]
    knightless_board = chess.Board(ADOPTION_DRILL_FEN)
    knightless_board.remove_piece_at(chess.B3)
    shadeless_board = chess.Board(ADOPTION_DRILL_FEN)
    shadeless_board.remove_piece_at(chess.D3)
    shadeless_board.set_piece_at(
        chess.E3, chess.Piece(chess.BISHOP, chess.WHITE)
    )
    check(
        "walk vetoes: arrival pawns, their path men, missing kit",
        not case2_kh
        and len(lower_kh) == 1
        and lower_kh[0].uci == "b4b2"
        and lower_kh[0].pawn_walk == 1
        and not [
            t for t in pawn_mate_templates(knightless_board, chess.WHITE)
            if t.king_holder
        ]
        and not [
            t for t in pawn_mate_templates(shadeless_board, chess.WHITE)
            if t.king_holder
        ],
        f"case2={len(case2_kh)}; lower={[t.uci for t in lower_kh]}",
    )

    # 22c. The adoption trigger. On the drill start the piece side's only
    # herder subset (the d3 bishop — everything else is holder or cage)
    # certifies dead, so the verdict is hopeless, the mirror cannot even
    # pose (c4 is our own pawn), and the plan must be REPLACED: commit the
    # corner king-holder plan, remember it, reset the policy era. The
    # trigger is one-way — a king-mode plan never re-adopts.
    adopt_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    adopt_bot._update_construction_plan(adopt_board, their_pieces=0)
    piece_plan_first = (
        adopt_bot.plan is not None
        and adopt_bot.plan.holder_mode == "piece"
    )
    adopt_target = adopt_bot.planned_target(adopt_board, chess.WHITE)
    _, adopt_verdict = adopt_bot._certify_herding(adopt_board, adopt_target, 1)
    adopt_bot._vi_policy = object()  # observe the reset
    adopted = adopt_bot._consider_kh_adoption(adopt_board)
    readopted = adopt_bot._consider_kh_adoption(adopt_board)
    check(
        "a hopeless piece side adopts the corner king-holder plan once",
        piece_plan_first
        and adopt_verdict == "hopeless"
        and adopted
        and adopt_bot.plan.holder_mode == "king"
        and adopt_bot.plan.label == "b-pawn/left/king"
        and adopt_bot._kh_adoption == (1, -1)
        and adopt_bot.vi_kh_adoptions == 1
        and adopt_bot._vi_policy is None
        and not readopted
        and adopt_bot.vi_kh_adoptions == 1,
        f"verdict={adopt_verdict}; adopted={adopted}; "
        f"plan={'none' if adopt_bot.plan is None else adopt_bot.plan.label}",
    )

    # 22d. Adoption memory survives the plan era. A promotion mid-walk
    # invalidates the plan; on the next king-and-pawns replan the sticky
    # target must re-commit the king-holder plan directly instead of
    # rebuilding a piece plan that would have to re-certify unconvertible
    # before steering back here.
    sticky_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    sticky_bot._kh_adoption = (1, -1)
    sticky_bot._update_construction_plan(adopt_board, their_pieces=0)
    check(
        "remembered adoptions re-commit without a fresh piece plan",
        sticky_bot.plan is not None
        and sticky_bot.plan.holder_mode == "king"
        and sticky_bot.plan.label == "b-pawn/left/king"
        and sticky_bot.vi_kh_adoptions == 1,
        f"plan={'none' if sticky_bot.plan is None else sticky_bot.plan.label}",
    )

    # 22e. Walk choreography gates. During the walk the ordering inverts:
    # the king marches BEFORE the cage exists (pending pushes make the
    # construction clock-free, and the parked king is the freeze that
    # stops the premature push), and the early-park regression veto lifts
    # for the same reason — while at arrival (pawn_walk == 0) both gates
    # restore the drill's cage-first order. The walk-clear commitment
    # keeps only freeze-releasing moves, and never one that shuffles a
    # blocker along the path.
    walk_board = chess.Board("8/8/1p1k4/R7/K1P5/2PB4/4N3/7R w - - 0 1")
    walk_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    walk_bot.plan = adopt_plan
    walk_target = walk_bot.planned_target(walk_board, chess.WHITE)
    walk_march = walk_bot._filter_king_march(
        walk_board,
        [chess.Move.from_uci("a4b3"), chess.Move.from_uci("h1h2")],
        walk_target,
    )
    arrived_board = chess.Board("8/8/3k4/R7/K1P5/1pPB4/4N3/7R w - - 0 1")
    arrived_target = walk_bot.planned_target(arrived_board, chess.WHITE)
    arrived_march = walk_bot._filter_king_march(
        arrived_board,
        [chess.Move.from_uci("a4b3"), chess.Move.from_uci("h1h2")],
        arrived_target,
    )
    park_board = chess.Board("8/8/1p1k4/R7/2P5/2PB4/4N3/2K4R w - - 0 1")
    park_target = walk_bot.planned_target(park_board, chess.WHITE)
    walk_park = walk_bot._filter_plan_regressions(
        park_board,
        [chess.Move.from_uci("c1b2"), chess.Move.from_uci("h1h2")],
        park_target,
    )
    parked_board = chess.Board("8/8/3k4/R7/2P5/1pPB4/4N3/2K4R w - - 0 1")
    parked_target = walk_bot.planned_target(parked_board, chess.WHITE)
    arrived_park = walk_bot._filter_plan_regressions(
        parked_board,
        [chess.Move.from_uci("c1b2"), chess.Move.from_uci("h1h2")],
        parked_target,
    )
    clear_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    clear_bot.plan = adopt_plan
    clear_target = clear_bot.planned_target(adopt_board, chess.WHITE)
    cleared = clear_bot._filter_walk_clear(
        adopt_board,
        [
            chess.Move.from_uci("b5e5"),
            chess.Move.from_uci("b5b4"),
            chess.Move.from_uci("a5a6"),
        ],
        clear_target,
    )
    check(
        "walk gates invert the construction order until arrival",
        walk_march == [chess.Move.from_uci("a4b3")]
        and len(arrived_march) == 2
        and chess.Move.from_uci("c1b2") in walk_park
        and chess.Move.from_uci("c1b2") not in arrived_park
        and cleared == [chess.Move.from_uci("b5e5")]
        and clear_bot.vi_walk_clears == 1,
        f"march walk={[m.uci() for m in walk_march]}"
        f"/arrived={[m.uci() for m in arrived_march]}; "
        f"park walk={[m.uci() for m in walk_park]}"
        f"/arrived={[m.uci() for m in arrived_park]}; "
        f"clear={[m.uci() for m in cleared]}",
    )

    # 22f. The wait phase shares the arena's adjudication oracle: a move
    # whose own landing — or ANY Zach reply to it — the arena would call
    # drawn is a funnel no tally of our own choices can see (the session-6
    # lesson replayed outside the sub-MDP, where no policy exists to burn
    # states). At halfmove 98 the quiet rook shuffle hands Zach a
    # fifty-move completion; the wall push resets the clock and survives.
    # The sub-MDP itself stays gated off while the pawn walks: geometry
    # that is not posed cannot be certified, flipped, or released.
    funnel_board = chess.Board("8/8/1p1k4/R7/K1P5/2PB4/4N3/7R w - - 98 60")
    funnel_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    funnel_bot.plan = adopt_plan
    funnel_target = funnel_bot.planned_target(funnel_board, chess.WHITE)
    guarded_moves = funnel_bot._filter_wait_funnels(
        funnel_board,
        [chess.Move.from_uci("h1h2"), chess.Move.from_uci("c4c5")],
        funnel_target,
    )
    gate_vi_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    gate_vi_bot.plan = adopt_plan
    gate_walk_target = gate_vi_bot.planned_target(walk_board, chess.WHITE)
    gate_choice = gate_vi_bot._vi_choice(
        walk_board, gate_walk_target, list(walk_board.legal_moves)
    )
    check(
        "the wait phase dodges adjudication funnels and skips the sub-MDP",
        guarded_moves == [chess.Move.from_uci("c4c5")]
        and funnel_bot.vi_wait_funnel_guards == 1
        and gate_walk_target is not None
        and gate_walk_target.pawn_walk == 3
        and gate_choice is None
        and gate_vi_bot.vi_builds == 0,
        f"guarded={[m.uci() for m in guarded_moves]}; "
        f"vi builds during walk={gate_vi_bot.vi_builds}",
    )

    # 22g. Review follow-ups, all three P1s. (1) Adoption memory is scoped
    # to the game whose verdicts earned it: the arena reuses bot instances,
    # so the rewind branch — the game boundary — must clear it, or game
    # N+1 recommits game N's corner without ever certifying a side (the
    # planner profile isolates the sticky replan path from re-adoption).
    # (2) A parked closer stays parked for the rest of the walk: a wander
    # can be interrupted by the pawn's arrival with the seal unservable.
    # (3) The king-mode pawn veto counts race debt instead of reading the
    # race_clear boolean: with pawns on both f2 and h2, f2-f3 clears one
    # debt and must pass, while h2-h3 merely trades the escape square for
    # the entry square and stays vetoed.
    rewind_bot = LoseBot(
        depth=1, opponent_model="zach", profile="planner",
        probe_cap=0, max_probe_n=1,
    )
    rewind_bot._kh_adoption = (1, -1)
    rewind_bot._last_seen_ply = 99
    rewind_bot.choose_move(adopt_board)
    closer_board = chess.Board("2N5/8/3k4/8/1pP5/2P5/1K6/1B5R w - - 0 1")
    closer_target = walk_bot.planned_target(closer_board, chess.WHITE)
    closer_kept = walk_bot._filter_plan_regressions(
        closer_board,
        [chess.Move.from_uci("c8e7"), chess.Move.from_uci("h1h2")],
        closer_target,
    )
    debt_board = chess.Board("5N2/8/8/8/7k/6p1/5PKP/6B1 w - - 0 1")
    debt_plan = ConstructionPlan(
        pawn_file=6, checked_side=1, created_ply=0, holder_mode="king"
    )
    debt_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    debt_bot.plan = debt_plan
    debt_target = debt_bot.planned_target(debt_board, chess.WHITE)
    debt_kept = debt_bot._filter_plan_regressions(
        debt_board,
        [
            chess.Move.from_uci("f2f3"),
            chess.Move.from_uci("h2h3"),
            chess.Move.from_uci("f8h7"),
        ],
        debt_target,
    )
    check(
        "review: game-scoped adoption, pinned closer, counted race debt",
        rewind_bot._kh_adoption is None
        and rewind_bot.plan is not None
        and rewind_bot.plan.holder_mode == "piece"
        and closer_target is not None
        and closer_target.pawn_walk == 1
        and chess.Move.from_uci("c8e7") not in closer_kept
        and chess.Move.from_uci("h1h2") in closer_kept
        and debt_target is not None
        and not debt_target.race_clear
        and chess.Move.from_uci("f2f3") in debt_kept
        and chess.Move.from_uci("h2h3") not in debt_kept
        and chess.Move.from_uci("f8h7") in debt_kept,
        f"rewind plan="
        f"{'none' if rewind_bot.plan is None else rewind_bot.plan.label}"
        f" memory={rewind_bot._kh_adoption}; "
        f"closer={[m.uci() for m in closer_kept]}; "
        f"debt={[m.uci() for m in debt_kept]}",
    )

    # 23a. Clock feasibility: hitting-time statistics on the solved graph,
    # FINISH-INCLUSIVE in two tiers (review P1: rejection and affirmation
    # need opposite conservatism). min_hit seeds the per-kind floor — one
    # mating reply for a forced mate, release plus mating reply for a
    # goal — and stays the rejection bound; fit_hit and exp_hit seed each
    # goal's audit-PROVEN completion tail, the affirmative bound.
    # fm-organic-h reaches its forced-mate fan in one ply and finishes in
    # 2 on both tiers (a forced mate owes exactly the mating reply) —
    # which FITS remaining 2 (halfmove 98: one quiet move to clock 99,
    # hxg2# mates), the review's exact false-rejection case. kh-herd-h4's
    # root REACHES its vacate goal floor-priced in 6 (best child 5,
    # detour child 9, dead child HIT_INF), but the audited race needs
    # probe-proven continuations (the Kh1/Kh3/Ng6/g2# branch), so the
    # affirmative tier prices the finish at 10 = 4 plies of herd + the
    # 2 + 2*probe_n proven tail, exp on the same deterministic track. A
    # their-turn root on the same static split (the clock-reset
    # hypothetical's shape) certifies the REAL post-reply continuation:
    # its children are the actual reply states, and every one still fits
    # a fresh era on the AFFIRMATIVE tier.
    from .herding_vi import HIT_INF

    hit_fm = HerdingPolicy.build(
        chess.Board(motif["fm-organic-h"].fen),
        _motif_target(motif["fm-organic-h"]),
        max_herders=1, state_cap=200_000, time_budget_ms=30_000,
        gamma=0.99, model="zach",
    )
    hit_kh = HerdingPolicy.build(
        chess.Board(motif["kh-herd-h4"].fen),
        _motif_target(motif["kh-herd-h4"]),
        max_herders=1, state_cap=200_000, time_budget_ms=30_000,
        gamma=0.96, model="zach", herders=((chess.A1, chess.ROOK),),
    )
    kh_hit_ranked = (
        hit_kh.ranked_moves(chess.Board(motif["kh-herd-h4"].fen)) or []
    )
    kh_child_hits = {
        hit_kh.child_min_hit(child) for _, _, child in kh_hit_ranked
    }
    kh_root_hits = hit_kh.hit_estimates(
        chess.Board(motif["kh-herd-h4"].fen)
    )
    their_board = chess.Board(motif["kh-herd-h4"].fen)
    their_board.turn = chess.BLACK
    hit_their = HerdingPolicy.build(
        their_board, _motif_target(motif["kh-herd-h4"]),
        max_herders=1, state_cap=200_000, time_budget_ms=30_000,
        gamma=0.96, model="zach", herders=((chess.A1, chess.ROOK),),
        root_theirs=True,
    )
    check(
        "hitting-time stats are exact and finish-inclusive",
        hit_fm.report.ok
        and hit_fm.report.root_converts
        and hit_fm.report.min_hit_root == 2
        and hit_fm.report.min_hit_root <= 2  # fits remaining 2 at clock 98
        and hit_fm.report.fit_hit_root == 2
        and abs(hit_fm.report.exp_hit_root - 2.0) < 1e-9
        and hit_fm.report.hit_converged
        and hit_kh.report.ok
        and hit_kh.report.root_converts
        and hit_kh.report.min_hit_root == 6
        and hit_kh.report.fit_hit_root == 10
        and abs(hit_kh.report.exp_hit_root - 10.0) < 1e-6
        and hit_kh.report.hit_converged
        and kh_root_hits is not None
        and kh_root_hits[0] == 6
        and kh_root_hits[1] == 10
        and kh_child_hits == {5, 9, HIT_INF}
        and hit_their.report.ok
        and hit_their.report.root_live
        and hit_their.report.root_converts
        and hit_their.report.min_hit_root == 5
        and hit_their.reply_fit_fraction() == 1.0
        and hit_kh.reply_fit_fraction() is None,
        f"fm=({hit_fm.report.min_hit_root}, "
        f"fit {hit_fm.report.fit_hit_root}, "
        f"{hit_fm.report.exp_hit_root:.2f}); "
        f"kh=({hit_kh.report.min_hit_root}, "
        f"fit {hit_kh.report.fit_hit_root}, "
        f"{hit_kh.report.exp_hit_root:.2f}); "
        f"kh-children={sorted(kh_child_hits)}; "
        f"their-root=({hit_their.report.min_hit_root}, "
        f"fraction={hit_their.reply_fit_fraction()})",
    )

    # 23b. The near-cliff release relaxation consults the solved MDP: with
    # the policy warm and the audited 1/2 vacate goal's PROVEN finish an
    # affirmative 10 plies away (review P1: the floor said 6, but the
    # audited race owes probe-proven continuations the floor cannot
    # see), remaining 16 affirms the herd still fits (fit_hit 10 and
    # soft-factored exp_hit 15 inside the budget, both honesty flags
    # required for the affirmation), so the strict standard holds and
    # the bot herds Ra2 toward the better race; remaining 6 has no
    # affirmable herd left (10 > 6), and the bot takes the best positive
    # lottery available now — Kh1 at race 1/3 — under relaxed standards.
    def _warm_kh_bot():
        warm = LoseBot(
            depth=1, opponent_model="zach", profile="vi", vi_herders=1
        )
        warm.choose_move(chess.Board(motif["kh-herd-h4"].fen))
        return warm

    hold_bot = _warm_kh_bot()
    hold_board = chess.Board(motif["kh-herd-h4"].fen)
    hold_board.halfmove_clock = 84
    hold_move = hold_bot.choose_move(hold_board)
    relax_bot = _warm_kh_bot()
    relax_board = chess.Board(motif["kh-herd-h4"].fen)
    relax_board.halfmove_clock = 94
    relax_move = relax_bot.choose_move(relax_board)
    check(
        "the cliff relaxation defers to a herd the MDP still affirms",
        hold_move == chess.Move.from_uci("a1a2")
        and hold_bot.vi_releases == 0
        and hold_bot.vi_clock_relaxed_releases == 0
        and relax_move == chess.Move.from_uci("g2h1")
        and relax_bot.vi_releases == 1
        and relax_bot.vi_clock_relaxed_releases == 1,
        f"remaining16={hold_board.san(hold_move)} "
        f"(relaxed={hold_bot.vi_clock_relaxed_releases}); "
        f"remaining6={relax_board.san(relax_move)} "
        f"(relaxed={relax_bot.vi_clock_relaxed_releases})",
    )

    # 23f. A p/m pass truncated behind a CONVERGED solve is not permanent
    # (review P1: solve_more never runs once converged, so nothing ever
    # recomputed the stats and hit_converged=False starved the release
    # affirmation forever). End to end: simulate the shared-deadline
    # truncation on a warm policy and the fits consumer itself retries on
    # a dedicated budget — the affirmation lights back up and the herd
    # holds Ra2 at remaining 16 instead of cashing the lottery. At the
    # policy level the retry is single-shot per value basis: a spent
    # ledger keeps returning the honest False instead of redoing
    # identical truncated work every move, and only a recompute on new
    # values (burn re-solves, resumed builds) re-arms it.
    refresh_bot = _warm_kh_bot()
    refresh_policy = refresh_bot._vi_policy
    refresh_policy.report.hit_converged = False
    refresh_policy.report.exp_hit_root = 0.0
    refresh_policy._exp_hit = None
    refresh_board = chess.Board(motif["kh-herd-h4"].fen)
    refresh_board.halfmove_clock = 84
    refresh_move = refresh_bot.choose_move(refresh_board)
    hit_kh.report.hit_converged = False
    hit_kh.report.exp_hit_root = 0.0
    hit_kh._exp_hit = None
    hit_kh._hit_refresh_spent = True
    spent_refused = hit_kh.refresh_hit_stats(30_000)
    spent_exp = hit_kh.report.exp_hit_root
    hit_kh._hit_refresh_spent = False
    rearmed = hit_kh.refresh_hit_stats(30_000)
    check(
        "truncated hitting stats refresh where consumed, once per basis",
        refresh_move == chess.Move.from_uci("a1a2")
        and refresh_bot.vi_hit_refreshes == 1
        and refresh_policy.report.hit_converged
        and abs(refresh_policy.report.exp_hit_root - 10.0) < 1e-6
        and not spent_refused
        and spent_exp == 0.0
        and rearmed
        and hit_kh.report.hit_converged
        and abs(hit_kh.report.exp_hit_root - 10.0) < 1e-6,
        f"refresh-pick={refresh_board.san(refresh_move)} "
        f"(refreshes={refresh_bot.vi_hit_refreshes}, "
        f"exp={refresh_policy.report.exp_hit_root:.2f}); "
        f"spent refused={not spent_refused} (exp={spent_exp:.2f}); "
        f"re-armed exp={hit_kh.report.exp_hit_root:.2f}",
    )

    # 23i. Affirmative gates read THIS decision's burn set (review P1:
    # the recount used to run after the release affirmation and the
    # clock gates, so second visits created by the last move-pair were
    # invisible exactly when the affirmation fired — a herd whose every
    # converting goal had just burned still read fit 10, suppressed the
    # lottery, and herded into a threefold-dead graph). The rook tour
    # below enters every converting vacate goal twice — each
    # (zk=h4, rook-on-rank-5) state via the rank-5 check and the forced
    # Kh4, cycled through the 6th/7th-rank tempo lanes so no position
    # reaches a third occurrence — and ends back at the fixture root.
    # The clock rides in the starting FEN (14 + 70 tour plies = 84):
    # a manual halfmove_clock override would be silently rebuilt by
    # is_repetition's pop/re-push walk. The warm bot recounts inside
    # the release gate, the affirmation dies honestly at fit INF, and
    # the Kh1 lottery fires at remaining 16 instead of being suppressed
    # by the stale fit of 10.
    def _kh_burn_history():
        tour = chess.Board(
            "5NN1/8/1R6/7k/5P2/5Pp1/6K1/6B1 w - - 14 1"
        )
        tour_files = "bcdef"
        san = []
        for i, x in enumerate(tour_files):
            san += [
                f"R{x}5", "Kh4", f"R{x}6", "Kh5",
                f"R{x}5", "Kh4", f"R{x}7", "Kh5",
            ]
            nxt = "a" if x == "f" else tour_files[i + 1]
            san += [f"R{nxt}7", "Kh4", f"R{nxt}6", "Kh5"]
        san += [
            "Ra5", "Kh4", "Ra6", "Kh5", "Ra5", "Kh4",
            "Ra7", "Kh5", "Ra1", "Kh4",
        ]
        for step in san:
            tour.push_san(step)
        return tour

    tour_board = _kh_burn_history()
    tour_bot = _warm_kh_bot()
    tour_pick = tour_bot.choose_move(tour_board)
    tour_policy = tour_bot._vi_policy
    tour_est = (
        None if tour_policy is None
        else tour_policy.hit_estimates(tour_board)
    )
    check(
        "release affirmation prices this decision's burns, not last turn's",
        tour_board.halfmove_clock == 84
        and tour_board.board_fen()
        == chess.Board(motif["kh-herd-h4"].fen).board_fen()
        and not tour_board.is_repetition(3)
        and tour_pick == chess.Move.from_uci("g2h1")
        and tour_bot.vi_clock_relaxed_releases == 1
        and tour_bot.vi_releases == 1
        and tour_bot.vi_burn_updates >= 1
        and tour_est is not None
        and tour_est[1] == HIT_INF,
        f"pick={tour_board.san(tour_pick)} "
        f"(relaxed={tour_bot.vi_clock_relaxed_releases}, "
        f"burn-updates={tour_bot.vi_burn_updates}, "
        f"burned={tour_bot.vi_burned_states}, "
        f"fit="
        f"{'INF' if tour_est and tour_est[1] >= HIT_INF else tour_est})",
    )

    # 23k. The release affirmation gates on the policy mapping the
    # position BEFORE the recount (review P3): a cached policy that no
    # longer maps can never answer hit_estimates, so the old order paid
    # a history recount — and, mid-solve, a vi_build_ms re-solve — per
    # near-cliff decision on a graph whose affirmation was never
    # coming. A warm kh policy marked mid-solve meets the near-cliff
    # board with a foreign a2 pawn: off the static split, contains()
    # False, so the bot must take the relaxed lottery without spending
    # a resolve on the stale graph — and without the main path
    # rebuilding either, since the release returns first. The
    # conservative outcome (no affirmation -> relax) is unchanged.
    stale_bot = _warm_kh_bot()
    stale_policy = stale_bot._vi_policy
    stale_policy.report.converged = False
    stale_board = chess.Board(motif["kh-herd-h4"].fen)
    stale_board.set_piece_at(chess.A2, chess.Piece(chess.PAWN, chess.WHITE))
    stale_board.halfmove_clock = 94
    stale_move = stale_bot.choose_move(stale_board)
    check(
        "a stale policy is not recounted or re-solved for the affirmation",
        not stale_policy.contains(stale_board)
        and stale_move == chess.Move.from_uci("g2h1")
        and stale_bot.vi_clock_relaxed_releases == 1
        and stale_bot.vi_resolves == 0
        and stale_bot.vi_builds == 1,
        f"pick={stale_board.san(stale_move)} "
        f"(resolves={stale_bot.vi_resolves}, "
        f"relaxed={stale_bot.vi_clock_relaxed_releases}, "
        f"builds={stale_bot.vi_builds})",
    )

    # 23g. Affirmative statistics respect repetition burns (review P1:
    # the fit/p-m passes traversed burned states, so a threefold-dead
    # route still proved affirmative finishes). Burning every converting
    # goal on the kh graph must kill the affirmative tier — fit INF, exp
    # inf, report roots back to no-claim — while min_hit keeps its
    # pristine floor (a lower bound survives path removal); lifting the
    # burns restores the proven 10. A burn that moves NO Bellman value
    # (a stalemate terminal already worth zero) still stales the stats —
    # barriers changed even though values did not — and the dedicated
    # refresh recomputes them on the unchanged numbers.
    from .herding_vi import STALEMATE as _STALEMATE

    kh_root_board = chess.Board(motif["kh-herd-h4"].fen)
    burn_goals = {
        index for index, fraction in hit_kh._conversion.items()
        if fraction > 0.0
    }
    hit_kh._set_burned(burn_goals)
    burn_deconverged = not hit_kh.report.converged
    hit_kh.solve_more(30_000)
    burned_est = hit_kh.hit_estimates(kh_root_board)
    burned_fit_root = hit_kh.report.fit_hit_root
    hit_kh._set_burned(set())
    hit_kh.solve_more(30_000)
    restored_est = hit_kh.hit_estimates(kh_root_board)
    quiet_index = next(
        index for index, kind in enumerate(hit_kh._kind)
        if kind == _STALEMATE
    )
    hit_kh._set_burned({quiet_index})
    quiet_stale = (
        hit_kh.report.converged and not hit_kh.report.hit_converged
    )
    quiet_refreshed = hit_kh.refresh_hit_stats(30_000)
    quiet_est = hit_kh.hit_estimates(kh_root_board)
    check(
        "affirmative hitting stats treat burned states as barriers",
        burn_deconverged
        and burned_est is not None
        and burned_est[0] == 6
        and burned_est[1] == HIT_INF
        and burned_est[2] == float("inf")
        and burned_fit_root == 0
        and restored_est is not None
        and restored_est[:2] == (6, 10)
        and abs(restored_est[2] - 10.0) < 1e-6
        and quiet_stale
        and quiet_refreshed
        and quiet_est is not None
        and quiet_est[:2] == (6, 10)
        and abs(quiet_est[2] - 10.0) < 1e-6,
        f"burned=({burned_est[0]}, "
        f"{'INF' if burned_est[1] == HIT_INF else burned_est[1]}, "
        f"{burned_est[2]}, fit_root={burned_fit_root}); "
        f"restored={restored_est[:2]}; "
        f"quiet burn stale={quiet_stale} "
        f"refreshed={quiet_refreshed} est={quiet_est[:2]}",
    )

    # 23j. Ranking prunes on exact reachability, not numerics (review
    # P2): a total burn's DECREASING re-solve stops inside the Bellman
    # tolerance, leaving crumbs (5.7e-6 here — above the raw 1e-6
    # tolerance, let alone the ranking's 1e-9 cutoff) that ranked as
    # real value, anchored the floor window, and noise-walked a herd
    # whose true value was 0. With every converting goal burned, every
    # ranked child reads child_value_live False — an exact zero-value
    # certificate while min_hit keeps its pristine floor, so the clock
    # veto never catches these — and the play-time loop crumb-prunes
    # them all into the honest zero fallback. Restored, the live
    # children affirm again and only the genuinely dead a5 child stays
    # False: a pristine monotone-from-zero solve gives value > 0 only
    # to states that reach a seed, so the filter never bites a
    # burn-free graph.
    hit_kh._set_burned(burn_goals)
    hit_kh.solve_more(30_000)
    crumb_ranked = hit_kh.ranked_moves(kh_root_board) or []
    crumb_top = crumb_ranked[0][0] if crumb_ranked else 0.0
    crumb_convertible = [
        hit_kh.child_value_live(child) for _, _, child in crumb_ranked
    ]
    hit_kh._set_burned(set())
    hit_kh.solve_more(30_000)
    live_ranked = hit_kh.ranked_moves(kh_root_board) or []
    live_convertible = {
        move.uci(): hit_kh.child_value_live(child)
        for _, move, child in live_ranked
    }
    check(
        "burn-dead crumbs prune on exact reachability, live values stay",
        len(crumb_ranked) == 12
        and 1e-9 < crumb_top < 1e-4
        and not any(crumb_convertible)
        and live_convertible.get("a1a5") is False
        and all(
            ok for move, ok in live_convertible.items() if move != "a1a5"
        ),
        f"crumb top={crumb_top:.2e}, convertible="
        f"{sum(crumb_convertible)}/{len(crumb_convertible)}; "
        f"live dead-children="
        f"{sorted(m for m, ok in live_convertible.items() if not ok)}",
    )

    # 23l. The exact-zero certificate covers the flat proxy tier
    # (review P2 follow-up): fit_hit is deliberately absent when the
    # root does not convert, so a fit-based filter no-claims EVERY
    # child of a live-but-unconvertible policy — and such a policy
    # outlives the flip/adoption cascade whenever no mirror converts,
    # ranking flat proxy values that burn like any others. On a fresh
    # 14d fixture (14h re-seeds the shared one), burning all seven
    # proxy goals leaves ~5e-5 of residue at gamma 0.99 — the
    # tolerance/(1-gamma) scale, three decades over the ranking
    # epsilon — and seed-reachability reads every crumb child dead
    # while fit stays honestly absent. Restored, every
    # solver-visible-positive child reads live again (the tiny-value
    # converse is not asserted: a monotone solve can freeze genuinely
    # reachable states at exactly 0.0 below the update tolerance).
    from .herding_vi import _WIN_KINDS as _WINS

    proxy_policy = HerdingPolicy.build(
        vi_board, vi_target, max_herders=1, state_cap=200_000,
        time_budget_ms=60_000, gamma=0.99, conversion_ms=30_000,
    )
    proxy_seeds = {
        index for index, kind in enumerate(proxy_policy._kind)
        if kind in _WINS
        and proxy_policy._terminal_seed_value(index) > 0.0
    }
    proxy_policy._set_burned(proxy_seeds)
    proxy_policy.solve_more(60_000)
    proxy_ranked = proxy_policy.ranked_moves(vi_board) or []
    proxy_top = proxy_ranked[0][0] if proxy_ranked else 0.0
    proxy_live = [
        proxy_policy.child_value_live(child)
        for _, _, child in proxy_ranked
    ]
    proxy_policy._set_burned(set())
    proxy_policy.solve_more(60_000)
    unburned_ranked = proxy_policy.ranked_moves(vi_board) or []
    unburned_positive_live = all(
        proxy_policy.child_value_live(child)
        for value, _, child in unburned_ranked
        if value > 1e-6
    )
    check(
        "the exact-zero certificate covers the flat proxy tier",
        proxy_policy.report.ok
        and not proxy_policy.report.root_converts
        and proxy_policy._fit_hit is None
        and len(proxy_seeds) == 7
        and len(proxy_ranked) == 13
        and 1e-9 < proxy_top < 1e-3
        and not any(proxy_live)
        and bool(unburned_ranked)
        and unburned_ranked[0][0] > 0.5
        and unburned_positive_live,
        f"converts={proxy_policy.report.root_converts}, "
        f"fit-absent={proxy_policy._fit_hit is None}, "
        f"seeds={len(proxy_seeds)}; crumb top={proxy_top:.2e}, "
        f"live={sum(proxy_live)}/{len(proxy_live)}; restored top="
        f"{unburned_ranked[0][0] if unburned_ranked else 0.0:.3f} "
        f"(positive all live={unburned_positive_live})",
    )

    # 23h. The soft clock trigger requires honest statistics (review P1:
    # a truncated p/m ratio errs either way — an early pass commonly
    # reads inf — and the junk-armed cascade spent reset scans, flip
    # probes, and fallback vetoes on MOVE ONE of a fresh 100-ply era).
    # A mid-herd root on the kh statics builds converged but its p/m
    # pass exceeds the update cap: the fixed code keeps clock_soft dark
    # (no cascade, no veto armed), where the old code fired it at clock
    # 0. Marking the pass drained re-arms the gate: the same numbers
    # then flag soft honestly and the cascade runs.
    far_board = chess.Board(
        motif["kh-herd-h4"].fen.replace("5P1k", "5P2")
    )
    far_board.set_piece_at(chess.D5, chess.Piece(chess.KING, chess.BLACK))
    far_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    far_bot.choose_move(far_board)
    far_policy = far_bot._vi_policy
    far_truncated = (
        far_policy is not None
        and far_policy.report.ok
        and far_policy.report.converged
        and not far_policy.report.hit_converged
    )
    dark_softs = far_bot.vi_clock_soft_plies
    dark_veto = set(far_bot._vi_reset_refused)
    if far_truncated:
        far_policy.report.hit_converged = True
        far_bot.choose_move(far_board)
    check(
        "the soft clock gate reads only honest hitting statistics",
        far_truncated
        and dark_softs == 0
        and far_bot.vi_clock_hard_plies == 0
        and dark_veto == set()
        and far_bot.vi_clock_soft_plies == 1,
        f"truncated={far_truncated} softs-dark={dark_softs} "
        f"veto-dark={sorted(m.uci() for m in dark_veto)}; "
        f"honest softs={far_bot.vi_clock_soft_plies}",
    )

    # 23c. The clock-hard cascade on a converting side. min_hit over the
    # remaining budget certifies this era cannot finish, so a certified
    # pawn push manufactures a fresh one: with the spare a2 pawn the
    # hypothetical rebuild — rooted at the pushed position with ZACH to
    # move (review P1: an our-turn root certified a state the game never
    # reaches) and the active policy's herder subset — certifies
    # live-and-converting with every real reply state fitting, and the
    # bot plays the reset. Arming the flags vetoes the WHOLE scan domain
    # for this decision (review P1: unjudged pushes must not reach the
    # fallbacks either), so _vi_reset_refused holds the refused f4-f5
    # (its hypothetical breaks the pocket and refuses honestly) AND the
    # never-scanned a2-a4, with only the certified a2-a3 lifted out.
    # Without the spare pawn nothing certifies, every ranked candidate
    # prunes as unfinishable, and the move falls through to the
    # fallbacks with the veto still armed — a blind push is never
    # played.
    reset_board = chess.Board("5NN1/6k1/8/8/5P2/5Pp1/P5K1/R5B1 w - - 0 1")
    reset_board.halfmove_clock = 96
    reset_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    reset_move = reset_bot.choose_move(reset_board)
    nospare_board = chess.Board("5NN1/6k1/8/8/5P2/5Pp1/6K1/R5B1 w - - 0 1")
    nospare_board.halfmove_clock = 96
    nospare_bot = LoseBot(
        depth=1, opponent_model="zach", profile="vi", vi_herders=1
    )
    nospare_move = nospare_bot.choose_move(nospare_board)
    f4f5 = chess.Move.from_uci("f4f5")
    check(
        "clock-hard resets certify or refuse; unfinishable lines prune",
        reset_move == chess.Move.from_uci("a2a3")
        and reset_bot.vi_clock_resets == 1
        and reset_bot.vi_clock_reset_builds == 2
        and reset_bot.vi_clock_hard_plies == 1
        and reset_bot.vi_clock_pruned == 0
        and reset_bot._vi_reset_refused
        == {f4f5, chess.Move.from_uci("a2a4")}
        and nospare_bot.vi_clock_resets == 0
        and nospare_bot.vi_clock_reset_builds == 1
        and nospare_bot.vi_clock_hard_plies == 1
        and nospare_bot.vi_clock_pruned == 4
        and nospare_bot.vi_zero_fallbacks == 1
        and nospare_bot._vi_reset_refused == {f4f5}
        and nospare_move != f4f5,
        f"spare={reset_board.san(reset_move)} "
        f"(resets={reset_bot.vi_clock_resets}"
        f"/{reset_bot.vi_clock_reset_builds} builds, "
        f"refused={sorted(m.uci() for m in reset_bot._vi_reset_refused)}); "
        f"no-spare={nospare_board.san(nospare_move)} "
        f"(pruned={nospare_bot.vi_clock_pruned}, "
        f"builds={nospare_bot.vi_clock_reset_builds}, "
        f"vetoes={nospare_bot.vi_clock_reset_vetoes})",
    )

    # 23d. The flip gate requires era feasibility of the prospect in two
    # tiers: min_hit_root is the rejection floor (a live prospect whose
    # best case cannot fit the budget is refused with the long back-off
    # whatever its audit says, while 0 — stats absent — never condemns),
    # and a conversion-required flip must additionally AFFIRM with a
    # nonzero fit_hit_root inside the budget — the floor only means
    # impossibility was not proven, so min 6 with a proven finish of 101
    # (or no fit claim at all) may not approve leaving a live side
    # (review P1). flip_board sits at clock 0: a finish of 100 fits the
    # 100-ply era exactly, 101 cannot fit any era.
    infeasible_fired, infeasible_bot = _flip_case(
        True, root_converts=True, min_hit_root=101
    )
    boundary_fired, boundary_bot = _flip_case(False, min_hit_root=100)
    unfit_fired, unfit_bot = _flip_case(
        True, root_converts=True, min_hit_root=6, fit_hit_root=101
    )
    unclaimed_fired, unclaimed_bot = _flip_case(
        True, root_converts=True, min_hit_root=6
    )
    check(
        "side flips require the mirror to fit the remaining era",
        not infeasible_fired
        and infeasible_bot._vi_next_flip_ply == 16
        and infeasible_bot.vi_side_flips == 0
        and boundary_fired
        and boundary_bot.vi_side_flips == 1
        and not unfit_fired
        and unfit_bot._vi_next_flip_ply == 16
        and unfit_bot.vi_side_flips == 0
        and not unclaimed_fired
        and unclaimed_bot._vi_next_flip_ply == 16
        and unclaimed_bot.vi_side_flips == 0,
        f"infeasible fired={infeasible_fired} "
        f"(cooldown={infeasible_bot._vi_next_flip_ply}); "
        f"boundary100 fired={boundary_fired}; "
        f"floor6-fit101 fired={unfit_fired} "
        f"(cooldown={unfit_bot._vi_next_flip_ply}); "
        f"no-fit-claim fired={unclaimed_fired}",
    )

    # 23e. Uncertified resets stay out of the heuristic fallbacks, and
    # the veto is SAME-DECISION evidence (review P1). Piece mode has no
    # blanket pawn veto, so on this fixture — the 13b construction plus a
    # spare h2 pawn outside it — the clock-urgent negamax nudge picks the
    # unaudited h2-h3 push the moment the VI path stands down
    # (vi_herders=0 forces the fall-through) and no veto is armed. The
    # filter leg vetoes both pushes and counts them; a set that would
    # empty the menu is ignored rather than obeyed. The stale leg seeds a
    # "last turn" refusal and shows the next VI decision clears it before
    # the fallbacks run: a veto never outlives the root it was audited
    # against (the in-decision end-to-end veto is 23c's no-spare bot).
    def _leak_bot():
        leak = LoseBot(
            depth=1, opponent_model="zach", profile="vi",
            probe_cap=64, max_probe_n=1, vi_herders=0,
        )
        leak.profile = _replace(
            leak.profile, herd_search_cap=0, modeled_herding_cap=0
        )
        leak.plan = ConstructionPlan(
            pawn_file=chess.square_file(chess.B6),
            checked_side=-1,
            created_ply=0,
        )
        board = chess.Board("k7/p7/Pp6/1B6/K7/PP6/7P/6RR w - - 0 1")
        board.halfmove_clock = 70
        return leak, board

    leak_control_bot, leak_control_board = _leak_bot()
    leak_control = leak_control_bot.choose_move(leak_control_board)
    veto_bot, veto_board = _leak_bot()
    veto_bot._vi_reset_refused = {
        chess.Move.from_uci("h2h3"), chess.Move.from_uci("h2h4")
    }
    veto_kept = veto_bot._filter_refused_resets(
        list(veto_board.legal_moves)
    )
    keep_bot, _ = _leak_bot()
    keep_bot._vi_reset_refused = {chess.Move.from_uci("a1a2")}
    kept_all = keep_bot._filter_refused_resets(
        [chess.Move.from_uci("a1a2")]
    )
    stale_bot, stale_board = _leak_bot()
    stale_bot._vi_reset_refused = {chess.Move.from_uci("h2h3")}
    stale_pick = stale_bot.choose_move(stale_board)
    check(
        "uncertified pushes veto same-decision; stale vetoes die",
        leak_control == chess.Move.from_uci("h2h3")
        and leak_control_bot.vi_clock_reset_vetoes == 0
        and chess.Move.from_uci("h2h3") not in veto_kept
        and chess.Move.from_uci("h2h4") not in veto_kept
        and veto_bot.vi_clock_reset_vetoes == 2
        and kept_all == [chess.Move.from_uci("a1a2")]
        and stale_pick == chess.Move.from_uci("h2h3")
        and stale_bot._vi_reset_refused == set(),
        f"control={leak_control.uci()}; "
        f"vetoed keeps {len(veto_kept)} moves "
        f"(vetoes={veto_bot.vi_clock_reset_vetoes}); "
        f"all-refused keeps={[m.uci() for m in kept_all]}; "
        f"stale-pick={stale_pick.uci()} "
        f"(residue={sorted(m.uci() for m in stale_bot._vi_reset_refused)})",
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


# King-holder construction drill (case 6): the full corner pipeline from an
# unassembled start — cage Bg1 first, march Kg2 last (two plies of premature
# g3-g2 push risk, priced ~1/pool per Zach move), VI-herd the king from c6
# into the {h4,h5} pocket (knight seals g6, pawns g4/g5, the king h3; h6 is
# the door the rook closes behind him before the Ra5+ timing), then the
# audited vacate race. The post-construction pose certifies live with a
# complete audit: 6/8 goal-vacate terminals convert at race 1/2. Run with
# --vi-herders 1: a second herder blows the state cap. A lost race eats the
# only executioner, so seeds converting at ~1/2 after surviving
# construction is the theoretical ceiling.
KING_HOLDER_DRILL_FEN = "R4N2/8/2k5/8/3B1P2/5Pp1/8/5K2 w - - 0 1"

# King-holder ADOPTION drill (case 7): the full-game shape of the corner
# motif. The b6 executioner is frozen by a completed piece-holder
# construction (Rb5 holder defended, king parked a4, cage Ra5/Nb3/Rb5) whose
# audit certifies the side unconvertible in one build — the release theorem
# live and measured. The mirror flip cannot even pose (c4 is our own pawn),
# so the gated reconsideration declines and the bot must REPLACE the plan:
# adopt the a1-corner king-holder template for the same pawn (walk 3,
# blockers Rb5+Nb3), release the freeze, march the king to b2 FIRST (during
# a walk the pending pushes make construction clock-free and the parked
# king stops the premature push structurally), cage Bd3-b1, wait out Zach's
# uniform pushes, then herd into the {a4,a5} pocket behind the c3/c4 walls
# — the drill-6 terminal mirrored to the queenside — and race the vacate.
ADOPTION_DRILL_FEN = "8/8/1p1k4/RR6/K1P5/1NPB4/8/8 w - - 0 1"

# Conversion drills: Zach is already stripped to king+pawns; can LoseBot
# force him to deliver mate? This is the phase where full games stall.
ENDGAME_FENS = [
    "6k1/5p1p/6p1/Q7/8/8/PP1BNPPP/1RR3K1 w - - 0 1",
    "k7/p7/1p6/8/2BQ4/2N5/PPP2PPP/R3K2R w - - 0 1",
    "7k/7p/8/8/8/3B4/PPP1QPPP/2KR3R w - - 0 1",
    "4k3/3p1p2/4p3/8/8/2N5/PPPQBPPP/2KR3R w - - 0 1",
    "1k6/p1p5/8/8/5B2/2N5/PPP1QPPP/2KR4 w - - 0 1",
    KING_HOLDER_DRILL_FEN,
    ADOPTION_DRILL_FEN,
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
            vi_herders=args.vi_herders,
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
            if planned_target.king_holder:
                plan_progress += f"/walk{planned_target.pawn_walk}"
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
                f" crumb-pruned={bot.vi_crumb_pruned};"
                f" goal-stalls={bot.vi_goal_stalls};"
                f" releases={bot.vi_releases}"
                f" ({bot.vi_release_nodes} probe nodes);"
                f" side-flips={bot.vi_side_flips}"
                f" ({bot.vi_conversion_flips} conversion-gated,"
                f" prospect={bot.vi_flip_value});"
                f" unconvertible-sides={bot.vi_unconvertible_sides};"
                f" kh-adoptions={bot.vi_kh_adoptions};"
                f" dead-certs={bot.vi_dead_certificates};"
                f" re-solves={bot.vi_resolves};"
                f" king-marches={bot.vi_king_marches};"
                f" walk-clears={bot.vi_walk_clears};"
                f" closer-parks={bot.vi_closer_parks};"
                f" cage-builds={bot.vi_cage_builds};"
                f" capture-guards={bot.vi_capture_guards};"
                f" funnel-guards={bot.vi_wait_funnel_guards};"
                f" burn-updates={bot.vi_burn_updates}"
                f" ({bot.vi_burned_states} burned at end);"
                f" pool-mismatches={bot.vi_pool_mismatches};"
                f" goals-convert={bot.vi_converting_goals}"
                f"/{bot.vi_conversion_checked}"
                f" (of {bot.vi_goal_states} goal states,"
                f" {bot.vi_forced_mates} forced mates,"
                f" {bot.vi_conversion_incomplete} audits cut short,"
                f" {bot.vi_conversion_nodes} probe nodes);"
                f" clock: min-hit="
                + ("n/a" if bot.vi_min_hit_root is None
                   else str(bot.vi_min_hit_root))
                + " exp-hit="
                + ("n/a" if bot.vi_exp_hit_root is None
                   else f"{bot.vi_exp_hit_root:.1f}")
                + f" hard={bot.vi_clock_hard_plies}"
                f" soft={bot.vi_clock_soft_plies}"
                f" pruned={bot.vi_clock_pruned}"
                f" relaxed-releases={bot.vi_clock_relaxed_releases}"
                f" resets={bot.vi_clock_resets}"
                f"/{bot.vi_clock_reset_builds} builds"
                f" ({bot.vi_clock_reset_vetoes} fallback vetoes)",
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

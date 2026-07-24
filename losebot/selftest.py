"""Fast self-checks for the pivot package.

Style matches the specialists' suite: named [PASS]/[FAIL] lines, exit
nonzero on any failure, everything runnable in seconds — the suite is
the Docker image's default command and the gate on every commit.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import chess

from . import oracle
from .engine import ModelEngine
from .evaluate import evaluate
from .league.families import ALL_FAMILIES
from .league.runner import run_league
from .models import (
    HypothesisPosterior,
    MixtureModel,
    ModelPlayer,
    UrgeModel,
    UrgeParams,
    make_model,
)
from .outcomes import (
    SELFMATE_FORCED,
    SELFMATE_MERCY,
    classify,
    focal_label,
)

# A position with a short adversarial forced-selfmate for White: the
# organic FORCED_MATE fixture from the specialists' conversion-audit
# era (session 4). The oracle proof is re-derived here, not assumed.
FORCED_FIXTURE = "8/8/8/R7/8/3PPk1p/6RP/6BK w - - 0 1"
FORCED_FIXTURE_N = 3  # smallest n the oracle must prove within

# The same corner shell made EXACTLY selfmate-in-2: Black owns one spare
# tempo (b4-b3) so every in-1 waiting proof fails, and the b2 KNIGHT is
# the one blocker that neither captures the tempo pawn nor freezes it
# preemptively (either would collapse the position back to in-1) while
# stopping b3-b2 dead. Two own-moves deep, it sits past the root probe
# at n=1 and past depth-3 terminal detection — the sub-probe's home turf.
IN2_FIXTURE = "8/8/8/R7/1p6/3PPk1p/1N4RP/6BK w - - 0 1"

# The dev-league sloppy g01 finale, distilled: Black (us) is in check
# with one evasion, Rxa8+, whose only answer Qxa8 mates us — the
# check-crossfire recapture device at SIX White non-king men. Past the
# material gate, inside the check gate: exactly what the second gate
# opener exists to see.
CROSSFIRE_FIXTURE = "Q3rQ2/2pb4/K1k4p/1pPp4/3P3p/P4p2/7P/8 b - - 0 1"

# Selective-depth fixture: White owns two free tempi (a3, a4) while
# Black is frozen to single replies — 1...h3 forced, then 2...hxg2#
# forced, mate at ply 4, one past flat depth 3's horizon. Every
# extended ply is an only-reply ply: the forced-sequence extension
# must carry steering to the mate with no oracle in the loop.
EXT_FIXTURE = "8/8/8/8/7p/3QPk2/P5RP/6BK w - - 0 1"

# Back-rank accident: White has Rb8# available plus many quiet moves
# (and Rxa7 as the only capture) — the mate and the capture are what
# mate-avoidant models and the engine's safety partition must refuse.
ACCIDENT_FEN = "7k/p7/6K1/8/8/8/R7/1R6 w - - 0 1"

# Posterior fixtures. MARCH: an open board where Black's king can walk
# — a kingside squatter marches e5-f6-g7-h8 (each step the UNIQUE
# homing pick, likelihood 1.0), while under sloppy the same steps are
# shuffle-share moves and the hunt urge pulls the OTHER way, toward
# the white knight (Kd4 — the wander direction the phantom net priced
# at half a mate). DECLINE-1/2: a free white knight parked next to the
# marched king; taking is greed's near-certainty, so a squatter who
# declines twice separates squat-pure from squat-greedy — the axis the
# corner march alone cannot see.
MARCH_FIXTURE = "n7/p7/8/4k3/8/8/8/KN6 b - - 0 1"
DECLINE_FIXTURE_1 = "n7/6k1/7N/8/8/8/8/K7 b - - 0 1"
DECLINE_FIXTURE_2 = "n7/6k1/5N2/8/8/8/8/K7 b - - 0 1"

# Session-19 greed adjudication poses: the x-ray defender the capturer's
# own body hides, and the pinned defender that cannot legally recapture.
XRAY_FEN = "b6k/8/2B5/3q4/8/8/8/6K1 w - - 0 1"
PIN_FEN = "6k1/6b1/5n2/3N4/8/8/8/1K4R1 w - - 0 1"

_RESULTS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    line = f"[{'PASS' if ok else 'FAIL'}] {name}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)
    _RESULTS.append(ok)


def _dist_map(model, board):
    return {move: prob for move, prob in model.distribution(board)}


def _walk_proof_line(board: chess.Board, n: int):
    """Follow the oracle's proof to the mate; returns the final board.

    Also asserts the structural fact the outcome taxonomy relies on:
    at n=1 the position after our proving move admits ONLY mating
    replies."""
    n_left = n
    while True:
        move = oracle.selfmate_in(board, n_left, [500_000])
        if move is None:
            return None
        board.push(move)
        replies = list(board.legal_moves)
        if n_left == 1:
            if not all(oracle.gives_mate(board, r) for r in replies):
                return None
        board.push(replies[0])
        if board.is_checkmate():
            return board
        n_left -= 1
        if n_left <= 0:
            return None


def test_oracle_and_forced_outcome() -> None:
    board = chess.Board(FORCED_FIXTURE)
    budget = [500_000]
    memo: dict = {}
    proven_n = None
    for n in range(1, FORCED_FIXTURE_N + 1):
        status, move = oracle.selfmate_status(board, n, budget, memo)
        if status is oracle.ProofStatus.PROVEN:
            proven_n = n
            break
    check(
        "oracle: fixture proves adversarially",
        proven_n is not None,
        f"n={proven_n}, budget left {budget[0]}",
    )
    if proven_n is None:
        return
    final = _walk_proof_line(chess.Board(FORCED_FIXTURE), proven_n)
    check("oracle: proof line reaches mate", final is not None)
    if final is None:
        return
    outcome = classify(final)
    check(
        "outcomes: proof-line mate is FORCED on the last ply",
        outcome is not None
        and outcome.mated == chess.WHITE
        and outcome.forced,
        f"reason={outcome.reason}, forced={outcome.forced}",
    )
    check(
        "outcomes: focal labels take sides",
        focal_label(outcome, chess.WHITE) == SELFMATE_FORCED
        and focal_label(outcome, chess.BLACK).startswith("accident"),
    )
    # UNKNOWN honesty: a starved budget must never claim DISPROVEN.
    status, _ = oracle.selfmate_status(
        chess.Board(FORCED_FIXTURE), proven_n, [5]
    )
    check(
        "oracle: starved budget reports UNKNOWN",
        status is oracle.ProofStatus.UNKNOWN,
    )


def test_mercy_outcome() -> None:
    board = chess.Board()
    for san in ("f3", "e5", "g4", "Qh4"):
        board.push_san(san)
    outcome = classify(board)
    check(
        "outcomes: fool's mate is mercy, not forced",
        outcome is not None
        and outcome.mated == chess.WHITE
        and not outcome.forced
        and focal_label(outcome, chess.WHITE) == SELFMATE_MERCY,
    )


def test_model_distributions() -> None:
    board = chess.Board(ACCIDENT_FEN)
    legal = list(board.legal_moves)
    mate = chess.Move.from_uci("b1b8")
    capture = chess.Move.from_uci("a2a7")
    zach = _dist_map(make_model("zach"), board)
    check(
        "models: zach never mates, never captures",
        mate not in zach and capture not in zach and len(zach) > 0,
        f"pool={len(zach)}",
    )
    check(
        "models: zach mass sums to one",
        abs(sum(zach.values()) - 1.0) < 1e-9,
    )
    rnd = _dist_map(make_model("random"), board)
    check(
        "models: random (mercy=1) is uniform over ALL legal moves",
        abs(rnd.get(mate, 0.0) - 1.0 / len(legal)) < 1e-9
        and len(rnd) == len(legal),
    )
    for name in ALL_FAMILIES:
        dist = _dist_map(make_model(name), chess.Board())
        total = sum(dist.values())
        if abs(total - 1.0) >= 1e-9:
            check(f"models: {name} sums to one on startpos", False,
                  f"sum={total}")
            break
    else:
        check("models: every family sums to one on startpos", True)


def test_greed_adjudication() -> None:
    board = chess.Board(XRAY_FEN)
    grabby = UrgeModel("grabby", UrgeParams(greed=1.0, trade=0.0))
    dist = _dist_map(grabby, board)
    bxd5 = chess.Move.from_uci("c6d5")
    bxa8 = chess.Move.from_uci("c6a8")
    check(
        "models: x-ray defender refutes the 'free' queen",
        dist.get(bxd5, 0.0) == 0.0 and dist.get(bxa8, 0.0) == 0.0,
    )
    trader = UrgeModel("trader", UrgeParams(greed=1.0, trade=1.0))
    dist = _dist_map(trader, board)
    check(
        "models: on the trade roll the biggest victim wins",
        abs(dist.get(bxd5, 0.0) - 1.0) < 1e-9,
    )
    board = chess.Board(PIN_FEN)
    dist = _dist_map(UrgeModel("grabby", UrgeParams(greed=1.0)), board)
    nxf6 = chess.Move.from_uci("d5f6")
    check(
        "models: a pinned defender does not defend",
        abs(dist.get(nxf6, 0.0) - 1.0) < 1e-9,
        f"P(Nxf6)={dist.get(nxf6, 0.0):.3f}",
    )


def test_squat_homing() -> None:
    board = chess.Board("8/8/8/8/8/7k/8/K7 b - - 0 1")
    dist = _dist_map(make_model("squat"), board)
    toward = {chess.Move.from_uci("h3h4"), chess.Move.from_uci("h3g4")}
    check(
        "models: squat homes on its corner",
        set(dist) == toward
        and all(abs(p - 0.5) < 1e-9 for p in dist.values()),
        f"picks={sorted(m.uci() for m in dist)}",
    )


def test_reply_support() -> None:
    from .search import reply_support, stable_seed

    check(
        "search: subset seed is process-stable (exact pin)",
        stable_seed(chess.Board()._transposition_key())
        == 9906737308688735056,
        f"got {stable_seed(chess.Board()._transposition_key())}",
    )

    def mv(uci: str) -> chess.Move:
        return chess.Move.from_uci(uci)

    mixed = [
        (mv("a2a3"), 0.5), (mv("b2b3"), 0.2), (mv("c2c3"), 0.2),
        (mv("d2d3"), 0.05), (mv("e2e3"), 0.05),
    ]
    kept = dict(reply_support(mixed, coverage=0.85, cap=3, seed=7))
    check(
        "search: coverage keeps whole probability classes",
        set(kept) == {mv("a2a3"), mv("b2b3"), mv("c2c3")}
        and abs(sum(kept.values()) - 1.0) < 1e-9
        and abs(kept[mv("a2a3")] - 0.5 / 0.9) < 1e-9,
        f"kept={len(kept)}, top={kept[mv('a2a3')]:.3f}",
    )
    board = chess.Board()
    flat = make_model("zach").distribution(board)
    once = reply_support(flat, coverage=0.85, cap=6, seed=1234)
    again = reply_support(flat, coverage=0.85, cap=6, seed=1234)
    legal = set(board.legal_moves)
    check(
        "search: an oversized tie class is a seeded unbiased subset",
        len(once) == 6
        and once == again
        and all(m in legal for m, _ in once)
        and abs(sum(p for _, p in once) - 1.0) < 1e-9
        and all(abs(p - 1.0 / 6.0) < 1e-9 for _, p in once),
        f"kept={len(once)} of {len(flat)}",
    )
    check(
        "search: a distribution within the cap is untouched",
        reply_support(mixed, coverage=0.85, cap=5, seed=7) == mixed,
    )


def test_report_rollups() -> None:
    from .league.play import GameRecord
    from .league.report import render, summarize

    def rec(family: str, label: str, index: int) -> GameRecord:
        return GameRecord(
            family=family, game_index=index, seed=index // 2,
            focal_color=chess.WHITE, white_name="e", black_name="o",
            label=label, reason="checkmate", forced=True, plies=40,
            seconds=1.0, final_fen="8/8/8/8/8/8/8/8 w - - 0 1",
        )

    records = [
        rec("zach", SELFMATE_FORCED, 0),
        rec("zach", "max-plies", 1),
        rec("random", "max-plies", 0),
        rec("random", "max-plies", 1),
    ]
    summary = summarize(records)
    text = render(summary)
    check(
        "report: dev and held-out rollups stay separate",
        summary["dev"]["forced"] == 1
        and summary["held_out"]["forced"] == 0
        and summary["held_out"]["games"] == 2
        and "held-out: 0/2" in text,
        f"dev={summary['dev']} held={summary['held_out']}",
    )


def test_evaluate_shape() -> None:
    bare = evaluate(chess.Board("8/8/8/8/8/4k3/8/4K3 w - - 0 1"),
                    chess.WHITE)
    armed = evaluate(chess.Board("8/8/8/8/4p3/4k3/8/4K3 w - - 0 1"),
                     chess.WHITE)
    check(
        "evaluate: a bare them is the worst state",
        bare < armed - 3000,
        f"bare={bare:.0f} armed={armed:.0f}",
    )
    # Same material, same king-to-executioner distance: the boxed corner
    # king (zero open flights) must outscore the open-center king.
    boxed = evaluate(chess.Board("8/8/8/8/8/6pk/7P/6NK w - - 0 1"),
                     chess.WHITE)
    open_ = evaluate(chess.Board("8/8/8/8/4K3/6pk/7P/6N1 w - - 0 1"),
                     chess.WHITE)
    check(
        "evaluate: closed flight squares beat open ones",
        boxed > open_ + 150,
        f"boxed={boxed:.0f} open={open_:.0f}",
    )


def test_sub_probe() -> None:
    from .search import best_move

    board = chess.Board(IN2_FIXTURE)
    s1, _ = oracle.selfmate_status(board, 1, [200_000], {})
    s2, move2 = oracle.selfmate_status(board, 2, [400_000], {})
    check(
        "oracle: in-2 fixture is exactly selfmate-in-2",
        s1 is oracle.ProofStatus.DISPROVEN
        and s2 is oracle.ProofStatus.PROVEN,
        f"n1={s1.value} n2={s2.value} via {board.san(move2) if move2 else '-'}",
    )

    # The steering layer alone (no root oracle) must walk INTO the net:
    # its chosen move leaves every non-mating reply provably lost at n=1.
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=3, topk=4, probe_n=1,
        probe_cap=20_000,
    )
    move, value, stats = best_move(
        board, us=chess.WHITE, model=make_model("sloppy"), depth=3, topk=4,
        probe_factory=engine._make_sub_probe(
            chess.WHITE, {}, len(list(board.legal_moves))
        ),
    )
    entered = move is not None and stats.probe_hits > 0
    if entered:
        board.push(move)
        for reply in list(board.legal_moves):
            board.push(reply)
            if board.is_checkmate():
                board.pop()
                continue
            status, _ = oracle.selfmate_status(board, 1, [50_000], {})
            board.pop()
            if status is not oracle.ProofStatus.PROVEN:
                entered = False
                break
        board.pop()
    check(
        "search: sub-probe steers into the net",
        entered and value > 90_000,
        f"move={move}, value={value:.0f}, hits={stats.probe_hits}",
    )

    # End-to-end handoff: root probe too shallow to see in-2 (probe_n=1),
    # sub-probes carry steering in, then the root oracle closes.
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=3, topk=4, probe_n=1,
        probe_cap=20_000,
    )
    from .league.play import play_game

    final, outcome = play_game(
        engine, ModelPlayer(make_model("zach"), seed=0), max_plies=12,
        start_fen=IN2_FIXTURE,
    )
    check(
        "engine: sub-probe steering converts past a starved root probe",
        focal_label(outcome, chess.WHITE) == SELFMATE_FORCED
        and len(final.move_stack) <= 6
        and engine.sub_probe_hits > 0
        and engine.forced_selfmates_found >= 1,
        f"label={focal_label(outcome, chess.WHITE)}, "
        f"plies={len(final.move_stack)}, subhits={engine.sub_probe_hits}",
    )

    # The material gate: a full board never opens it.
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=2, topk=4, probe_n=1,
        probe_cap=2_000,
    )
    engine.choose_move(chess.Board())
    check(
        "engine: sub-probe gate stays closed on a full board",
        engine.sub_probe_calls == 0 and engine.sub_probe_nodes == 0,
        f"calls={engine.sub_probe_calls}",
    )

    # The check gate: our king in check opens the probe past any
    # material count, and the crossfire net proves at n=1.
    engine = ModelEngine(belief=make_model("sloppy"))
    board = chess.Board(CROSSFIRE_FIXTURE)
    them_men = chess.popcount(board.occupied_co[chess.WHITE]) - 1
    hook = engine._make_sub_probe(chess.BLACK, {}, 1)()
    check(
        "engine: check gate opens past the material gate",
        them_men > engine.sub_probe_men and hook(board) == 1,
        f"their_men={them_men}, proven_n={hook(board)}",
    )

    # A cap smaller than the root pool is a TOTAL, not a per-branch
    # floor: every share rounds to zero, not one node is spent, and
    # every gated call is ledgered UNKNOWN (born-dry shares never
    # count as drained) — steering degrades to the bare heuristic
    # without crashing and without overspending the configured cap.
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=3, topk=4, probe_n=1,
        probe_cap=20_000, sub_probe_cap=1,
    )
    move = engine.choose_move(chess.Board(IN2_FIXTURE))
    check(
        "engine: starved sub-budget stays capped, ledgers unknowns",
        move in chess.Board(IN2_FIXTURE).legal_moves
        and engine.sub_probe_calls > 0
        and engine.sub_probe_nodes == 0
        and engine.sub_probe_exhaustions == 0
        and engine.sub_probe_unknowns == engine.sub_probe_calls,
        f"move={move}, calls={engine.sub_probe_calls}, "
        f"nodes={engine.sub_probe_nodes}, "
        f"unknowns={engine.sub_probe_unknowns}",
    )

    # Fairness: the cap is split per root candidate, not first-come.
    # With two roots and a cap of two, EACH branch drains its own
    # one-node share — two exhaustions, one node spent in each. Under
    # the old shared budget the first branch drank both nodes (one
    # exhaustion) and the second steered blind, so the chosen move
    # could turn on root order.
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=2, topk=4, sub_probe_cap=2,
    )
    board = chess.Board(IN2_FIXTURE)
    pool = [chess.Move.from_uci("a5a6"), chess.Move.from_uci("a5a7")]
    best_move(
        board, us=chess.WHITE, model=make_model("sloppy"), depth=2, topk=4,
        root_moves=pool,
        probe_factory=engine._make_sub_probe(chess.WHITE, {}, len(pool)),
    )
    check(
        "engine: sub-probe budget drains per branch, not first-come",
        engine.sub_probe_exhaustions == 2
        and engine.sub_probe_nodes == 2
        and engine.sub_probe_hits == 0
        and engine.sub_probe_unknowns >= 2,
        f"exhaustions={engine.sub_probe_exhaustions}, "
        f"nodes={engine.sub_probe_nodes}, unk={engine.sub_probe_unknowns}",
    )


def test_selective_depth() -> None:
    from .search import best_move

    board = chess.Board(EXT_FIXTURE)
    _move, flat, _stats = best_move(
        board, us=chess.WHITE, model=make_model("sloppy"), depth=3, topk=4,
    )
    move, ext, stats = best_move(
        board, us=chess.WHITE, model=make_model("sloppy"), depth=3, topk=4,
        forced_ext=4,
    )
    check(
        "search: forced-sequence extension pierces the horizon",
        flat < 90_000 and ext > 90_000 and stats.extensions > 0
        and move is not None and move.uci() in ("a2a3", "a2a4"),
        f"flat={flat:.0f} ext={ext:.0f} extensions={stats.extensions}",
    )
    # The budget is a hard per-line bound: from depth 2 the mate needs
    # two free plies, so one extension must NOT be enough (a perpetual
    # check would otherwise recurse forever on the house).
    _move, v1, _stats = best_move(
        board, us=chess.WHITE, model=make_model("sloppy"), depth=2, topk=4,
        forced_ext=1,
    )
    _move, v2, _stats = best_move(
        board, us=chess.WHITE, model=make_model("sloppy"), depth=2, topk=4,
        forced_ext=2,
    )
    check(
        "search: extension budget is a hard per-line bound",
        v1 < 90_000 and v2 > 90_000,
        f"ext1={v1:.0f} ext2={v2:.0f}",
    )
    # The node cap clamps mid-tree and still answers with a legal
    # move. What the cap bounds is EXPANSION: entries that pass the
    # limit and grow children. Clamped entries are leaf evals closing
    # already-open loops (truncating them instead would bias a chance
    # node's expectation by its missing mass), so the invariant is
    # nodes - clamped <= cap, not a bound on raw entries.
    start = chess.Board()
    move, _value, stats = best_move(
        start, us=chess.WHITE, model=make_model("sloppy"), depth=3, topk=4,
        node_cap=60,
    )
    check(
        "search: node cap clamps to a legal answer",
        move in start.legal_moves and stats.clamped > 0
        and stats.nodes - stats.clamped <= 60,
        f"nodes={stats.nodes} clamped={stats.clamped} "
        f"expanded={stats.nodes - stats.clamped}",
    )
    # Fairness: the cap is split per root candidate, not first-come —
    # a candidate's value must not depend on where the root walk put
    # it (one shared counter compared the sort-front candidates'
    # full-depth values against bare leaf evals for the rest). Each
    # pool member searched jointly under k shares must equal itself
    # searched alone under one share.
    pool = [chess.Move.from_uci(u) for u in ("e2e4", "d2d4", "g1f3")]
    _move, _value, joint_stats = best_move(
        start, us=chess.WHITE, model=make_model("sloppy"), depth=3, topk=4,
        root_moves=pool, node_cap=150,
    )
    joint = dict(joint_stats.root_values)
    fair = True
    for mv in pool:
        _m, solo_value, _s = best_move(
            start, us=chess.WHITE, model=make_model("sloppy"), depth=3,
            topk=4, root_moves=[mv], node_cap=50,
        )
        if joint[mv] != solo_value:
            fair = False
            break
    check(
        "search: node cap splits per root candidate, not first-come",
        fair and joint_stats.clamped > 0,
        f"joint={ {m.uci(): round(v, 1) for m, v in joint.items()} } "
        f"clamped={joint_stats.clamped}",
    )
    # The deep gate reads THEIR strip: few men, or king+pawns of any
    # count (the squat pawn_last shape) — never a mixed-piece four.
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=2, topk=4, probe_n=1,
        probe_cap=2_000, sub_probe_cap=2_000, deep_depth=3,
    )
    queen = chess.Board("8/8/8/3k4/2q5/8/3K4/8 w - - 0 1")
    gate_ok = (
        engine._deep_position(queen)
        and engine._deep_position(
            chess.Board("8/8/8/3k4/1ppppp2/8/3K4/8 w - - 0 1")
        )
        and not engine._deep_position(
            chess.Board("8/8/8/3k4/1nbrp3/8/3K4/8 w - - 0 1")
        )
    )
    engine.choose_move(queen)
    deep_on_strip = engine.deep_moves
    engine.choose_move(chess.Board())
    check(
        "engine: deep depth gates on the strip, and only there",
        gate_ok and deep_on_strip == 1 and engine.deep_moves == 1,
        f"gate={gate_ok}, deep_moves={engine.deep_moves}",
    )


def test_posterior() -> None:
    # Before any evidence, the configured belief is the real prior
    # anchor, while the exploratory half is balanced by broad family.
    # Four squat variants must not receive four times Zach's family
    # mass just because the hypothesis set represents more squat axes.
    zach_posterior = HypothesisPosterior.from_belief(make_model("zach"))
    zach_weights = zach_posterior.weights()
    zach_families = zach_posterior.families
    sloppy_mass = sum(
        weight for weight, family in zip(zach_weights, zach_families)
        if family == "sloppy"
    )
    squat_mass = sum(
        weight for weight, family in zip(zach_weights, zach_families)
        if family == "squat"
    )
    config = zach_posterior.configuration()
    check(
        "posterior: configured belief anchors a family-balanced prior",
        zach_posterior.map_model().name == "zach"
        and zach_posterior.observations == 0
        and abs(sloppy_mass - squat_mass) < 1e-12
        and zach_weights[2] > sloppy_mass
        and config["collapse"] == zach_posterior.collapse
        and config["prior_rule"]
        == "configured-point-plus-family-balanced"
        and config["configured_mass"] == 0.5
        and all(
            set(hypothesis) == {"name", "family", "params", "prior"}
            and isinstance(hypothesis["params"], dict)
            for hypothesis in config["hypotheses"]
        ),
        f"zach={zach_weights[2]:.4f}, sloppy={sloppy_mass:.4f}, "
        f"squat={squat_mass:.4f}",
    )
    posterior = HypothesisPosterior.from_belief(make_model("sloppy"))

    # The corner march: three observed homing steps must collapse the
    # posterior onto the squat FAMILY. squat-k and squat-greedy-k stay
    # exactly tied (no capture ever offered, and greed is the only
    # axis they differ on), so the tie-break names squat-k while the
    # single-hypothesis collapse gauge stays honestly at zero.
    board = chess.Board(MARCH_FIXTURE)
    for black_move, white_reply in (
        ("e5f6", "b1c3"), ("f6g7", "c3b1"), ("g7h8", "b1c3"),
    ):
        posterior.observe(board, chess.Move.from_uci(black_move))
        board.push_uci(black_move)
        board.push_uci(white_reply)
    weights = posterior.diagnostics()["posterior_weights"]
    squat_mass = sum(
        weight for name, weight in weights.items()
        if name.startswith("squat") and not name.endswith("-q")
    )
    check(
        "posterior: three homing steps collapse onto the squat family",
        posterior.map_model().name == "squat-k"
        and squat_mass > 0.95
        and posterior.collapse_at == 0,
        f"squat-k+greedy={squat_mass:.4f}, weights={weights}",
    )

    # THE PHANTOM REPRICING — the mirage mechanism in one assert. At
    # the march start the fixed sloppy belief gives the away-from-home
    # hunt step Kd4 over a tenth of the mass (the g03 nets stood
    # behind exactly such wander replies at ~0.5); the collapsed
    # posterior mixture prices it at nothing, and the homing step at
    # near-certainty.
    start = chess.Board(MARCH_FIXTURE)
    wander = chess.Move.from_uci("e5d4")
    home = chess.Move.from_uci("e5f6")
    sloppy_p = dict(make_model("sloppy").distribution(start))
    mix_p = dict(posterior.mixture_model().distribution(start))
    check(
        "posterior: collapsed mixture kills the wander mass",
        sloppy_p.get(wander, 0.0) > 0.10
        and mix_p.get(wander, 0.0) < 0.01
        and mix_p.get(home, 0.0) > 0.95,
        f"P(wander): sloppy={sloppy_p.get(wander, 0.0):.3f} "
        f"mix={mix_p.get(wander, 0.0):.4f}; "
        f"P(home): mix={mix_p.get(home, 0.0):.3f}",
    )

    # Smoothing: a pawn lapse (a7a5 — squat holds pawns hostage while
    # pieces can move, and sloppy's push urge LOVES the double step)
    # costs the squat read three orders of magnitude but must not zero
    # it; two more homing steps bring the family back.
    lapse = chess.Move.from_uci("a7a5")
    posterior.observe(board, lapse)
    board.push(lapse)
    board.push_uci("c3b1")
    survived = posterior.weights()
    finite = all(w == w and w >= 0.0 for w in survived)
    squat_alive = survived[3] > 1e-9
    for black_move, white_reply in (("h8g8", "b1c3"), ("g8h8", "c3b1")):
        posterior.observe(board, chess.Move.from_uci(black_move))
        board.push_uci(black_move)
        board.push_uci(white_reply)
    weights = posterior.diagnostics()["posterior_weights"]
    recovered = sum(
        weight for name, weight in weights.items()
        if name.startswith("squat") and not name.endswith("-q")
    )
    check(
        "posterior: one off-model lapse wounds but never kills",
        finite and squat_alive and recovered > 0.9
        and posterior.map_model().name == "squat-k",
        f"post-lapse squat-k={survived[3]:.2e}, recovered={recovered:.4f}",
    )

    # Two declined free knights separate pure squat from greedy squat
    # (greed .85 leaves only .15 for the homing step a pure squatter
    # plays with certainty) — and the point-collapse gauge fires only
    # here, once ONE hypothesis owns 0.95.
    for fen in (DECLINE_FIXTURE_1, DECLINE_FIXTURE_2):
        pose = chess.Board(fen)
        posterior.observe(pose, chess.Move.from_uci("g7h8"))
    diag = posterior.diagnostics()
    check(
        "posterior: declined gifts split the greed axis and collapse",
        diag["posterior_map"] == "squat-k"
        and diag["posterior_map_weight"] >= 0.95
        and diag["posterior_collapse_at"] == posterior.observations,
        f"map@{diag['posterior_map_weight']}, "
        f"collapse@{diag['posterior_collapse_at']}, "
        f"live={diag['posterior_live']}",
    )
    # Pruning is deliberately a later, separate event: the point can
    # be confidently identified while more than one low-weight rival
    # remains live in the mixture.
    pose = chess.Board(DECLINE_FIXTURE_1)
    posterior.observe(pose, chess.Move.from_uci("g7h8"))
    diag = posterior.diagnostics()
    check(
        "posterior: low-weight rivals prune after point collapse",
        diag["posterior_collapse_at"] < posterior.observations
        and diag["posterior_live"] <= 2,
        f"collapse@{diag['posterior_collapse_at']}, "
        f"obs={posterior.observations}, live={diag['posterior_live']}",
    )

    # Mixture arithmetic: exact weighted merge, normalized, sorted.
    board = chess.Board(MARCH_FIXTURE)
    sloppy = make_model("sloppy")
    zach = make_model("zach")
    mix = MixtureModel([(sloppy, 0.6), (zach, 0.4)])
    merged = mix.distribution(board)
    s_p = dict(sloppy.distribution(board))
    z_p = dict(zach.distribution(board))
    exact = all(
        abs(prob - (0.6 * s_p.get(move, 0.0) + 0.4 * z_p.get(move, 0.0)))
        < 1e-12
        for move, prob in merged
    )
    check(
        "posterior: mixture is the exact weighted merge",
        exact
        and abs(sum(p for _, p in merged) - 1.0) < 1e-9
        and all(
            merged[i][1] >= merged[i + 1][1]
            for i in range(len(merged) - 1)
        ),
        f"moves={len(merged)}",
    )


def test_posterior_engine() -> None:
    from .league.play import play_game

    def infer_engine(mode: str) -> ModelEngine:
        return ModelEngine(
            belief=make_model("sloppy"), depth=2, topk=4, probe_n=1,
            probe_cap=2_000, sub_probe_cap=2_000, infer=mode,
        )

    configured = ModelEngine(
        belief=make_model("zach"), depth=1, probe_n=1,
        probe_cap=10, sub_probe_n=0, infer="map",
    )
    check(
        "engine: configured belief reaches zero-evidence inference",
        configured.posterior.map_model().name == "zach"
        and configured._current_belief().name == "zach",
    )

    # End-to-end vs a real squatter: the engine's posterior must read
    # the temperament off the observed moves alone — and two identical
    # runs must reproduce to the ply, because posterior updates are
    # pure functions of the observed sequence (the determinism claim
    # every pinned league leans on).
    runs = []
    for _ in range(2):
        engine = infer_engine("mix")
        opponent = ModelPlayer(make_model("squat"), seed=5)
        final, _outcome = play_game(
            engine, opponent, max_plies=16
        )
        runs.append((final.fen(), engine.gauges()))
    fen_a, gauges_a = runs[0]
    fen_b, gauges_b = runs[1]
    check(
        "engine: inference reads a squatter from its moves alone",
        gauges_a["posterior_map"].startswith("squat")
        and gauges_a["posterior_observations"] > 0,
        f"map={gauges_a['posterior_map']}"
        f"@{gauges_a['posterior_map_weight']}",
    )
    check(
        "engine: inferring runs reproduce to the ply",
        fen_a == fen_b and gauges_a == gauges_b,
        f"final={fen_a.split(' ')[0]}",
    )

    # MAP mode plays legal chess end to end, and the off switch keeps
    # the posterior machinery entirely out of the engine.
    engine = infer_engine("map")
    final, _outcome = play_game(
        engine, ModelPlayer(make_model("squat"), seed=5), max_plies=8
    )
    fixed = ModelEngine(
        belief=make_model("sloppy"), depth=2, topk=4, probe_n=1,
        probe_cap=2_000, infer="off",
    )
    check(
        "engine: MAP mode plays, off mode carries no posterior",
        len(final.move_stack) == 8
        and engine.posterior is not None
        and fixed.posterior is None
        and "posterior_map" not in fixed.gauges()
        and fixed.name == "losebot(sloppy)"
        and engine.name == "losebot(infer-map)",
        f"map game plies={len(final.move_stack)}",
    )

    # If the opponent makes the terminal move, choose_move() is never
    # called again. The league's final synchronization must still put
    # that move into the persisted posterior snapshot. A one-ply game
    # gives the engine no turn at all when it sits Black, isolating the
    # boundary exactly.
    _summary, records = run_league(
        lambda: infer_engine("map"),
        ("zach",),
        games_per_family=2,
        max_plies=1,
        log=lambda *args, **kwargs: None,
    )
    check(
        "league: final opponent move reaches posterior diagnostics",
        records[0].probes["posterior_observations"] == 0
        and records[1].probes["posterior_observations"] == 1,
        f"white={records[0].probes['posterior_observations']}, "
        f"black={records[1].probes['posterior_observations']}",
    )


def test_fit() -> None:
    from .league.play import play_game
    from .models.fit import (
        COARSE_GRID,
        fit,
        neg_log_likelihood,
        observations_from_play,
    )

    def kernel_obs(family: str, seed: int, plies: int):
        """One kernel-vs-sloppy game; the kernel's own moves are the
        observations, so the fitted parameters have a known truth."""
        white = ModelPlayer(make_model(family), seed=seed)
        black = ModelPlayer(make_model("sloppy"), seed=seed + 100)
        board, _outcome = play_game(white, black, max_plies=plies)
        return observations_from_play(
            chess.Board(), board.move_stack, chess.WHITE
        )

    # Known-parameter recovery, the fitter's licence to operate: squat
    # games must fit back to the corner premise, and the fit may never
    # score worse than the truth it was generated from (the truth is
    # on the grid, so descent finding worse would be a bug, not noise).
    obs = kernel_obs("squat", 0, 120)
    fitted, nll = fit(obs, grid=COARSE_GRID)
    truth = neg_log_likelihood(make_model("squat").params, obs)
    check(
        "fit: squat games recover home=1 and the pawn hostage",
        fitted.home == 1.0 and fitted.pawn_last
        and fitted.home_side == "king" and nll <= truth + 1e-9,
        f"home={fitted.home} pawn_last={fitted.pawn_last} "
        f"side={fitted.home_side} nll={nll:.1f} truth={truth:.1f} "
        f"obs={len(obs)}",
    )

    obs = kernel_obs("zach", 0, 120)
    fitted, nll = fit(obs, grid=COARSE_GRID)
    truth = neg_log_likelihood(make_model("zach").params, obs)
    check(
        "fit: zach games recover the all-zero shuffle",
        fitted.home == 0.0 and fitted.greed == 0.0
        and fitted.promote == 0.0 and fitted.mercy == 0.0
        and nll <= truth + 1e-9,
        f"fitted={fitted} nll={nll:.1f} truth={truth:.1f} "
        f"obs={len(obs)}",
    )


def test_engine_safety_and_oracle() -> None:
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=2, topk=4, probe_n=1,
        probe_cap=4_000,
    )
    move = engine.choose_move(chess.Board(ACCIDENT_FEN))
    check(
        "engine: refuses the one-ply accident mate",
        move.uci() != "b1b8",
        f"chose {move.uci()}",
    )
    # Rxa5 would strip the last mating man; the partition must refuse
    # while alternatives exist.
    bare_fen = "k7/8/8/n7/8/8/8/R3K3 w - - 0 1"
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=2, topk=4, probe_n=1,
        probe_cap=4_000,
    )
    board = chess.Board(bare_fen)
    move = engine.choose_move(board)
    check(
        "engine: refuses to bare their king",
        chess.Move.from_uci("a1a5") in board.legal_moves
        and move.uci() != "a1a5",
        f"chose {move.uci()}",
    )
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=2, topk=4,
        probe_n=FORCED_FIXTURE_N, probe_cap=500_000,
    )
    board = chess.Board(FORCED_FIXTURE)
    engine.choose_move(board)
    check(
        "engine: plays the oracle certificate when one exists",
        engine.forced_selfmates_found == 1 and engine.oracle_moves == 1,
    )


def test_league_smoke() -> None:
    def factory():
        return ModelEngine(
            belief=make_model("zach"), depth=2, topk=4, probe_n=1,
            probe_cap=2_000,
        )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        summary, records = run_league(
            factory, ("zach",), games_per_family=2, max_plies=30,
            out_dir=out, log=lambda *a, **k: None,
        )
        pgns = list(out.glob("*.pgn"))
        check(
            "league: each seed plays the pair of seats",
            len(records) == 2
            and records[0].focal_seat == "white"
            and records[1].focal_seat == "black"
            and records[0].seed == records[1].seed
            and summary["overall"]["games"] == 2
            and len(pgns) == 2,
            f"labels={[r.label for r in records]}",
        )
        # The probe gauges must survive into report.json: the pinned
        # report is the only artifact retained, so a sub=/unk=
        # diagnosis has to be reproducible from it alone.
        import json

        from .league.report import write_json

        payload = json.loads(
            write_json(summary, records, {}, out).read_text(
                encoding="utf-8"
            )
        )
        probes = payload["games"][0]["probes"]
        check(
            "league: probe gauges persist per game into the report",
            records[0].probes is not None
            and records[0].probes["moves_played"] > 0
            and probes == records[0].probes,
            f"unk={probes and probes.get('sub_probe_unknowns')}",
        )
    player = ModelPlayer(make_model("sloppy"), seed=7)
    sampled = player.choose_move(chess.Board())
    check(
        "league: sampling stays legal",
        sampled in chess.Board().legal_moves,
    )


def run() -> int:
    for test in (
        test_oracle_and_forced_outcome,
        test_mercy_outcome,
        test_model_distributions,
        test_greed_adjudication,
        test_squat_homing,
        test_reply_support,
        test_report_rollups,
        test_evaluate_shape,
        test_sub_probe,
        test_selective_depth,
        test_posterior,
        test_posterior_engine,
        test_fit,
        test_engine_safety_and_oracle,
        test_league_smoke,
    ):
        test()
    ok = all(_RESULTS)
    print(
        f"selftest: {'OK' if ok else 'FAILED'} "
        f"({sum(_RESULTS)}/{len(_RESULTS)})"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())

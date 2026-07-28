"""Fast self-checks for the pivot package.

Style matches the specialists' suite: named [PASS]/[FAIL] lines, exit
nonzero on any failure, everything runnable in seconds — the suite is
the Docker image's default command and the gate on every commit.
"""

from __future__ import annotations

import argparse
import contextlib
import io
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

#: The depth claim, pinned to a REAL position: zach_g05 ply 73, the
#: decision behind the most expensive certificate the project has ever
#: found. The exhaustive prover needs 45,282 nodes to reach that n=3
#: net; the forcing-restricted one returns the same move (f7f6) in 858.
#: At the shared cap below the complete prover is still UNKNOWN while
#: the restriction has already certified — which is the whole trade in
#: one fixture, at a price the suite can afford.
DEEP_FIXTURE = "1r1bkr2/p1pbnp1p/P1PpP1p1/1p4K1/1Pn3P1/7P/5q2/8 b - - 2 37"
DEEP_FIXTURE_N = 3
DEEP_FIXTURE_WIDTH = 8
DEEP_FIXTURE_CAP = 3_000
DEEP_FIXTURE_VERIFY = 2_000_000

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

# Device-plan fixtures (2026-07-27/28 declaration). G09_PLAN: the
# squat_g09 pre-terminal decision (SAN ply 88, the n=1 cert position's
# board one our-move earlier) — the proposer must find the game's own
# device: pawn-strike, executioner f5, king f7, donation g6. The
# HEAVY fixture (their six men with pieces) shuts the plan region.
G09_PLAN_FIXTURE = "4nbnr/4pkpp/3p1pq1/2pP1P1P/2p5/8/4r3/5b1K b - - 0 44"

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


def _verify_certificate(fen: str, move: chess.Move, n: int,
                        cap: int = 200_000) -> bool:
    """Is ``move`` really a forced selfmate in n, by the COMPLETE prover?

    Checks the certificate itself, not merely that the position happens
    to be winnable: after the move, EVERY legal reply must mate us on
    the spot or leave a position the exhaustive prover certifies at
    n-1. A restricted prover that returned a plausible-but-wrong move
    would pass a position-level check and fail this one.
    """
    board = chess.Board(fen)
    if move not in board.legal_moves:
        return False
    board.push(move)
    if board.is_checkmate() or board.is_stalemate():
        return False
    for reply in board.legal_moves:
        board.push(reply)
        if board.is_checkmate():
            board.pop()
            continue
        if n <= 1:
            board.pop()
            return False
        status, _ = oracle.selfmate_status(board, n - 1, [cap], {})
        board.pop()
        if status is not oracle.ProofStatus.PROVEN:
            return False
    return True


def test_forcing_certifier() -> None:
    """The restricted prover's contract: sound, silent, never refuting.

    It buys depth by giving up completeness, so the ONLY thing standing
    between it and a laundered claim is that every certificate it
    returns is a real one and every failure is labelled as ignorance.
    Both are asserted here directly rather than inferred from the
    engine's behaviour.
    """
    fixtures = (
        ("forced", FORCED_FIXTURE), ("in2", IN2_FIXTURE),
        ("crossfire", CROSSFIRE_FIXTURE),
    )
    proven, verified, statuses = 0, 0, set()
    for _name, fen in fixtures:
        for width in (3, 5, 8):
            # One ladder per width, exactly as the engine runs it: the
            # first rung that proves is the certificate, and deeper
            # rungs are never asked.
            budget = [200_000]
            memo: dict = {}
            for n in range(1, 4):
                status, move = oracle.forcing_selfmate_status(
                    chess.Board(fen), n, budget, memo, width
                )
                statuses.add(status)
                if status is oracle.ProofStatus.PROVEN:
                    proven += 1
                    # SOUNDNESS: the complete prover must agree that
                    # THIS MOVE forces the net — every reply mating us
                    # now or losing at n-1. Position-level agreement is
                    # not enough; the certificate is the move.
                    if _verify_certificate(fen, move, n):
                        verified += 1
                    break
                if budget[0] <= 0:
                    break
    check(
        "oracle: every restricted certificate is a real forced selfmate",
        proven > 0 and verified == proven,
        f"{verified}/{proven} verified against the exhaustive prover",
    )
    check(
        "oracle: the restricted prover never returns DISPROVEN",
        oracle.ProofStatus.DISPROVEN not in statuses,
        f"statuses seen: {sorted(s.value for s in statuses)}",
    )
    # A width of zero is a disabled prover, not a refuting one, and a
    # starved one is UNKNOWN — the two silences stay distinguishable
    # from each other and from a refutation.
    off, _ = oracle.forcing_selfmate_status(
        chess.Board(FORCED_FIXTURE), 3, [200_000], {}, 0
    )
    # Starvation at every stage: mid-ordering, and dead on arrival.
    # A budget of zero must not let an EMPTY candidate list fall
    # through to "nothing found" — a node that never saw its own move
    # set owes UNKNOWN, not absence.
    starved = [
        oracle.forcing_selfmate_status(
            chess.Board(FORCED_FIXTURE), 3, [left], {}, 5
        )[0]
        for left in (0, 1, 4, 20)
    ]
    check(
        "oracle: NOT_FOUND, UNKNOWN and DISPROVEN stay three answers",
        off is oracle.ProofStatus.NOT_FOUND
        and all(s is oracle.ProofStatus.UNKNOWN for s in starved),
        f"width0={off.value} starved={[s.value for s in starved]}",
    )
    # The width tag is what makes a shared memo safe: a restriction-
    # tainted DISPROVEN must be unreachable by the complete prover.
    shared: dict = {}
    oracle.forcing_selfmate_status(
        chess.Board(IN2_FIXTURE), 2, [200_000], shared, 2
    )
    tainted = sum(
        1 for key, value in shared.items()
        if value is oracle.ProofStatus.DISPROVEN and key[0] != "forcing"
    )
    status, _ = oracle.selfmate_status(
        chess.Board(IN2_FIXTURE), 2, [400_000], shared
    )
    check(
        "oracle: a shared memo cannot leak a restricted refutation",
        tainted == 0 and status is oracle.ProofStatus.PROVEN,
        f"untagged refutations={tainted}, exhaustive re-read={status.value}",
    )


def test_forcing_depth_claim() -> None:
    """The pinned depth claim: a net the exhaustive prover cannot reach.

    The reach verdict's own warning was that climbing further is not
    the same as bringing something back, so the claim is pinned as a
    CONVERSION at equal cost: at one shared cap the complete prover
    finds nothing and the restricted one returns a certificate that
    the complete prover then confirms when given far more money.
    """
    board = chess.Board(DEEP_FIXTURE)
    cap = DEEP_FIXTURE_CAP
    exhaustive_found = None
    budget = [cap]
    memo: dict = {}
    for n in range(1, DEEP_FIXTURE_N + 1):
        status, move = oracle.selfmate_status(board, n, budget, memo)
        if status is oracle.ProofStatus.PROVEN:
            exhaustive_found = (n, move)
            break
        if budget[0] <= 0:
            break
    restricted_found = None
    budget = [cap]
    memo = {}
    for n in range(1, DEEP_FIXTURE_N + 1):
        status, move = oracle.forcing_selfmate_status(
            board, n, budget, memo, DEEP_FIXTURE_WIDTH
        )
        if status is oracle.ProofStatus.PROVEN:
            restricted_found = (n, move)
            break
        if budget[0] <= 0:
            break
    check(
        "oracle: the restriction reaches a net the exhaustive cap cannot",
        exhaustive_found is None and restricted_found is not None,
        f"exhaustive={exhaustive_found} restricted={restricted_found} "
        f"at cap {cap:,}",
    )
    if restricted_found is None:
        return
    n, move = restricted_found
    check(
        "oracle: that deep net is confirmed by the complete prover",
        _verify_certificate(DEEP_FIXTURE, move, n),
        f"n={n} move={move}",
    )


def test_layer_budget_accounting() -> None:
    """Allocation is READABLE from the gauges, not re-derived from a run.

    The 2026-07-24 reach verdict had to rebuild the per-layer split by
    hand from a pinned report before it could see that the budgets were
    allocated backwards. These assertions make that split a property of
    the engine instead: every layer bounded by its OWN cap, the two
    root provers ledgered apart, and the restricted ladder's three
    outcomes counted separately so silence never reads as absence.
    """
    caps = dict(probe_cap=3_000, probe_forcing_cap=5_000,
                sub_probe_cap=4_000, node_cap=20_000)
    engine = ModelEngine(
        belief=make_model("sloppy"), depth=2, topk=3, infer="off",
        probe_n=2, probe_forcing_n=4, probe_forcing_width=3, **caps,
    )
    board = chess.Board()
    opponent = ModelPlayer(make_model("zach"), seed=0)
    for _ply in range(8):
        board.push(engine.choose_move(board))
        board.push(opponent.choose_move(board))
    decisions = engine.moves_played
    # The sub-probe gate stays shut on a full board, so its bound is
    # measured where it actually fires: a stripped position, starved
    # root, one decision.
    sub_engine = ModelEngine(
        belief=make_model("sloppy"), depth=3, topk=4, infer="off",
        probe_n=1, probe_cap=500, sub_probe_cap=4_000,
    )
    sub_engine.choose_move(chess.Board(IN2_FIXTURE))
    check(
        "engine: each proving layer is bounded by its own cap",
        decisions > 0
        and engine.probe_nodes <= caps["probe_cap"] * decisions
        and engine.probe_forcing_nodes
        <= caps["probe_forcing_cap"] * decisions
        and sub_engine.sub_probe_nodes > 0
        and sub_engine.sub_probe_nodes <= 4_000,
        f"decisions={decisions} root={engine.probe_nodes} "
        f"forcing={engine.probe_forcing_nodes} "
        f"sub={sub_engine.sub_probe_nodes}/4,000 in one decision",
    )
    check(
        "engine: the two root provers are ledgered apart",
        engine.probe_nodes > 0 and engine.probe_forcing_nodes > 0,
        f"exhaustive={engine.probe_nodes} "
        f"restricted={engine.probe_forcing_nodes}",
    )
    # The restricted ladder's own three answers. Every rung it runs
    # ends in exactly one of them, so the counters must account for
    # the whole ladder and never silently drop a rung.
    outcomes = (engine.probe_forcing_hits + engine.probe_forcing_not_found
                + engine.probe_forcing_unknowns)
    check(
        "engine: restricted NOT_FOUND and UNKNOWN are counted apart",
        outcomes > 0
        and engine.probe_forcing_not_found > 0
        and engine.probe_forcing_hits == 0,
        f"hits={engine.probe_forcing_hits} "
        f"not_found={engine.probe_forcing_not_found} "
        f"unknown={engine.probe_forcing_unknowns} "
        f"exhaustions={engine.probe_forcing_exhaustions}",
    )
    # Off by default: the whole restricted layer must be inert unless
    # all three of its knobs are set, so a config that forgets the cap
    # gets today's engine rather than a silently disabled prover.
    for knobs in (dict(probe_forcing_n=4, probe_forcing_width=3),
                  dict(probe_forcing_n=4, probe_forcing_cap=5_000),
                  dict(probe_forcing_width=3, probe_forcing_cap=5_000)):
        idle = ModelEngine(belief=make_model("sloppy"), depth=1, topk=2,
                           infer="off", probe_n=1, probe_cap=500, **knobs)
        idle.choose_move(chess.Board())
        if idle.probe_forcing_nodes:
            break
    check(
        "engine: the restricted ladder needs all three knobs to fire",
        idle.probe_forcing_nodes == 0,
        f"partial config spent {idle.probe_forcing_nodes} nodes",
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

    # The layer block must carry ACTUAL caps and saturations when the
    # engine description is supplied — a report that only names the
    # cap's knob sends its reader back to the metadata join this block
    # exists to remove. Two decisions at 40,000 root nodes against a
    # 50,000 cap is 80% saturation, readable from summary and render
    # alike; a knob the description lacks (here the forcing cap) stays
    # null rather than guessed.
    records[0].probes = {"moves_played": 2, "probe_nodes": 80_000,
                         "sub_probe_nodes": 40_000, "search_nodes": 8_000}
    engine = {"probe_cap": 50_000, "sub_probe_cap": 100_000,
              "node_cap": 400_000}
    layered = summarize(records, engine=engine)["layers"]
    root = layered["by_layer"]["root_probe"]
    sub = layered["by_layer"]["sub_probe"]
    forcing = layered["by_layer"]["root_forcing"]
    rendered = render(summarize(records, engine=engine))
    check(
        "report: layer block states caps and saturation, not knob names",
        layered["decisions"] == 2
        and root["cap"] == 50_000
        and abs(root["saturation"] - 0.80) < 1e-9
        and abs(sub["saturation"] - 0.20) < 1e-9
        and forcing["cap"] is None
        and forcing["saturation"] is None
        and "80% of cap" in rendered,
        f"root={root} forcing_cap={forcing['cap']}",
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


def test_eval_proximity() -> None:
    """The value-plumbing terms: off is identity, on is the priced
    feature and nothing else — each fixture compares one board to
    ITSELF so every legacy term cancels exactly."""
    from .evaluate import (
        CHECK_MENU_CAP,
        RING_DONATION_CAP,
        EvalParams,
        evaluate,
    )

    boards = (
        chess.Board(),
        chess.Board(CROSSFIRE_FIXTURE),
        chess.Board(FORCED_FIXTURE),
    )
    zero = EvalParams()
    defaults = ModelEngine(make_model("sloppy")).eval_params
    armed18 = ModelEngine(
        make_model("sloppy"), eval_king_approach=18
    ).eval_params
    check(
        "eval: all-zero params are the a12 eval; a14 defaults disarm",
        all(
            evaluate(b, c, zero) == evaluate(b, c)
            for b in boards for c in (chess.WHITE, chess.BLACK)
        )
        and defaults is None
        and armed18 == EvalParams(king_approach=18),
        f"defaults={defaults}; explicit 18 -> {armed18}",
    )

    # Their menu holds exactly one checking reply (d6-d5+): the bonus
    # is the price, once.
    one_check = chess.Board("k7/8/3p4/8/4K3/8/8/8 b - - 0 1")
    armed = EvalParams(check_menu=45)
    check(
        "eval: check_menu prices a checking reply",
        evaluate(one_check, chess.WHITE, armed)
        - evaluate(one_check, chess.WHITE) == 45,
        f"delta={evaluate(one_check, chess.WHITE, armed) - evaluate(one_check, chess.WHITE):.0f} want 45",
    )
    # Two checking replies (Ra1+, Rf2+) meet the cap exactly.
    two_checks = chess.Board("8/8/8/8/8/p7/r7/5K1k b - - 0 1")
    check(
        "eval: check_menu caps at CHECK_MENU_CAP",
        CHECK_MENU_CAP == 2
        and evaluate(two_checks, chess.WHITE, armed)
        - evaluate(two_checks, chess.WHITE) == 90,
        f"delta={evaluate(two_checks, chess.WHITE, armed) - evaluate(two_checks, chess.WHITE):.0f} want 90",
    )

    # Our knight stands on the king's ring, en prise to their rook.
    ring = chess.Board("k7/8/8/8/8/8/r5N1/6K1 w - - 0 1")
    armed = EvalParams(ring_donation=30)
    check(
        "eval: ring_donation prices a man offered at the box",
        RING_DONATION_CAP == 2
        and evaluate(ring, chess.WHITE, armed)
        - evaluate(ring, chess.WHITE) == 30,
        f"delta={evaluate(ring, chess.WHITE, armed) - evaluate(ring, chess.WHITE):.0f} want 30",
    )

    # Approach: the a2 pawn is FROZEN (front blocked, nothing to
    # take), so the nearest legitimate target is their king at
    # distance 4 — not the pawn at distance 2. Unblock the pawn and
    # the target flips to it.
    frozen = chess.Board("k7/8/8/8/1K6/8/p7/N7 w - - 0 1")
    mobile = chess.Board("k7/8/8/8/1K6/8/p7/8 w - - 0 1")
    armed = EvalParams(king_approach=9)
    frozen_delta = (evaluate(frozen, chess.WHITE, armed)
                    - evaluate(frozen, chess.WHITE))
    mobile_delta = (evaluate(mobile, chess.WHITE, armed)
                    - evaluate(mobile, chess.WHITE))
    check(
        "eval: king_approach targets mobile men, never frozen pawns",
        frozen_delta == -36 and mobile_delta == -18,
        f"frozen={frozen_delta:.0f} want -36; mobile={mobile_delta:.0f} want -18",
    )

    # Six non-king men with pieces among them: the stripped gate is
    # shut and the two GATED terms are inert (check_menu is
    # menu-native — its own gate is MENU_LIMIT, tested above). The
    # approach term carries this check non-vacuously: were the gate
    # broken, the a3 knight at distance 2 would show up as -18.
    heavy = chess.Board("4k3/3pp3/8/2K5/8/n6n/8/r6r w - - 0 1")
    armed = EvalParams(ring_donation=30, king_approach=9)
    check(
        "eval: gated proximity terms are inert outside the strip",
        evaluate(heavy, chess.WHITE, armed) == evaluate(heavy, chess.WHITE),
        "their_men=6 with pieces: armed == shipped",
    )


def test_device_plan() -> None:
    """The device-plan layer: off is byte-inert, on it proposes only
    what the oracle certifies, prices distance-to-assignment, gates
    donations on completion, and dies on refutation."""
    from . import plan as device_plan

    board = chess.Board(G09_PLAN_FIXTURE)
    us = board.turn

    # Defaults: knob 0, no state, and a full decision on a plan-region
    # board moves no plan gauge (the cert fires here; retire-with-
    # honors must also stay silent with no plan to retire).
    engine = ModelEngine(make_model("sloppy"))
    move = engine.choose_move(board.copy(stack=False))
    check(
        "plan: defaults are off and inert",
        engine.plan_steer == 0 and engine._plan is None
        and all(getattr(engine, g) == 0 for g in engine.GAUGES
                if g.startswith("plan"))
        and move is not None,
        f"plan_steer={engine.plan_steer}",
    )

    # The proposer, pointed at the squat_g09 pre-terminal position,
    # must adopt the game's actual device: the trophy is the fixture.
    candidates = device_plan.generate_candidates(board, us)
    adopted = None
    for candidate in candidates[:device_plan.MAX_VALIDATIONS]:
        budget = [device_plan.VALIDATE_BUDGET]
        proven_n, _status = device_plan.validate(
            board, us, candidate.placements, candidate.king_target, budget
        )
        if proven_n is not None:
            adopted = (candidate, proven_n)
            break
    check(
        "plan: proposer re-derives the squat_g09 device",
        adopted is not None
        and adopted[0].template == "pawn-strike"
        and adopted[0].king_target == chess.F7
        and adopted[0].donation is not None
        and adopted[0].donation.square == chess.G6
        and adopted[1] == 1,
        "none" if adopted is None else
        f"{adopted[0].template} K={chess.square_name(adopted[0].king_target)}"
        f" n={adopted[1]}",
    )

    # Leaf arithmetic on a hand fixture: king 2 from its target, the
    # box rook 5 from f1 — then the assembled twin, where completion
    # un-gates the donation term (queen 2 from h2).
    plan_state = device_plan.PlanState(
        template="pawn-strike", king_target=chess.G1,
        donation=device_plan.Assignment(chess.H2, (chess.QUEEN,)),
        executioner=chess.A8, box=(
            device_plan.Assignment(chess.F1, (chess.ROOK,)),
        ),
        king_price=24, box_price=12, validated_n=1,
    )
    apart = chess.Board("k7/8/8/8/7Q/8/8/R3K3 w - - 0 1")
    together = chess.Board("k7/8/8/8/7Q/8/8/5RK1 w - - 0 1")
    delta_apart = plan_state.leaf_delta(apart, chess.WHITE)
    delta_together = plan_state.leaf_delta(together, chess.WHITE)
    check(
        "plan: leaf prices distance-to-assignment, donation gated",
        delta_apart == -(24 * 2 + 12 * 5)
        and delta_together == -(12 * 2)
        and not plan_state.assembly_complete(apart, chess.WHITE)
        and plan_state.assembly_complete(together, chess.WHITE),
        f"apart={delta_apart:.0f} want -108; "
        f"together={delta_together:.0f} want -24",
    )

    # Armed engine adopts on the fixture (plan tick, not choose_move —
    # the root cert would fire first here and that path is checked
    # below); the region gate stays shut on a middlegame board.
    armed = ModelEngine(make_model("sloppy"), plan_steer=24)
    armed._plan_tick(board)
    adopted_live = armed._plan
    heavy = chess.Board("4k3/3pp3/8/2K5/8/n6n/8/r6r w - - 0 1")
    gated = ModelEngine(make_model("sloppy"), plan_steer=24)
    gated._plan_tick(heavy)
    check(
        "plan: armed tick adopts in-region, region gate holds outside",
        adopted_live is not None
        and adopted_live.template == "pawn-strike"
        and armed.plans_adopted == 1 and armed.plans_proposed == 1
        and gated.plans_proposed == 0 and gated._plan is None,
        f"in-region adopted={adopted_live is not None}; "
        f"middlegame proposals={gated.plans_proposed}",
    )

    # Footprint drift that eats the donation man = death (the plan's
    # queen is gone, placement resolution fails), and the re-proposal
    # happens in the same tick. An UNKNOWN re-validation would keep
    # the plan — refuted-or-broken kills, budget expiry does not, by
    # the declaration's own rule.
    drifted = chess.Board(G09_PLAN_FIXTURE)
    drifted.remove_piece_at(chess.F5)
    drifted.set_piece_at(chess.G6, chess.Piece(chess.PAWN, chess.WHITE))
    armed._plan_tick(drifted)
    check(
        "plan: losing the donation man = death, then re-proposal",
        armed.plan_deaths == 1 and armed.plans_proposed == 2,
        f"deaths={armed.plan_deaths} proposed={armed.plans_proposed}",
    )

    # A root certificate retires a live plan with honors.
    closer = ModelEngine(make_model("sloppy"), plan_steer=24)
    closer._plan = plan_state
    move = closer.choose_move(chess.Board(G09_PLAN_FIXTURE))
    check(
        "plan: certificate retires the plan",
        closer.oracle_moves == 1 and closer.plan_cert_retires == 1
        and closer._plan is None and move == chess.Move.from_uci("h7h6"),
        f"move={move}",
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


def test_posterior_mercy() -> None:
    """The corpus-fitted mercy family and its controlled ladder.

    Five claims, one per check: the ladder's spacing IS the declared
    rule (mercy halved rung to rung, structure the corpus fit
    verbatim); the human family repartitions the prior exactly; an
    observed avoidable mate — the one move class every mercy-free
    hypothesis prices at literal zero — lands the posterior on the
    mercy family through the epsilon floor; a RARE taken mate at a
    low rate names a LOW rung over both the .70 residue and every
    mercy-free hypothesis (the axis the ladder exists to move); and
    the family does not blur kernel reads on the march fixture.
    """
    from dataclasses import replace

    from .models.posterior import (
        FITTED_HUMAN,
        HYPOTHESES,
        HYPOTHESIS_FAMILIES,
        MERCY_LADDER_RUNGS,
    )

    # The rule is the spacing: every hypothesis in the human family is
    # FITTED_HUMAN with mercy halved some number of times and NOTHING
    # else moved — asserted by writing the fit's mercy back into each
    # rung and demanding the corpus point returns, field for field.
    # Halving is float-exact, so the comparisons are exact, not toleranced.
    ladder = [
        params
        for (_name, params), family in zip(HYPOTHESES, HYPOTHESIS_FAMILIES)
        if family == "fitted-human"
    ]
    check(
        "posterior: ladder rungs halve mercy and hold the fit's structure",
        len(ladder) == MERCY_LADDER_RUNGS
        and ladder[0] == FITTED_HUMAN
        and ladder[0].mercy == 0.70
        and all(
            ladder[k + 1].mercy * 2 == ladder[k].mercy
            for k in range(len(ladder) - 1)
        )
        and all(
            replace(rung, mercy=FITTED_HUMAN.mercy) == FITTED_HUMAN
            for rung in ladder
        ),
        f"rungs={tuple(round(rung.mercy, 6) for rung in ladder)}",
    )

    def family_mass(posterior, family: str) -> float:
        return sum(
            weight
            for weight, fam in zip(posterior.weights(), posterior.families)
            if fam == family
        )

    # Prior arithmetic with the ladder, pinned to the digit:
    # belief=sloppy keeps its configured half, the exploratory half
    # splits four ways (0.125/family), and the human family's share
    # divides across five rungs (0.025 each) — growing the ladder
    # taxes only its own family, never the others. Wrong arithmetic
    # here silently reprices every inferring game's opening, so the
    # whole vector is asserted, not just its shape.
    posterior = HypothesisPosterior.from_belief(make_model("sloppy"))
    expected = (
        0.5625, 0.0625, 0.125,               # sloppy anchor, mild, zach
        0.03125, 0.03125, 0.03125, 0.03125,  # four squat variants
        0.025, 0.025, 0.025, 0.025, 0.025,   # the five-rung mercy ladder
    )
    check(
        "posterior: the ladder repartitions the prior exactly",
        len(HYPOTHESES) == 12
        and len(set(HYPOTHESIS_FAMILIES)) == 4
        and len(posterior.prior) == len(expected)
        and all(
            abs(got - want) < 1e-12
            for got, want in zip(posterior.prior, expected)
        ),
        f"prior={tuple(round(w, 5) for w in posterior.prior)}",
    )

    # A mercy-bearing sequence on the accident fixture: the greedy
    # Rxa7 (structured, sloppy's best-explained move), then the
    # avoidable Rb8# — mercy is the only urge that puts mass on moves
    # that mate us, so every ladder rung prices the mate at mercy/L
    # while every mercy-free hypothesis prices it at exactly zero and
    # eats the epsilon floor. One lapse must outweigh the anchor's
    # prior head start over even the lowest rung.
    board = chess.Board(ACCIDENT_FEN)
    capture = chess.Move.from_uci("a2a7")
    posterior.observe(board, capture)
    board.push(capture)
    board.push_uci("h8g8")
    mate = chess.Move.from_uci("b1b8")
    board.push(mate)
    mate_is_mate = board.is_checkmate()
    board.pop()
    avoidable = board.legal_moves.count() > 1
    mercy_free_p = {
        name: dict(
            UrgeModel(name, params).distribution(board)
        ).get(mate, 0.0)
        for name, params in HYPOTHESES
        if params.mercy == 0.0
    }
    fitted_p = dict(
        UrgeModel("fitted-human", FITTED_HUMAN).distribution(board)
    ).get(mate, 0.0)
    posterior.observe(board, mate)
    diag = posterior.diagnostics()
    # The claim is family-level: WHICH rung wins a two-observation
    # fixture is ladder arithmetic (one lapse in two reads nearest
    # .35), but the mercy family as a whole must take the posterior
    # from the anchor on a single taken mate.
    check(
        "posterior: an avoidable mate taken names the mercy family",
        mate_is_mate and avoidable
        and len(mercy_free_p) == 7
        and all(prob == 0.0 for prob in mercy_free_p.values())
        and fitted_p > 0.02
        and diag["posterior_map"].startswith("fitted-human")
        and family_mass(posterior, "fitted-human") > 0.95
        and max(
            weight
            for weight, fam in zip(posterior.weights(), posterior.families)
            if fam != "fitted-human"
        ) < min(
            weight
            for weight, fam in zip(posterior.weights(), posterior.families)
            if fam == "fitted-human"
        ),
        f"map={diag['posterior_map']}@{diag['posterior_map_weight']}, "
        f"family={family_mass(posterior, 'fitted-human'):.4f}, "
        f"P(mate|fitted)={fitted_p:.4f}",
    )

    # THE LADDER'S REASON TO EXIST: a stream that is structured nine
    # observations in ten and accepts an avoidable mate on the tenth —
    # twenty such cycles, 200 observations, lapse rate exactly .10.
    # The residue rung (.70) tithes 70% of its mass
    # to uniform and cannot explain the structured run; the mercy-free
    # seven explain the run but price every taken mate at the epsilon
    # floor. Only a LOW rung holds both ends — the lapse rate ~.10
    # sits nearest .0875 in log space, and the posterior must point-
    # collapse there, not merely favor the family. Both observations
    # reuse the accident fixture: the free Rxa7 is the greed urge's
    # unique pick (exact cascade probability, no estimate), and the
    # post-capture Rb8# is the avoidable mate whose only mass is
    # mercy/L.
    posterior = HypothesisPosterior.from_belief(make_model("sloppy"))
    structured_board = chess.Board(ACCIDENT_FEN)
    lapse_board = chess.Board(ACCIDENT_FEN)
    lapse_board.push(capture)
    lapse_board.push_uci("h8g8")
    for _cycle in range(20):
        for _ in range(9):
            posterior.observe(structured_board, capture)
        posterior.observe(lapse_board, mate)
    diag = posterior.diagnostics()
    weights = diag["posterior_weights"]
    residue_w = weights["fitted-human"]
    mercy_free_w = max(
        weights[name]
        for (name, params) in HYPOTHESES
        if params.mercy == 0.0
    )
    check(
        "posterior: a rare taken mate names a low rung, not the residue",
        diag["posterior_map"] == "fitted-human-m0875"
        and diag["posterior_map_weight"] >= 0.95
        and diag["posterior_collapse_at"] > 0
        and weights["fitted-human-m0875"] > residue_w
        and weights["fitted-human-m0875"] > mercy_free_w,
        f"map={diag['posterior_map']}@{diag['posterior_map_weight']}, "
        f"residue={residue_w}, best-mercy-free={mercy_free_w}, "
        f"collapse@{diag['posterior_collapse_at']}",
    )

    # And the other direction: kernel streams must read exactly as
    # before the growth. Three homing steps on the march fixture still
    # collapse onto the squat family fast, with the mercy family's
    # uniform floor picking up nothing worth naming.
    posterior = HypothesisPosterior.from_belief(make_model("sloppy"))
    board = chess.Board(MARCH_FIXTURE)
    for black_move, white_reply in (
        ("e5f6", "b1c3"), ("f6g7", "c3b1"), ("g7h8", "b1c3"),
    ):
        posterior.observe(board, chess.Move.from_uci(black_move))
        board.push_uci(black_move)
        board.push_uci(white_reply)
    check(
        "posterior: the mercy family does not blur kernel reads",
        posterior.map_model().name == "squat-k"
        and family_mass(posterior, "squat") > 0.95
        and family_mass(posterior, "fitted-human") < 0.01,
        f"map={posterior.map_model().name}, "
        f"squat={family_mass(posterior, 'squat'):.4f}, "
        f"fitted={family_mass(posterior, 'fitted-human'):.6f}",
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

    # With --infer defaulting to map, every advertised held-out belief
    # must fail AT THE CLI BOUNDARY (clean parser error naming the
    # --infer off escape hatch), never as a construction traceback.
    from .__main__ import main as cli_main

    failures = []
    for name in ("sloppy-held", "human-held", "squat-held", "random"):
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                cli_main(["play", "--belief", name, "--max-plies", "1"])
            failures.append(f"{name}: returned without exiting")
        except SystemExit as exc:
            if exc.code != 2 or "--infer off" not in stderr.getvalue():
                failures.append(f"{name}: code={exc.code}")
    check(
        "cli: held-out beliefs at default inference stop at the boundary",
        not failures,
        f"failures={failures if failures else 'none'}",
    )

    # Help must RENDER, for the root and every subcommand. argparse
    # percent-interpolates help strings only at render time, so a
    # stray % in any help text is invisible to every code path except
    # a user typing --help — a11 shipped exactly that ("-19.8% total")
    # and both play --help and league --help crashed with ValueError.
    from .__main__ import build_parser

    parser = build_parser()
    rendered = {"root": parser.format_help()}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                rendered[name] = sub.format_help()
    empty = [name for name, text in rendered.items() if not text.strip()]
    check(
        "cli: --help renders for the root and every subcommand",
        len(rendered) >= 6 and not empty,
        f"rendered={sorted(rendered)} empty={empty or 'none'}",
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
        test_forcing_certifier,
        test_forcing_depth_claim,
        test_layer_budget_accounting,
        test_mercy_outcome,
        test_model_distributions,
        test_greed_adjudication,
        test_squat_homing,
        test_reply_support,
        test_report_rollups,
        test_evaluate_shape,
        test_eval_proximity,
        test_device_plan,
        test_sub_probe,
        test_selective_depth,
        test_posterior,
        test_posterior_mercy,
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

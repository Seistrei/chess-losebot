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
from .models import ModelPlayer, UrgeModel, UrgeParams, make_model
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

# Back-rank accident: White has Rb8# available plus many quiet moves
# (and Rxa7 as the only capture) — the mate and the capture are what
# mate-avoidant models and the engine's safety partition must refuse.
ACCIDENT_FEN = "7k/p7/6K1/8/8/8/R7/1R6 w - - 0 1"

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

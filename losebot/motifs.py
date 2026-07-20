"""Motif adjudication: pose conversion-motif FENs, audit them, report honestly.

Instrument-first protocol (tuning log, 2026-07-16): before template machinery
is built for a conversion motif, the motif is posed as concrete endgame FENs
and adjudicated with the conversion audit under research budgets. The
protocol's asymmetry is deliberate:

- POSITIVE verdicts (``root_converts=True``, or a directly scored release)
  are facts at any audit coverage — every explored state is root-reachable
  and a reply only counts as winning on a completed PROVEN probe.
- NEGATIVE verdicts are admissible only when ``conversion_complete``, which
  requires both that every goal was visited AND that every refusal rested
  on DISPROVEN probes — a refusal that leaned on an UNKNOWN (budget-starved)
  probe is an artifact, not a verdict. Even a clean complete negative means
  "no conversion provable at this probe depth", never an exact
  impossibility.
- Anything else — audit cut short, or refusals starved — is UNKNOWN.

A root that is already a goal terminal exits the build as
``root-already-terminal`` before any audit runs (likewise ``no-free-herders``
when every piece is welded into the construction). Those positions are what
play would score on arrival anyway, so the harness falls back to calling
``score_release_moves`` on the root directly — the reviewer-recommended
protocol for already-terminal release positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import chess

from .herding_vi import HerdingPolicy, score_release_moves


@dataclass(frozen=True)
class MotifFixture:
    name: str
    family: str  # king-holder | forced-mate | piece-holder
    fen: str
    arrival: str
    checked: str | None = None  # None: stub carries no checked square
    herders: tuple = ()  # square names; empty -> greedy selection
    max_herders: int = 1
    note: str = ""


# ---------------------------------------------------------------------------
# Fixtures. King-holder corner geometry (design B/C, 2026-07-16): our king
# holds the arrival square of the mating pawn; the checked square is the
# corner, whose escapes are one own bishop (uncapturable — the pawn's capture
# squares are kept empty), one square covered by the entering defender, and
# the arrival square itself (king capture barred by the defender). The
# closer knight seals the defender's retreat without giving check. Verified
# move by move against the exact probe before being added here.
# ---------------------------------------------------------------------------

FIXTURES = [
    MotifFixture(
        name="kh-corner-h",
        family="king-holder",
        fen="5N2/8/8/R7/5P1k/5Pp1/6K1/6B1 w - - 0 1",
        arrival="g2",
        checked="h1",
        note="exact vacate position: Kh1! then {Kh3 -> Ng6! g2# forced, "
             "g2+ -> Kxg2 reset}; the root classifies GOAL_VACATE so the "
             "build exits root-already-terminal and direct scoring takes "
             "over",
    ),
    MotifFixture(
        name="kh-corner-a",
        family="king-holder",
        fen="2N5/8/8/7R/k1P5/1pP5/1K6/1B6 w - - 0 1",
        arrival="b2",
        checked="a1",
        note="queenside mirror of kh-corner-h (drill-2 flavored b-pawn): "
             "Ka1! then {Ka3 -> Nb6! b2# forced, b2+ -> Kxb2 reset}",
    ),
    MotifFixture(
        name="kh-herd-h4",
        family="king-holder",
        fen="5NN1/8/8/8/5P1k/5Pp1/6K1/R5B1 w - - 0 1",
        arrival="g2",
        checked="h1",
        herders=("a1",),
        note="VI-level pose: roam pocket {h4,h5}, rook herder a1. The "
             "policy must wait out the parity, seal h5 with Ra5+ exactly "
             "when his king stands on h5 (Ra5 on h4-parity is stalemate), "
             "then the GOAL_VACATE state (zk=h4, R=a5) audits at race 1/2",
    ),
    MotifFixture(
        name="fm-organic-h",
        family="forced-mate",
        fen="8/8/8/R7/8/3PPk1p/6RP/6BK w - - 0 1",
        arrival="a8",
        note="organic forced-capture-mate baseline (selftest 14g): hxg2# "
             "is the only legal reply after most herder waits; the graph "
             "is forced-mate-only with zero proxy goals",
    ),
    MotifFixture(
        name="fm-organic-a",
        family="forced-mate",
        fen="8/8/8/7R/8/p1kPP3/PR6/KB6 w - - 0 1",
        arrival="h8",
        note="queenside mirror of fm-organic-h: axb2# family",
    ),
    MotifFixture(
        name="fm-deep-h",
        family="forced-mate",
        fen="R7/8/8/8/8/3P1k1p/6RP/3N2BK w - - 0 1",
        arrival="b8",  # stub square only; must not sit on the herder
        note="multi-move forced-mate reachability: without the e3-pawn "
             "(Nd1 seals e3/f2 instead) his king oscillates {f3,f4} and "
             "leaks upward unless the rook holds rank 5; the policy must "
             "seal rank 5, shuffle along it, and drop to rank 4 on f3 "
             "parity to empty his pool — hxg2# forced several plies deep",
    ),
    MotifFixture(
        name="ph-contained-root",
        family="piece-holder",
        fen="8/p7/Pp6/1Bk5/K7/PP6/8/3R2R1 w - - 0 1",
        arrival="b5",
        checked="a4",
        note="release-theorem exhibit: bishop holder, defender already "
             "contained on c5, so the root is GOAL_CONTAINED and the build "
             "cannot audit it; direct scoring must refuse every retreat "
             "(each re-attacks b5 along the vacated diagonal)",
    ),
    MotifFixture(
        name="kh-stack-a",
        family="king-holder",
        fen="2N5/8/2N5/8/kpP5/1p6/1K6/1B6 w - - 0 1",
        arrival="b2",
        checked="a1",
        note="doubled-executioner stack (2026-07-19): Ka1! races 1W/1L/2P "
             "with the b4 rear inert (frozen by its own front pawn, both "
             "capture squares empty); the lost coin renews — Kxb2, then "
             "b4-b3 is Zach's whole pool, and the re-posed race scores "
             "1W/1L/2P again (EV 3/4). The c6 knight is the race-2 b4 "
             "wall; our c4 pawn (b5 wall) is rear-safe, a c3 pawn would "
             "be rear food (the bxc3 delivery leak refuses every retreat)",
    ),
    MotifFixture(
        name="kh-stack-h",
        family="king-holder",
        fen="5N2/8/5N2/8/5Ppk/6p1/6K1/6B1 w - - 0 1",
        arrival="g2",
        checked="h1",
        note="kingside mirror of kh-stack-a: Kh1! 1W/1L/2P, f6 knight "
             "walls g4 for the renewed race, f4 pawn walls g5, no f3 pawn "
             "(rear food)",
    ),
    MotifFixture(
        name="kh-stack-a-herd",
        family="king-holder",
        fen="1NN5/8/N7/8/kpP5/1p6/1K6/1B5R w - - 0 1",
        arrival="b2",
        checked="a1",
        herders=("h1",),
        note="VI-level stacked pose: roam pocket {a4,a5} (c4 pawn walls "
             "b5, a6 knight is the b8-defended race-2 b4 wall), rook "
             "herder h1 seals a5 by the rank-5 rake at a5-parity, and "
             "every goal-vacate terminal audits at race 1/2 with the "
             "stack frozen behind the executioner",
    ),
]


def _resolve_herders(board: chess.Board, names: tuple) -> tuple | None:
    if not names:
        return None
    herders = []
    for name in names:
        square = chess.parse_square(name)
        piece = board.piece_at(square)
        if piece is None:
            raise SystemExit(f"no piece on herder square {name}")
        herders.append((square, piece.piece_type))
    return tuple(herders)


def run_motif(fixture: MotifFixture, conversion_ms: int, budget_ms: int,
              state_cap: int, max_losing: int, probe_cap: int,
              gamma: float = 0.99) -> dict:
    """Build+audit one fixture; fall back to direct release scoring.

    Returns a result dict so callers (and future selftests) can assert on
    verdicts instead of parsing stdout.
    """
    board = chess.Board(fixture.fen)
    if not board.is_valid():
        raise SystemExit(f"{fixture.name}: invalid FEN ({board.status()!r})")
    target = SimpleNamespace(arrival_square=chess.parse_square(fixture.arrival))
    if fixture.checked is not None:
        target.checked_square = chess.parse_square(fixture.checked)

    print(f"\nmotif {fixture.name} ({fixture.family})")
    print(f"  fen: {fixture.fen}")
    if fixture.note:
        print(f"  note: {fixture.note}")

    policy = HerdingPolicy.build(
        board, target,
        max_herders=fixture.max_herders,
        state_cap=state_cap,
        time_budget_ms=budget_ms,
        gamma=gamma,
        herders=_resolve_herders(board, fixture.herders),
        validate_pools=True,
        conversion_ms=conversion_ms,
        race_max_losing=max_losing,
        conversion_probe_cap=probe_cap,
    )
    report = policy.report
    result = {
        "name": fixture.name,
        "family": fixture.family,
        "build_ok": report.ok,
        "reason": report.reason,
        "verdict": "UNKNOWN",
        "odds": None,
        "report": report,
    }

    if report.ok:
        print(
            f"  build: ok states={report.states} edges={report.edges}"
            f" herders={[chess.square_name(s) for _, s in policy._root_herders]}"
            f" terminals={report.terminals}"
            f" pool-mismatches={report.pool_mismatches}"
            f" {report.build_ms:.0f}ms"
        )
        print(
            f"  audit: live={report.root_live}"
            f" converts={report.root_converts}"
            f" complete={report.conversion_complete}"
            f" goals-convert={report.converting_goals}"
            f"/{report.conversion_checked}"
            f" (of {report.goal_states} goal states,"
            f" {report.forced_mates} forced mates,"
            f" {report.goal_states - report.conversion_checked} unchecked,"
            f" {report.conversion_unknowns} starved refusals,"
            f" {report.conversion_nodes} probe nodes)"
            f" root={report.root_value:.3f}"
            f" converged={report.converged}"
        )
        if report.root_converts:
            best = max(policy._conversion.values(), default=0.0)
            result["verdict"] = "POSITIVE"
            # A forced mate is not a race: it converts with certainty.
            result["odds"] = 1.0 if report.forced_mates else best
            detail = (
                "forced mates reachable"
                if report.forced_mates and not report.converting_goals
                else f"best audited goal race {best:.3f}"
            )
            print(f"  verdict: POSITIVE — {detail}")
        elif report.conversion_complete:
            result["verdict"] = "NEGATIVE"
            print(
                "  verdict: NEGATIVE (complete audit, all refusals"
                " DISPROVEN; no conversion provable at probe depth 2)"
            )
        else:
            print("  verdict: UNKNOWN (audit cut short or refusals starved"
                  " before any conversion was found — not admissible as"
                  " negative)")
        return result

    print(f"  build: {report.reason}")
    if report.reason not in ("root-already-terminal", "no-free-herders"):
        print("  verdict: UNKNOWN (build failed before the audit; fixture"
              " needs repair)")
        return result

    # The root itself is where play would score the release: do it directly.
    nodes = [0]
    unknowns = [0]
    choice = score_release_moves(
        board, target, "zach", max_losing,
        probe_n=2, probe_cap=probe_cap, nodes_out=nodes,
        unknown_out=unknowns,
    )
    result["direct"] = True
    if choice is None:
        if unknowns[0]:
            result["verdict"] = "UNKNOWN"
            print(f"  direct release scoring: every retreat refused, but"
                  f" {unknowns[0]} refusal(s) leaned on UNKNOWN probes"
                  f" ({nodes[0]} probe nodes)")
            print("  verdict: UNKNOWN (starved refusals — raise --probe-cap"
                  " before reading this as negative)")
        else:
            result["verdict"] = "NEGATIVE"
            print(f"  direct release scoring: every retreat refused"
                  f" ({nodes[0]} probe nodes)")
            print("  verdict: NEGATIVE (all refusals DISPROVEN; no release"
                  " provable at probe depth 2)")
    else:
        odds = choice.winning / choice.pool
        result["verdict"] = "POSITIVE"
        result["odds"] = odds
        print(
            f"  direct release scoring: {board.san(choice.move)}"
            f" winning={choice.winning} losing={choice.losing}"
            f" pool={choice.pool} ({nodes[0]} probe nodes)"
        )
        print(f"  verdict: POSITIVE — release accepted, race {odds:.3f}")
    return result


def run_motifs(args) -> int:
    if args.list:
        for i, fixture in enumerate(FIXTURES, 1):
            print(f"{i}. {fixture.name} ({fixture.family})")
        return 0
    if args.fen:
        if not args.arrival:
            raise SystemExit("--fen requires --arrival")
        fixtures = [MotifFixture(
            name="adhoc", family="adhoc", fen=args.fen,
            arrival=args.arrival, checked=args.checked,
            herders=tuple(args.herders.split(",")) if args.herders else (),
            max_herders=args.max_herders,
        )]
    else:
        fixtures = list(FIXTURES)
        if args.case is not None:
            fixtures = [fixtures[args.case - 1]]
    verdicts = {}
    for fixture in fixtures:
        result = run_motif(
            fixture,
            conversion_ms=args.conversion_ms,
            budget_ms=args.budget_ms,
            state_cap=args.state_cap,
            max_losing=args.max_losing,
            probe_cap=args.probe_cap,
        )
        verdicts[fixture.name] = (
            result["verdict"],
            result["odds"],
        )
    print("\nsummary:")
    for name, (verdict, odds) in verdicts.items():
        print(f"  {name}: {verdict}"
              + (f" (odds {odds:.3f})" if odds is not None else ""))
    return 0

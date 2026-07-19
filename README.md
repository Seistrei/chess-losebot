# ChessLosebot

A **misère chess** engine: standard chess rules, but the goal is to *get
checkmated*. Built to out-lose Worstfish against opponents that refuse to
deliver mate (like Chess.com's Zach bot).

Everything runs in Docker — no local installs.

## Build

```powershell
docker build -t losebot .
```

## Run

```powershell
# sanity checks (forced-selfmate probe, mate refusal, Zach zugzwang)
docker run --rm losebot

# LoseBot (White) tries to lose to a Zach clone (Black), saving PGNs to .\games
docker run --rm -v "D:\ChessLosebot\games:/app/games" losebot `
  pypy3 -m losebot arena --white losebot --black zach --model zach -n 10 --pgn-dir /app/games

# Baseline: Worstfish (real Stockfish argmin) fails to lose to Zach
docker run --rm losebot pypy3 -m losebot arena --white worstfish --black zach -n 4

# Two dedicated losers fight it out
docker run --rm losebot pypy3 -m losebot arena --white losebot --black worstfish -n 2

# Inspect a finished game
docker run --rm -v "D:\ChessLosebot\games:/app/games" losebot `
  pypy3 -m losebot.analyze /app/games/game_001_losebot_vs_zach.pgn

# Endgame conversion drills (Zach pre-stripped to king+pawns)
docker run --rm losebot pypy3 -m losebot endgames --seed 5

# Reproducible profile comparison with a bounded exact probe
docker run --rm losebot pypy3 -m losebot endgames --profile v03 --seed 5 `
  --max-plies 40 --probe-cap 10000 --probe-depth 3

# Inspect one drill and its final position
docker run --rm losebot pypy3 -m losebot endgames --profile template `
  --case 2 --seed 5 --max-plies 40 --probe-cap 10000 `
  --probe-depth 3 --show-fen

# Exercise the stateful construction planner with bounded tactical searches
docker run --rm losebot pypy3 -m losebot endgames --profile planner `
  --seed 5 --max-plies 40 --probe-cap 10000 --probe-depth 3

# Guarded depth-two herding experiment (beam search plus memoization)
docker run --rm losebot pypy3 -m losebot endgames --profile herding `
  --case 2 --seed 5 --max-plies 120 --probe-cap 10000 --probe-depth 3

# Exact value iteration over the herding sub-MDP, with dead-side
# certificates and prospective side-flips
docker run --rm losebot pypy3 -m losebot endgames --profile vi `
  --case 2 --seed 5 --max-plies 240 --probe-cap 10000 --probe-depth 3

# King-holder corner drills: case 6 builds the corner from a delivered
# pawn; case 7 starts from a certified-dead piece construction, adopts
# the corner plan, and walks the executioner to it
docker run --rm losebot pypy3 -m losebot endgames --profile vi `
  --case 7 --seed 1 --vi-herders 1 --max-plies 240 --show-fen

# Same drill with the release audit: log every release-scan decision
# (candidate verdicts, audited goal odds, clean-board twin rescore)
docker run --rm losebot pypy3 -m losebot endgames --profile vi `
  --case 7 --seed 1 --vi-herders 1 --max-plies 240 --release-audit

# Adjudicate conversion motifs (king-holder release, forced capture-mate)
# with the conversion audit under research budgets
docker run --rm losebot pypy3 -m losebot motifs
docker run --rm losebot pypy3 -m losebot motifs --case 3 --conversion-ms 120000
```

## How LoseBot works

1. **Never** delivers mate or stalemate if any alternative exists.
2. **Exact forced-selfmate probe** (`selfmate_in`): finds moves after which
   *every* opponent reply leads to LoseBot being checkmated — the selfmate
   search Worstfish's flipped-Stockfish construction cannot express. Probes
   deepen as the opponent runs out of mobile pieces.
3. **Opponent model** (`--model zach`): restricts the opponent's reply set in
   the probe to the pool Zach actually samples from (never mates if avoidable,
   never captures if avoidable), making forced losses far easier to prove.
4. **Misère negamax** otherwise, with inverted terminals (being mated = +MATE)
   and an eval encoding the human-discovered recipe: eat their mobile pieces
   (they are shuffle fuel), leave them king-and-pawns, walk our king in front
   of their pawns, smother it with our own men, minimize their mobility,
   and treat draws/50-move drift as failure.

Named engine profiles keep experiments reproducible: `current` preserves the
pre-profile build, `v03` reconstructs the best historic full-game weights from
the tuning log, and experimental `template` couples both kings to one concrete
opponent-pawn mating push. Experimental `planner` persists one such target,
holds a defended blocker on the pawn's mating square until release, preserves
the king cage, filters repetitions and plan regressions, and uses bounded
short-horizon searches to herd the defending king. The `herding` profile is a
separate depth-two experiment: it retains every forcing check, limits quiet
setup continuations to an eight-move beam, memoizes only fully evaluated
modeled states, and accounts for Zach reply classification inside its cap.
Deep proof searches are only unlocked when the selected target is close and
partially caged.

The baseline `planner` modeled search deliberately remains at one turn, 1,000
nodes, and 250 ms per invocation. `herding` retries two turns with an eight-
move beam, a 5,000-node cap, a draw-history-safe transposition table, and the
same hard 250 ms deadline. It is intentionally experimental: the tuning log
records that the guarded search is fast but has not improved conversions.

The `vi` profile treats the herd phase as what it actually is against a fixed
stochastic opponent: a Markov decision process. With the construction frozen
(king parked, holder defended, pawns blocked), the only dynamic units are
their king and one or two of our free pieces, and `losebot/herding_vi.py`
solves that sub-MDP exactly by value iteration — the opponent edges reproduce
`support_zach` move-for-move and are validated against it on every build
(plus a full-graph audit mode in the selftest). The dead/live certificate is
exact graph reachability computed on the completed state graph, independent
of the solver: a value-iteration pass cut short by its deadline can degrade
move ranking (it reports `converged=False` and resumes across moves), never
a certificate. A checked side is only declared hopeless once **every**
maximal herder subset of the frozen configuration is certified dead; that
verdict is scoped to the exact certified configuration (it cannot be
inherited by a rebuilt plan) and triggers a prospective flip of the plan to
the mirrored checked side when a completed build certifies that side live.
The certify sweep also carries the conversion audit's side-level verdict:
it stops early only for a live subset that positively converts, keeps the
first merely-live subset as the playable fallback, and — when the sweep and
every live subset's audit completed with nothing converting — declares the
side unconvertible, which triggers the same prospective flip under a
stricter gate: abandoning a live side requires a mirror that positively
converts (forced-mate pockets or accepted release races), while a hopeless
side keeps accepting any live mirror.
Committed march/cage filters, a forced-capture guard, and a draw-aware
scored race-release (it shares the arena's fifty-move/repetition/material
adjudications) round out the profile. At play time the policy also prices
the arena's threefold rule into the solved values: each move it recounts
the game's reversible era, maps every position (either side to move) onto
a graph state, and pins twice-seen states at value 0 — re-entering one is
the draw — so Zach's deterministic funnels reprice the moves that feed
them instead of tripping repetition mid-herd, and an irreversible move
lifts the burns with the era. Piece holders provably cannot release
the arrival square (every retreat re-attacks it and refutes the mate); the
one immune holder is our own king, and the `motifs` command adjudicates
that motif with the conversion audit: king-holder graphs get a dedicated
GOAL_VACATE goal (classified against the hypothetically vacated position),
and the corner fixtures audit convertible at race odds 1/2 — the entry and
the premature pawn push are legalized by the same vacate tempo. King-holder
template mode builds that construction in real games (cage-first,
king-parks-last, vacate gated on the audited race) and converts the
dedicated drill; the tuning log records the geometry rules the probe
taught. Adoption pressure routes full games there: a side whose certify
verdict comes back hopeless or unconvertible replaces its piece plan
with the corner king-holder plan of a walkable b/g-file pawn (walking
templates name the corner geometry before it exists), releases the
freeze, marches the king to the arrival square FIRST (pending pushes
make the walk clock-free, and the parked king stops the premature
push), cages the bishop, parks the knight closer on its template
square, and waits out Zach's uniform pushes behind a funnel guard that
shares the arena's draw adjudications — then the ordinary certify,
herd, and audited-race machinery finishes the game.

## Roadmap

- v1: add Fairy-Stockfish with a `[misere:chess] checkmateValue = win` variant
  as a deep tactical oracle for forced selfmate nets.
- Lichess BOT bridge (lichess-bot) — there is currently no misère bot there.

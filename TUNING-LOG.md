# ChessLosebot tuning log — the model era

Running lab notebook for the post-pivot architecture (the `losebot/`
package: urge-family opponent models, expectimax steering, the
opponent-free oracle, and the frozen league). One entry per session or
review round; every performance claim cites a league report under
`games/league/`.

The specialist era's complete notebook (2026-07-12 through the pivot:
eval tuning, herding VI, king-holder templates, the donation guard,
every drill battery and live-game postmortem) lives with its code at
`specialists/TUNING-LOG.md`. Its commands predate the rename and read
`pypy3 -m losebot ...`; substitute `-m specialists`.

## The pivot: one opponent family, expectimax steering, oracle closing (2026-07-21)

Decision, taken with two concurring outside opinions on the same
evidence: the specialist line stays frozen as teacher and anchor, and
primary development moves to a model-based architecture. The evidence
that forced it, all first-party: case-9/10 convert 10/10 vs the squat
kernel and 0/10 vs sloppy FROM THE SAME CORNER; the two kernels demand
opposite doctrines (early lift vs. plug hold) and the session-19 fix
round concluded "no position predicate discriminates"; YBZEWDGj's one
two-move fork beat 497 donation-guard vetoes because model=zach search
explores no capturing reply at any depth; six live games produced zero
forced mates (both landed mates were human cooperation); and the drill
EVs vs Zach have sat at their audited structural caps (vacate coin at
1/2-3/4) since 07-17 while each live game bought 2-3 new kernel-scoped
exposures at a session of machinery apiece. The economics inverted:
cost per exposure rising, transfer per fix ~zero. The fix is not a
bigger doctrine stack and not tabula-rasa self-play RL either (misère
equilibrium is a mutual-strip draw; self-play never observes the
error distribution that makes weak opponents beatable). It is: put the
opponent's policy DISTRIBUTION in the tree, and make certificates
opponent-free.

What landed (package `losebot/`, the old engine renamed intact to
`specialists/` — its selftest passed through the rename untouched):

- `models/`: the URGE FAMILY — one parametric stochastic opponent
  (mate-avoidant core; urges: mercy lapse, promote, greed+trade with
  the push-and-scan recapture adjudication, check, push, hunt, corner
  homing, pawn-hostage shuffle) exposing EXACT per-move distributions.
  Zach = all-zeros, session-19 sloppy = one point, the corner squatter
  = home 1.0 + pawn_last. New behavior updates parameters, not code.
- `oracle.py`: the exact forced-selfmate probe, ported adversarial-only
  (Zach-modeled probes remain a specialist tool). Repetition-era
  history walk, draw-state memo keys, UNKNOWN-vs-DISPROVEN honesty all
  preserved verbatim.
- `search.py` + `engine.py`: expectimax over the model distribution
  (top-k truncated, renormalized) under an oracle-first, misère-safe
  root partition (no one-ply accident mate/stalemate/draw while an
  alternative exists).
- `evaluate.py`: the asymmetric CURRENT-profile core (root-as-loser
  at every leaf, mate-aware menu squeeze, executioner preservation,
  clock fear) minus all template machinery — steering owns that now.
- `league/`: the FROZEN LEAGUE. Dev families zach/sloppy/squat;
  held-out families sloppy-held/human-held/squat-held/random with
  parameters pinned in `models/presets.py` on 2026-07-21 — report
  against, never tune against. Fresh RNG and fresh engine per game
  (the old arena's shared-stream cascade caveat is retired), seats
  alternated, outcomes classified by taxonomy (forced vs mercy mate,
  accident wins, stalemates both ways, draw kinds), per-family rows
  plus worst-family billing. `--engine specialist` runs the frozen
  bot on the same scoreboard via a lazy wrapper (bridge's >=60s-tier
  budget clamps).

Selftest: 19/19 (oracle re-proves the organic FORCED_MATE fixture
adversarially at n=1 and the proof line's last ply IS the taxonomy's
forced case; the x-ray/pin greed poses port as distribution tests;
league smoke alternates seats end-to-end). Timing: ~0.2s/move at
depth 3 / topk 5 under PyPy — a 240-ply game in ~23s, a full 7x10
league in ~30-40 min serial.

Protocol from here: tuning and fitting touch dev families only;
held-out parameters move for mechanics bugs, never performance; every
progress claim cites the league report (JSON + PGNs under
games/league/), mean AND worst family; milestones 60/80/90% held-out
forced rate; the live bar stays "the corner poses and the mate lands
BY FORCE against a human."

### Baseline league (2026-07-21, re-pinned same day)

The first pin (commit c1b4588) was superseded within hours by the
review round — coverage-true chance nodes and seed-paired seats change
what the runs mean — so THESE are the baseline tables of record
(artifacts: games/league/baseline-model/ and baseline-specialist/,
report.json + per-game PGNs). The superseded run survives in git
history; its one lesson worth keeping: the 4 mercy mates `random`
handed the model engine there vanished under the new seed schedule —
mercy-of-noise is luck, which is exactly why the scoreboard separates
it from forced.

MODEL ENGINE (belief=sloppy, depth 3, topk 6, coverage 0.85, probe
n<=3 cap 40k; 10 games/family = 5 seed-pairs, max 240 plies):

```
family       split      n  forced st-them st-us insuf fifty rep maxply
sloppy       dev       10       0       0     2     4     0   1      3
squat        dev       10       0       0     0     0     0   1      9
zach         dev       10       0       0     0     0     0   0     10
human-held   held-out  10       0       1     0     2     0   1      6
random       held-out  10       0       0     0     0     0   1      9
sloppy-held  held-out  10       0       0     0     5     0   1      4
squat-held   held-out  10       0       0     0     0     0   3      7
forced — held-out: 0/40 (0%); dev: 0/30 (0%); worst held-out: 0%
```

SPECIALIST ANCHOR (field+zach, fast tier; 4 games/family = 2 pairs):

```
family       split      n  forced st-them st-us insuf fifty rep maxply
sloppy       dev        4       0       0     1     0     1   1      1
squat        dev        4       0       0     0     0     0   0      4
zach         dev        4       0       1     0     0     0   0      3
human-held   held-out   4       0       1     0     1     0   0      2
random       held-out   4       0       0     0     0     0   0      4
sloppy-held  held-out   4       0       0     0     1     0   0      3
squat-held   held-out   4       1       0     0     0     0   0      3
forced — held-out: 1/16 (6%); dev: 0/12 (0%); worst held-out: 0%
```

THE ANCHOR DREW FIRST BLOOD: squat-held game 2 (engine White) is the
specialist's first full-game forced selfmate ever recorded — every
prior conversion started from a hand-set endgame drill. The corner
construction poses organically (Kh1, g1 plug, g-pawn executioner
preserved through the squatter's greed), the rook strips the last
loose pawn, and 81.Qg5+ Kh3 82.Qf4 g2# closes a genuine zugzwang —
the exact shape of the standing live bar, landed against a held-out
kernel. PGN: baseline-specialist/squat-held_g02_selfmate-forced.pgn.
Two readings, both true: the corner machinery is real when the
opponent's king cooperates by temperament (a squatter walks into its
own pocket), and one family at 25% with every other held-out row at
zero is precisely the specialist's known shape — strength where the
opponent matches a modeled kernel, nothing where it doesn't.

The model engine's zeros decompose the same way as the first pin:
greedy families end in stalemate-us/mutual-strip (it strips
competently, donates under pressure, and has no conversion pressure),
avoidant families wall at max-plies. The gap to close is now concrete
and named: the new engine must first MATCH the anchor's 1/16 held-out
mark, then pass it — steering depth, sub-root oracle probes, and
league-legal endgame guidance are the levers, then the corpus fit.

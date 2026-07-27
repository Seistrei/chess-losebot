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

Pinned twice-over on the same day: the first pin (commit c1b4588) was
superseded by the review round (coverage-true chance nodes and
seed-paired seats change what runs mean), and the model table was
superseded once more by the process-stable subset seed (hash(None) is
id-derived on PyPy, so pre-fix containers modeled different reply
subsets from identical positions — the run wasn't reproducible). The
specialist table needed no third run: its path never touches the
subset seed. THESE are the tables of record (artifacts:
games/league/baseline-model/ and baseline-specialist/, report.json +
per-game PGNs). One lesson from the superseded runs stays: the 4
mercy mates `random` once handed the model engine vanished under a
different seed schedule — mercy-of-noise is luck, which is exactly
why the scoreboard separates it from forced.

MODEL ENGINE (belief=sloppy, depth 3, topk 6, coverage 0.85, probe
n<=3 cap 40k; 10 games/family = 5 seed-pairs, max 240 plies):

```
family       split      n  forced st-them st-us insuf fifty rep maxply
sloppy       dev       10       0       0     2     1     3   0      4
squat        dev       10       0       0     0     0     0   1      9
zach         dev       10       1       0     0     0     0   0      9
human-held   held-out  10       0       0     0     3     0   0      7
random       held-out  10       0       0     0     0     0   1      9
sloppy-held  held-out  10       0       0     1     5     0   0      4
squat-held   held-out  10       0       0     0     0     0   3      7
forced — held-out: 0/40 (0%); dev: 1/30 (3%); worst held-out: 0%
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

AND THE MODEL ENGINE DREW BLOOD IN THE SAME PIN: zach game 5 (engine
Black) is the new stack's first forced selfmate ever — 72...Qf7+
73.gxf7#, the queen donated onto the square where the pawn capture is
the opponent's only legal reply and the recapture IS the mate. That
is the forced-recapture device, the same family as v0.3's historic
54.Qc2+ Kxc2# — rediscovered organically by oracle+steering with zero
construction machinery. PGN:
baseline-model/zach_g05_selfmate-forced.pgn. The two firsts are a
clean diagnostic pair: the anchor converts via the kernel-matched
zugzwang (corner squatter walks into its own pocket), the model via
the opponent-robust forcing device. Everything else decomposes as
before — greedy families end in stalemate-us/mutual-strip (competent
strip, no sustained conversion pressure), avoidant families wall at
max-plies, and held-out stays 0/40. The ladder is explicit now:
match the anchor's 1/16 held-out, then pass it — sub-root oracle
probes, selective steering depth, and league-legal endgame guidance
are the levers, then the corpus fit.

## Sub-root probes and the crossfire: first held-out blood (2026-07-21)

The session opened the named levers in order and the league graded
each honestly. What landed (commit e7c1f2d, selftest 24 -> 32
checks):

- SUB-ROOT PROBES: steering's our-nodes carry a budgeted oracle probe
  (n<=2, 30k/move sliced 8k/call, memo shared with the root probe —
  its keys were already position+clock+repetition+n+side complete).
  Two gates, either opens: opponent at <=5 non-king men, or our king
  in check.
- FLIGHT-SQUARE PRICING (evaluate.py): in the king+pawns regime,
  every open flight square around our king costs 24 — corner
  affinity, self-smothering, and their-coverage in one gradient.
- BARE-KING GUARD: the safety partition now refuses to strip the last
  mating man while alternatives exist.
- ROOT PROBE DEEPENED: n 3 -> 4 under cap 40k -> 50k; iterative
  deepening self-regulates (wide positions burn out early and answer
  UNKNOWN, narrow ones — where conversions live — reach n=4).

Dev evidence chain (games/league/dev-subprobe-r1/r2/r3, 10
games/family, baseline seeds): r1 (material gate <=3) produced the
session's first discovery — sloppy g01, the CROSSFIRE DEVICE:
37...Re8 baits the near-certain promotion, 38.a8=Q+ Rxa8+ 39.Qxa8# —
check, counter-check, forced recapture-mate. The model engine's
first forced selfmate against a greedy family, found by the leaf
zugzwang term through the belief's 95% promotion mass, at SIX
opponent men — invisible to the material gate (and to the oracle
gauge: the engine's final move was its only legal one, so no probe
ever ran). The r1 autopsies also caught the engine stripping zach to
a bare king and then donating a bishop to reset the draw clock over
the corpse — hence the guard. r2 isolated the widened gate cleanly:
IDENTICAL trajectories to r1, the probe confirming the crossfire
(sub=4/182) and proving nothing anywhere else (thousands of calls,
zero hits) — the certifier works; steering never assembles anything
for it to certify. r3 (guard + n=4) prevented the corpses without
changing a label. Cost: ~35-64s/game on strip-heavy families (~52
min full league).

### Pinned league (2026-07-21, engine model, subprobe stack)

belief=sloppy, depth 3, topk 6, coverage 0.85, probe n<=4 cap 50k,
sub-probe n<=2 cap 30k men<=5|check; 10 games/family; artifacts:
games/league/subprobe-model/.

```
family       split      n  forced mercy st-us insuf rep maxply
sloppy       dev       10       1     0     1     2   0      6
squat        dev       10       0     0     0     0   2      8
zach         dev       10       0     0     0     0   2      8
human-held   held-out  10       0     0     2     4   0      4
random       held-out  10       1     2     0     0   0      7
sloppy-held  held-out  10       0     0     0     6   0      4
squat-held   held-out  10       0     0     0     0   2      8
forced — held-out: 1/40 (2%); dev: 1/30 (3%); worst held-out: 0%
```

FIRST HELD-OUT BLOOD: random g00 (engine White) is the model
engine's first held-out forced selfmate — and it is the corner
construction itself, assembled organically against UNIFORM NOISE.
The engine walks its king to h1 behind its own h2 pawn, preserves
random's h-pawn as the executioner the whole game, herds random's
king across the board with queen checks (Qa2/Qb2/Qc2 driving
Kc1-d1-e1-f1), promotes a second queen for tempo, and donates:
99.Qg2+ hxg2# — the forced-recapture finish on the FORCED_FIXTURE's
exact shell, closed under three root certificates (oracle=3). PGN:
subprobe-model/random_g00_selfmate-forced.pgn. Against mercy=1.0
there is no policy to exploit — the net held against every legal
reply, which is the robustness claim in its purest form. The two
random mercy mates in the same row are ledgered as luck, exactly as
the taxonomy intends. Against the baseline: held-out 0/40 -> 1/40
(2%), dev 1/30 -> 1/30 (the conversion relocated from zach's
recapture device to sloppy's crossfire), worst held-out 0% in both.
The anchor still leads on rate (1/16, 6%) — but the diagnostic pair
sharpened: the anchor converts the kernel-matched squatter and
nothing else; the model now converts the two families NO kernel ever
cracked (a greedy human, pure noise) and not the squatters. Strip
quality also moved: sloppy-held's draws shifted toward
insufficient-material 6/10 (clean strips, no conversion pressure)
and stalemate-us stayed rare (3/70 total).

The reading, for next session: certification is solved down to the
budget knobs — the root oracle plus sub-probes close whatever
steering reaches, and the gauges prove where nothing was reachable
(sub=0/N across 69 of 70 pinned games). The binding constraint is
ASSEMBLY: flat depth-3 steering does not construct nets, and the r2
null is the cleanest possible statement of it. Lever 2 stays the
named next move — selective deepening in stripped positions, which
needs value memoization to be affordable, which needs a decision
about draw-state honesty in a steering-only cache. The squat
near-miss (r1 g00: king frozen into pawn_last, pawns released to
promotion) is the concrete target shape.

### Artifact policy (2026-07-21)

Adopted with the subprobe merge: git keeps the citable minimum —
every PINNED-run forced-selfmate PGN (the trophies; four tracked as
of today) and report.json for runs a log entry pins as a table of
record. Draw PGNs and dev-exploration runs stay on disk, out of git
— dev-* wholesale, trophies included: the r1-r3 duplicates of the
pinned sloppy g01 trophy left with their runs, and by gitignore
mechanics nothing under an ignored directory can be re-included, so
a NOVEL dev trophy will never surface in git status on its own.
Promotion is therefore an explicit step: re-run the config a dev
report records into a pinned directory before citing its trophy.
The process-stable seed makes every run regenerable bit-for-bit
from the committed code plus the config its report records, so bulk
artifacts are redundant evidence. The two baseline directories
predate the policy and stay tracked as pushed.

### Sub-probe fairness + honest unknowns (2026-07-21, review fixes)

Review caught the sub-probe cap being first-come-first-served
across root candidates: the root order front-loads captures and
checks, those branches drank the 30k, and later branches steered on
the bare heuristic — reversing equal-priority root moves could
change the chosen move. The cap is now SPLIT EVENLY per root
candidate (search takes a probe factory, minted once per branch;
the shared memo still ferries proofs, so later branches probe
cheaper, never blinder), and the root sort is now total (priority
class, then UCI) so the argmax tie winner is position-intrinsic
too: the reversal repro returns the identical move with
bit-identical root values and gauges. Second catch: a probe call
whose slice expired returned None exactly like a refutation. New
gauge
sub_probe_unknowns counts gated calls that ended without an answer
(share dry, or slice died mid-proof); league lines now print it as
unk=. A sub=0/N null is only evidence when unk is low — the pinned
league's "sub=0/N across 69 of 70" reading predates the gauge, so
re-run before leaning on it again. Engine behavior changed:
2.0.0a0 -> 2.0.0a1. The pinned subprobe-model tables are a 2.0.0a0
record (their report.json says so) and regenerate from that
version's commit, not from HEAD.

### The a1 re-pin: fair shares double the take, and the unknowns flip the diagnosis (2026-07-21)

Re-run of the full league on 2.0.0a1 (the fairness + unknowns
commit), superseding the a0 subprobe-model tables as the model table
of record (a0 stays citable as its version's record; artifacts:
games/league/subprobe-model-a1/).

```
family       split      n  forced mercy st-them st-us insuf fifty rep maxply
sloppy       dev       10       0     0       0     0     1     1   0      8
squat        dev       10       1     0       0     0     0     0   1      8
zach         dev       10       2     0       0     0     0     0   1      7
human-held   held-out  10       1     0       0     2     1     1   2      3
random       held-out  10       0     1       1     0     0     0   1      7
sloppy-held  held-out  10       0     0       0     1     3     1   0      5
squat-held   held-out  10       0     0       0     0     0     0   1      9
forced — held-out: 1/40 (2%); dev: 3/30 (10%); overall: 4/70 (6%)
worst held-out: sloppy-held (0%)
```

TWO FINDINGS, BOTH LOAD-BEARING. First: fair shares alone DOUBLED
the take (2/70 -> 4/70; dev 1/30 -> 3/30 with the model stack's
first squat conversion and zach doubled; held-out blood moved to
human-held). The a0 budget was being drunk by the capture-first
front of the root order — the quiet box-building candidates, where
nets actually form, steered blind. Giving them eyes was worth two
conversions immediately. Second: the unk gauge says MOST gated probe
calls end starved, not refuted — game lines run sub=0/9616
unk=6931, sub=1/6174 unk=3813 (a 30k cap split across ~20-30 root
branches is ~1-1.5k nodes per branch, an eighth of one slice). The
merge entry's r2 diagnosis — "the certifier works; steering never
assembles anything for it to certify" — is hereby OVERTURNED as
unproven: we never gave the certifier the budget to say. Next lever
reordered by both findings at once: PROBE BUDGET SCALING first
(raise sub_probe_cap / concentrate the gate; the fairness jump is
itself evidence that budget binds), selective depth second, corpus
fit unchanged behind them.

### The cap becomes a ceiling and the unknowns enter the record (2026-07-21, review fixes)

Two catches against the fairness commit. First: the share floor —
max(1, cap // branches) — turned sub_probe_cap into a per-branch
MINIMUM whenever branches outnumbered nodes: a cap of 1 over a
30-move root would spend 30. The floor is gone; shares are the bare
floor division, zero when the cap cannot cover the pool, and a
born-dry share's gated calls ledger UNKNOWN exactly as before — the
starvation audibility that motivated the floor rides unk, and the
cap holds as a true total. No pinned run is touched: at 30k over
20-40 branches the floor never engaged (shares 750-1500), so a1
trajectories are bit-identical; only the selftest's cap=1 corner
changes meaning (it now asserts zero spend, unknowns == calls, and
that born-dry shares never count as exhaustions). Second: the a1
entry's own evidence — sub=0/9616 unk=6931 — lived ONLY in console
lines, which the artifact policy deliberately does not retain: the
diagnosis that overturned r2 was unreproducible from the pinned
report. Engines now expose gauges() (the model's eleven counters;
the specialist wrapper's one) and the runner snapshots it per game
onto record.probes in report.json — the console line derives from
the same dict, so log and record cannot diverge. Records schema +
starvation-corner semantics: 2.0.0a1 -> 2.0.0a2. The a1 tables
remain the table of record; from a2 on, a sub=/unk= claim is
checkable from report.json alone.

### The a2 audit pin: same table to the ply, and the starvation number enters the record (2026-07-21)

Re-run on 2.0.0a2 (cap-is-a-ceiling + persisted gauges; league-config
behavior identical by construction — the one-node floor never fired
at cap 30k). The prediction attached to the launch held EXACTLY:
**all 70 games identical to the a1 pin — label, plies, and final FEN,
game for game** — the first end-to-end verification that the stack's
determinism claims (process-stable subset seeds, total root order,
per-game RNG) survive a full league under a code change that should
not move play. Tables of record therefore UNCHANGED from the a1
entry (held-out 1/40, dev 3/30, worst held-out sloppy-held 0%);
subprobe-model-a2/ supersedes -a1/ as the citable artifact because
its report now carries what the diagnosis needs: per-game probe
gauges in every row. The starvation reading, previously console-only,
is now a number in the pinned report: **325,802 of 441,116 gated
sub-probe calls (74%) ended UNKNOWN** against 12 hits. Budget
starvation is a fact of the record, not an anecdote — the
budget-scaling lever keeps its place at the head of the queue.

## Funding the certifier: dev says refuted, held-out says converted (2026-07-22)

The a2 record's lever — 74% of gated sub-probe calls starved, fund
the certifier before building anything new — went through a
four-config dev sweep and one pinned league. The sweep returned the
honest-failure signature; the pin overturned it where it counts.

DEV SWEEP (zach/sloppy/squat, 10 games/family, baseline seeds, vs the
a2 dev rows: forced 3/30, unk 77.8%, 6 hits; artifacts
games/league/dev-fund-*/, untracked dev runs, regenerable from HEAD +
config):

```
config          forced  hits  unk%   nodes/call  diverged-vs-a2
30k men5 (a2)     3/30     6  77.8         252   —
30k men3          3/30     6  69.7         247   0 of 30
100k men3         3/30     6  54.9         682   0 of 30
100k men5         3/30    10  64.2         665   1 of 30
300k men5         3/30    10  32.4        1474   2 of 30
```

Four dev findings. (1) THE GATE AXIS IS A COST KNOB, NOT A PLAY KNOB:
both men3 runs are bit-identical to a2 — only HITS feed steering
(refuted and unknown both hand the search the same None), a tighter
gate can only lose hits, and the ≤3-men/check band was already
saturated at 6. (2) THE 4-5 MEN BAND HOLDS REAL PROOFS: at men5 100k
squat gained 4 hits — coverage beats concentration, the gate stays at
5. (3) DEV HITS SATURATE AT 10 BY 100k: 300k's extra 200k nodes
bought zero new proofs while halving unknowns again — sloppy's gate
at 5.5% unknown is essentially fully funded and still proves nothing
new. (4) The only dev play effect at any budget: two already-forced
games (zach g01, squat g00) convert two plies sooner. Budget up,
unknowns down, forced flat — on dev, starvation was real but NOT
binding; funded calls refute. (Sweep wall numbers ran under 4-way
container load and are not citable; the men3 games, bit-identical to
a2, clocked +70% — cost claims below come from the solo pin.)

### Pinned league (2026-07-22, engine model, funded certifier)

belief=sloppy, depth 3, topk 6, coverage 0.85, probe n<=4 cap 50k,
sub-probe n<=2 CAP 100k (was 30k) slice 8k men<=5|check; 10
games/family; artifacts: games/league/funded-100k/. Chosen by dev
evidence: hit saturation at a third of 300k's wall cost.

```
family       split      n  forced mercy st-them st-us insuf fifty rep maxply
sloppy       dev       10       0     0       0     0     1     1   0      8
squat        dev       10       1     0       0     0     0     0   1      8
zach         dev       10       2     0       0     0     0     0   1      7
human-held   held-out  10       1     0       0     2     1     1   2      3
random       held-out  10       0     2       1     0     0     0   0      7
sloppy-held  held-out  10       2     0       0     0     3     1   0      4
squat-held   held-out  10       0     0       0     0     0     0   1      9
forced — held-out: 3/40 (7.5%); dev: 3/30 (10%); overall: 6/70 (9%)
worst held-out: squat-held (0%)
```

THE ANCHOR'S RATE IS PASSED. Held-out moved 1/40 -> 3/40 (7.5%),
past the specialist's 1/16 (6.25%) for the first time, and the two
new conversions are exactly the lever's mechanism paying out:
sloppy-held g04, a 240-ply MAX-PLIES WALL in a2, now converts by
force in 116 plies off one previously-starved hit; sloppy-held g08, a
STALEMATE-US BLUNDER in a2, now converts in 74 plies — the fastest
organic forced selfmate on the project's record — off two new hits.
Both close identically: king to d1, the greedy family fed until the
board is stripped, and ...e2# under zugzwang — the same net, built
twice, against a held-out family no kernel models. Third divergence:
random g07's repetition draw became a mercy mate (ledgered as luck,
as always). Fourth: squat g00's known 2-ply speedup. All 66 other
games identical to a2, and the dev rows reproduce the sweep's
cap100k run gauge-for-gauge across separate containers — determinism
holds through a config change, again.

THE DIAGNOSIS, BOTH HALVES NOW MEASURED. On dev families the a1
starvation reading did not survive: fed to 5.5% unknown, the
certifier returns refutations, and the r2 verdict — steering never
assembles nets — stands re-confirmed there. On held-out it was the
binding constraint: sloppy-held's provable nets existed at 30k and
starved (3 hits, 63.5% unk); at 100k (7 hits, 43.5% unk) they
certify and CONVERT. One number for the asymmetry: the funded run's
24 hits against a2's 12, with every marginal hit on the two families
(squat, sloppy-held) whose games sit longest in the 4-5-men band.
Starvation survives as a live secondary fact — squat still 78.5%
unknown, squat-held 59.4% at 100k — but the dev-side evidence says
feeding it further buys refutations, not nets.

Cost and config of record: 73.7s/game solo, 86 min the full league
(a2: 51.7s/game, 60 min) — +42% wall for the funded certifier.
cap 100k men 5 is the working configuration from here; the CLI
default stays 30k in code this session (the pinned report's engine
block is the config of record, per policy). Next lever unchanged
from the a1 entry's queue, now sharpened by the split verdict:
SELECTIVE DEPTH for the dev-shaped walls (squat/zach max-plies
games, the r1 near-miss shape — king frozen into pawn_last, pawns
released), graded by a certifier that funding has now made honest.
Milestones stand at 60/80/90% held-out; 7.5% is the first rung
above the anchor, not the wall's top.

### The default catches up to the record (2026-07-22)

sub_probe_cap 30k -> 100k in engine and CLI defaults: the funded-100k
table of record's config IS now the default config, no flags needed.
Behavior at defaults changes accordingly; 2.0.0a2 -> 2.0.0a3.

## Selective depth: the horizon was never the wall — the belief was (2026-07-22)

The a1-queue's second lever went in as three orthogonal, default-off
knobs (2.0.0a3 -> 2.0.0a4, selftest 34 -> 38): FORCED-SEQUENCE
EXTENSION (a node in check or down to one legal reply spends a
per-line extension budget instead of depth — check chains and
only-reply boxes deepen without widening; the budget is the
perpetual-check bound, and the suite proves it binds), DEEP ROOTS
(root-gated deepening when THEIR side is stripped to deep_men non-king
men or king+pawns of any count, optional topk narrowing), and a
NODE CAP (per-move clamp, degrade-to-leaf instead of stalling; never
fired at 400k in any arm — every cost below is shape, not pathology).
Three dev arms, 10 games/family, baseline seeds (artifacts
games/league/dev-seldepth-{base,ext,deep}/, untracked, regenerable
from HEAD + the report's engine block):

```
arm    config                        forced  hits  unk%     snodes  div-vs-funded
base   a4 defaults (=funded-100k)      3/30    10  64.2      13.6M   0 of 30
ext    forced_ext 6, node_cap 400k     3/30   644  99.1      66.7M  30 of 30
deep   depth4 topk3 men3, cap 400k     1/30    60  98.0      23.0M  30 of 30
```

BASE: the a4 hot-path refactor reproduces the funded-100k dev rows to
the ply, gauge for gauge — flags off is bit-identical, so the arms'
changes are the levers' alone. DEEP is refuted twice over: topk 3
narrowing gutted steering against the diffuse family (zach hits 6 ->
0, both conversions lost), and deepening is structurally ANTI-probe —
gated calls per game exploded up to 109x (zach g01: 4.5k -> 492k)
while each branch's share was drunk by the shallowest nodes, leaving
the frontier the depth was bought for blind (98%+ unknown). EXT is
the interesting verdict: forced count identical at 3/30 but the
three are different games — g01's conversion halved to 65 plies on
the same seed, g03 and g04 are NEW organic devices of exactly the
targeted shapes (g03: 40.f7+ Qxf7+ 41.gxf7#, the crossfire recapture
through a check-on-check chain; g04: 62.Rg1+ Kf2 63.Qb8 fxe2#, a
donated knight cashed by a QUIET tempo move under zugzwang — the
first waiting-move net on the model stack's record), while zach g09
and squat g00 un-converted and sloppy g01 walked into a stalemate-us.
The relocations are opening chaos, not mechanism: every ext game
diverges from base by ply 4 on a 3-point eval flutter (Bb5 vs Bc4),
200 plies upstream of any endgame. At n=10/family the game-for-game
ledger is noise; the honest units are the aggregate (flat) and the
device inventory (+2, both real). Cost: 4.9x search nodes for six
extension plies. Neither arm meets "dev forced off 3/30"; no pinned
league was run, and funded-100k REMAINS the table of record — a
re-pin of the incumbent config would only have reproduced it
bit-for-bit (the base arm just did, for the dev half).

### The phantom net: 629 hits, zero arrivals, one mirage (2026-07-22)

The sweep's real yield. Ext squat g03 logged 629 sub-probe hits —
ALL of squat's hits — against zero root-oracle closures in a 240-ply
max-plies wall. Replaying its endgame with the live engine: a perfect
two-ply oscillation, plies 145/149/153/... seeing 8-36 hits with the
argmax at 52,940-75,131 (0.53 x MATE, then 0.75 x at two men) while
the plies between see zero hits at eval scale (~550). The engine
shuffles Ba6/Bb7/Rb7 forever, paid half a mate per offer for a net
the oracle really did prove — behind a king-wander reply the BELIEF
(sloppy, ~0.5 mass) expects and the OPPONENT (squat, home 1.0) never
plays. Fifty-plus consecutive untaken coin-flips is not variance;
believed-p vs true-p is the whole story. And it is CONFIG-INDEPENDENT:
the flat searcher at the same positions sees the same 19-22 hits at
the same 52.9k values with ext 0 — the hits fire at ply-2 our-nodes
that depth 3 already probes. Selective depth neither causes nor cures
it; ext g03 merely wandered into mirage territory while base g03's
ply-4 flutter steered elsewhere. Two standing facts snap into focus:
squat/zach max-plies walls (phantom EV outbids every real assembly
plan, so steering shuffles), and the funded pin's sloppy-held
conversions (the SAME mechanism with honest odds — belief matched
opponent, the offers landed, the nets cashed). The plumbing prices
exactly what it is told; what it is told about squat is wrong.

Queue reorder, forced by the mechanism: the CORPUS FIT is promoted
ahead of value plumbing — an online posterior over urge parameters
from the game's observed moves kills a phantom's wander-mass in a
handful of observations and leaves honest mirages untouched, whereas
any static discount on chance-mass certificates taxes the true and
the false alike (sloppy-held's conversions were the true). Value
plumbing drops to third; selective depth goes to the bench with its
knobs in the tree (the extension's two new devices and the halved
conversion say it will matter again once the odds are honest).
Milestones unchanged: held-out 60/80/90%, worst family named, the
live bar still "the corner poses and the mate lands BY FORCE."

### The node cap splits like the probe cap (2026-07-23, review fix)

Review caught the node cap repeating the sub-probe cap's original
sin: one counter shared across the root, so the sort-front
candidates (captures and checks, by the root order) searched at
full depth and every quiet candidate behind them was compared on a
bare leaf eval — at cap 60 on the start position, 19 of 20 root
values differed from a fair allowance and the argmax flipped (e4 ->
a4). Quiet moves are where boxes get built; a biased cap taxes
exactly the payload. The cap now splits evenly per root candidate
(bare floor division; an absolute per-branch threshold that is
None-disabled, because a zero share at a zero node count must not
read as no-limit), so every root value is computed under the same
allowance regardless of walk position, and a cap smaller than the
pool degrades every branch to its entry eval, evenly. What the cap
bounds is EXPANSION — clamped entries are leaf evals closing
already-open loops, since truncating a chance node's remaining
children would bias its expectation by the missing mass — and the
suite now pins the invariant directly: nodes - clamped <= cap, and
a pool member's joint value equals itself searched alone under one
share. Selftest 38 -> 39; 2.0.0a4 -> 2.0.0a5. No pinned run is
touched (node_cap has never appeared in a pinned config, and
flags-off stays bit-identical); the dev-seldepth ext/deep arms
recorded node_cap 400000 and are a 2.0.0a4 record — regenerate them
from that commit, not HEAD, because per-branch shares can trip
where their never-reached global total did not.

## The belief becomes an inference: the posterior reads every opponent, and the phantom dies on schedule (2026-07-23)

The phantom-net entry's queue reorder went through whole: opponent
inference from observed moves, built, graded on dev, and pinned.
What landed (selftest 39 -> 50, 2.0.0a5 -> 2.0.0a6):

- models/posterior.py: a log-space Bayesian POSTERIOR over seven
  dev-pure urge hypotheses (sloppy, half-strength sloppy, zach, the
  squat premise on both corners, and squat grafted with sloppy's own
  greed numbers), updated after every observed opponent move via the
  family's exact distribution() likelihoods — the reason those
  likelihoods exist. Chance nodes price the MAP hypothesis (--infer
  map) or the pruned posterior mixture (--infer mix) instead of a
  config constant. Epsilon-uniform smoothing (1e-3) makes an
  off-model move four orders of magnitude of evidence, never a death
  sentence; pruning benches a hypothesis without deleting it.
  Inference reads ONLY the observed moves of the current game — no
  family name, no held-out parameter — and the frozen-preset
  protocol stands untouched. Updates are pure functions of the
  observed sequence; the suite replays an inferring game twice and
  demands bit-identical trajectories, and the pin below reproduced
  the dev arm's 30 games to the ply across the mount/bake boundary.
  Diagnostics (MAP + weight, moves-to-collapse, live count, full
  weight vector) ride gauges() into report.json per game.

- models/fit.py + the fit CLI: the OFFLINE half, v2 groundwork.
  Coordinate descent over a value grid on the same smoothed exact
  likelihood; stdlib only, deterministic, forced replies skipped as
  weightless. Licence to operate proven in-suite: kernel games with
  known truths fit back EXACTLY (squat -> home=1.0 + pawn hostage +
  king corner at truth-equal NLL; zach -> the all-zero shuffle).
  First human corpus run (the eight Iptychs live games, 768
  observations): from zeros, descent stalls in the mercy=1.0 flat —
  uniform noise, 1.9663 nats/move, and mercy=1.0 is the random
  preset's exact point, arrived at independently from data. From the
  sloppy start it finds real structure: mercy .70, greed .95, trade
  .45, hunt .90, push .30, promote .10, check 0.0 at 1.8541
  nats/move, beating uniform by .11 and hand-seeded sloppy by .64.
  Two readings: the family explains kernels perfectly and real
  humans mostly as noise (the 70% mercy residue is a
  misspecification measurement), and the structured remainder is
  sharp enough to correct sloppy on two axes — the human hunts and
  grabs with near-certainty and never once sought a check. The
  fitted-human hypothesis waits for a future session's own dev
  evidence; nothing here nudged a preset.

THE ACCEPTANCE PROBE, ON THE MIRAGE'S OWN BOARDS. Replaying ext
g03's recorded oscillation plies against both engines (artifact
untracked, regenerable from its 2.0.0a4 config):

```
ply   fixed-sloppy (funded config)       infer (posterior, same board)
145   Rb5=52959   sub=21/126  phantom    Rb3=99996  sub=1/49  honest net
147   Rb3+=544    sub=0/98    eval scale Rd1=537    sub=0/51  eval scale
149   Rb5=52958   sub=21/126  phantom    Rb3=99996  sub=1/49  honest net
151   Rb3+=543    sub=0/97    eval scale Rd1=531    sub=0/50  eval scale
153   Rb5=52957   sub=22/131  phantom    Rb3=99996  sub=1/50  honest net
```

The fixed belief reproduces the mirage to the node — half-a-mate
argmaxes on 21-22 certificates the squatter will never let stand.
The posterior at the same boards, collapsed by the same 145 observed
plies, answers at eval scale or with ONE certificate at near-full
MATE: a net that holds under the squatter's actual reply. The
phantom is not discounted; it is repriced to what it always was.
Full-game replay of the g03 seed point-collapses onto squat-k at
observation 12 and STILL walls at max-plies with zero certificates —
the two layers separate exactly as the bench note predicted: pricing
was the mirage, and assembly is the constraint that remains.

DEV ARMS (map vs mix, 10 games/family, baseline seeds; artifacts
dev-infer-{map,mix}/, untracked; vs funded's dev 3/30):

```
arm   sloppy  squat  zach  total  notes
map      0      1      1   2/30   squat g00 156 -> 78 plies; zach -> g08 (118, 2 certs)
mix      1      0      0   1/30   sloppy g07 NEW: 75 plies, 3 certs; 3 st-us blunders
```

Neither arm holds the dev bar, and the ledger says relocation, not
mechanism: inference identified the true family in ALL 60 games
(zero misreads, median collapse ~10 observations), the phantom hits
are GONE (funded's squat walls accumulated mirage certificates; the
honest walls run sub=0), and with them went the capital they had
bought — funded's zach pair were real devices reached through
misprized approach paths, and honest beliefs do not walk those
paths. What honest play landed is better per device: the same-seed
squat conversion in HALF the plies, and a 75-ply sloppy net under
three root certificates. MAP took the pin on aggregate, the cleaner
sloppy row, and cost.

### Pinned league (2026-07-23, engine model, posterior-map)

Defaults (= funded-100k config) + --infer map; 10 games/family;
epsilon 1e-3, prune 1e-3, seven hypotheses recorded in the report's
engine block; artifacts: games/league/posterior-map/.

```
family       split      n  forced mercy st-them st-us insuf fifty rep maxply
sloppy       dev       10       0     0       0     0     3     0   0      7
squat        dev       10       1     0       0     0     0     0   0      9
zach         dev       10       1     0       0     0     0     0   0      9
human-held   held-out  10       0     1       0     1     0     0   0      8
random       held-out  10       1     0       0     0     1     0   0      8
sloppy-held  held-out  10       2     0       0     1     2     2   0      3
squat-held   held-out  10       0     0       0     0     0     0   0     10
forced — held-out: 3/40 (7.5%); dev: 2/30 (7%); overall: 5/70 (7%)
worst held-out: human-held (0%)
```

THE CRITERIA SPLIT, AND BOTH HALVES ARE THE FINDING. Held-out HELD
at 3/40 — the anchor-passing rate, kept by an engine whose beliefs
are now earned rather than configured: sloppy-held's conversions
survived inference (g08's 74-ply record game intact, g04's
conversion relocated to g02 at 90 plies), and random g01 is a NEW
forced device class — a ten-check HERD CHAIN driving the noise king
across the board into c6, sealed by the quiet 76...Ne4 into a
position where every legal reply mates, closed under a root
certificate. Against uniform noise the check chain is the only
forcing instrument there is, and steering found it organically.
squat-held stayed at 0% — the prize not taken — but for the first
time the zero is DIAGNOSED rather than ambient: all ten games read
map=squat-greedy-q@1.00 (collapse 5-31 observations — the mirrored
corner and the greed graft both earned their hypothesis seats; the
posterior derived "greedy squatter, queen corner" from observation
alone) and the funded engine's sub-probe hits on those walls are
simply gone (46 hits / 402,627 calls league-wide, unk 47.7%, 9 root
certificates). Before this session, squat-held's zero could have
been belief error or construction gap; now it is measured: the
belief is right and the constructor is absent. The same signature
covers dev squat/zach — walls with correct beliefs and nothing for
the certifier to certify.

The posterior read every held-out family correctly from moves
alone: sloppy-held -> sloppy 10/10, human-held -> sloppy-mild 8/10
(the half-strength interpolation exists for exactly that region),
squat-held -> squat-greedy-q 10/10, random -> sloppy-mild 10/10 at
weight 1.00 — the flattest structured hypothesis standing in for
noise the set cannot name; a mercy-bearing hypothesis (the fitter's
human point) is the obvious future seat. And honesty is CHEAPER:
49.3s/game solo, 58 min the full league, against funded's 73.7 —
the phantom oscillations were burning probe budget on certificates
that never cash, forever.

Tables of record: funded-100k REMAINS the record at defaults, and
defaults do not move (the precedent flips defaults when a pin beats
the record; this pin ties held-out, trades composition, and cedes
one dev game). posterior-map is pinned as the INFERENCE record: the
config, the diagnostics schema, and the trophies are citable from
its report alone. Queue, forced by the diagnosis: SELECTIVE DEPTH
x HONEST ODDS first — the benched deep/ext knobs re-armed on
--infer map, aimed at walls that are now proven assembly-bound
(squat, squat-held, zach: correct beliefs, sub=0); hypothesis-set
growth second (the mercy family for random/human-held, the
fitted-human point, both through dev evidence); value plumbing
third, unchanged. Milestones stand at 60/80/90% held-out; the live
bar stays "the corner poses and the mate lands BY FORCE."

## Posterior review hardening (2026-07-23)

Four review findings on the inference pin were accepted; 2.0.0a6 ->
2.0.0a7, selftest 50 -> 53:

- `--belief` now initializes inference as an actual prior. Half the
  mass sits on the configured dev point and half is balanced across
  the sloppy/zach/squat families, then divided among variants inside
  each family. Thus `belief=zach --infer=map` starts at Zach, while
  adding a fourth squat variant no longer grants squat four times a
  one-point family's exploratory mass. All hypotheses retain positive
  mass and can recover after contrary evidence.
- The league synchronizes the final board before `gauges()`. An
  opponent terminal move is now included even when the engine never
  receives another `choose_move()` call; the one-ply, engine-as-Black
  regression records one observation, while engine-as-White records
  zero.
- Future reports persist epsilon, prune, collapse, the prior rule and
  exact per-hypothesis prior, family, and full `UrgeParams` dictionary,
  plus `snapshot=final-board`. The pinned a6 report was enriched
  without changing its results: it truthfully records the historical
  uniform 1/7-per-hypothesis prior and
  `snapshot=engine-last-decision`.
- The human-held narrative is corrected from sloppy-mild 7/10 to
  8/10, matching the ten game records (two ended at sloppy).

Docker validation: selftest 53/53. A two-game CLI smoke with
`belief=zach --infer=map`, one-ply games, emitted 2.0.0a7 metadata
with Zach prior 2/3, sloppy-family prior 1/6, squat-family prior 1/6,
and every parameter dictionary present. No performance league was
rerun: this is a behavior-affecting prior correction, so
`posterior-map/` remains the historical a6 inference pin rather than
being relabeled as an a7 result. Runtime and conversion gains: no
claim.

## Selective depth x honest odds: the extension comes off the bench and doubles the record (2026-07-23)

The posterior-map queue said it plainly: re-arm the benched a4 depth
knobs on --infer map, aimed at walls that are now proven
assembly-bound. The whole a4 sweep was graded inside the phantom's
environment — fixed-sloppy EV outbidding real plans on every squat
wall — so its "no arm moves dev" was a measurement of the poison, not
of the knobs. Re-graded with honest odds, the verdict flips, and the
pin below supersedes funded-100k as the table of record.

FIRST, THE CONTROL SAID SOMETHING ITSELF. infer-base (a7 defaults +
--infer map, the posterior-map config re-run on current code) does
NOT reproduce the a6 pin: 13 of 30 dev games diverge in movetext,
exactly as the a7 review entry warned when it declined to relabel the
pin. What survives is everything that matters: the aggregate holds at
forced 2/30 with the SAME two conversions ply-for-ply (squat g00's
78-ply window, zach g08's 118), and the assembly-bound diagnosis got
SHARPER — the a6 pin's squat g09 carried 4 wall hits; at a7 every dev
wall runs sub=0 with the family still read correctly, and matched
families collapse faster (the anchored prior starts sloppy at 0.583,
so 0.95 arrives in 3-8 observations against a6's 5-29). posterior-map
stays the a6 inference record; infer-base is the a7 control this
sweep grades against.

DEV ARMS (zach/sloppy/squat, 10 games/family, baseline seeds, all
--infer map; artifacts dev-infer-seldepth-{base,ext,deep}/, untracked,
regenerable from HEAD + the report's engine block; arm wall-seconds
ran under 3-way container load and are not citable):

```
arm    config                     forced  hits  unk%   certs  snodes  st-us
base   defaults                     2/30     3  63.7       3   11.0M      1
ext    forced_ext 6, cap 400k       6/30    47  99.0      12   53.0M      0
deep   depth 4 men 3, topk kept     4/30    30  97.6       7   23.7M      2
```

THE TOGETHER-TEST PASSES ON ZACH, AND SLOPPY JOINS IN. The honest
certifier's criterion was hits and forced moving together on the wall
families. Ext zach: hits 1 -> 23 WITH forced 1 -> 4. Ext sloppy: hits
0 -> 21 WITH forced 0 -> 1. Deep zach shows the same signature weaker
(20 hits, 3 forced) plus two stalemate-us blunders ext does not have,
and its a4 pathology survives inference unchanged: deepening is
structurally anti-probe (gated calls x61, unk 97.6%; its conversions
closed through root certificates, not sub-probes). Squat is the
flat-flat family in BOTH arms — one conversion each, relocated (the
control's g00 window became ext's new g09 construction), walls still
sub=0 — so dev squat's wall stays assembly-bound at every depth
tried. Ext costs what it cost in a4 — 4.8x search nodes, the same
ratio — and the a5 per-branch node cap now actually trips where a4's
global counter never did (squat g07: 2,900 clamped entries),
degrading evenly by design instead of biasing the quiet candidates.
Ext takes the pin on every axis: triple the control's forced, zero
blunders, and the fastest conversions on record.

### Pinned league (2026-07-23, engine model, posterior-ext)

Defaults + --infer map --forced-ext 6 --node-cap 400000 (config of
record in the report's engine block, prior rule and per-hypothesis
priors included); 10 games/family; artifacts:
games/league/posterior-ext/.

```
family       split      n  forced mercy st-them st-us insuf fifty rep maxply
sloppy       dev       10       1     0       0     0     1     0   1      7
squat        dev       10       1     0       0     0     0     0   0      9
zach         dev       10       4     0       0     0     0     0   0      6
human-held   held-out  10       0     0       0     0     0     0   1      9
random       held-out  10       3     1       0     0     0     0   1      5
sloppy-held  held-out  10       1     0       0     0     1     0   0      8
squat-held   held-out  10       2     0       0     0     0     0   0      8
forced — held-out: 6/40 (15%); dev: 6/30 (20%); overall: 12/70 (17%)
worst held-out: human-held (0%)
```

THE RECORD IS DOUBLED EVERYWHERE AT ONCE: held-out 3/40 -> 6/40, dev
3/30 -> 6/30, overall 6/70 -> 12/70 against funded-100k, with the
anchor's 6.25% now lapped twice over. Determinism held end-to-end:
all 30 dev games are bit-identical to the ext arm's across the
solo/loaded container boundary, so the arm evidence and the pin are
one experiment, not two.

SQUAT-HELD IS OFF ZERO — the standing trophy target, the family every
league since the baseline scored 0%, and the cleanest test in the
project after the posterior-map pin proved its belief right and its
constructor absent. The constructor arrived. g01 (169 plies, 2 certs)
is the LIVE BAR'S OWN SHAPE landed on a held-out family: the engine
walks its king into the a8 corner tomb, preserves the squatter's
a6-pawn as executioner, and donates a knight to b7 — where the greed
graft inference identified (squat-greedy-q@1.00, all ten games, read
from moves alone) takes the bait: 85.axb7#. g02 (156 plies, 2 certs)
is a double-donation crossfire: 77.Qb8+ baits Kxc6, 78.Qb5+ forces
axb5#. The row's sub-probe hits sit exactly on the two converting
games (5 and 1); the eight walls still run sub=0 — the certifier
agrees the constructor reaches nets in some games and none of the
others, which is what a real capability looks like at n=10.

The rest of the held-out ledger: sloppy-held g03 converts in 53
PLIES — the fastest organic forced selfmate on the project's record
(old record 74) — by feeding its own rook to f7 and letting the
greedy family's 27.exf7# close over the self-boxed king, three root
certificates deep. Random tripled to 3/10: the g00 pawn-bait pocket
(49.g3 hxg3#), the g03 herd chain driving the noise king five checks
across the board into the quiet 55...Rb7 and 56.axb7#, and the g05
herd into knight-feed (78.cxd7#); its fourth mate is mercy, ledgered
as luck as always. Relocation cuts both ways and is recorded
honestly: sloppy-held's funded-era pair (the 74-ply record game
included) walled or drew on these trajectories — the a4 lesson
stands that game-for-game ledgers are noise at n=10 while aggregates
and device inventories are the units, and both units moved up.

The dev half of the pin (identical to the arm): zach g03's crossfire
at 55 plies, g02's herd chain — the class's first landing on a dev
family — g05's waiting-move net (check-drive into the quiet 39...g5,
cashed by 40.cxd7#), g08's induced rook underpromotion into 97.Qh1+
Rxh1#, squat g09's quiet buildup (h6, Qg3, Re6) around the squatted
corner closed by 42.fxe6#, and sloppy g00's herd into 84.Qd2+
Kxd2# — six conversions, five device classes, three of them new to
the inventory (herd-on-dev, the squat construction, the record
crossfires).

HUMAN-HELD IS NOW THE LAST ZERO, and for the first time the record
itself carries a diagnosis: the posterior cannot name the family.
Reads scatter between sloppy-mild (0.78-0.93) and sloppy
(0.57-0.99), one game never collapses at all (g05: coll=0), and the
one 240-ply row with 3 hits still certifies nothing. Every other
family reads at 1.00 and converts or walls on construction merit;
here modeling is the FIRST UNRESOLVED CONFOUND — until a hypothesis
can name the family, assembly on this row cannot be diagnosed
either way (squat-held's zero hid a working-belief/absent-constructor
split; this zero may hide an assembly wall behind the modeling one).
The queued mercy-bearing hypothesis (the fitter's human point: mercy
.70, greed .95, hunt .90, check 0.0) is aimed at exactly this
confound.

Cost and gauges of record: 166.1s/game solo, 194 min the full
league — 3.4x posterior-map's 49.3, the price of 27.0M extension
nodes inside 126.8M total. Sub-probes: 78 hits / 42.6M gated calls,
unk 98.8% — the extension keeps the certifier starved (the a4
shape), and the 24 root certificates did the closing; probe-budget
scaling under ext trees is an open lever, not a refuted one. The
node cap's first real work at solo scale: 38,795 clamped entries
league-wide, 25,687 of them in random g09's 3.7M-call blowup game —
the backstop held that pathological game to 390s (the record's
per-game figure; move-level timing is not persisted) instead of
stalling the clock.

Queue, forced by the one remaining zero and the walls that stayed:
HYPOTHESIS-SET GROWTH first (the mercy family / fitted-human point
for human-held and random, through dev evidence, exactly as the
posterior-map entry queued it); VALUE PLUMBING second (dev squat
still walls 9/10 with a correct belief and a working constructor
elsewhere — proven-node scores vs chance-layer dilution is the named
suspect); deep roots stay benched (starves probes, converts less
than ext, and blunders). Milestones stand at 60/80/90% held-out;
15% is the second rung. The live bar stays "the corner poses and
the mate lands BY FORCE against a human" — squat-held g01 is that
exact shape against a held-out kernel, which is the strongest
evidence yet that the bar is reachable.

### The default catches up to the record, again (2026-07-23)

Per the a3 precedent (a pin beats the record, its config becomes the
defaults): engine and CLI defaults move to the posterior-ext config —
infer off -> map, forced_ext 0 -> 6, node_cap 0 -> 400000. Behavior
at defaults changes accordingly; 2.0.0a7 -> 2.0.0a8. One suite touch
rides along: the off-mode-carries-no-posterior check now requests
infer="off" explicitly, since silence no longer means off. The
posterior-ext tables are a 2.0.0a7 record and regenerate from that
commit with the flags its report records; at a8 the same
configuration is simply spelled with no flags.

### Post-pin review round (2026-07-24)

Three findings on the pin + flip, all accepted; no engine behavior
changes, version stays a8 (trajectories, reports, and regeneration
are untouched — the a1/a5/a7 bump precedent is for code that moves
play).

- THE FLIP BROKE FOUR ADVERTISED BELIEFS (P2, real): with --infer
  defaulting to map, every held-out name in --belief's own choices
  list (sloppy-held, human-held, squat-held, random) died as an
  uncaught ValueError from engine construction — the posterior's
  deliberate dev-purity rejection surfacing as a traceback mid-run.
  Reproduced at the CLI before fixing. main() now validates the
  belief x infer combination at the parser boundary for engine-bearing
  commands (play, league --engine model): the same rejection arrives
  as a clean parser error naming the escape hatch ("a fixed held-out
  belief needs --infer off"), and --infer off keeps every advertised
  belief usable. Held-out choices stay exposed on purpose — a fixed
  held-out belief is a legitimate diagnostic configuration; only
  anchoring INFERENCE on one is protocol leakage, and the posterior
  still enforces that. Suite 53 -> 54: the new check drives all four
  names through the real CLI and demands exit 2 plus the escape
  hatch in the message.
- HUMAN-HELD OVERCLAIM CORRECTED (P2, real): the pin entry read the
  scattered posterior as "a modeling gap, not an assembly gap" —
  but zero conversions cannot exclude an assembly wall hiding behind
  the modeling one; only the confound ORDER is proven. The entry now
  says modeling is the first unresolved confound and assembly there
  is undiagnosable until a hypothesis can name the family. The
  queued mercy-hypothesis experiment is unchanged — it resolves the
  confound either way.
- 390s ATTRIBUTED TO THE GAME (P3, real): report.json persists
  per-game seconds only; the node-cap sentence claimed a
  "pathological move" held to 390s. It now cites the game figure and
  notes move-level timing is not persisted — per the artifact rule
  that a pinned claim must be checkable from report.json alone.

## The mercy family: human-held falls off zero, random is named and fished, and the zero moves (2026-07-24)

The posterior-ext queue's first lever went in whole: hypothesis-set
growth aimed at the last zero's named confound — no hypothesis
carried a mercy axis, so human-held's scattered reads could not,
even in principle, name a family that sometimes mates us on purpose.
What landed (2.0.0a8 -> 2.0.0a9, selftest 54 -> 57):

- models/posterior.py: the FITTED-HUMAN family, two points. The full
  point is the corpus fit verbatim (the 2026-07-23 offline MLE over
  the eight Iptychs live games, 768 observations, 1.8541 nats/move:
  mercy .70, greed .95, trade .45, hunt .90, push .30, promote .10,
  check 0.0) and the mild point is its half-scale by the sloppy-mild
  precedent applied literally — _scaled halves EVERY continuous urge,
  so fitted-human-mild is a globally milder human (mercy .35 and half
  the structure with it), not a mercy-only interpolation. Every value
  traces to the corpus fit or dev reasoning; no number touches a
  frozen preset — corpus-derived is dev-legal, and the module
  docstring now says so. The prior grows a fourth family under the
  review round's family-balanced rule, exactly the mechanism that
  redesign anticipated: belief=sloppy now opens 0.5625 / 0.0625 /
  0.125 / 4x0.03125 / 2x0.0625, asserted to the digit in-suite.

- Why mercy is THE axis: it is the only urge that puts mass on moves
  that mate us, so every mercy-free hypothesis prices an observed
  avoidable mate at literal zero and eats the epsilon floor — one
  taken mate is a ~700x likelihood factor toward the mercy family,
  and no volume of mercy-free evidence can ever say "this opponent
  mates us on purpose". The new suite checks pin the mechanism from
  three sides: an observed avoidable mate on the accident fixture
  (the greedy Rxa7, then Rb8#) lands map=fitted-human with
  mercy-family mass 0.97 through the sloppy anchor's 9x prior head
  start; the march fixture still collapses onto squat-k at 0.998
  with the mercy family at 4e-4 (kernel reads unblurred); and the
  nine-hypothesis prior vector is asserted exactly.

DEV CONTROL: THE GATE FIRED, THE DIAGNOSIS EXONERATED, THE A/B
RESOLVED. The dev arm (zach/sloppy/squat, 10 games, baseline seeds,
a9 defaults; artifacts dev-infer-mercy/, untracked) came back naming
perfect, aggregate short: every game reads its true family at 1.00
(collapse 3-18 observations, median 10; the mercy rungs at 0.0 on
every mercy-free stream) — but forced 4/30 against the record's dev
6/30, and the session's own gate says aggregate holds or the growth
is mis-tuned. The offline divergence replay (the posterior is a pure
function of the observed sequence, so the pin-era belief trajectory
reconstructs without search) localized the whole dip: 22 of 30 games
are BIT-IDENTICAL to the pin — four of its six dev conversions
reproduced ply-for-ply — and all 8 divergent games diverge at ply
3-4 by ONE signature: the old set's MAP had already handed sloppy
off to zach at the engine's second decision, the grown set holds
sloppy one observation longer (zach's exploratory prior fell 1/6 ->
1/8 with the fourth family), and the opening re-rolls from there.
The mercy hypotheses never held MAP for a single ply in any dev
game — the values are exonerated; the re-roll is the prior
renormalization ANY fourth family causes, whatever its content. The
re-rolled 8 landed 0/8 where the pin's had gone 2/8. Whether that is
a rate drop or a coin was measured, not argued: a fresh-seed A/B
(seed0=100, seeds neither set ever saw; grown set on the a9 tree,
old set on the a8 HEAD in a worktree; artifacts dev-mercy-s100/ and
dev-old-s100/, untracked):

```
arm            set        forced  sloppy  squat  zach  certs
dev-mercy-s100 grown (9)   10/30       5      2     3     16
dev-old-s100   old (7)      8/30       4      2     2     12
```

The grown set BEATS the old set on fresh ground, names 30/30 there
too (>=0.95, zero fitted-MAP finals), and the pooled count across
all 60 paired dev games is 14 = 14 — rate-neutral on dev with the
naming capability added. Not mis-tuned; gate answered. (Both s100
arms also outscored both s0 arms — seed-schedule variance at n=30 is
+/-3, one more vote for the a4 rule that aggregates and device
inventories are the units, single schedules are not.)

### Pinned league (2026-07-24, engine model, posterior-mercy)

a9 defaults, no flags (= the posterior-ext config over the grown
nine-hypothesis set; prior rule and per-hypothesis priors in the
report's engine block); 10 games/family; artifacts:
games/league/posterior-mercy/. Dev rows are bit-identical to the
dev-infer-mercy arm across the mount/bake boundary — the arm and the
pin are one experiment, again.

```
family       split      n  forced mercy st-them st-us insuf fifty rep maxply
sloppy       dev       10       0     0       0     1     1     0   0      8
squat        dev       10       1     0       0     0     0     0   0      9
zach         dev       10       3     0       0     0     0     0   0      7
human-held   held-out  10       1     0       0     0     0     1   0      8
random       held-out  10       0     7       0     0     0     0   0      3
sloppy-held  held-out  10       2     0       0     0     2     0   0      6
squat-held   held-out  10       2     0       0     0     0     0   0      8
forced — held-out: 5/40 (12%); dev: 4/30 (13%); overall: 9/70 (13%)
worst held-out: random (0%)
```

THE TIERED VERDICT, HONESTLY: (b) YES, (a) NO, (c) NO BY ONE.

HUMAN-HELD IS OFF ZERO — tier (b), the conversion the family was
grown for, by a route nobody predicted. g01 (103 plies, engine
Black, 1 root certificate, 4 sub-probe hits) is the
pawn-executioner shell landed on the last unconverted family: the
engine strips White with a queen rampage, gives the queen back to
seal material, entombs its own king on g8 behind the g7 pawn it
FORCED White to push (34.hxg7+), then shepherds White's f-pawn up
the board with rook-and-knight herding until 52.f7# is White's only
legal move. But the posterior that steered it read sloppy-mild@0.95
(c@6) with the mercy family at 0.04 — the conversion did NOT come
from naming. It came from a re-rolled trajectory under the same
mis-read the record's zero carried.

TIER (a) FAILED, AND THE FAILURE IS NOW A MEASUREMENT: 0/10
human-held games collapse onto a mercy-bearing hypothesis. Reads
still scatter (sloppy x6 at 0.54-0.99, sloppy-mild x4 at
0.79-0.95), two games never collapse at all (g05/g07, c@0 — and
exactly those two show the mercy family's best mass, 0.27 and 0.11:
the tug-of-war is visible but never won). The mechanism is priced,
with one honest caveat: the two fitted points vary GLOBAL scale,
not mercy alone (_scaled halves the structure too), so the failure
cannot be attributed to the mercy value in isolation. What is
measured is that neither the corpus point nor its half-scale beats
the sloppy family on this stream — the rare lapse evidence (~700x
per observed off-model move) loses to the mass the mercy component
tithes from the structured moves that are ~95% of it. Scaling
further down would weaken structure further, chasing the confound;
and a mercy-0.05 point is the held-out value, the anchor the
protocol forbids. The legal paths forward are named: a richer live
corpus (more first-party games, milder players), or a CONTROLLED
MERCY LADDER — structure held at the corpus fit, mercy varied and
scored on corpus NLL — so the axis is finally moved in isolation
with every value still corpus-traced. Until then the modeling
confound on human-held STANDS — with one side newly bounded:
assembly there is possible even under the mis-read (g01 proves it),
so the wall is not assembly-behind-modeling; it is modeling alone,
plus construction variance.

AND THE MERCY FAMILY PROVED ITSELF AS MACHINERY — ON THE SET'S
NEAREST PROXY FOR NOISE: random reads fitted-human x9 +
fitted-human-mild x1, the first MAP collapses onto the new family
on the record. Read the claim precisely: a closed-set MAP at 1.00
names the best point IN THE SET, and no hypothesis is actually
random (mercy 1.0, structure zero) — fitted-human, mercy .70 with
real structure retained, is STANDING IN for noise exactly as
sloppy-mild did in the posterior-map pin, one large step closer on
the one axis that matters. A conservative, misspecified proxy, and
the offer diagnosis below survives the misspecification in the safe
direction: the proxy UNDER-prices true acceptance. Under that
belief the engine's play transformed: it stopped building and
started OFFERING. Seven of ten random games end in mercy mates
(70-97 plies mostly — the fastest anything has ever ended against
random), zero by force, three walls: believed P(take) of 0.7/L per
offer, true 1/L, offers cash faster than construction converts —
and more often than the engine expects, never less. The engine got
mated in 7/10 games against noise — the best mated-at-all rate ever
recorded on that row — and the forced column reads 0%, because
every one of those mates is ledgered as the luck it is. The zero
MOVED: worst held-out is now random (0%), human-held is off it.
This is not a modeling error the posterior could fix from inside
the set (fitted-human IS its closest point to noise); it is the
OBJECTIVE/METRIC SPLIT made visible for the first time: expectimax
maximizes P(mated), the record counts only P(mated by force), and
mercy-bearing beliefs are what let luck be purchased at all. The
queued value-plumbing lever now has a second mandate from the
opposite direction: distinguish certificate value from chance-mass
value in the search itself, so forced nets outbid coin-flip offers
when both are live.

The rest of the ledger holds or reproduces: sloppy-held 2/10 (g03
IS the 53-ply record game, reproduced to the ply; g02 converts in
72 at map sloppy@0.89 c@0 — a conversion under partial collapse),
squat-held's pair survives the prior change bit-for-bit (g01 169
plies, g02 156, the corner tomb and the double-donation crossfire,
both still read squat-greedy-q@1.00), dev 4/30 as the arm measured.
Cost of record: 93.7s/game solo, 109 min the full league — 44%
CHEAPER than posterior-ext's 166.1, because offer-games end early
and nothing pathological ran: node-cap clamps fell 38,795 -> 13,912
(21 games touched, the largest human-held g00 at 3,621 — no
counterpart to the ext pin's 25,687-entry single-game blowup; the
backstop still works, it just had less to stop). Sub-probes: 41
hits / 37.3M calls, unk 98.7% — the extension keeps the certifier
starved, unchanged.

TABLES OF RECORD: posterior-ext REMAINS the table of record
(held-out 6/40 > 5/40; overall 12/70 > 9/70). posterior-mercy is
pinned as the MERCY-FAMILY record: the growth's config,
diagnostics, and trophies are citable from its report alone. The
grown set STAYS in the a9 defaults — so defaults no longer
regenerate the record tables (the record is a 2.0.0a7/a8 artifact
and regenerates from those commits) — for the project's own
reasons: the posterior program's premise is that beliefs must be
earned from evidence, and un-shipping a family whose beliefs are
EARNED (random 10/10, the first true mercy reads on the record)
because an honest belief loses a forced-only accounting would be
belief-falsification for score, the exact sin the phantom-net entry
prosecuted in the other direction. Dev is rate-neutral by direct
A/B; the naming capability is load-bearing for the live bar (the
corpus fit measures a large mercy-shaped noise component in real
human play — whatever mix of true lapses and unmodeled structure it
contains, only a mercy-bearing hypothesis can represent it, and the
target opponent is exactly that kind of human).

Queue, forced by the split verdict: VALUE PLUMBING first, doubly
mandated (dev squat still walls 9/10 with correct beliefs and sub=0
— the standing mandate — and the random row now shows chance-mass
EV outbidding certificate-bearing construction — the new one);
HUMAN-HELD NAMING second, by legal means only (grow the corpus, or
build the controlled mercy ladder on it; never a held-out anchor);
selective depth stays shipped, deep roots stay benched. Milestones stand at
60/80/90% held-out; the live bar stays "the corner poses and the
mate lands BY FORCE against a human" — and the session's exhibit is
that human-held's first-ever forced mate is exactly that shape,
landed while the family it was built to name still cannot be
named.

### Mercy-pin review round: the rung is a scale, the residue is not a lapse rate, and random is named by proxy (2026-07-24)

Four findings on the pin accepted; no engine behavior changes,
version stays a9 (comments and log prose only — trajectories,
reports, and regeneration untouched, per the precedent that version
bumps are for code that moves play).

- THE MILD POINT IS A GLOBAL SCALE, NOT A MERCY RUNG (P2, real):
  _scaled halves every continuous urge, so fitted-human-mild is a
  globally milder human — the sloppy-mild precedent applied
  literally — and the entry's diagnosis had attributed the
  human-held naming failure to the mercy values (.70/.35) as if the
  axis had been varied in isolation. It was not; the two points vary
  overall scale. Comment and entry now say so, and the queue's legal
  path sharpens into the CONTROLLED MERCY LADDER: structure held at
  the corpus fit, mercy varied and scored on corpus NLL — the axis
  moved alone, every value still corpus-traced.
- MERCY .70 IS RESIDUE, NOT A LAPSE RATE (P2, real): the fit
  supports a 70% uniform-over-legal component inside this family —
  the a6 entry's own misspecification reading — not a claim that a
  human abandons mate-avoidance seven moves in ten. Avoidable mates
  are merely the move class only that component can explain.
  Docstring and entry rephrased to keep the interpretation.
- RANDOM IS NAMED BY PROXY (P2, real): a closed-set MAP at 1.00
  names the best point in the set, and no hypothesis is truly
  random — fitted-human (mercy .70, structure retained) stands in
  for noise as sloppy-mild did in the posterior-map pin, one large
  step closer on the mercy axis. The offer-vs-forced diagnosis
  survives unchanged, in the safe direction: the proxy UNDER-prices
  true acceptance (0.7/L believed, 1/L true), so offers cash more
  often than the engine expects, never less.
- THE ZERO-CLAMP CLAIM WAS A TOOLING BUG, NOT THE REPORT'S (P3,
  real): the entry claimed the node cap never fired; report.json
  says 13,912 clamped entries across 21 games, the largest
  human-held g00 at 3,621 — down from the ext pin's 38,795 with its
  25,687-entry single-game blowup, so the honest sentence is
  "substantially less to stop", not "nothing". The zero came from
  session tooling summing a gauge key that does not exist
  (node_cap_clamped for clamped_nodes) — the pinned report was
  right all along, and the artifact policy is why the error was
  catchable: the claim was checkable from report.json alone, and
  that is exactly how review caught it.

## The mercy ladder: the axis moves alone, random climbs to the top rung, and the board loses its last zero (2026-07-24)

The review round's named construction went in whole: a CONTROLLED
MERCY LADDER on the corpus fit, replacing fitted-human-mild's global
half-scale — the point whose review proved the human-held naming
failure could never be attributed to the mercy value in isolation,
because _scaled halved the structure along with it. What landed
(2.0.0a9 -> 2.0.0a10, selftest 57 -> 59):

- models/posterior.py: five rungs, one rule. Structure is held at
  the corpus fit verbatim (greed .95, trade .45, hunt .90, push
  .30, promote .10, check 0.0) and mercy descends by SUCCESSIVE
  HALVING from the fit's .70 residue: .70 (fitted-human itself,
  kept), .35, .175, .0875, .04375 — rung k is .70/2^k, exact in
  floats, and the suite asserts the spacing and the frozen
  structure field for field. The rule is the legality argument: no
  rung was chosen because a held-out family uses a value; the
  bottom rung lands near the held-out mercy point the protocol
  forbids as an anchor, and that is the halving's doing, said here
  preemptively. Corpus NLL scored every adjacent pair before the
  set was accepted (768 observations, the eight Iptychs games):

  ```
  mercy .70      1443.25 total  1.8792/move
  mercy .35      1514.18        1.9716   (+70.9)
  mercy .175     1618.56        2.1075   (+104.4)
  mercy .0875    1719.02        2.2383   (+100.5)
  mercy .04375   1804.67        2.3498   (+85.7)
  (next .021875  1872.44        2.4381   (+67.8) — not adopted)
  ```

  Every gap is tens of nats: the corpus discriminates every
  adjacent pair, so the declared ~5-rung cap stops the descent, not
  the data. The ladder is ONE human family under the
  family-balanced prior: belief=sloppy opens 0.5625 / 0.0625 /
  0.125 / 4x0.03125 / 5x0.025, asserted to the digit in-suite —
  and, load-bearing for everything below, NO other family's prior
  moves: the ladder repartitions only the human family's interior.

- The fit reconciliation, for the record: rescoring exposed that
  FITTED_HUMAN (1.8792/move above) is the corpus MLE restricted to
  the seven axes the fitter entry recorded. The full 2026-07-23
  descent endpoint — re-derived deterministically this session —
  also carried home=.25 (queen-side) and the pawn hostage, at
  1423.95 total = the recorded 1.8541/move exactly. The ladder
  inherits the seven-axis restriction deliberately: it extends the
  in-set point (consistency is what makes rung comparisons clean),
  and the dropped axes are squat-shaped behaviors the set already
  prices in the squat family. .0251/move is the restriction's
  measured cost.

- Selftest 57 -> 59, the ladder's contract in-suite: rung spacing
  IS the declared rule (writing .70 back into any rung must
  reproduce FITTED_HUMAN field for field); the prior vector to the
  digit; the accident-fixture mate still names the mercy family at
  0.97 — MAP inside the family moves to m35, one lapse in two
  observations being ladder arithmetic, so the check pins the
  FAMILY claim and lets the rung float; NEW, the naming the mercy
  pin could not even express: a synthetic stream structured nine
  observations in ten, accepting an avoidable mate on the tenth
  (twenty cycles, 200 observations, lapse rate exactly .10),
  point-collapses on fitted-human-m0875@0.97 (collapse@158) — a
  LOW rung named over both the .70 residue and every mercy-free
  hypothesis; and the march fixture still collapses squat-k@0.9986
  with the whole ladder at 1e-4 — kernel reads unblurred.

DEV CONTROL: THE GATE HELD WITHOUT AN A/B, AND THE ONE DIVERGENCE
HAS A MECHANISM. The dev arm (zach/sloppy/squat, 10 games, baseline
seeds, a10 defaults; artifacts dev-infer-ladder/, untracked) came
back 4/30 forced — the mercy pin's number exactly, row for row —
with naming still perfect: every game MAPs its true family, squat
10/10 point-collapsed at bit-identical plies. The offline
divergence replay (tooling validated first by reproducing all 70 of
the mercy pin's posterior gauges from its PGNs alone) found 29/30
games BIT-IDENTICAL to the pin — the mercy pin's growth re-rolled
8 games by repartitioning zach's prior; the ladder re-rolled one,
because no family-level prior moved. The exception broke a record
worth breaking: in sloppy g08, fitted-human-m0875 TOOK MAP at
observation 25 — the first mercy-family MAP on a dev stream ever —
held it for 75 plies, and the re-rolled game's evidence put sloppy
back on top (final read sloppy@0.44, uncollapsed; outcome class
unchanged, max-plies; the other 29 games carry zero ladder-MAP
plies). The anatomy is one sentence: that stream is a
capture-starved king-walk, hunting king steps are priced at 2-3x
sloppy's shuffle share by the fit's hunt=.90, and a low rung tithes
only .0875 of that structure to uniform — twenty-five such
observations ground down the anchor's 22.5x head start. The old
points could never do this (fitted-human tithes 70%; the mild
point halved hunt along with mercy): the ladder's low rungs sit
nearer the kernels in behavior space BY DESIGN, and the cost of
moving mercy alone is now measured — one transient mis-MAP in
thirty games, self-corrected, aggregate unmoved. Collapse gauges
also shift on bit-identical streams (the denominator effect):
sloppy g04's short stream ends sloppy@0.62 c@0 on the pin's exact
moves because five structure-strong rungs retain mass where two
diluted points died, and zach point-collapses EARLIER for the
mirrored reason. MAP is what steers, and MAP moved in one game;
the gauge is set-relative, the argmax mostly is not.

### Pinned league (2026-07-24, engine model, posterior-ladder)

a10 defaults, no flags (the posterior-ext config over the
twelve-hypothesis ladder set; prior rule and per-hypothesis priors
in the report's engine block); 10 games/family; artifacts:
games/league/posterior-ladder/. Dev rows are bit-identical to the
dev-infer-ladder arm across the mount/bake boundary, 30/30 — the
arm and the pin are one experiment, again. Against the mercy pin's
league, 60/70 games reproduce to the byte (squat-held 10/10 for a
third consecutive pin); all ten re-rolls trace to the ladder.

```
family       split      n  forced mercy st-them st-us insuf fifty rep maxply
sloppy       dev       10       0     0       0     1     1     0   0      8
squat        dev       10       1     0       0     0     0     0   0      9
zach         dev       10       3     0       0     0     0     0   0      7
human-held   held-out  10       1     0       0     0     0     0   0      9
random       held-out  10       1     5       0     0     0     0   0      4
sloppy-held  held-out  10       2     0       0     0     3     0   0      5
squat-held   held-out  10       2     0       0     0     0     0   0      8
forced — held-out: 6/40 (15%); dev: 4/30 (13%); overall: 10/70 (14%)
worst held-out: human-held and random, 10% — the first board with
no zero row in the project's history
```

THE TIERED VERDICT: (a) SPLIT AND THE SPLIT IS THE MEASUREMENT,
(b) YES BY REPRODUCTION, (c) TIED, NOT RETAKEN.

TIER (a), RANDOM'S HALF: THE LADDER SEPARATES NOISE UPWARD. Random
reads fitted-human — the TOP rung — in 10/10 games, and for the
first time COLLAPSES in 10/10 (>=0.9736, seven at 0.999+, c@6-29;
the mercy pin collapsed 4/10 with one game on the mild point). The
named-by-proxy caveat was testable and the test ran: a stream that
truly wants mercy 1.0 should reject every lower rung and take the
highest available, and it did, ten times, hard — while human-held
(below) took none. The ceiling is the top rung by construction
(the declared rule only descends from .70), so "climbs above
fitted-human" was never satisfiable; what is measured is the
DIRECTION: random rejected the entire ladder below the residue,
confirming the misspecification points up toward 1.0, and the
proxy still under-prices true acceptance in the safe direction.

TIER (a), HUMAN-HELD'S HALF: THE TESTED AXIS IS CLOSED, AND THE
CONFOUND HAS A SMALLER NAME. 0/10 human-held games collapse onto a
mercy rung — the same census as the pin (sloppy x6 at 0.66-0.99,
sloppy-mild x4 at 0.79-0.98, now 9/10 collapsed with only g05
never settling). But this failure MEASURES something the pin's
could not: the review round showed the old points varied global
scale, so no statement about mercy was separable; the ladder varied
mercy ALONE at full corpus structure, and every rung from .70 down
to .04375 loses to the sloppy family on these streams.

Stated at exactly the width of the evidence: FIVE declared values
spanning a 16x range were tested, with the descent stopped by a
declared cap rather than by data, so what is closed is the declared
ladder — not the continuum. Values between rungs and below .04375
were never scored on these streams, and the honest reason no finer
grid was run is that the direct measurement is PROTOCOL-FORBIDDEN:
fitting mercy to human-held games would make every future rung an
anchor read off a held-out family, the one thing the ladder was
built to avoid. What the pinned report does license (already-
collected weights, no new fitting) is the SHAPE of the loss, and
it is informative: mean mercy-family mass per rung across the ten
human-held games runs .0079 / .0119 / .0058 / .0031 / .0020 from
.70 down — a DESCRIPTIVE average, not a Bayes factor, and read only
for its SHAPE: unimodal with an INTERIOR maximum at m35, declining
in both directions, so the untested region that could matter is the
.70-.175 bracket rather than the tail. The peak rung's 1.19% mean
mass sits ~80x under the 0.95 naming bar (1.9 orders in mass) —
and because averaging ten posteriors is not evidence arithmetic,
the size of the miss is quoted per game in the unit that IS well
defined. Posterior odds equal prior odds times likelihood ratio, so
the factor a rung must gain over a game's own stream to reach odds
19 is exactly its odds gap:

```
game  best rung   weight    obs  odds gap   short by (nats)  /obs
g00   m35         8.0e-04    89  2.4e+04    10.1             0.113
g01   fitted-.70  6.9e-03    44  2.7e+03     7.9             0.180
g02   m35         6.9e-08   119  2.8e+08    19.4             0.163
g03   fitted-.70  2.9e-04    69  6.6e+04    11.1             0.161
g04   m35         8.2e-03    89  2.3e+03     7.7             0.087
g05   m35         9.1e-02    54  1.9e+02     5.2             0.097
g06   fitted-.70  7.4e-05    89  2.6e+05    12.5             0.140
g07   m35         7.5e-03    59  2.5e+03     7.8             0.133
g08   m35         6.7e-03    30  2.8e+03     7.9             0.265
g09   m35         2.0e-03    43  9.4e+03     9.1             0.213
odds gap: median 9.4e+03, min 1.9e+02 (g05), max 2.8e+08
per-observation shortfall: median 0.161 nats, range 0.087-0.265
```

The total gaps span six orders because streams differ in length —
which is precisely why an average of them says little. The stable
quantity is the RATE: the best tested rung trails by ~0.09-0.27
nats per observation, median 0.16, in every single game. That rate
is the number with teeth, because it is directly comparable to what
the mercy axis can BUY: one halving step is worth .09-.14 nats/move
on the corpus. So the missing likelihood is one to two rung-steps
in MAGNITUDE but unavailable in DIRECTION — moving along the axis
past m35 made things worse, not better, in all ten games. Random's
profile is the mirror image (.9971 on the top rung, ~0 below) — the
two held-out streams are cleanly distinguishable on this axis,
which is the capability the ladder did buy.

What remains most likely is the STRUCTURE: the corpus fit is one
player's temperament (greed .95, hunt .90, the Iptychs games), and
human-held's structured moves evidently do not match it closely
enough for the mercy dial to compensate anywhere on the tested
grid. So the confound shrank from "mercy value, global scale, or
structure?" to structure-plus-an-80x-gap — and the PRIMARY legal
lever is the one the queue already names: grow the corpus (more
first-party games, milder players) until the fitted structure
stops being one person's. A finer or wider mercy rule stays legal
in principle, but only if its values trace to a declared rule and
the corpus and are NOT steered by the numbers above; that needle
is narrow enough that corpus growth is the path this queue
commits to. One leakage in the other direction, priced honestly:
sloppy-held g07 ends on fitted-human-m35@0.48 uncollapsed (the dev
g08 mechanism on a held-out stream; outcome class unchanged, row
still 2/10 with both trophies byte-identical).

TIER (b): human-held g01 reproduces BYTE FOR BYTE — the
pawn-executioner shell, 103 plies, 52.f7# — still under the
sloppy-mild mis-read (0.9766 now, c@8; the weight shift on
identical moves is the denominator effect). Off zero again, by
reproduction rather than construction; a conversion under a
correct read remains unclaimed, and after this pin the honest
prediction is that it waits on the corpus, not the ladder.

TIER (c), AND THE HEADLINE NOBODY TIERED: held-out forced is 6/40
— TIES posterior-ext's record, does not retake it (ext keeps
overall, 12/70 vs 10/70). But the zero moved OFF the board
entirely: random g05 (89 plies, engine Black, 3 oracle
certificates) is the first FORCED selfmate ever landed against
noise — 43...Qc6+ forces bxc6, 44...Bb6 leaves cxd7# as White's
only legal move: a certificate net, valid against ANY reply,
built while the posterior read the top rung at 0.97. The
forced-vs-offers ledger (the objective/metric split's third data
point): mercy mates 7 -> 5, forced 0 -> 1, max-plies 3 -> 4. The
sharpened 10/10 collapse bought one certificate and gave back two
offers — the first time the trade ran TOWARD the metric — and the
value-plumbing mandate stands with its first existence proof that
forced nets CAN outbid coin-flip offers when search finds them.

TABLES OF RECORD, THREE READINGS STATED PLAINLY: posterior-ext
keeps the overall count (12/70 > 10/70). The held-out count is
TIED at 6/40. And on the metric this log privileged from the a1
protocol forward — the WORST held-out row, because an average can
hide exactly the family you cannot beat — posterior-ladder is the
best table ever pinned: worst row 10% against a 0% somewhere in
every predecessor. The ladder set STAYS in the a10 defaults, by
the same belief-earning logic as the mercy pin: random's 10/10
top-rung collapse is the strongest naming on the record, dev is
rate-neutral with 29/30 bit-identity, and the conversions the old
set earned reproduce byte for byte under the new one.

Cost of record: 94.3s/game solo, 110 min the league — the mercy
pin's cost within noise (93.7/109), and 43% under posterior-ext's
166.1, offer-games still ending early. Node-cap clamps 13,055
entries across 22 games, largest human-held g00 at 3,621 (the pin
had 13,912/21/3,621 — that largest game reproduced exactly).
Sub-probes: 41 hits / 38.8M calls, unk 98.8% — the certifier stays
starved, unchanged three pins running.

Queue, sharpened by the split verdict: VALUE PLUMBING first,
standing on both mandates plus g05's existence proof (dev squat
still walls 9/10 with correct beliefs and sub=0; random still
cashes five coins for one certificate); CORPUS GROWTH second and
the committed path for human-held naming — the declared ladder
closed the mercy axis as tested, the previous review round closed
the scale axis, and what is left is more humans in the fit, by
legal means only (first-party games; never a held-out anchor).
Selective depth stays shipped, deep roots stay benched. Milestones
stand at 60/80/90% held-out; the live bar stays "the corner poses
and the mate lands BY FORCE against a human" — and the record now
holds two shapes of proof that the machinery can do it: the
reproduced f7# shell against the human family, and the first
certificate net cashed against pure noise.

### Ladder-pin review round: the closed axis is the tested grid, the fitted constant is a restriction, and the gap gets its units (2026-07-24)

Four findings on the pin accepted across two passes; no engine
behavior changes,
version stays a10 (comments and log prose only — trajectories,
reports, and regeneration untouched, per the precedent that version
bumps are for code that moves play).

- THE CONCLUSION OVERRAN THE GRID (P2, real): the entry had claimed
  the mercy VALUE exonerated with "no setting of that dial" naming
  human-held, and STRUCTURE ALONE remaining. Five discrete values
  with a declared (non-data) stop cannot support either: the
  continuum between rungs and below .04375 was never scored. The
  verdict is narrowed to the declared ladder, and the narrowing is
  paid for with already-collected report weights rather than new
  fitting — mean mercy mass per rung on the ten human-held games
  runs .0079/.0119/.0058/.0031/.0020 from .70 down, read for shape
  only: unimodal with an INTERIOR maximum at m35, so the untested
  region that could matter is the .70-.175 bracket, not the tail.
  The protocol point that makes this the right
  stopping place is now stated where the claim is: fitting mercy to
  human-held streams would turn every future rung into a held-out
  anchor, so refinement can never be STEERED by these numbers —
  which is why corpus growth is the committed lever rather than the
  merely-preferred one. The size of the miss is requantified in the
  unit that survives scrutiny (a second review pass caught the first
  attempt mixing 80x-in-mass with "three orders" and treating an
  average of ten posteriors as evidence arithmetic): per-game
  posterior-odds gaps, median 9.4e3, min 1.9e2, max 2.8e8 — six
  orders of spread, so their mean was never the story — whose
  stable rate is 0.09-0.27 nats/observation, median 0.16, against
  the .09-.14 nats/move one halving step buys on the corpus. One to
  two rung-steps in size, wrong direction.
- THE FITTED CONSTANT IS A SEVEN-AXIS RESTRICTION (P2, real): the
  FITTED_HUMAN comment attributed 1.8541 nats/move to a point that
  scores 1.8792. The full 2026-07-23 endpoint also carried home=.25,
  queen-side homing, and pawn_last=True — the entry above recorded
  the reconciliation, but the foundational comment kept the old
  attribution, exactly the place a future session would read it from.
  The comment now states the restriction, both scores, the
  .0251/move cost, why the restriction is deliberate (dropped axes
  are squat-shaped; every rung must extend ONE structure), and warns
  against treating the constant as the unrestricted MLE.
- THE SYNTHETIC RATE WAS MISSTATED (P3, real): the new suite check's
  loop records nine structured observations then one mate — 9/10
  structured, lapse rate .10 — while its comment said "nineteen
  moves in twenty" alongside the correct "once per ten", and the
  entry repeated the contradiction. The m0875 collapse is consistent
  with the implemented .10, so this was prose, not code: both now
  say nine-in-ten with the cycle count and total spelled out.

## The reach verdict: nothing was missed, the rungs that pay are cheap, and the queue's first item loses its mechanism (2026-07-24)

A pure replay diagnostic — no engine or CLI code, so no version bump
(stays 2.0.0a10, selftest 59/59 green before and after). The question
was declared before anything ran: when the engine found no
certificate, was one THERE? Tooling lives in games/league/dev-reach/,
untracked wholesale by the artifact policy, and it touches no belief
and no held-out parameter — the oracle is opponent-free by
construction, which is what made this the cleanest experiment
available on held-out boards.

FIRST, THE QUEUE CORRECTION THE PIN'S OWN REPORT DEMANDED. The ladder
pin listed VALUE PLUMBING first, on the mechanism that "forced nets
CAN outbid coin-flip offers when search finds them" — g05 as its
existence proof. Cross-tabbing all 70 games of the pinned report
kills the mechanism: the population is empty. Ten games logged at
least one oracle certificate and ALL TEN converted forced; the five
mercy mates found ZERO certificates ever, and so did all fifty
max-plies games, the four insufficient-material draws and the one
stalemate-us. In every game oracle_moves equals
forced_selfmates_found, so a certificate was ALWAYS played the ply it
was proven. A certificate has never lost to an offer, because the two
have never been on the board at the same time. Whatever g05 proves,
it is not that forced nets outbid offers — it is that the two
outcomes come from disjoint positions.

THE INSTRUMENT, VALIDATED BEFORE IT WAS BELIEVED (the mercy-pin
review round's lesson about session tooling summing a key that does
not exist): the replay walks each pinned PGN, and at every position
where the engine actually DECIDED — lone legal moves are excluded,
because choose_move returns those without probing — re-runs
engine._probe verbatim, fresh memo per decision, one budget shared
across the n ladder. Run against the ten games whose report says
certificates fired, it re-derived all 22 from the PGNs alone: right
count per game, right ply, and the proving move identical to the move
played in all 22. Only then was it pointed at the walls.

THE SWEEP, AND IT IS EMPTY. All sixteen named targets, full coverage,
nothing skipped: the five random mercy mates, the nine squat dev
walls, and the three near-misses where sub-probes hit but no root
certificate resulted. 1,600 decisions, each probed at the SHIPPED
budget (n<=4, cap 50k) and at a FAT one (n<=5, cap 500k):

```
arm      exhausted        verdicts                     died at n=
shipped  1582/1600 98.9%  unknown 1582, disproven 18   n3 1301, n4 299
fat      1592/1600 99.5%  unknown 1592, disproven  8   n4 1485, n5 92
MISSED CERTIFICATES: 0 — in every game, at every decision
```

Read the second row before the first conclusion. The fat arm found
nothing AND WAS ITSELF UNKNOWN on 99.5% of decisions, having spent
798.5M nodes. That is not evidence of absence; UNKNOWN is not
DISPROVEN, and the instrument is bound by the oracle's own contract
exactly as the engine is. Worse, the fat arm is LESS definitive than
the shipped one: deepening probe_n without funding it proportionally
moved the death rung one deeper and cut definitive answers from 18 to
8. So the declared criterion's second branch — "the fat budget finds
nothing either, therefore those positions were net-poor" — could not
be licensed by the experiment as designed. A third outcome the
criterion did not declare had occurred: both arms too weak to decide.
Named here so no future session re-runs a bigger version of it.

THE INSTRUMENT THAT DOES TERMINATE. What settles it is the cost of a
FULL resolution: per position, each n run alone, fresh budget, fresh
memo, a ceiling high enough to finish. 24 positions (tail-40 samples
from seven games across four families):

```
n     resolved      median nodes    vs shipped cap 50k
1       24/24                 63
2       24/24              2,056
3       24/24             65,998    132% — the cap cannot finish it
4       23/24          2,044,599    41x the cap
5        3/24          8,338,458
step ratio n=4/n=3: x33.3
n=4 outcome: DISPROVEN 23, unknown 1 — not one certificate
```

THE VERDICT IS NOT REACH. At the probe's OWN ADVERTISED DEPTH the
positions are genuinely net-poor, proven definitively rather than
inferred from a starved instrument: fully funding n=4 would cost 41x
the shipped cap and return DISPROVEN on 23 of 24 sampled positions.
The certificates are not there to be missed. The declared criterion's
second branch fires — the engine steered wrong EARLIER — but it is
the escalation that licenses it, not the fat sweep.

AND THE RUNGS THAT PAY ARE THE CHEAP ONES. Every certificate the
project has ever landed, by proof depth:

```
n=1  10 (45%)     n=3   3 (14%)
n=2   8 (36%)     n=4   1 ( 5%)
median nodes to FIND one: 194;  worst: 49,559;  all under the cap
```

81% of the record is n<=2, at a median of 194 nodes. The engine
spends 46,996 nodes per decision — 94% of its cap — reaching for an
n=3 whose median cost it cannot cover, and the n>=3 rungs have
produced four certificates in the project's history. This is the
starvation diagnosis inverted: the certifier is not starved of
budget, it is over-funded on rungs that hold nothing and correctly
funded on the two that hold everything.

THE BUDGETS ARE ALLOCATED BACKWARDS FROM WHERE THEY BIND, which
answers the two subsidiary questions the lever posed:

```
layer        nodes/decision       cap     saturation
root probe           46,996    50,000        94%
sub probes           71,091   100,000        71%
steering             16,671   400,000         4%
```

Node-cap clamps are NOT binding — 13,055 entries is 1.84 per decision
against 16,671 search nodes, 0.01%; steering has 24x headroom it has
never used. And the sub-probe's 98.8% unknown has a one-line
mechanism: 38.8M calls spent 504M nodes, which is 13.01 NODES PER
CALL against the 2,056 the cheapest useful proof (n=2) costs. The
100k cap splits across ~30 root branches, so a branch share of ~3,333
funds about one n=2 proof and then answers UNKNOWN for the ~180
remaining gated calls in its subtree. 1.15% of calls ever returned a
definitive answer. The layer is not mis-tuned; it is funded at under
1% of the price of its own cheapest possible answer.

THE SHAPE LEVER, PRICED BUT NOT BUILT. The ~33x per rung is our
OR-node width: the proof tries all ~30 own moves while the opponent
AND-node below usually bails on its first refutation. A prototype
certifier restricting our nodes to the most FORCING moves (fewest
replies, checks first) and leaving the opponent's node exhaustive —
sound but INCOMPLETE, so its failures return NOT_FOUND and never
DISPROVEN — reaches, at the SAME 50k cap: n=5 at width 8, n=6 at
width 5, n=7-9 at width 3. Two to six rungs deeper at constant price.
It found nothing on random_g00, which is what the exhaustive
DISPROVEN at n<=4 predicts, and its silence is weaker evidence than
the exhaustive arm's by construction. It is a diagnostic; nothing it
says has reached an engine or a league.

Queue, corrected and reordered by the verdict:

- VALUE PLUMBING loses its stated mechanism and keeps its slot with a
  new one. It was never a tiebreak between certificates and offers —
  that population is empty and always was. The measured population is
  the trajectory: 1,600 decisions in which no certificate existed
  within four own-moves, so the objective has to change where the
  engine GOES tens of plies earlier, not what it prefers at the
  moment a net appears. That is an OBJECTIVE change, as the lever
  declared, but it must price PROXIMITY to net-bearing structure, not
  certificates themselves — a categorical bonus on certificates would
  fire 22 times in 7,094 decisions and change nothing else.
- RE-BUDGET THE CERTIFIER, promoted to first because it is cheap,
  measured, and pays for the item above. The productive range is
  n<=2 at ~2k nodes; the ~45k per decision now spent failing to
  finish n=3 bought zero certificates in 1,600 decisions even at 10x.
  Reclaim it for steering, which runs at 4% of its own cap. Whether
  the freed budget is better spent as depth, as width, or on the
  forcing-restricted certifier above is the next graded arm.
- CORPUS GROWTH stays the committed path for human-held naming,
  unchanged and still blocked on collecting games from MORE PLAYERS
  (the corpus is eight games from one opponent) — not a dev-session
  task.
- Selective depth stays shipped, deep roots stay benched. Milestones
  stand at 60/80/90% held-out; the live bar stays "the corner poses
  and the mate lands BY FORCE against a human."

COST AND COVERAGE, HONESTLY. 878M nodes over the sweep (79.7M
shipped, 798.5M fat) plus the escalations; ~3.5 hours of detached
container time. The sweep covers 16 of 70 games and 1,600 of 7,094
decisions — the named targets in full, nothing skipped, and 54 games
NOT examined. The cost curve samples 24 positions from seven games
across four of seven families; sloppy-held, squat-held and zach were
never sampled for it, and the tail-40 sampling means the curve
describes late positions, where the pinned conversions actually
landed, not openings. One escalation container was SIGKILLed (exit
137) at position 19 by a Docker engine restart; it writes its JSON
only on completion, so its console log was rescued for the 18
positions already measured and the two interrupted games were re-run
separately — the 24 positions above are those two runs pooled, which
is why their ceilings differ (12M and 9M).

## Two provers, two budgets: the verdict nobody reads is free to give up (2026-07-25)

Version 2.0.0a11, selftest 69/69 (was 59/59; ten new checks). The
session's thesis rests on one claim the queue asked to be verified
rather than assumed, so that came first and everything else was built
on the answer.

THE CLAIM, VERIFIED TWO WAYS. Nothing in the engine consumes a
definitive negative: `_probe` branches on PROVEN and on budget
exhaustion, the sub-probe adds only UNKNOWN, and `search._node_value`
collapses every non-PROVEN answer to None (search.py:249 keeps only
`proven_n is not None`). Reading code is not evidence, so DISPROVEN
was MASKED to a status object the engine has never seen — at the
oracle's PUBLIC BOUNDARY only, leaving the recursion, the memo, the
pruning and the node spend bit-identical, so that only what the
engine is TOLD changed:

```
selftest   58/59 — the single failure is selftest.py:357, the oracle's
           OWN contract test, which asserts DISPROVEN directly. Every
           engine, search and league test passed.
play       zach/squat/sloppy/random, seed 0, 120 plies: identical
           plies, identical final FEN, identical certificate count in
           all four. The mask fired 16,568 times (3,324/4,891/6,075/
           2,278) — the experiment was not vacuous.
```

A definitive negative is worth nothing to this engine. Trading
completeness for reach costs nothing that was being spent.

ITEM 0 FIRST, BECAUSE IT GATED THE REST. The reach verdict's cost
curve never sampled sloppy-held, squat-held or zach — the families
that DO convert. Same escalation, each n alone, fresh budget, fresh
memo, 10M ceiling, tail-40; 23 positions across nine games:

```
family        n      runs  median nodes                  outcome
sloppy-held   1..4      9  12 / 94 / 768 / 5,915         DISPROVEN all
squat-held    1..4      9  55 / 1,421 / 35,849 / 894,297 DISPROVEN all
zach          1..3      5  111 / 5,960 / 326,523         DISPROVEN all
zach          4         4  10,000,000 (ceiling)          UNKNOWN
REACHABLE NETS AT ANY RUNG, ANY FAMILY: none
```

[Count note, third review round: this header's "23 positions" and
the zach rows above predate the outage forensics; the corrected
account in COST AND COVERAGE below — 24 of 27 planned, zach 6 of 9,
five runs reaching n=4 — was written with the rescued console logs
in hand and supersedes them where they disagree. No verdict moves:
every completed run is DISPROVEN except zach's n=4 UNKNOWNs.]

The verdict GENERALIZES and the re-budget can be global — with the
honesty the reach entry itself demanded: zach's n=4 is UNKNOWN at a
10M ceiling, NOT DISPROVEN. Three rungs are definitive in all three
families and the fourth in two of three. Nothing was found anywhere.

AND THE COST CURVE IS NOT UNIVERSAL — a correction to the reach entry.
Its tail-40 sample put n=4 at 2,044,599 nodes, 41x the shipped cap.
sloppy-held resolves n=4 at a median of 5,915 — TWELVE PERCENT of the
cap. On stripped families the shipped engine is already complete to
its advertised depth, and its silence there really is absence. "n=4
costs 41x the cap" describes the families sampled, not the layer.

THE CENSUS THAT REDESIGNED THE FEATURE. Every certificate the project
has landed, re-derived alone with a fresh budget:

```
n=1 x10  max     86 nodes      n=3 x3  4,311 / 11,898 / 45,282
n=2 x 8  max  1,254 nodes      n=4 x1  24,285
```

(Census prices are each n ALONE. In play the ladder pays the lower
rungs first, so the same trophy bills cumulatively — the 45,282
n=3 here is the 49,559 the engine docstring and the reach entry
cite: alone + n1/n2 spend. The bridge holds for all four deep
certs: 5,438=4,311+1,127; 13,945=11,898+2,047; 28,297=24,285+4,012;
49,559=45,282+4,277.)

THE DEAREST TROPHY IS AN n=3 FIND. A cheap exhaustive n<=2 phase does
NOT protect it, so any design funding a second prover out of
`probe_cap` spends money the first one provably needs. That was not
feared, it was MEASURED: the shared-budget hybrid (exhaustive n<=2,
then restricted n=3..8 at width 5, one 50k cap) was built, run, and
LOST ALL FOUR n>=3 FIRST-CERTIFICATES — random_g05 ply83 and
sloppy-held_g03 ply47 as first written, PLUS zach_g03 ply49 and
zach_g05 ply73 (hybrid-trophy-w5.json; each trio's later, shallower
certificates were still found) — for zero gains across the TEN wall
games in hybrid-walls-w5.json (five random, one each sloppy-held/
squat-held/zach, two squat). Rejected on its own evidence. [Third
review round: the entry had said "exactly the two deep trophies";
its own artifact says every deep first-cert died, which strengthens
the rejection it documents.]

WHAT SHIPPED: TWO PROVERS, TWO BUDGETS, THE SECOND ADDITIVE. The
exhaustive ladder is untouched — same order, same cap, same breaks —
so trophy safety is structural rather than hoped for. The
forcing-restricted ladder (`oracle.forcing_selfmate_status`) runs
afterwards on its OWN `probe_forcing_cap`, restricting our OR-node to
the `width` most forcing moves (fewest replies, checks first) while
leaving the opponent's AND-node EXHAUSTIVE, which is where soundness
lives. Sound but incomplete: its failures are NOT_FOUND, never
DISPROVEN.

THE TROPHY REGRESSION, AND IT GAINED. All 465 decisions of the ten
games that ever logged a certificate, both arms, 50k exhaustive cap
plus a 50k forcing cap:

```
shipped certificates  22/22 re-derived     LOSSES 0     UNSOUND 0
GAIN  zach_g05 ply71  f4f2 at n=4, found by the restriction and
      VERIFIED by the exhaustive prover at 647,381 nodes — 13x the
      shipped cap, which is exactly why the shipped engine is blind
      to it
root nodes/decision   47,853 -> 94,566
```

Read the gain precisely. zach_g05's recorded conversion runs plies
73/75/77; the restriction certifies at ply 71, TWO PLIES EARLIER. In
play that diverges the game, so the honest claim is not "a 23rd
trophy" but "one decision, in ten games, where the shipped engine
found nothing and the restriction returned a verified forced net
before the shipped conversion." One gain in 465 decisions.

AND IT IS AVAILABLE FOR LESS. The ply-71 net needs width 8 and 17,888
nodes; width 5 never finds it at any cap up to 50k. So
`probe_forcing_cap 20,000` at width 8 buys the same gain for +20k per
decision rather than +50k. The layer's price is set by what its one
conversion costs, not by the exhaustive cap it sits beside.

SOUNDNESS, ASSERTED RATHER THAN ARGUED. Three fixtures are enough to
catch a broken port and not enough to carry a claim the engine now
rests on, so a differential fuzz walked real corpus positions:

```
194 positions, widths 1..8 and 250, n<=3
  15 restricted certificates, ALL verified MOVE-LEVEL against the
     exhaustive prover (push it; every reply must mate us now or lose
     at n-1) — position-level agreement was not accepted
 174 exact agreements at an UNRESTRICTING width (>= the legal move
     count), where the restricted prover IS the exhaustive one
   0 unsound, 0 disagreements, and DISPROVEN returned 0 times, ever
```

A LABELLING BUG CAUGHT IN REVIEW, WHICH WOULD OTHERWISE HAVE SHIPPED.
When the budget died during the ordering pass, `_forcing_order`
returned an empty candidate list, the OR-node fell through to
DISPROVEN and the public entry to NOT_FOUND — a starved node claiming
absence, the exact sin the UNKNOWN distinction exists to prevent. The
ordering pass now reports truncation and such a node owes UNKNOWN;
the selftest asserts it at budgets 0, 1, 4 and 20.

THE SELFTEST ADDITIONS (the suite is the gate), ten checks: soundness
move-level on all three fixtures; NEVER returns DISPROVEN; NOT_FOUND
vs UNKNOWN vs DISPROVEN kept three distinct answers; a shared memo
cannot leak a restriction-tainted refutation (restricted keys are
width-tagged, so sharing is SAFE rather than merely discouraged);
per-layer budget accounting bounded by each layer's own cap with the
two root provers ledgered apart; the layer inert unless all three of
its knobs are set; and THE DEPTH CLAIM PINNED AS A CONVERSION rather
than a reach — `DEEP_FIXTURE` is zach_g05 ply73, where at a SHARED cap
of 3,000 the exhaustive prover is UNKNOWN and the restriction returns
f7f6 at n=3, confirmed move-level. The reach entry warned that
climbing further is not the same as bringing something back; this
fixture pins the latter.

ITEM 1, RE-MEASURED — AND THE STATED MECHANISM IS NOT THE WASTE. From
the pinned report, 70 games / 7,094 decisions:

```
layer        nodes/decision       cap   saturation   share
root probe           46,996    50,000         94%    34.9%
sub probes           71,091   100,000         71%    52.8%
steering             16,671   400,000          4%    12.4%

sub_probe_hits ACROSS THE ENTIRE LEAGUE: 41
38,760,792 calls; 504,319,626 nodes; 12.3M nodes per hit
```

The "13.01 nodes per call" is real but is not where the money goes: a
dry branch share returns UNKNOWN at ZERO node cost, so the futile
calls are FREE. The 504M was spent by the 1.15% of calls that ran to a
definitive answer — about 446,021 of them, of which 41 were PROVEN.
The layer's actual bill is ~445,980 REFUTATIONS the search discards.
Same disease as the root probe, one layer down, and it reframes the
fix: not "fund the branch shares better" but "stop buying the verdict
nobody reads."

The caution against gutting it, stated because the cross-tab invites
it: 8 of 10 forced conversions had sub-probe hits against 3 of 60
non-converting games — but the gate opens on stripped positions, which
is also where conversions happen, so the association is confounded by
reaching an endgame at all. Two conversions (zach_g05 and random_g05,
three certificates each) had ZERO sub-probe hits. Hence measured arms
rather than an assumption.

CODE DOES NOT CHANGE PLAY, AND THE GATE SAYS SO. Every new knob
defaults off, and the check is byte-level: the same four games
replayed under the current source are IDENTICAL to unmodified main. No
pinned league is owed for the code itself; one is owed only if a
CONFIG change ships, and that decision waits on the arms.

READABLE ALLOCATION, so no future session re-derives it by hand. The
league report now carries a `layers` block and prints one line per
run: nodes per decision and share, per layer, against each layer's own
cap. The reach verdict had to rebuild that split from a pinned report
before it could see the budgets were backwards.

COST AND COVERAGE, HONESTLY. The escalation covers 24 of 27 PLANNED
positions across nine games and three families, tail-40, sample 3 per
game: sloppy-held and squat-held are complete at 9 positions each,
zach contributed 6 of 9 before its container was SIGKILLed (exit 137)
at position 24, and zach's n=4 is UNKNOWN at the 10M ceiling in all
five runs that reached it. So the zach column is the thin one in both
senses — fewer positions AND the only unresolved rung — and a session
wanting zach's n=4 definitively must budget well past 10M for it. The
trophy regression covers all 465 decisions of the ten games that ever
converted. The wall sweeps that produced zero gains cover five random
games and are NOT a corpus-wide statement.

ITEM 1, ANSWERED FOR WHAT WAS TESTED: THE TWO NAMED KNOBS DO NOT
RECLAIM IT, AND ZERO FUNDING COSTS A TROPHY.
Four dev arms, all complete: zach/sloppy/squat, 10 games, baseline
seeds, one knob each. Arms A/B/C ran the BAKED image (unmodified
main); arm D needed the new `--sub-probe-slice` flag and so ran the
current source, which the byte-level identity check above shows plays
identically to main at defaults — the knob remains the only variable.

```
arm                     conversions   nodes/dec    root     sub   steer   sub hits
posterior-ladder (ref)   3/0/1 @70g     134,758  46,996  71,091  16,671        41
A base                   3/0/1          139,159  47,627  75,256  16,276        12
B sub_probe_men 4        3/0/1          135,521  47,627  71,618  16,276        10
C sub_probe_n 0 (OFF)    2/0/1           64,508  47,796       0  16,712         0
D sub_probe_slice 800    3/0/1          137,043  47,296  73,634  16,113        47
                                   (zach/sloppy/squat, 30 games each)
```

THE BASELINE GATE PASSES OUTRIGHT. Arm A reproduces posterior-ladder's
dev rows across all 30 games with ZERO divergences and zero
reconstruction mismatches — every belief trajectory rebuilds from the
observed move sequence alone. The protocol held and the arms are
comparable.

AND EVERY CANDIDATE FAILS, EACH IN ITS OWN WAY:

- OFF (C) is the only material saving — 53.6% of ALL node work — and
  it LOSES zach_g03. The confounded cross-tab could not settle whether
  the layer earns its 52.8%; this does. It earns it.
- TIGHTER GATE (B) saves 2.6% and changes NOTHING: zero divergences
  across 30 games, identical conversions. A free 2.6%, and 2.6% is not
  a re-budget.
- SMALLER SLICE (D) is the mechanism working exactly as designed and
  paying nothing. Hits go 12 -> 47, nearly FOUR TIMES, on 2% FEWER
  nodes: the slice does convert refutation-spend into finds, which is
  the whole thesis of this session applied one layer down. Four games
  diverge, every trajectory reconstructs (so the movement is the
  re-budget and not an inference regression) — and the conversions are
  identical. Four times the certificates, the same outcomes.

So the queue's premise was right about the SIZE of the waste, and the
two knobs it NAMED do not recover it: the gate saves 2.6%, the slice
2%, and the only material saving tested — deletion — costs a trophy.
WHAT THIS DOES NOT ESTABLISH, review round: irreducibility. These
three settings bracket nothing between them — no arm varied
`sub_probe_cap` itself, tried `sub_probe_n 1`, narrowed the gate to
checks only, or sampled any budget between zero and full, and zero
losing a trophy does not imply every partial budget does. On the
contrary, D is weak evidence AGAINST irreducibility: it showed hits
get CHEAPER when refutation-spend is starved, so a halved or
quartered cap keeping zach_g03 is a live possibility, not a settled
question. The five-arm sweep that settles it (cap 50k / 25k / 10k,
gate checks-only via men 0, n=1) is running as this is written; its
table is the addendum below.

Read D against the session's own thesis before calling it a failure.
Cutting the price of a refutation is what made the ROOT layer better
and it is exactly what D does to the SUB layer — 3.9x the certificates
for less money. It did not convert because sub-probe hits are steering
NUDGES, not claims: search.py:253 scores a proven node as a
near-terminal, and 47 nudges in 3,164 decisions moved four games'
trajectories without moving one outcome. That is a finding about what
the sub-probe layer is FOR, not about the slice.

NO PINNED LEAGUE, AND THAT IS THE PROTOCOL WORKING. The rule is one
pinned league if and only if code changed play. The code does not:
every new knob defaults off and the identity check is byte-level. No
config change earns one either — B changes no play, D changes play but
no outcome, C is rejected, and the forcing certifier's measured value
is one earlier conversion in 465 decisions at +20k nodes per decision.
Pinning any of these would spend hours to record a null. The success
tiers stand unclaimed and are named as such: not CHEAPER (2.6% is not
material), not DEEPER (the gain is n=4, and the tier asks n>=5), not
METRIC (held-out untouched; the arms were dev-only by protocol).

THE NEXT ARMS, DECLARED. Item 3's reallocation was never tested,
because it was gated on a reclamation these arms did not produce —
and whether one EXISTS is exactly what the cap sweep above will say.
Steering still sits at 4% of its own cap with clamps at 0.01%. The
honest next questions are (a) whether steering can be made to spend
its 24x headroom on its OWN account — raised depth/topk as their own
arm, priced against the 96% of its cap it never touches; and (b)
whether the sub-probe layer should be a FINDER rather than a prover
at all, since D shows finds are cheap and refutations are what the
layer actually buys — the cap sweep's 10k arm is a first crude cut of
exactly that. Both are arms, not conclusions.

A NOTE ON THE INSTRUMENT, because it bit three times. Docker Desktop
updated mid-session twice; the FIRST outage did destroy five in-flight
containers, and one escalation container was SIGKILLed (exit 137) at
position 24. The second outage destroyed nothing — but every watcher
reported it as if it had, because `until [ -z "$(docker ps -q ...)" ]`
reads an API ERROR as an empty container list. Three watchers
announced completion for runs that were still at 99% CPU. Health-check
the daemon before believing an empty list: a dead daemon and an idle
one are indistinguishable to that idiom. This is the reach entry's
lesson in a second costume — UNKNOWN is not absence, and neither is an
unreachable instrument.

And a third costume, the sharpest of the three, because this one
accused the engine. The divergence replay defaulted its prior anchor
to `--belief zach` while the league's default is SLOPPY, and the
posterior anchors half its prior on that belief — so it rebuilt the
wrong trajectory and reported NINE reconstruction mismatches, the one
reading the tool itself declares "the only reading that indicts the
re-budget". Every one was the instrument. The fix is not a better
default but the removal of the default: the replay now reads the
belief out of the arm's OWN report metadata, because a hardcoded
assumption about a run is exactly the kind of key that goes stale
silently. With it read correctly: A and B diverge from the pinned run
ZERO times, D diverges four times, and reconstruction mismatches are
zero everywhere. The mercy-pin round warned about session tooling
summing a key that does not exist; this is the same warning about
tooling ASSUMING a key's value.

## Sub-probe review round: three settings are not irreducibility, saturation lands in the report, and the help text tells the truth (2026-07-25)

Outside review of the a11 session, three items, all three accepted.
Selftest 70/70 (one new check).

ITEM ONE, THE SUBSTANTIVE ONE: the entry generalized three settings
into "the cost is not recoverable." The arms established exactly
three points — men 4 saves 2.6%, slice 800 saves ~2% while
quadrupling hits, zero funding loses zach_g03 — and nothing between
zero and full was ever sampled: not `sub_probe_cap` itself, not
`sub_probe_n 1`, not a checks-only gate. Zero losing a trophy does
not imply every partial budget does; if anything, D's
cheaper-hits-when-starved result points the other way. The headline
and the recoverability paragraph are narrowed IN PLACE to the tested
settings, and the missing sweep is running as this entry is written —
five arms, baseline seeds, baked image, one knob each: cap 50k, cap
25k, cap 10k (a crude first cut of the finder-not-prover question),
men 0 (checks-only gate), n 1. Its table lands in an addendum below
when the arms finish. Until then the strongest licensed claim is: the
two knobs the QUEUE NAMED do not reclaim the layer's cost.

ITEM TWO: the entry promised "per-layer saturation FROM report.json"
and the layer block delivered nodes, share, and only the NAME of the
cap's knob — the saturation line in this log was hand-joined from
metadata, the exact archaeology the block claims to remove. The
docstring even said "saturation is against the layer's own cap" while
computing none. Fixed by threading the engine description (the same
dict the metadata records) through `run_league` into `summarize`: the
block now carries `cap` and `saturation` per layer, the render line
prints both ("root_probe 50,000/dec (52% of nodes, 100% of cap)"),
and knobs the description lacks stay null rather than guessed. A
focused selftest pins 80%/20% saturations and the null case.

ITEM THREE: `--probe-forcing-n`'s help text still described the
REJECTED design — "continues from --probe-n+1 on whatever budget the
exhaustive ladder leaves" — while the shipped prover re-climbs n=1 up
to its rung on its own additive cap and touches no exhaustive budget.
The engine docstrings were correct; the CLI lied. Rewritten to
describe the independent ladder. A user reading the old text would
have mis-set both the depth range and the budget arithmetic, which
for a layer whose whole design argument is "never carve the
exhaustive cap" is not a cosmetic error.

The pattern across all three is worth naming: each is a claim that
outran its evidence — a generalization past the tested grid, a
promised column that was never computed, a description of a design
that was rejected. The reviewer caught in one pass what four
instrument failures in one session should have taught already: state
what was measured, exactly, and nothing else.

ADDENDUM, THE SWEEP THE REVIEW DEMANDED (same day). Five arms, 30
games each, baseline seeds, baked image, one knob apiece; divergence
replay run on every arm, reconstruction mismatches ZERO everywhere —
all movement below is the knob, never inference.

```
arm                zach  sloppy  squat  nodes/dec   sub/dec  sub hits
A base (100k)      3/10    0/10   1/10    139,159    75,256        12
E cap 50k          2/10    0/10   1/10    103,179    38,916        15
F cap 25k          2/10    0/10   1/10     85,596    19,835         8
G cap 10k          2/10    0/10   1/10     73,849     8,087         8
H men 0 (checks)   2/10    0/10   1/10     74,840    10,332         0
I n=1 only         3/10    2/10   1/10    116,347    49,471       272
C off (from above) 2/10    0/10   1/10     64,508         0         0
every arm except A and I: lost=zach_g03, gained=none
I: lost=zach_g03, gained=sloppy_g07, sloppy_g09, zach_g01 — NET +2
```

THE REVIEW'S QUESTION HAS A CLEAN ANSWER: the interpolation was
unlicensed and TRUE ON ITS OWN AXIS. Every partial budget sampled —
50%, 25%, 10% — loses zach_g03, exactly as zero does, so the tested
grid now brackets the range and the trophy needs FULL funding. The
mechanism is the design comment's own arithmetic: the share is
cap // ~30 branches, an n=2 proof costs ~2,056, and 100k//30 = 3,333
funds one while 50k//30 = 1,666 funds none. zach_g03's critical hit
is an n=2 proof, so the cliff sits between 50k and 100k and every
sampled rung below it falls off. The checks-only gate (H) makes the
complement point: 3% of the calls, 63% definitive — and ZERO hits,
because the finds live behind the MATERIAL gate, in the stripped
zugzwang positions, not in the check chains.

AND THE THESIS GOT ITS IN-VIVO PROOF, for free: arms F and G played
THIRTY BYTE-IDENTICAL GAMES while spending 19,835 vs 8,087 sub-nodes
per decision. The 11,748-node difference bought only UNKNOWNs and
refutations — non-PROVEN answers, which steering maps to None — and
play did not move by one ply. Only PROVEN changes play; here are 30
games of it.

THE SURPRISE IS ARM I, AND IT IS THE FINDER THESIS WITH DATA. n=1-only
sub-probes: 272 hits against the base's 12, at 16% fewer total nodes
per decision — and TWO SLOPPY CONVERSIONS, a family that has never
converted in any league since the pivot, plus zach_g01, against
zach_g03 lost. Net +2 conversions on the dev board (6/30 vs 4/30),
cheaper. Mechanically consistent: n=1 proofs cost ~60-200 nodes, so
the same shares that starve n=2 proofs fund DOZENS of n=1 finds, and
272 nudges steered two sloppy games into nets. Every trajectory
reconstructs; the movement is the knob. (A phrase that stood here —
"nets nothing else has ever reached" — is struck by the fresh-seed
addendum below: the base engine reaches sloppy nets fine at other
seeds. Self-caught this time.)

WHAT ARM I IS NOT, yet: a result. One seed set, dev families only,
and a +2 delta that two games of seed noise could erase. By the
standing standard the verdict waits on a fresh-seed A/B (base vs n=1,
seed0 100, launched as this addendum is written). If it holds there,
sub_probe_n=1 is the first CONFIG-CHANGE candidate this session has
produced — it would owe the one pinned league, and the interesting
question becomes whether the reclaimed 26k/decision plus the sloppy
capability survive held-out families. If it does not hold, it joins
the slice result as evidence about the layer's character (finder, not
prover) without being a shippable setting.

The review item stands answered either way: three settings were not
irreducibility, and the sweep that replaced the interpolation found
both a confirmation (the trophy needs full funding on every sampled
partial budget) and a candidate the narrower grid could never have
seen.

FRESH-SEED A/B, AND A SELF-CAUGHT CORRECTION FIRST. At seed0 100 the
BASE engine converts sloppy 5/10. The previous addendum's framing of
arm I's sloppy conversions as reaching "nets nothing else has ever
reached" was seed luck dressed as capability, and it is struck in
place above. The deeper reading: base converts 4/30 at baseline seeds
and 10/30 at seed0 100 — the family conversion rate on a 10-game
sample swings by a factor of 2.5 on seeds ALONE, so a ±2 conversion
delta between arms is weather, and the durable readings in all these
tables are the mechanism-level ones: which specific decision lost its
hit, what a hit costs, where the cliff sits. The taste for byte-level
evidence this session developed is not a style; it is what survives
the seed noise.

THE A/B ITSELF (base vs sub_probe_n=1, seed0 100, 30 games each,
baked image, divergence-replayed clean):

```
arm            zach  sloppy  squat   nodes/dec   sub/dec   hits
base           3/10    5/10   2/10     141,428    74,152     47
n=1 only       3/10    5/10   2/10     116,124    48,213    169
n=1 swaps zach games (loses g03+g08@s100, gains g00+g06@s100);
family and total counts IDENTICAL.  Nodes -17.9%.
POOLED ACROSS BOTH SEED SETS (the unit): base 14/60, n1 16/60;
n1 cheaper by ~18% on each set independently.
```

THE VERDICT THE UNIT LICENSES: n=1-only sub-probing is
conversion-neutral (never worse in total on either seed set, +2
pooled, which the seed-noise reading above says to treat as zero) and
MATERIALLY CHEAPER — 17.9% of all node work at fresh seeds, 16.4% at
baseline, the sub layer itself down ~35%. The layer's character
claim holds at both seed sets: restricted to the rung where finding
is cheap, it finds 3.6x to 22x more and spends a third less.

THE DECISION: sub_probe_n's default flips 2 -> 1. That is a code
change that changes play, so it owes THE pinned league, and the
tier-(a) CHEAPER case is the claim it will test: nodes per decision
down materially with the 22 intact. The 22 are structurally
untouched — they are root-prover certificates and the root prover is
unchanged — and the replay re-verification runs alongside the league
anyway. The risk is named now, before the report: the n=2 sub-nudges
being given up are the assembly horizon of the organic recapture
devices, and those lived in HELD-OUT families (human-held, the
squat-held boxes). Dev families cannot price that loss; the pinned
league is the instrument that can. If held-out forced regresses, the
default reverts and this entry prices the attempt.

## The finder priced and returned: n=1 wins the dev board, loses a held-out box, and the default walks back (2026-07-25)

THE pinned league for the a11 config flip (sub_probe_n 2 -> 1), run
because that flip is a code change that changes play: rebuilt image,
fresh out dir games/league/finder-n1/, all seven families, standard
seeds. Selftest 70/70 before and after. The verdict first, because the
rule that decides it was declared before the run: held-out forced
REGRESSED, 6/40 to 5/40, so the default REVERTS, and this entry prices
the attempt.

```
family       split      n  forced  mercy  st-us  insuf  maxply  forced%
sloppy       dev       10       2      0      1      0       6      20%
squat        dev       10       1      0      0      0       9      10%
zach         dev       10       3      0      0      0       7      30%
human-held   held-out  10       1      0      0      0       9      10%
random       held-out  10       1      6      0      0       3      10%
sloppy-held  held-out  10       2      0      3      0       5      20%
squat-held   held-out  10       1      0      0      0       9      10%

forced — held-out 5/40 (12%); dev 6/30 (20%); overall 11/70 (16%)
worst held-out family: human-held (10%)
nodes/decision 108,051 (ladder: 134,758, -19.8%) over 7,023 decisions
per-layer, NATIVE from report.json's new layers block:
  root_probe 46,966/dec (43% of nodes, 94% of cap)
  sub_probe  44,551/dec (41% of nodes, 45% of cap)
  steering   16,533/dec (15% of nodes,  4% of cap)
clamps 18,556 = 2.64/dec (0.016% of search nodes); sub hits 394
(ladder: 41); oracle certificates fired 18; ext_nodes 23.97M
```

THE EXACT TRADE, GAME BY GAME, at seeds every prior pin shares —
deterministic engine, so these swaps are the CONFIG, not weather:

```
lost    squat-held_g01  HELD-OUT — the named risk, verbatim: the box
                        whose two certificates ride plies 165/167
                        behind a long n=2-nudged assembly
        zach_g03        dev — the known n=2-hit conversion
gained  sloppy_g07, sloppy_g09   the first sloppy conversions in any
                                 pinned league (ladder: 0/10)
        zach_g01        dev
```

Benchmarks: posterior-ladder 6/40 held-out, 10/70 overall;
posterior-ext 6/40, 12/70. finder-n1 lands 5/40, 11/70 — MORE overall
than the config it replaced and one short of both bars that matter.
The no-zero board WIDENS: for the first time no family on the full
seven-row board has a zero forced column — and the held-out bar is
still missed, which is the project's own hierarchy working as
designed. Dev boards do not generalize; the worst held-out row is the
scoreboard; a first is not a bar.

POSTERIOR DIAGNOSTICS: the posterior CODE is unchanged; its READS are
not, and the first version of this paragraph said "unchanged" while
listing a changed row in its own parenthesis — review caught the
contradiction. A pure function of the observed sequence changes its
answer exactly when a diverged game shows it a different sequence.
Six of seven families match the ladder pin row for row (zach 10/10
zach, sloppy 10/10 sloppy, squat 10/10 squat-k, squat-held 10/10
squat-greedy-q, random 10/10 fitted-human, human-held the same 6/4
sloppy/sloppy-mild split). The seventh moved: sloppy-held's 9 sloppy
+ 1 fitted-human-m35 becomes 10/10 sloppy — one diverged trajectory,
one changed read, which is the posterior WORKING, not drifting, and
the reconstruction checks (zero mismatches on every arm) are what
license that sentence. Median collapse plies 9-24.

THE TROPHY LEDGER: 22/22 re-derived under the shipped code, zero
mismatches, zero misses over all 465 pinned decisions
(dev-rebudget/trophy-revalidate-n1.json) — the root prover is
untouched by the sub knob, and now that is measured rather than
argued.

TIER SCORING, against the declared bars:
  (a) CHEAPER — DEMONSTRATED, NOT CLAIMED: -19.8% nodes/decision with
      the 22 intact is exactly the tier's text, but the config walks
      back, and an unshipped config claims nothing.
  (b) DEEPER — not attempted; the forcing certifier stayed off by
      default throughout, as shipped.
  (c) METRIC — missed by one game: 5/40 against >= 6/40, the no-zero
      held-out board holding (and widening to the full board).

WHY THE REVERT IS RIGHT even though 11 > 10 overall: the regression
is in the held-out column, in the exact mechanism named before the
run — the n=2 sub-nudges are the assembly horizon of the organic box
devices, and squat-held_g01 is such a box. At pinned seeds that loss
is causal, not noise. The brief's hierarchy puts held-out above
overall and the worst row above the mean; a 20% compute saving buys
nothing the project is short of, and one held-out box is something it
has exactly six of. The declared rule ("if held-out forced regresses,
the default reverts") fires as written. sub_probe_n=1 remains one
flag away for any run that wants the finder behavior, now with a
complete price tag: +2 dev, -1 held-out box, -19.8% nodes, hits x9.6.

ITEM 1 CLOSES WITH THE LAYER CHARACTERIZED TO ITS TESTED BOUNDS —
"fully characterized, irreducible by cap and gate" stood here first,
and review struck it for the same sin as the round before: the grid
proves the trophy needs MORE THAN 50k, not that it needs all 100k,
and it brackets nothing between men 4 and men 0. What the numbers
license: 52.8% of all node work; every sampled cap at or below 50k
loses the trophy and 100k keeps it, with the 50-100k interval open —
the share arithmetic (share = cap // branches, an n=2 proof at
~2,056 nodes) predicts the cliff near branches x ~2,100, which is
~63k for a thirty-branch root, so a 75k arm is the declared probe
and runs as this correction lands, a men-3 arm beside it for the
gate's untested middle. Reducible a third by rung, at the measured
price of one held-out box conversion. What stands regardless of the
open intervals: the layer is a finder that must stay funded as a
prover on SOME n=2 budget, because the rung that is expensive to
prove is the rung the boxes are assembled on — the open question is
only how much of the 100k that budget actually needs. Neither arm
can ship a config this session either way: the pinned league is
spent, and a cap or gate change would owe its own.

WHAT REMAINS SHIPPED FROM THE SESSION, all off by default or
play-inert, byte-identity with pre-session main re-verified after the
revert: the NOT_FOUND status and the forcing-restricted certifier
(priced: one verified n=4 conversion two plies early per 465 pinned
decisions, at width 8 / cap 20k); the oracle starvation-labelling fix;
the report's native per-layer caps and saturations; the divergence
replay reading beliefs from run metadata; eleven new selftest checks
(59 -> 70).

## Second review round: the help that crashed, the interval the grid skipped, and the posterior that did move (2026-07-25)

Three items, all three accepted; selftest 71/71 (one new check).

ITEM ONE, P1, A REAL CRASH: argparse percent-interpolates help
strings at render time, so the "-19.8% total" in the reverted
--sub-probe-n help raised ValueError ("unsupported format character
't'") on both `play --help` and `league --help` — demonstrated on the
baked image before fixing, per this session's own rule about
verifying before believing. The % is escaped, and the class is gated,
not just the instance: parser construction is split out of main() as
`build_parser()`, and a new selftest renders the help of the root and
every subcommand, because a stray % is invisible to every code path
except a user typing --help — which is why 70 green checks never saw
it.

ITEM TWO, P2, THE SAME SIN AS THE ROUND BEFORE, one level down: the
pinned entry declared the layer "irreducible by cap" off a grid that
proves the trophy needs MORE THAN 50k, not that it needs all 100k —
the 50-100k interval was never sampled, and men 1-3 sit untested
between the gate's endpoints. Corrected in place to the tested
bounds, with the share arithmetic's prediction stated (cliff near
branches x ~2,100 ≈ 63k for a thirty-branch root) and the two probes
it implies — cap 75k and men 3, baseline seeds, one knob each —
launched before this entry was written. Their table lands below when
they finish. Neither can ship a config this session: the pinned
league is spent, and a cap or gate change would owe its own.

ITEM THREE, P3, A SELF-CONTRADICTION: the pinned entry called the
posterior diagnostics "unchanged... row for row" while its own
parenthesis recorded sloppy-held moving from 9+1 to 10/10. The
implementation is unchanged; the reads are not, and cannot be where
trajectories diverged — a pure function of the observed sequence
answers differently when shown a different sequence. Reworded to say
exactly that, with the delta retained and the zero-mismatch
reconstruction checks cited as what licenses "working, not drifting."

The round's shape, for the log's memory: last round's lesson was
"state what was measured, exactly, and nothing else." This round
caught the places where the statement was exact but the MEASUREMENT'S
BOUNDS were not — an untested interval called closed, a changed read
called unchanged, and a string no measurement ever rendered. The
suite gates what it renders; it cannot gate what nothing exercises.

ADDENDUM, THE INTERVAL ARMS (same day): both landed, and the open
intervals close at tested bounds.

```
arm            zach  sloppy  squat  nodes/dec   sub/dec  hits  vs base
A base (100k)  3/10    0/10   1/10    139,159    75,256    12  —
J cap 75k      3/10    0/10   1/10    120,930    57,020    24  lost NONE
E cap 50k      2/10    0/10   1/10    103,179    38,916    15  lost zach_g03
K men 3        2/10    0/10   1/10    131,743    67,451    13  lost zach_g03
```

THE CAP CLIFF IS BRACKETED: (50k, 75k]. Cap 75k keeps every
conversion — 29 of 30 games BYTE-IDENTICAL to base, the thirtieth
(squat_g09) converting anyway by a longer route — at 24% less
layer spend and 13% less total. The share arithmetic predicted the
cliff near 63k and the bracket agrees; a 60-70k bisection could
tighten it, but 75k is already a validated point with margin.

MEN 4 IS THE LOWEST TESTED SUCCESSFUL GATE: arm B kept the trophy
at men 4, arm K loses it at men 3 — adjacent settings, so the flip
MEASURES the critical decision's opponent material as exactly four
non-king men (that part is licensed and stands). NOT established:
that men 4 is the floor. Men 1-2 were never run, and this session's
own tables show trajectories recovering non-monotonically after a
knob change, so "3 and 0 lose" does not price 1 and 2. They stay
untested deliberately: nothing ships on an axis worth 2.6%, so the
claim narrows to the tested points instead of buying two arms.
The men-4 saving remains 2.6%; the gate axis is closed at its
tested points — 4 keeps, 3 and 0 lose, 1-2 open. [Third review
round: "exactly" and "closed" outran the grid, in the round that
had just coined the phrase.]

So the layer's characterization at its tested bounds: cap
reducible to 75k for a quarter of the layer's cost (validated
point, cliff somewhere in the 25k above 50k); gate reducible one
step for 2.6%; rung reducible by a third at the pinned price of one
held-out box. Cap 75k is the standing dev-validated candidate for a
NEXT session: fresh-seed A/B first by the standard, then its own
pinned league if the default flips — this session's pin is spent
and its verdict stands.

## Third review round: the floor becomes the lowest tested rung, and three counts meet their artifacts (2026-07-26)

Four items accepted — one from outside review, three from the
reviewing session's artifact pass over dev-rebudget/. Log-only: no
code, no behavior, version stays a11, selftest 71/71 untouched.
Edits are in place at the claims; this entry is the index.

- THE GATE FLOOR OUTRAN ITS GRID (P2, outside review): "exactly
  men 4" and "the gate axis is closed" asserted men 1-2 results
  never run — the third instance of the class in three rounds,
  caught in the round that coined "the closed axis is the tested
  grid." Narrowed in place: lowest TESTED successful gate; the
  men4/men3 adjacency measurement stands; 1-2 stay open and
  untested by choice, priced against an axis worth 2.6% with no
  config shipping on it.
- THE HYBRID LOST FOUR, NOT TWO: hybrid-trophy-w5.json records all
  four n>=3 first-certificates dead — the two the entry named plus
  zach_g03 ply49 and zach_g05 ply73, each trio's later certs
  retained — and its wall file covers ten games, not five. The
  correction strengthens the rejection it documents.
- ONE TROPHY, TWO CURRENCIES: the census's 45,282 (n=3 alone) and
  the docstring's 49,559 (in-game, ladder-cumulative) are the same
  certificate; the bridge (alone + lower-rung spend) is now stated
  at the census table and verified for all four deep certs.
- ITEM 0 DISAGREED WITH ITSELF: the outage forensics corrected the
  cost paragraph (24 of 27, zach 6 of 9, five n=4 runs) but not the
  table above it (23, zach 5, four). The later account is marked
  as superseding; no tabled verdict moves.

The round's one-line lesson is the second round's, unchanged: the
suite gates what it renders, and artifacts gate what they record —
prose that cites neither is where the drift lives.

## The cap flip ships and the steering ledger closes: 75k reproduces the ladder pin game for game, and the headroom was never headroom (2026-07-26/27)

Two levers from the standing queue, by the house standard — dev arms,
fresh-seed A/B, at most one pinned league. The verdict first: the 75k
candidate passed its acceptance rule, took the league seat, and
SHIPS — sub_probe_cap 100,000 -> 75,000, version 2.0.0a12. A word on
that rule's provenance, because the log's prior entry commits only to
"fresh-seed A/B first by the standard, then its own pinned league if
the default flips" and records no acceptance criterion: the
neutral-or-better-pooled rule was declared in the SESSION BRIEF,
before any fresh-seed game ran — outside this log, which is why its
first in-repo appearance is beside its result. [Review round, same
day: this provenance note replaces an unqualified "pre-declared".] Both
steering knobs failed their fresh-seed A/Bs and no steering config
ships; the negative is characterized to its tested bounds below.
Selftest 71/71 at every code state (the flip adds none and breaks
none); baked image byte-verified against the tree before every run
block; divergence replay on ALL SEVEN runs this session — six dev
arms and the pinned league — with reconstruction mismatches ZERO
everywhere. Every movement below is its knob, never inference.

THE PINNED LEAGUE (games/league/subcap-75k/, all seven families,
standard seeds, a12 defaults, no overrides):

```
family       split      n  forced  mercy  st-us  insuf  maxply  forced%
zach         dev       10       3      0      0      0       7      30%
sloppy       dev       10       0      0      1      1       8       0%
squat        dev       10       1      0      0      0       9      10%
sloppy-held  held-out  10       2      0      0      3       5      20%
human-held   held-out  10       1      0      0      0       9      10%
squat-held   held-out  10       2      0      0      0       8      20%
random       held-out  10       1      5      0      0       4      10%

forced — held-out 6/40 (15%); dev 4/30 (13%); overall 10/70 (14%)
worst held-out family: human-held (10%); no zero rows on the board
nodes/decision 117,813 (ladder pin: 134,758, -12.6%) over 7,097 dec
per-layer, native from report.json:
  root_probe 47,004/dec (40% of nodes, 94% of cap)
  sub_probe  54,144/dec (46% of nodes, 72% of cap)
  steering   16,666/dec (14% of nodes,  4% of cap)
clamps 13,055 = 1.84/dec (0.0016% of nodes); sub hits 53 (ladder:
41); oracle certificates fired in-game 21 (ladder: 22, the delta is
squat_g09 below); ext_nodes 24.48M
```

THE SHIP RULE READS: held-out forced 6/40 meets the >= 6/40 bar with
no held-out regression — and the trophy board is not merely equal in
count, it is THE SAME TEN GAMES as the posterior-ladder pin, game for
game: lost NONE, gained NONE. Sixty-nine of seventy games are
BYTE-IDENTICAL to the ladder pin; the seventieth, squat_g09, is the
same diverger the dev arm found and it CONVERTS ANYWAY by a longer
route (89 plies vs 83, one in-game certificate vs two). The pinned
divergence replay: compared=70, diverged=1, reconstruction
mismatches 0. Benchmarks for the record: posterior-ladder 6/40 +
10/70; posterior-ext 6/40 + 12/70 (still the table of record —
overall is tied with the ladder, not with ext, and no record is
claimed); finder-n1 5/40 + 11/70 (reverted). subcap-75k lands 6/40 +
10/70: the ladder pin's exact scoreboard at 87% of its price.

THE TROPHY LEDGER, MEASURED NOT ARGUED, twice: the offline
re-derivation of all 22 certificates over the ten pinned trophy PGNs
runs under a12 with zero mismatches, zero misses, zero extras over
all 465 pinned decisions — and NODE-FOR-NODE identical to the
finder-session artifact, 22,251,688 nodes both times
(dev-rebudget/trophy-revalidate-cap75k.json vs trophy-revalidate-n1
.json; the root prover reads no sub-probe knob, and now that is a
measurement under BOTH configs). The generator script itself is now
persisted as dev-rebudget/trophy_revalidate.py — the n=1 session
kept only its output, and this session had to rebuild the
instrument before it could trust it: it reproduced the n=1 artifact
exactly (dev-rebudget/trophy-revalidate-a11-check.json) before being
believed about a12.

POSTERIOR DIAGNOSTICS: six families read identically to the ladder
pin row for row (zach 10/10 zach, sloppy 10/10 sloppy, squat 10/10
squat-k, squat-held 10/10 squat-greedy-q, random 10/10 fitted-human,
human-held the same 6/4 sloppy/sloppy-mild split), and sloppy-held
is BACK to the ladder's 9 sloppy + 1 fitted-human-m35 — the read
finder-n1 had moved, restored because the trajectory that moved it
is restored. Median collapse ply 10 (range 0-60). A pure function of
the observed sequence, observing near-identical sequences.

THE 75K FRESH-SEED A/B that earned the seat (seed0 100, 30 games a
side, one knob; baseline-seed side standing from the interval arms):

```
arm                    zach  sloppy  squat  total  nodes/dec   sub/dec  hits
base-s100 (100k)       3/10    5/10   2/10  10/30    141,428    74,152    47
cap75k-s100            3/10    5/10   2/10  10/30    122,456    56,211    32
baseline side:  dev-sub-a-base 4/30 == dev-sub-j-cap75k 4/30 (J lost NONE)
```

The declared rule — flip if conversion totals are neutral-or-better
pooled across both seed sets — reads 14/60 vs 14/60: NEUTRAL, at
-13.4% total nodes fresh-side, -13.1% baseline-side. Two honesty
notes the totals hide. FIRST, the fresh set ends the cap's
conversion-inertness: 28 of 30 byte-identical, and the two divergers
SWAP a conversion. zach_g03(s100) converts at 100k (ply 231, 12 sub
hits) and dies to max-plies at 75k, diverging at ply 185 — the
tighter share starves a late sub-read behind a long assembly, the
mechanism the n=1 league priced. zach_g00(s100) runs the other way:
max-plies at 100k, diverges at ply 138, converts at ply 152 under
the tighter cap. One lost, one gained, same knob, same family — the
full width of what 60 games license is "totals-neutral with one swap
each way", and the baseline-seed "keeps every conversion" claim
stays true at its own seeds only. SECOND, the fresh base side
doubled as a determinism cross-check: the a11 rerun of the a10
finder-session base is byte-identical in all 30 PGNs (replay:
diverged 0, reconstruction 0) — fixed config, fixed seeds, two
package versions, same game to the ply, on a seed set the post-revert
byte-verification never touched.

STEERING ON ITS OWN ACCOUNT — ~16.5k/dec against a 400k node_cap
(4% saturation) was the last big untested search lever. One knob per
arm, both seed sets, base rows repeated for reading:

```
arm            seeds  zach  sloppy  squat  total  nodes/dec  steer/dec  sat  clamp/dec
base            s0    3/10    0/10   1/10   4/30    139,159     16,276   4%       1.6
depth4          s0    6/10    4/10   0/10  10/30    249,766    115,151  29%     303.9
topk8           s0    2/10    2/10   1/10   5/30    135,638     15,856   4%       2.4
base            s100  3/10    5/10   2/10  10/30    141,428     20,123   5%       4.7
depth4          s100  3/10    2/10   0/10   5/30    256,926    123,825  31%     433.2
topk8           s100  5/10    2/10   1/10   8/30    140,681     19,190   5%       5.3
```

DEPTH 4 IS THE FINDER STORY A THIRD TIME, one layer up: +6 on the
baseline dev board — zach 6/10 the best zach dev row ever recorded,
sloppy 4/10 at seeds where sloppy had converted only under the
reverted finder — and then fresh seeds take five back (5/30 against
the same base's 10/30). Pooled +1/60 at +80% nodes/dec (+79.5% s0,
+81.7% s100), with dev-squat ZEROED on both seed sets (0/20 pooled
vs base 3/20) and 23 of 60 game outcomes churned (s0: 2 lost, 8
gained; s100: 9 lost, 4 gained). One of its four fresh-seed gains,
zach_g00(s100), is the very game the 75k cap converts at -13%
instead of +82%. Dev boards do not generalize; a pooled +1 whose
family floor drops to zero is not an earner; no belief, no flip, no
league seat. TOPK 8 fails without needing the hierarchy: pooled
13/60 vs 14/60, and on baseline seeds it reshuffles the ENTIRE
conversion set — loses all four of base's converts, gains five
others — for +1 there and -2 on fresh. A reply-cap widening
re-weights every chance node, re-sorts every line, relocates every
game; what it does not do is convert more.

THE MECHANISMS, from the native layer blocks, at tested bounds:

- THE NODE_CAP BINDS PER-BRANCH, AND THE AGGREGATE HID IT. [Review
  round, same day: this bullet's first draft was headlined "the
  node_cap was never the wall" off 29-31% aggregate saturation —
  the same overclaim class as three rounds running, and wrong twice
  over. The cap splits evenly across root candidates with NO
  rollover (share = cap // moves), so cheap branches strand
  allowance while dear ones clamp: a low aggregate is fully
  consistent with heavy per-branch binding. And clamped_nodes
  COUNTS positions answered by leaf eval past a branch's share —
  each one truncates a subtree of unmeasured size, so "0.26-0.35%
  of the layer's nodes" priced clamp EVENTS against SPENT nodes,
  a denominator that says nothing about withheld work.] What the
  depth-4 arms measure: 807,094 (s0) and 1,217,292 (s100) clamped
  nodes — binding OCCURRED, at 304-433 events/dec, so the depth-4
  verdict is a verdict on depth 4 AT A BINDING 400k CAP, not on
  depth 4 with room. At depth 3 the cap engages three orders of
  magnitude more rarely (1.6-4.7 clamp-nodes/dec) — rare, not
  never. Whether either engagement withholds conversions is
  exactly the cell the grid skipped, and two probe arms are
  running as this correction lands: the shipped a12 config with
  the cap DISABLED (node_cap 0, one knob), and depth 4 at a 4x cap
  (1,600,000, one knob off the depth-4 arm, sub cap pinned 100k).
  Their table lands in an addendum below. Until it does, the
  licensed claims stop at: depth 5 and topk 10 untested, the cap
  axis untested, and the FIRST rung of depth/topk at the DEFAULT
  cap reshuffles rather than grows.

- DEPTH MULTIPLIES THE SUB-PROBE LAYER'S CALL SITES AND DILUTES ITS
  SHARES. Gated calls 16.2M -> 88.8M (s0), 18.4M -> 104.7M (s100),
  5.5-5.7x, while layer nodes rise only 14-16%: the shared
  per-decision cap self-limits, each site's slice thins, and hits
  swing in OPPOSITE directions by seed set — 12 -> 131 on s0,
  47 -> 22 on s100. A deeper tree exposes more probe sites AND
  starves each one; which effect wins is seed weather, which is what
  a reshuffle looks like from the layer below.

- THE ROOT PROVER: ~47k/dec in every arm (its own cap), certificates
  10 -> 20 (s0) and 16 -> 7 (s100) — certificates follow which
  endgames the relocated trajectories reach; the prover itself
  neither pays nor saves.

So the steering-headroom question, at the bounds these six arms
tested: the depth and topk rungs reshuffle rather than grow, AT THE
DEFAULT CAP. [Review round, same day: the first draft closed this
paragraph with "NOTHING WAS BEING WITHHELD", a sentence the grid
does not license — the depth-4 arms ran against a per-branch
binding cap (previous bullet), and no arm varied the cap at fixed
depth. The two probe arms running as this lands are what can close
it; their addendum below says whether the withheld subtrees were
buying anything.] What stands regardless: the knob depth 4 turns
hardest is one it does not name — sub-probe site count — and that
turn buys +1/60 pooled for +80% spend with a family zeroed. Depth
{3,4} and topk {6,8} are priced at cap 400k; deeper and wider rungs
stay open and unpriced, and nothing in these six arms argues for
buying them.

TIER SCORING, against the declared bars:
  (a) CHEAPER — SHIPPED: a validated default (sub_probe_cap 75,000,
      2.0.0a12) with held-out intact at 6/40, the same ten trophy
      games as the ladder pin, the 22-certificate ledger re-derived
      node-for-node, at -12.6% nodes/decision against the pin it
      reproduces.
  (b) CHARACTERIZED — the depth and topk rungs answered at tested
      bounds with mechanisms (site-dilution the real coupling,
      reshuffle not growth at the default cap); the CAP AXIS opened
      by review, probed same-day, and closed at its tested points:
      cap {400k, disabled} at depth 3 flips nothing (29/30
      byte-identical, zero conversions moved), cap {400k, 1.6M} at
      depth 4 churns both ways with squat still zero. Claimed at
      that width — see the review round's addendum.
  (c) METRIC — not retaken and not claimed: 6/40 ties the standing
      bar, posterior-ext's 12/70 overall stands.

WHAT SHIPS — meaning lands in the COMMIT: the a12 default flip
(engine + CLI, help text stating the priced claim at its tested
width) and the pinned league subcap-75k/ (report + ten trophy
PGNs). The revalidate instrument and its two artifacts PERSIST
LOCALLY in dev-rebudget/ but do NOT ship: dev-* is untracked
wholesale by the standing artifact policy, deliberately (the
.gitignore states why), so a fresh checkout gets the claim and the
recipe, not the instrument — it is reproducible, and it proved
itself by re-deriving the n=1 artifact exactly before being
believed about a12. [Review round, same day: the first draft
listed the instrument under "ships", conflating persisted-on-disk
with in-the-commit.] WHAT DOES NOT SHIP: any steering change —
both knobs revert to defaults untouched, priced in this entry. The cap cliff interval stands OPEN at (50k, 75k]: 75k is a
validated point with margin, not a floor; 60-70k was deliberately
not bisected because nothing ships on that refinement. sub_probe_n=1
remains one flag away with its complete price tag. The depth and
topk axes close at their tested rungs at the default cap; the cap
axis is open until the addendum's probe arms land.

## Review round on the a12 entry: the aggregate hid the binding, the rule names its source, and ships means the commit (2026-07-27)

Three items from outside review, all three accepted — the third in
part, with the disagreement stated. Log-only: no code, no behavior,
version stays a12, selftest 71/71 untouched. Edits are in place at
the claims (each marked "[Review round, same day]"); this entry is
the index.

- THE AGGREGATE HID THE BINDING (P1, the substantive one): "the
  node_cap was never the wall" rested on 29-31% aggregate
  saturation — but the cap splits per root branch with no rollover,
  so cheap branches strand allowance while dear ones clamp, and the
  arms' own 807,094 / 1,217,292 clamped nodes prove binding
  OCCURRED. Worse, the "0.26-0.35% of layer nodes" reassurance
  priced clamp events against spent nodes when every clamped node
  truncates a subtree of unmeasured size. The depth-4 rejection
  therefore stands as measured — depth 4 AT A BINDING 400k CAP
  loses its fresh-seed A/B — but "nothing was withheld" outran the
  grid: no arm varied the cap at fixed depth. Two probe arms
  launched with the correction, one knob each: the shipped a12
  config with node_cap 0 (does the cap's rare depth-3 engagement
  withhold anything from the DEFAULT?), and depth 4 at cap
  1,600,000 with sub cap pinned at 100k (was depth 4's reshuffle
  an artifact of starvation?). Addendum below when they land.
  Fourth instance of the outran-the-grid class in four rounds, in
  the entry that quoted the class by name.
- THE RULE NAMES ITS SOURCE (P2): "pre-declared" pooled acceptance
  was declared in the SESSION BRIEF before any fresh-seed game ran,
  but the log's prior entry records only "fresh-seed A/B first by
  the standard" — inside the repo, the rule first appears beside
  its result. The opening paragraph now states the provenance
  instead of the adjective. A rule that lives outside the log is a
  rule the log cannot gate; recording acceptance criteria in the
  candidate's own entry, before the run, is the cheap fix the next
  candidate should get.
- SHIPS MEANS THE COMMIT (P3, accepted in part): the entry listed
  the revalidate instrument under "WHAT SHIPS" while dev-rebudget/
  is untracked wholesale — a fresh checkout gets neither script nor
  artifacts. The wording is fixed (persists locally, does not
  ship). The review's remedy of promoting them to a tracked path is
  DECLINED as policy: dev-* untracked is the standing artifact
  policy, stated with its rationale in .gitignore, and the
  instrument is reproducible — it re-derived the n=1 artifact
  node-for-node before being believed about a12. If instruments
  ever warrant tracking, that is a policy change to make
  deliberately, not a side effect of a wording fix.

ADDENDUM, THE CAP-AXIS PROBES (same day): both landed, one knob
each, reconstruction mismatches zero on both (the a12 probe
diverges from its base in 1 of 30 games, the depth-4 probe in 26).

```
arm                     zach  sloppy  squat  total  nodes/dec  steer/dec    sat  clamp/dec
j-cap75k (= a12 base)   3/10    0/10   1/10   4/30    120,930     16,264   4.1%      1.57
nocap (a12 + cap 0)     3/10    0/10   1/10   4/30    121,060     16,394      —      0
depth4 (cap 400k)       6/10    4/10   0/10  10/30    249,766    115,151  28.8%    303.9
depth4-cap1600k         7/10    4/10   0/10  11/30    379,943    246,340  15.4%    138.2
```

THE SHIPPED CONFIG WITHHOLDS NOTHING — MEASURED THIS TIME: at a12
defaults nine of thirty games clamp somewhere (4,965 nodes total,
heaviest squat_g07 at 2,900). Disabling the cap returns 29 of 30
games BYTE-IDENTICAL, perturbs exactly squat_g07's route without
moving its outcome (max-plies, 240 plies, both ways), and flips
ZERO conversions at +0.8% steering nodes. For the default at its
tested seeds, "nothing withheld" is now a measurement with a zero
in it, not an inference from an aggregate.

DEPTH 4 WAS NOT STARVED INTO FAILING: its tree's appetite is at
least 246k/dec — the 400k cap was withholding roughly half of what
it wanted — and paying 4x reshuffles the conversion set AGAIN: lost
sloppy_g06 and zach_g00/g05/g09, gained sloppy_g08 and
zach_g01/g03/g04/g07, net +1 at +52% nodes over the 400k arm
(+173% over base), squat STILL 0/10, and clamping still present
(138/dec — the appetite exceeds even 4x in some branches; a full
disable at depth 4 was not run because unbounded worst-case depth-4
trees are exactly the stall the cap exists to prevent, so the
bounded raise is the sound instrument). The dilution mechanism
lands its starkest number here: gated sub-probe sites grow 88.8M ->
200.9M calls against the same 100k sub cap and hits COLLAPSE
131 -> 25. More search below the root buys thinner probes
everywhere it matters. The 11/30 is a BASELINE-SEED note, not a
candidate: the depth axis already failed its fresh-seed A/B at the
cheaper rung, this arm shows the same churn signature, and the
probe's question was starvation — answered, no.

So the cap axis closes at its tested points: {400k, disabled} at
depth 3 with zero flips; {400k, 1.6M} at depth 4 with churn both
ways and the family zero unmoved. Tier (b) is claimed at exactly
that width, and the a12 entry's tier line is updated in place to
say so.

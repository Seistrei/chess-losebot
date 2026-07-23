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

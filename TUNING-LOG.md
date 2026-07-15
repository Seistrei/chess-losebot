# LoseBot tuning log (2026-07-12/13)

Every config change and its measured result, in order. Small samples (2-8
games) — treat single-run differences as noise unless the mechanism is clear.
**Lesson learned the hard way: this folder wasn't a git repo, so v0.3's exact
weights were overwritten during tuning. Reconstruction spec at the bottom.
`git init` before iterating further.**

| ver | change | vs Zach result |
|-----|--------|----------------|
| v0.1 | symmetric eval, mobility squeeze, support-callable probe | 0/2 (max-plies; Zach stripped to bare king) |
| v0.2 | +bare-king/frozen-pawn penalties, lazy probe, mate-aware squeeze (≤8), squeeze depth +1, PyPy | 0/2 (1 stalemate, 1 dead draw with frozen g2 pawn) |
| v0.3 | **asymmetric eval (root=loser at every leaf)** — the parity-bug fix | **1/4 mated (25%), probe hits 4** — game_003: 54.Qc2+ Kxc2# |
| v0.4 | zach-aware leaf menu (captures discounted), +55 first-pawn, deeper probe tiers, ≤9-men depth +1 | 0/6 (all repetition; 1 freak perpetual) |
| v0.5 | zach-pool tree pruning, hard no-revisit rule, +900 zugzwang jackpot | 0/6 (2 insufficient-material: Zach ATE the hanging cages) |
| v0.6 | revert tree pruning, gate king-march on their_pieces≤2 | 0/8 (5 fifty-move) |
| v0.7 | ungate king-march (v0.3 geometry), soft repeat/clock root nudges, king-move weight 1.6 in menu, endgame testbed added | drills 1/5 (endgame 1 converts) |
| v0.8 | herd their king toward their pawns (−16×dist, +120 adjacency) | drills 1/5 (endgame 5 converts, endgame 1 breaks, endgame 4 stalemates) — whack-a-mole |
| v0.9 | memoized probe, n≤9/3M budget (runaway cost — hours/game), then capped to n≤7/500k; herding −16→−8 | drills 1/5 (deep probes: zero extra hits); full games 0/4; vs Worstfish 0/2 draws |

Baseline for all comparisons: **Worstfish clone vs Zach clone: 0/4, all draws.**

## v0.3 reconstruction spec (best full-game result)

Asymmetric eval, root player = loser, sign-flip for negamax at return:
- our men: +25 each (count, not points)
- their pieces (non-pawn): −0.90 × {N320 B330 R500 Q900}
- their pawns: +30 × min(count, 3); +150 if pieces == 0; −6000 bare king; −3000 all-pawns-frozen (pieces == 0)
- menu (≤8 their moves, else −12×count): −14 per non-mating, +90 × min(mating, 2); no king-move weighting, no +900 clause
- us in check: +40 + 6 × max(0, 8 − escapes)
- our king: −9 × dist(our king, nearest their pawn | their king); +6 per own man adjacent
- clock: −1.5 × halfmove_clock (root only); draw contempt ±400 in negamax terminals
- depth: base 2, +1 when their mobility ≤ 8 (no ≤9-men bump)
- probe tiers: pieces==0 & mob≤10 → n4/300k; pieces==0 → n3/120k; ≤1 piece → n2/60k; else n1/25k
- root: mate/stalemate filters only (no repeat/clock nudges); no endgame herding term

## Open problem: endgame conversion

Phase 1 (strip Zach to king+pawns) succeeds in every game. Phase 2 (forced
self-mate construction) is the frontier. Hand analysis of drill position 2
(Ka8, a7+b6 pawns) shows a full winning construction exists — WKa4, Ba6, Na5,
Rd4, Pa3, Pb3, his king driven to c5 so it DEFENDS b5, then b5# is his only
move — but it needs ~8 coordinated units placed over 20+ plies: beyond any
depth-3 gradient. The load-bearing fact: **with only king+pawns left, the
mate arrival square can only be defended by their own king** — herding his
king next to his pawns is necessary, not optional.

Next steps, in rough order of expected value:
1. `git init`; benchmark configs on the testbed with ~10 seeds each (results
   here are 1-sample noise); A/B the v0.3 spec against the current build.
2. Scripted finisher: recognize king+pawns endings and execute the known
   construction as a plan (target squares for each unit), with the probe
   sealing the last 4-6 plies.
3. Fairy-Stockfish `[misere:chess] checkmateValue = win` as a deep oracle
   (needs a ~few-MB binary download into the image).
4. lichess-bot bridge — no misère bot exists on Lichess.

## Solver foundation and template baseline (2026-07-13)

Implemented without changing the `current` profile's weights:

- immutable `current`, reconstructed `v03`, and experimental `template`
  profiles, selectable from the Docker CLI;
- tri-state exact search (`PROVEN`, `DISPROVEN`, `UNKNOWN`) so exhausting a
  node budget is never cached as a genuine refutation;
- exact-probe draw handling aligned with the arena's repetition and 50-move
  rules, including draw-history state in transposition keys;
- probe node, exhaustion, completed-depth, and deep-skip diagnostics;
- a coupled pawn-mate template: one opponent pawn push, our king's checked
  square, their king's pawn-defense square, and our local cage occupancy;
- preservation penalty when king+pawns remain but no usable pawn-push template
  survives; and
- a template-proximity gate: n=1 is always checked, while n=2+ is attempted
  only at template distance <=2 with at least three cage occupants.

Docker regression suite: **8/8 passing**.

Bounded comparison: seed 5, all five drills, 40 plies, probe cap 10,000,
maximum probe depth 3. These are navigation/performance measurements, not
conversion-rate estimates.

| profile | conversions | other result | probe nodes | exhaustions |
|---------|-------------|--------------|-------------|-------------|
| current | 0/5 | 1 stalemate, 4 max-plies | 916,308 | 91 |
| v03 | 0/5 | 5 max-plies | 1,000,000 | 100 |
| template, before gate | 0/5 | 5 max-plies | 1,000,000 | 100 |
| template, gated | 0/5 | 5 max-plies | **505,050** | **50** |

The template profile reduced best setup distance from 5 to 2-3 in all five
drills and built 3-4 cage occupants. In drill 2 it initially allowed the last
usable pawn to reach a dead promotion square; the no-template penalty fixed
that regression (final target improved from distance 5/cage 2 to distance
2/cage 3 at ply 40).

A 120-ply drill-2 run later regressed to distance 7 as Zach's king wandered
away. This is the next concrete frontier: maintain a selected construction and
herd/box the reluctant king over a long horizon. A stateless leaf gradient can
recognize a good template but cannot yet preserve the plan.

## Stateful planner and bounded herding (2026-07-13)

Added an experimental `planner` profile on top of the immutable `template`
baseline:

- a persistent construction target keyed by opponent pawn file and checked
  side, so ordinary leaf evaluation cannot silently switch plans;
- explicit HOLD/RELEASE state for a mobile piece occupying the future mating
  square, including defense of that holding piece;
- root filters that preserve our king placement, a three-piece cage reserve,
  the pawn runway, the defended holder, and non-repeating alternatives;
- exact bounded AND/OR search for checks that force every Zach-policy reply to
  move the defending king closer; and
- a bounded Zach-policy expectimax fallback for useful but non-forcing herding
  moves.

The first depth-2 expectimax experiment was stopped after roughly 90 minutes.
That runtime was accidental: reply classification expanded before the intended
budget could effectively bound the work. The default is now depth 1, 1,000
nodes, and a hard 250 ms deadline per invocation. Do not restore depth 2 as a
default without selective move generation, memoization, or both.

Docker regression suite: **12/12 passing**. A five-drill bounded run (seed 5,
40 plies, probe cap 10,000, probe depth 3) completed in **11.5 seconds**:

| profile | conversions | other result | exact probe nodes |
|---------|-------------|--------------|------------------:|
| planner | 0/5 | 5 max-plies | about 10,000 total |

This is not yet a conversion win, but it cuts the exact-probe work from the
template baseline's 505,050 nodes to roughly 1,800-2,400 per drill while
preserving a stable plan. Drill 2 exercised two exact herding proofs and 13
modeled choices.

A 120-ply drill-2 run completed in **4.7 seconds** with no exact-probe budget
exhaustions. It kept a defended holder and ended at plan distance 3, with 52
bounded modeled-herding choices. It still failed to convert before max plies,
so the next algorithmic problem is productive long-horizon king herding rather
than simply spending more nodes on the current branching tree.

## Selective depth-two herding (2026-07-13)

Added a separate experimental `herding` profile; the documented `planner`
profile remains the depth-one comparison baseline. The new modeled search:

- keeps every plan-preserving check and beams quiet setup moves to the best
  eight candidates at both our root and recursive choice nodes;
- charges candidate ranking and Zach reply classification to the 5,000-node
  cap and observes a hard 250 ms deadline during both operations;
- memoizes only complete expectimax values, with the halfmove clock and
  repetition history in the transposition key; and
- caches Zach's exact uniform reply pool separately from depth-dependent
  values.

A correctness regression surfaced during the first benchmark: after an
opponent pawn promoted, the stateful bot kept enforcing a king-and-pawns plan
while the new knight chased its king onto the selected pawn's runway. Plans are
now invalidated whenever an opponent mobile piece exists and reconstructed if
the position later returns to king+pawns. Docker regression suite: **14/14
passing**.

The five-drill bounded comparison (seed 5, 40 plies, probe cap 10,000, probe
depth 3) remained **0/5** for both `planner` and `herding`. Wall time was about
11.8 seconds for `planner` and 11.1 seconds for `herding`; drill 2 ended at the
same distance 3/cage 4, although depth two closed one additional outward king
escape at ply 40.

The more relevant comparison used drill 2 for 120 plies across seeds 0-9:

| profile | conversions | other result | mean final distance/cage | mean time |
|---------|-------------|--------------|--------------------------|-----------|
| planner | 0/10 | 10 max-plies | 3.1 / 3.8 | 4.8 s |
| herding | 0/10 | 9 max-plies, 1 repetition | 3.2 / 4.1 | 4.1 s |

Depth two was operationally bounded: all modeled invocations completed their
selective tree, totaling 320,638 accounted nodes, 55,644 Zach replies, 86,278
pruned quiet candidates, and 4,665 cache hits over 59,590 stored entries. It
nevertheless produced no conversion or durable distance improvement and added
one repetition regression. **Do not promote `herding` over `planner`.**

The negative result argues against another move-level depth increase. The next
experiment should search an abstract herding state: selected pawn/side,
opponent king square, open outward squares, and cage/holder invariants. Piece
moves then become macro-actions that close a required escape or force the
next king-square transition. A small route/box policy (or value iteration over
that abstraction) can represent the required 20+ ply objective; the existing
exact probe should still seal the final tactical 4-6 plies. Promotion threats
from non-selected pawns also need an explicit freeze/block priority rather than
being left to the leaf gradient.

## Sub-MDP value iteration and dead-side certificates (2026-07-15)

Reframe: against the fixed Zach kernel this is not adversarial search but a
Markov decision process. During the herd phase nearly every unit is static
(king parked, holder frozen, cage and pawn blockers placed, opponent reduced
to king plus frozen pawns), so the dynamic state is tiny: (their king, one or
two of our free "herder" pieces, side to move). New `losebot/herding_vi.py`
solves that sub-MDP exactly:

- bitboard transition model whose opponent edges mirror `support_zach`
  move-for-move (root pool validated against the real function on every
  build; every fast-path dead end re-classified on a reconstructed board —
  **0 pool mismatches across all runs**);
- goal terminals where the surrounding machinery takes over (their king
  adjacent to the arrival square and contained, or every quiet reply entering
  the defense zone); stalemate/forced-capture/mated-them terminals at 0;
- asynchronous value iteration over the BFS-reachable graph. PyPy solves
  10k-350k states / 60k-2.5M edges in 0.1-4 s per build.

V(root) is a **certificate**: 0 means no herder policy can ever walk their
king into the goal zone under the frozen statics. The first drill runs
returned 0 everywhere — and a coverage dump proved it genuine: in drill 2 the
b-pawn/right construction seals every reachable defense square with pieces
that can never move again (holder covers a6/c6, king-adjacency kills b4/c5,
the b3 pawn kills a4; his king is boxed in a7-c8 with zero zone squares
reachable). The 120-ply "stable plan, distance 3" stalls of the previous
sessions were not search failures; they were geometric impossibilities the
depth ladder could never have detected.

Mechanisms added around the policy (all `vi`-profile only except the two
marked bugfixes, which are shared):

- herder selection prefers pieces whose current square covers defense-zone
  squares (a static queen on d5 seals c5 forever; the same queen as a herder
  is a door that can open);
- dead-side memory plus **prospective side-flip**: on a dead certificate the
  mirrored checked square is certified with the king hypothetically parked
  there; if live, the plan re-commits (drill 2: right side 0.000, left side
  0.94 — the flip fires in-game and the machinery rebuilds on the far flank);
- king-march and cage-build filters: the depth-2 gradient never executes
  either (checks always outscore a one-tempo march; the game_005 carousel
  donated four majors this way), so once the hold is defended the bot commits
  tempo like the hold filter always did;
- forced-capture guard: never leave Zach a pool of nothing but non-mating
  captures (he eats the construction: the bxc5 executioner loss, the Qc7+
  Kxc7 donation), while the one good forced capture — one that mates us —
  stays available because support_zach leaves that pool empty;
- bugfix (shared): `herding_move` now searches only the caller's filtered
  root moves instead of raw legal moves;
- bugfix (shared): the plan-regression filter allows a *transient* runway
  block for marching king steps — Kc4-b4-a4 crosses the runway square, and
  with a5 covered by the executioner it is the only path; the old rule locked
  the king out of its own checked square;
- the policy keeps its waiting moves (twofold repetitions are legal; only the
  bot's own threefold is vetoed) with a least-visited-successor tie-break
  among near-optimal moves.

Results (240 plies, probe cap 10,000, probe depth 3):

| drill (seed 5) | planner | vi | vi certificate story |
|---|---|---|---|
| 1 g-pawn | 0, max-plies, d3 | 0, max-plies, d4 | dead both sides (root 0, mirror unposable) |
| 2 b-pawn | 0, max-plies, d3 | 0, repetition, d3 | right dead / left 0.94 -> flip, herd, ds0, release-blocked |
| 3 h-pawn | 0, max-plies | 0, max-plies | hold never established -> vi never engaged |
| 4 e-pawn | 0, max-plies, d3 | 0, max-plies, d4 | dead both sides (prospect 0.0) |
| 5 a-pawn | 0, max-plies | 0, max-plies | hold never established |

Drill 2 across seeds 0-9: planner **0/10**, every game on the certified-dead
right side, final distance d3, nine max-plies burns. vi **0/10**, every game
flipped to the certified-live left side, four games delivered the defender to
**defender_steps 0** (d2; seed 3: 16 goal-stalls with his king standing on
the defense square), endings split between repetition and fifty-move.

**The conversion blocker is now a single named fact: a piece holding the
arrival square cannot release it.** Sliders re-attack the vacated square
along their retreat line (so the pawn-push "mate" dies to Holder-x-arrival),
knights always re-attack their previous square, and the retreat lines that
could be blocked are covered or physically occupied by the defender himself
(bishop on b5 with their king on c6 has no legal retreat at all; seed-3's 16
goal-stalls are the release scorer correctly refusing every option). Rook and
queen holders are worse: they cover the rank-adjacent defense squares and
deny the zone outright. The one holder type immune to all of this is **our
own king** — a defended arrival square bars a king capture (that is the
load-bearing "only their king can defend the mate square" fact in reverse),
so king-steps-aside is a clean release. The template/planner machinery
currently forbids exactly that configuration (holder must be a non-king
piece; our_king_steps gates assume the king parks on the checked square
before the hold completes).

Next steps, in expected-value order:

1. **King-holder template mode**: king holds the arrival square while the
   cage builds around the checked square, then steps aside as the release.
   Requires template semantics (king-on-arrival during construction) and
   march/cage re-ordering; kills the release problem structurally.
2. In-graph winning-path extraction: Zach's endgame pools are often
   singletons, so the MDP degenerates into a deterministic path problem the
   greedy stationary policy executes badly under the arena's threefold rule
   (repetition draws at plies 56-122). Extract and validate the full path
   against real position history instead of re-argmaxing per ply.
3. Exploit FORCED_MATE terminals (the Qc2+ Kxc2# capture-mate family needs no
   holder release at all); currently none are reachable in the drill graphs,
   which itself is certificate information about the cage shapes being built.
4. Construction-phase gaps: drills 3 and 5 never establish a defended hold,
   so none of this machinery engages; the hold itself needs the same
   commitment treatment on those templates.
5. Fifty-move awareness: the herd phase is inherently reversible, so
   (herd + release + mate) has a hard 100-ply budget from the last capture;
   gamma 0.96 is a proxy, clock-in-state is the real fix.

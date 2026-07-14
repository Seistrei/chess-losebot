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

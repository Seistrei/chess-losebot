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

## Certificate integrity, draw-law alignment, visitation (2026-07-16)

An external review of the VI reframe confirmed the architecture but found
four certificate/scoring bugs, all reproduced and fixed here. The common
thread: every bug lied in the **false-dead direction**, exactly the
direction that misdirects side flips and future motif comparisons.

1. **Partial solves masqueraded as certificates.** `build` marked the report
   ok unconditionally; `_solve` stops silently on its deadline or update
   limit. On the known-live 111,541-state selftest graph, an expired solve
   reported root 0.0 (real value 0.923) — read downstream as a dead side.
   Worse, `prospective_flip_value` used the same builder, and every non-live
   flip outcome (including timeouts and *unposable hypotheticals*) was
   permanently recorded as a dead mirror: one slow build could kill both
   flanks for the rest of the game.

   Fix: the dead/live certificate is now **exact reachability**. Our nodes
   maximize, Zach nodes average a full support, all non-goal terminals are
   0, so fixpoint V(s) > 0 iff s reaches a goal terminal — one backward BFS
   from the goal terminals (`root_live`), computed on the completed graph
   before any Bellman update. Corollary: the explored graph only contains
   root-reachable states, so a dead graph has no goal terminal at all and
   certification costs **zero updates**. Value iteration only ranks moves;
   it now reports `converged` honestly and resumes across moves
   (`solve_more`, worklist kept on the policy) instead of being trusted
   half-baked. Flips fire only on a *completed* live certificate; a dead
   prospect backs off 16 plies, transients 8, and nothing poisons anything.

2. **Dead-side memory was scoped too broadly and survived replanning.** The
   old key was `(pawn_file, checked_side)`, but a certificate is a fact
   about one frozen configuration and one herder subset; a rebuilt plan
   after a promotion inherited the stale verdict and was never recertified.
   Negative memory is now the dead-certified policies themselves: a
   position is known dead only if `contains()` maps it into a certified
   graph (herders may wander — every state of a dead graph is dead — but
   any static change misses and forces recertification). Replanning clears
   the ledger outright.

   And a single dead build no longer condemns the side: deadness is
   monotone in the herder set (an unchosen candidate is frozen; a larger
   subset can replay any smaller subset's trajectory by never moving the
   extra piece), so `_certify_herding` walks every **maximal** herder
   subset — greedy preference first, answered from certificates when
   possible — and only a completed all-dead sweep returns the hopeless
   verdict that gates a flip. Unbuildable subsets (state-cap) are
   remembered and block the verdict rather than counting toward it.

3. **Release scoring ignored the arena's draw law.** It checked only
   checkmate/stalemate after the release, but the arena adjudicates
   fifty-move, repetition, and insufficient material BEFORE Zach replies:
   at halfmove 99 the scorer offered a "guaranteed" zugzwang release and
   the game drew on the spot. The three draw rules now live in one shared
   `arena_draw` predicate (arena, probes via `_probe_draw`, release scorer,
   and the VI candidate veto all call it), so the components cannot drift.

4. **The least-visited-successor tie-break queried keys that were never
   written.** Visits were tallied on positions with LoseBot to move;
   candidates are keyed after LoseBot's move, Zach to move — and
   side-to-move is part of the transposition key, so every lookup returned
   zero and the anti-repetition tie-break was a silent no-op. Visits are
   now tallied on the post-move position of whatever `choose_move` returns.

Also: the review noted "0 pool mismatches" only ever covered the root pool
and the empty-pool slow path. A `validate_pools` audit mode now cross-checks
every explored Zach node against `support_zach`; the selftest runs it (0
mismatches) alongside seven other new regression checks covering all four
fixes (starved-solve honesty, zero-update dead certificates, `contains`
scoping, certificate clearing on replan, sweep reuse, draw-aware releases at
clock 98/99, visit keying).

Revised next steps (supersedes the list above):

1. Extend the certificate through conversion: value goal terminals by
   release feasibility (static holder-geometry test at build; the play-time
   probe stays the exact gate) so "fraction of goal terminals convertible"
   replaces raw delivery as the headline metric. Drill 2's four
   delivered-but-stuck games were invisible to the current goal semantics.
2. Engage-time clock feasibility: expected hitting time from the solved MDP
   + release + mate depth vs the remaining fifty-move budget; release early
   when the budget tightens (log item 5, now cheap to compute).
3. Adjudicate motifs with the extended certificate: pose king-holder
   endgame FENs (the vacate-then-enter race) and the FORCED_MATE
   capture-mate family, and measure conversion probability before building
   template machinery for either.
4. Feed double-dead verdicts back into template selection: a both-flanks
   hopeless certificate should ban the pawn file and re-plan, not shuffle
   to max-plies (drills 1 and 4).

## Sweep honesty and the conversion audit (2026-07-16)

A second review round (external) confirmed the reachability-certificate
architecture and found three more bugs, all in the sweep layer that turns
per-subset certificates into the hopeless verdict — i.e. all three could
misdirect or starve the side flip. Fixed together with the first cut of
revised-next-step 1: the conversion audit.

1. **Subset enumeration silently truncated.** `herder_subsets` capped the
   walk at 12 subsets (and 8 candidates) without telling anyone: six
   candidates with two herders is C(6,2)=15 maximal subsets, so an all-dead
   walk over 12 could return `hopeless=True` while three subsets — possibly
   the live ones — were never examined. The subset cap is gone (builds are
   the expensive part and the sweep deadline already bounds those); the
   candidate cap survives as a combinatorial guard but the function now
   returns `(subsets, complete)` and a truncated enumeration blocks the
   hopeless verdict exactly like an exhausted budget does.

2. **The dead-policy ledger evicted mid-sweep.** Eight retained policies
   against sweeps that can hold 15+ subsets: with roughly one build fitting
   per turn, eviction made later sweeps rebuild earlier subsets forever and
   the all-dead verdict never arrived. Dead certificates now
   `strip_to_certificate()` — a dead policy only ever answers
   `contains()`/`dynamic_squares()` again, so it sheds edges, values, and
   solver state and keeps just the state-index keys and the static split —
   and the ledger cap rises to 64, comfortably above any real enumeration.
   Play-time interfaces (`ranked_moves`, `state_value`, `solve_more`)
   refuse on stripped policies rather than reading freed arrays.

3. **Oversized-build memory ignored the dynamic root.** The unbuildable
   fingerprint (arrival, herder types, static placement) deliberately
   excludes their king and the herder squares — right for dead-graph reuse,
   wrong for state-cap/timeout failures, whose reachable-graph size is a
   property of the root. One king-in-open-space blowup permanently banned a
   configuration that becomes affordable once the king is boxed. State-cap
   failures are now remembered under a **rooted** fingerprint (fingerprint
   + their king + herder squares); a configuration that blows up from a
   second distinct root graduates to the config-wide skip.

**The conversion audit (instrument first, gate later).** `root_live` means
a *proxy* goal is reachable; the audit asks whether any reachable goal
actually converts. At build time every goal terminal is reconstructed on a
real board and scored with the same `score_release_moves` the bot runs at
play time (plausible releases probed first, budget `vi_conversion_ms`,
default 3s), so the report now carries `goal_states`, `converting_goals`,
`conversion_complete`, and `root_converts` — and `root_converts=True` is a
positive fact about the root, since every explored state is root-reachable.
Once any goal converts, terminal seeds become the audited race
probabilities (refused goals drop to 0) so the ranking steers toward goals
that finish; with none, the flat proxy seeding is kept — silencing the
policy without a better move on offer would only trade a confident stall
for a fallback shuffle.

Deliberately NOT gated yet: play and flips still key on `root_live`. Every
current template is a piece-holder construction, so per the release theorem
both flanks audit unconvertible — gating now would thrash flips between
two dead sides with nothing to steer to. The gate lands with the
king-holder template, when a convertible side can exist.

Evidence the instrument works:

- Standard fixture (13b): root_live, root 0.923 — and **0 of 260 goal
  terminals convert** (audit complete). The bishop holder re-attacks b5
  from every retreat; their king's defense only bars OUR king from
  recapturing, so the retreated holder refutes the mate itself.
- Case-2 seed-5 drill (the review's reproduction): same 42 VI moves,
  root 0.528, 0 releases — but the vi line now reads
  `goals-convert=0/17 (of 17 goal states, 0 audits cut short)`. The
  120-ply stall announces itself at build time.

Selftests: 24 -> 28 (subset truncation, rooted oversize memory, stripped
certificates, live-but-unconvertible audit), all green.

Next: pose the king-holder vacate-then-enter FENs and the FORCED_MATE
capture-mate family and adjudicate them with the audit (log items 1+3
above) BEFORE building template machinery; then gate flips/seeding on
audited conversion and add the fifty-move clock feasibility check.

### Review round 2 follow-ups (2026-07-16, same day)

The reviewer re-checked the fixes above and caught three real problems in
them; all three taken.

1. **The two-strike escalation was the original sin at threshold 2.** Two
   oversized roots prove nothing about a third, and since
   `skipped-unbuildable` blocks the hopeless verdict anyway, the config-wide
   skip never unblocked anything — it only saved wall time the sweep
   deadline already bounds, at the price of permanently suppressing roots
   that may become affordable as the king gets boxed. Removed: oversized
   memory is rooted keys only, no strike count. (Bare config-level keys are
   still honored by `build` for callers that pass one explicitly.)

2. **Mixed-scale seeding.** Audited seeding kicked in as soon as one goal
   converted, but goals the audit deadline never reached defaulted to 1.0 —
   so an unknown proxy could outrank a known conversion worth less than 1,
   and with plausible-first probing the unchecked goals are precisely the
   ones ranked least likely to release. Now: once anything converts, forced
   mates seed 1, audited goals seed their race odds, refused AND unchecked
   goals seed 0. A known conversion always outranks an unknown proxy.

3. **FORCED_MATE is a conversion.** It was excluded from the audit, so a
   graph whose only real wins are forced mates reported
   `root_converts=False` — the exact misread that would sink the
   capture-mate-family motif experiment. The report now carries
   `forced_mates` and `root_converts` is true when forced mates exist or
   any audited goal converts (and seeding then steers to them).

Also: refused release probes now bill their spend (`nodes_out` accumulator
on `score_release_moves`), so `conversion_nodes` explains audit cost —
case-2 seed-5 now reads `goals-convert=0/17 (of 17 goal states, 0 forced
mates, 0 audits cut short, 156163 probe nodes)` with play unchanged.

Protocol note for the motif experiments, per review: a NEGATIVE motif
verdict (root_converts=False read as "this device cannot finish") is only
admissible when `conversion_complete` — an audit cut short is unknown, and
in-game 3s audits of large graphs will usually be cut short. Positive
verdicts are facts at any coverage.

Lock-in tests added per review: (a) an organic forced-mate-only fixture —
`8/8/8/R7/8/3PPk1p/6RP/6BK w` — their king boxed by statics, hxg2 (a
forced capture-mate) the only legal reply after most herder waits: 11
FORCED_MATE terminals, zero proxy goals, and the report must read
root_converts=True with conversion_checked=0 and the policy steering at
the mate (root 0.990); (b) the mixed-seeding case, injected white-box into
the 14d build (an organically converting goal terminal IS the king-holder
problem): one checked goal at 0.4 + audit cut short must converge to root
0.277 — under the old unchecked-goals-seed-1.0 bug it converges to ~0.787,
so the test fails loudly on regression. Suite now 30 checks.

## Motif adjudication: the king-holder release converts (2026-07-16)

Ran the planned motif experiments (log items 1+3 above) with a new
`motifs` CLI harness (`losebot/motifs.py`): fixture FENs adjudicated by
`HerdingPolicy.build` under research budgets (`--conversion-ms`/
`--budget-ms` 60 s, `validate_pools=True`), with the reviewer's protocol
built in — a root that classifies terminal (or has no free herders) cannot
be audited by the build, so the harness calls `score_release_moves()` on
it directly, which is what play would do on arrival. Negative verdicts are
reported only under `conversion_complete`; positives are facts at any
coverage.

One structural gap had to be fixed first: with our KING as the arrival
holder, every defense-zone square is adjacent to the arrival square and
therefore king-attacked, so GOAL_CONTAINED/GOAL_RACE could never fire — a
king-holder build read as dead for a reason that had nothing to do with
the position (the false-dead direction again, this time by construction).
King-holder graphs now classify a third goal, **GOAL_VACATE**, against the
hypothetically vacated position: our-move states where the vacate (arrival
-> checked square) is legal and every post-vacate quiet reply enters the
defense zone. The mating pawn's premature push — legal the instant the
king steps off — is deliberately invisible to the proxy and priced exactly
by the audit, where it is the losing side of the scored race.
`_release_plausible` also learned that a king's re-attack of the vacated
square refutes nothing (the defender that makes the state a goal also bars
the king capture), so king releases are probed first, not last.

FEN design was itself probe-driven, and the failures were the lesson:

- an escape-square occupant diagonally adjacent to the mating pawn is
  pawn-food (`bxa5` ate the a5 knight of the first b-file design and
  escaped the lock through the capture);
- a rank pin on the mating pawn can gate the premature push, but the same
  pin makes the mate illegal once the defender enters on the pin line, and
  pinning through the entry square makes the entry unstandable — the pin
  family is closed;
- the sound economical geometry is the CORNER: checked square h1/a1,
  escapes = own bishop on g1/b1 (uncapturable: the pawn's capture squares
  are kept empty), one square covered by the entering defender itself, and
  the arrival square (king capture barred). The closer is a knight move
  that seals the defender's retreat without check — a rook check there
  mates THEIR king (misère loss), which the graphs record as mated-them
  traps the policy correctly prices at 0.

Results (all audits complete; `pypy3 -m losebot motifs`):

| fixture | family | verdict | odds | mechanism |
|---|---|---|---|---|
| kh-corner-h `5N2/8/8/R7/5P1k/5Pp1/6K1/6B1 w` | king-holder | **POSITIVE** | 0.500 | root is GOAL_VACATE -> root-already-terminal -> direct scoring: Kh1! accepted, {Kh3 -> Ng6! g2# forced} vs premature g2+ |
| kh-corner-a (a1 mirror, b-pawn) | king-holder | **POSITIVE** | 0.500 | Ka1! / Nb6! / b2# — drill-2-flavored flank |
| kh-herd-h4 `5NN1/.../R5B1 w` | king-holder | **POSITIVE** | 0.500 | full VI build: pocket {h4,h5}, policy waits out parity, Ra5+ on the h5 beat (Ra5 on the h4 beat is stalemate), 7 goal-vacate terminals, **6/7 audit convertible**, root 0.480 |
| fm-organic-h (14g) | forced-mate | POSITIVE | 1.000 | 11 forced-mate terminals, zero goals — baseline |
| fm-organic-a (a-side mirror) | forced-mate | POSITIVE | 1.000 | axb2# family mirrors cleanly |
| fm-deep-h `R7/8/8/8/8/3P1k1p/6RP/3N2BK w` | forced-mate | POSITIVE | 1.000 | 2,750 states: rook must seal rank 5, shuffle, drop to rank 4 on the f3 beat; 6 forced mates deep in the graph, 56 junk proxy goals all audited 0 and seeded 0, root 0.990 |
| ph-contained-root (bishop holder, Kc5 contained) | piece-holder | NEGATIVE | — | terminal root -> direct scoring refuses every retreat (each re-attacks b5 along the vacated diagonal) — the release theorem, now a regression fixture |

The one refused king-holder goal is the best evidence the instrument
works: with the herder rook on g5, the audit refuses the vacate because
after g3-g2 the push itself vacates g3 and the rook re-attacks the mate
square through it — the slider rule extends to lines the mating push
opens, and the audit found that without being told.

What the numbers say about the motif: the premature push puts a hard
floor under the race — the vacate legalizes the push and the entry in the
same tempo, so the post-vacate pool is never smaller than {enter, push}
and a single-entry corner converts at 1/2 per attempt. The push branch is
not a loss (our king recaptures, resetting the fifty-move clock) but it
eats the mating pawn, so the race is one-shot per usable pawn. Verdict:
**the king-holder template machinery is now justified** — the release
that was structurally impossible for piece holders is probe-accepted and
audit-visible end to end for king holders.

Lock-ins (suite 30 -> 34): terminal-root fallback scores Kh1 at 1/2;
GOAL_VACATE graph audits 6/7 with zero pool mismatches; the piece-holder
terminal root stays refused; deep forced-mate reachability converts
through 56 refused proxy goals with mated-them traps priced at 0.

Next, in expected-value order:

1. King-holder template mode in the planner/bot: allow holder==our king
   (template semantics currently force a non-king holder and assume the
   king parks on the checked square before the hold completes), order the
   march/cage so the king takes the arrival square last, require a
   knight-class closer to exist, and gate the vacate on the audited race
   (GOAL_VACATE at play time = `score_release_moves` accepting).
2. Then gate side-flips and terminal seeding on audited conversion
   (deferred in the previous entry precisely until a convertible side
   could exist — it now can).
3. Multi-pawn race stacking: the push-reset consumes one pawn; a
   construction whose reset re-poses a second template would compound
   1/2 -> 3/4. Needs a fixture before any machinery.
4. Fifty-move/clock feasibility from the solved MDP (unchanged).

### Review round 3 follow-ups (2026-07-16, same day)

External review of the motif work found two P1s and two P2s; all four
taken. The reviewer's bottom line stands after the fixes: the positive
king-holder conclusion was already credible (it rests on completed PROVEN
releases), and the repairs are about making NEGATIVES trustworthy.

1. **Post-vacate attack maps included their king as a slider blocker.**
   `_white_attacks` deliberately leaves their king out of the occupancy so
   rays pass through it (a king cannot step backward along the ray that
   checks it); the new `_their_quiet_moves_vacated` reused one occupancy
   mask for both destination filtering and attack generation, so a ray the
   vacate opened onto their king stopped AT him and the square behind him
   entered the fast pool as a legal retreat. Under-classification in the
   false-dead direction. Fixed to mirror `_white_attacks`; the shipped
   fixtures were unaffected (the reviewer cross-checked every state — no
   through-king geometry occurs in them; the rerun reproduces 6/7 at race
   0.500 exactly), and regression 19e now compares the fast vacated pool
   against real-board legality on a position where the old code admits the
   illegal retreat (rook ray opening across the vacated square, h4 behind
   the checked king).

2. **UNKNOWN counted as a losing reply, so refusals could be budget
   artifacts.** Conservative and correct for ACCEPTANCE (a reply only
   counts winning on a completed PROVEN probe, so offered races are sound
   lower bounds — play is unchanged), but a refusal that leaned on an
   UNKNOWN probe is the probe-tri-state lesson relearned: with
   `--probe-cap 0` the known-positive kh-corner-h read NEGATIVE.
   `score_release_moves` now reports unknown-tainted refusals
   (`unknown_out`, same accumulator convention as `nodes_out`); the audit
   counts tainted goals in the new `conversion_unknowns` and
   `conversion_complete` is False whenever it is nonzero — so the protocol
   ("negatives require conversion_complete") automatically rejects starved
   negatives. The motif harness distinguishes the three outcomes in its
   verdicts: POSITIVE / NEGATIVE (all refusals DISPROVEN) / UNKNOWN
   (starved or cut short). Measured fallout: none — the 14d bishop-holder
   audit, the ph-contained-root NEGATIVE, and the case-2 seed-5 in-game
   audits (0/17 at the 6,000-node play cap, 156,163 probe nodes) all
   re-verify as DISPROVEN-clean, so no previously recorded negative was
   starved.

3. **`motifs --probe-cap` only reached direct terminal scoring.** Graph
   audits silently kept the 6,000-node play default. `build` now takes
   `conversion_probe_cap` and the CLI passes its research cap (default
   50,000) to both paths.

4. **The vacate could teleport.** Nothing checked that the target's
   checked square is one king step from the arrival square, so an ad-hoc
   stub could classify GOAL_VACATE through an impossible move. King-holder
   mode now requires `square_distance(checked, arrival) == 1` and shuts
   itself off otherwise (regression 19h: a bogus checked square yields
   zero goals and a dead root instead of teleport goals).

Suite 34 -> 38 (through-king pool vs ground truth; starved refusal
reporting with a clean-refusal contrast; audit taint through the
`conversion_probe_cap` plumbing at cap 0, 7/7 tainted; teleport guard).
Full motif suite re-run: verdicts and odds unchanged, with every audit
line now carrying its starved-refusal count.

## King-holder template mode: first full-game conversions (2026-07-17)

Log item 1 built: the planner/bot can now construct, hold, and release the
adjudicated corner king-holder device end to end. **Result: the new
construction drill converts 5/10 seeds from an unassembled start — the
first full-game conversions this project has ever produced** (every
piece-holder drill in the log: 0).

Template layer (`templates.py`): `pawn_mate_templates` emits a king-holder
variant alongside each piece template when the adjudicated geometry can
possibly close — checked square is a CORNER, a knight-class closer exists
(the sealing move must not check), and a bishop of the cage square's color
complex exists. The corner fixes every special square as a function of
(arrival, checked): the cage square (arrival file at corner rank — our
bishop, the only sound piece there: rook/queen re-attack the arrival
square and refute the mate, a knight covers the defender's entry), the
file escape (kept empty, defender-covered, also a pawn-capture square),
the defender entry, the knight's seal square, and the far pawn-capture
square. For king-holder templates `our_king_steps` measures the march to
the ARRIVAL square, `cage_occupancy` is the single bishop, and
`ready_to_release` is constant False — the vacate is never granted by
filters. `ConstructionPlan` gains `holder_mode` ("piece"|"king"): plans
are mode-committed so the resolver cannot flip constructions move to
move. `best_pawn_mate_template` prefers king-holder over any piece
distance (a completed piece hold is worth zero by the release theorem; the
corner race is worth 1/2). Note this preference is enumeration-wide, so
pre-planner profiles could in principle see it — but only when a corner
template exists (pawn at its pre-corner square + knight + right-shade
bishop), which no legacy fixture start position has.

Bot layer (`bot.py`): the hold filter pivots on the new
`hold_established` (piece: holding blocker; king: king parked on
arrival) so the parked king cannot wander; the release still deliberately
bypasses it. Ordering is committed as "cage first, king takes the arrival
square LAST" (pre-park construction can still reset the fifty-move clock;
post-park play is all reversible): a regression-filter clause vetoes
parking before the cage exists, the march filter gates king mode on the
cage bishop being placed, and the cage filter routes the cage-colored
bishop with landing-dominates-approaching commitment — the fallback
search cannot rank those two because an adversarial premature-push line
washes every candidate to the same template loss (found by the failing
selftest: it played Be3 over Bg1 on a tiebreak). The transient-runway
regression clause is piece-only now, since for a king holder the "runway"
square IS the cage square. `_vi_choice` gains king-mode entry gates
(parked + caged + corner free) and the existing `defender_steps <= 1`
release path is the vacate gate: GOAL_VACATE at play time IS
`score_release_moves` accepting, exactly as specified. Side-flips carry
`holder_mode` (the corner's mirror is never a corner, so king-holder
flips resolve to nothing and back off harmlessly). Heuristics: runway
penalty gated off for king mode; hold bonus via `hold_established`; two
new defaulted profile weights (`kh_bishop_pull`, `kh_knight_pull`, set on
PLANNER lineage only) pull the cage bishop toward the corner and keep a
knight in seal range. `endgames` now actually forwards `--vi-herders`
(the flag existed but was dropped on the floor).

Drill (endgames case 6, `R4N2/8/2k5/8/3B1P2/5Pp1/8/5K2 w`): king f1,
bishop d4, rook a8, knight f8, pawns f3/f4 vs king c6 + g3-pawn. The bot
must cage (Bg1), march (Kg2 — two plies of premature-push exposure,
~1/pool per Zach move), VI-herd the king from c6 through the h6 door into
the {h4,h5} pocket, close the door and time Ra5+, then win the audited
vacate race. Drill design lesson: the first pose kept BOTH knights
(g6+h6 sealed) and certified live-but-unconvertible with the defender
outside — a sealed pocket cannot be entered; the h6 door with the rook
closing it behind him is what makes the herd reach the goal states
(pre-flight: live, complete audit, 6/8 goals convert at race 1/2).

10 seeds, `--profile vi --vi-herders 1`: **5 converted** (34-90 plies,
each ending in the exact motif mate g3-g2# against Kh1), 3 threefold
repetitions DURING the herd (the documented deterministic-Zach
path-extraction item, unchanged — now with a 1-second repro), 2 races
lost to the premature push (the accepted 1/2 branch; single executioner
by design — both ended as stalemates because with the pawn burned the
rook seal leaves Zach no moves). Releases offered 7, won 5. Regression
sweep: selftest 38 -> 43 all green (enumeration/preference/mode
commitment; knight+bishop existence gates; cage-before-march with the
early-park veto; march commitment; sealed-vs-unsealed vacate gating);
motif suite verdicts and odds unchanged; case-2 seed-5 reproduces its
documented line (fifty-move, 125 plies, 0/17, 156,163 probe nodes).

### Review follow-up (2026-07-17, same day)

External review found one P2, taken: the deep-probe gate compared every
template against `deep_probe_min_cage=3`, a piece-holder reserve size,
while a finished corner cage is exactly one bishop — so king-holder mode
permanently reduced the exact probe to depth 1 (`deep_probe_skips=1`,
`deepest_probe_completed=1` on kh-corner-h). The corner drill never
misses a net that way (the premature push refutes any proof line through
the vacate), but in general king-holder positions — a second mobile pawn,
a half-built construction — organic multi-move forced selfmates are real
(the fm-organic family), the probe is the only machinery that finds them,
and a forced win must outrank a 1/2 race. The gate now compares against
the template's own `required_cage`; regression 20e locks in skips=0 with
disproofs completing at n>=2 and the choice still falling through to the
scored vacate (suite 44). Deliberately NOT added: a "their king is the
only mover, no net can exist" fast-out — it is unsound, because a frozen
executioner unfreezes inside probe lines the moment the probe tries our
king stepping off the arrival square. Measured cost: the pocket-phase
moves now burn their full probe budget as disproofs (drill games ~1s ->
~13-16s, ~1-1.5M nodes; outcomes and move sequences unchanged on re-run
of a converted and a race-lost seed). If drill wall time ever matters,
the knob is probe-cap tuning at low mobility, not re-blinding the gate.

Next, in expected-value order:

1. In-graph path extraction / anti-threefold herding (now 3/10 of drill
   seeds and the biggest single loss source): Zach's endgame pools are
   often singletons, so the stationary VI policy retraces positions into
   the arena's threefold rule even with the least-visited tie-break.
2. Gate side-flips and terminal seeding on audited conversion (log item
   2, unchanged) — a convertible side now exists to steer toward.
3. Adoption pressure for king-holder plans in full games: the corner
   template only exists once the executioner reaches its pre-corner
   square, but piece-holder plans freeze the pawn far from it. Needs a
   freeze-release / pawn-advance choreography before the mode can fire
   from the standard fixtures.
4. Multi-pawn race stacking; fifty-move feasibility from the solved MDP
   (unchanged).

## Anti-threefold herding: repetition burning in the sub-MDP (2026-07-17)

Log item 1 built. **Case-6 drill, 10 seeds: 7 converted / 1 fifty-move /
2 stalemates / 0 repetitions** (baseline reproduced first: 5 / 0 / 2 / 3)
— threefold, the biggest single loss source, is eliminated, and 7/10 is
the best full-game conversion rate the project has produced.

The diagnosis the baseline PGNs confirmed: the arena draws the third
occurrence of a position, and during the herd it can complete AFTER
Zach's reply, on an our-turn state that no tally of our own successor
choices can see coming. In the seed-6 shuttle (11.Rf5 Kh6 12.Rf7 Kh5
13.Rf5+ Kh6 14.Rf7 Kh5 15.Rf5+ Kh6 draw) every rook move landed on a
FRESH their-turn position — the funnel state (rook f5, king h6, us to
move) was the twice-seen one. The least-visited tie-break was
structurally blind to that side of the move alternation, and its
lifetime tallies also wandered value plateaus (seed 2's
Re1/Re2/Re3/Re6/Re1 noodling), so it caused drift without preventing
draws.

The fix prices the rule into the model instead of patching the
tie-break. Every sub-MDP state is one real position (the statics never
move), so `HerdingPolicy.apply_repetition_history` recounts the game's
reversible era each move — the same span `is_repetition` scans, walked
on a stack copy — maps every position onto a graph state (their-turn
positions included, via the new `_state_of`), and pins each twice-seen
state at value 0: re-entry IS the draw, a losing terminal for as long as
the era lasts. Decreases propagate through the same resumable worklist;
resuming is still sound because discounted Bellman is a sup-norm
contraction (the old monotone-from-below claim in `solve_more` is gone —
burns approach the new fixpoint from above). An irreversible move resets
the era and the same diff un-burns: NORMAL states re-derive by Bellman,
WIN terminals restore their audited seed values exactly (the seeding
logic now lives in `_terminal_seed_value`, shared by `_seed_solver` and
the restore). Certificates are untouched: burning prices play, never
deadness, and `root_live`/dead ledgers keep their build-time meaning.

On the shuttle position the repricing is visibly correct: Rf5+'s child
averages Zach's {Kh4 -> pocket, Kh6 -> burned draw} pool and drops
0.417 -> 0.240 — the gamble is priced, not vetoed, and is taken only
when nothing safer outranks it.

Play-time consequences in `_vi_choice`:

- Era counts (by graph state, from the same walk; `ranked_moves` now
  returns the child index) replace the `_vi_visits` lifetime tally as
  the freshness tie-break, and the tally is deleted — it counted the
  wrong side of the alternation across the whole game instead of the
  era, and its test (old 16) with it.
- The near-optimal window shrinks from an absolute 0.05 to ONE OPTIMAL
  PLY (floor = top * gamma). The wide window was the tie-break's escape
  hatch back when it was the only threefold defense; with burning in the
  values it only bought freshness detours — at herd-typical values under
  gamma 0.96, 0.05 admits ~13-ply regressions. Measured: the burn-only
  intermediate config converted 4/10 with the freed games dying at
  exactly ply 100 (48 policy moves, zero goal states reached); the
  tightened window converted 7/10.
- The immediate arena_draw veto on candidates stays: it is the one law
  the clockless sub-MDP cannot price (a quiet move that lands on the
  fifty-move adjudication).

Loss taxonomy after the change: both stalemates are the accepted
1/2-race branch (9 of 10 seeds reached the goal and offered the scored
release — seed 2 excepted — 7 races won, 2 lost; every conversion ends
in the exact motif mate g3-g2#). Seeds 3/5/8 reproduce byte-identically
(pure-argmax lines, burn-updates=0). The remaining fifty-move draw
(seed 2, burn-updates=10, 13 states burned) is a slow-herd clock death:
the rook holds the h6 door for 48 policy moves while Zach's king
oscillates g7/g8/h8 and the clock expires with zero goal states reached
— log item 4 (clock feasibility) now cleanly exposed instead of masked
by the repetition rule. New diagnostics: `burn-updates=N (M burned at
end)` in the endgames and arena vi lines.

Suite 44 -> 45 (one test replaced by two): the seed-6 shuttle regression
replays the drill's exact 28-ply prefix and asserts the funnel state is
counted twice, burned, and pinned at 0.0; Rf5+ reprices 0.417 -> 0.240
while the root stays live through alternatives; and an era reset
restores 0.417 to 7 decimals. The mechanics test on the two-rook fixture
locks in pin-in-place (child and WIN-terminal both 0.0 exactly),
deconverge-then-drain honesty on each diff, and exact seed-value
restoration.

Full regression battery: selftest 45/45; motif suite verdicts and odds
byte-unchanged (kh-corner-h/a and kh-herd-h4 POSITIVE 0.500, fm-organic
and fm-deep POSITIVE 1.000, ph-contained-root NEGATIVE all-DISPROVEN).
Case-2 seed-5 keeps its documented outcome and length — fifty-move in
125 plies, 0 goals converting with 0 audits cut short and 0 pool
mismatches, so the piece-holder unconvertibility fact stands — but the
middle game legitimately diverges (47 VI moves vs 42, 18 goal states vs
17, 173,353 audit probe nodes vs 156,163): the tie-break source and
window changed, so this entry's line is the new reference. Its vi line
also shows `burn-updates=13 (0 burned at end)` — the un-burn-on-era-
reset path exercised by a real game, not just the white-box test.

Next, in expected-value order:

1. Gate side-flips and terminal seeding on audited conversion (log item
   2, unchanged) — a convertible side now exists to steer toward.
2. Adoption pressure for king-holder plans in full games (unchanged):
   piece-holder plans freeze the executioner far from its pre-corner
   square; needs freeze-release choreography.
3. Fifty-move/clock feasibility from the solved MDP — promoted by the
   seed-2 result: with threefold priced, the clock is the herd's binding
   constraint, and the policy still cannot see it.
4. Multi-pawn race stacking (unchanged).

### Review follow-up (2026-07-17, same day)

External review of the burn work found one P1 and one P3; both taken,
plus one same-defect fix next door that the P1 exposed.

1. **The era walk crossed real repetition boundaries (P1).** The walk
   was bounded by the halfmove clock, but the boundary `is_repetition`
   scans to is the last IRREVERSIBLE move — and a first king or rook
   move strips castling rights (irreversible for repetition purposes)
   without resetting the clock; ceded en passant is the same trap.
   Graph states carry no rights, so the clock-bounded walk merged
   positions from either side of a rights change: from
   `k7/8/8/8/8/8/8/4K2R w K - 0 1`, the shuttle Rh2 Ka7 Rh1 Ka8 gives
   `is_repetition(2) == False` — the start still has the right the
   return position lost — yet the old walk counted one graph state
   twice and burned it, falsely rejecting live paths. Reachable in
   full games whenever a rights-bearing king holds while an original
   rook herds; inert in every drill and fixture (rights are "-"
   everywhere the log has numbers), which is why nothing caught it.
   The walk now mirrors `is_repetition` exactly — pop, stop on
   `is_irreversible` without counting the far-side position — and the
   soundness argument is in the docstring: inside the true era every
   position shares one castling/ep state, which is exactly what makes
   placement plus side-to-move a complete repetition identity for
   graph states. Regression 16c locks in both halves on a real build:
   the rights-crossing shuttle burns nothing (walk max count 1), the
   same shuttle replayed inside the stripped era is a genuine twofold
   and burns all four of its states.

2. **`_history_counts` had the same clock bound (adjacent fix).** The
   probes' repetition law is under the same share-the-arena's-draw-law
   contract, and its root walk had the identical defect. Overcounting
   across a rights boundary can only declare phantom draws — false
   refusals, never false proofs — and only in rights-bearing
   positions. Same fix, same boundary semantics.

3. **The burn gauge outlived its policy (P3).** `_reset_vi_state`
   dropped the active policy but left `vi_burned_states` at its last
   reading, so a replan, promotion, side flip, or rewind followed by
   game end reported "N burned at end" that no live policy contained.
   The gauge now zeroes wherever the active policy is dropped or
   replaced (plan reset, state-miss drop, and rebuild — a fresh build
   carries no burns until its first era recount) while
   `vi_burn_updates` stays cumulative; folded into regression 17.

Suite 45 -> 46. Full battery: the 10-seed drill reproduces byte-for-
byte in moves, outcomes, and every counter EXCEPT the two race-loss
seeds' gauges — seeds 7/9 now end `(0 burned at end)` instead of
`(11/7 burned at end)`, which is the P3 scenario itself (lost race ->
plan invalidated -> policy dropped -> game ends) reporting honestly.
Motif verdicts and odds unchanged; case-2 seed-5 reproduces its
reference line exactly (fifty-move, 125 plies, 47 VI moves, 0/18,
173,353 probe nodes, burn-updates=13 with 0 burned at end).

## Conversion-gated side flips and the side-level certify verdict (2026-07-17)

Log item 2 built — the deferred half of "gate side-flips and terminal
seeding on audited conversion". The seeding half landed with the audit
itself (terminal seeds become audited race odds once anything converts);
what remained was play and flips keying on `root_live` alone, which is
how a live-but-unconvertible side herds into the 42-move stall with the
flip machinery never even asked. Both now key on the audit:

- `_certify_herding` returns a side-level verdict, not a hopeless bool.
  The sweep short-circuits only on a live subset whose audit found a
  conversion (`"converts"` — positives are facts at any coverage, and
  the common case still costs one build), keeps the first merely-live
  subset as the playable fallback, and continues hunting a convertible
  one. `"unconvertible"` demands the whole ledger of negatives be
  complete — sweep finished AND every live subset's audit complete
  (deadline-clean and UNKNOWN-free) — mirroring exactly how
  `"hopeless"` requires every maximal subset dead; anything less is
  `"live"` and blocks the trigger. Play still herds the fallback under
  every live verdict: gating PLAY on conversion would silence the
  policy without offering a better move (the session-4 deferral
  reasoning, unchanged) — the verdict's job is to arm the flip.
- `_consider_side_flip(require_conversion=...)` -> bool: leaving a LIVE
  side now requires a mirror prospect that positively converts
  (`root_converts`: forced-mate pockets or accepted release races); a
  hopeless side keeps accepting any live prospect, since there is
  nothing to stay for. A live prospect refused under the gate backs off
  16 plies when its audit completed, 8 when starved (more budget could
  flip it); the prospect is a single greedy-subset hypothetical, so a
  refusal only ever sets a cooldown, never a verdict about the mirror.
  Unconvertible sides also RE-consider the flip whenever the cooldown
  expires: certification only reruns on rebuilds, which a stable herd
  never triggers, and the prospect's convertibility is
  position-dependent (their king drifts, forced-mate pockets open).
- No flip thrash by construction: leaving A for B requires B to convert
  while A provably does not. And since plans are mode-committed and a
  king-holder mirror has no corner (kh mirrors never pose), today the
  gated flip can only fire toward a piece-mode mirror with reachable
  FORCED_MATE terminals — precisely the fm-organic capture-mate family.
- Diagnostics: `unconvertible-sides` (certify verdicts) and
  `conversion-gated` flips in the vi line; a mid-sweep config-level
  refusal after a live fallback exists no longer discards the fallback
  (the reason must be subset-dependent — a config-wide one would have
  refused the fallback's build too); it marks the sweep incomplete.

Suite 46 -> 48. Regression 21a locks the sweep continuation on the 14d
fixture: the greedy rook subset is live with a complete 0/7 audit, the
sweep must BUILD THE SECOND rook subset too (builds=2 where the old
sweep stopped at 1), and only then pass "unconvertible" with the first
subset as the playable fallback. Regression 21b white-boxes the flip
decision table at the prospect (the suite has no organic position whose
MIRROR prospect converts yet): converting prospect fires the gated flip
(and counts it), complete-audit refusal backs off 16, starved refusal
8, and the hopeless path keeps firing on any live prospect. Test 18's
unpack moved to the verdict ("hopeless").

Full battery:

- Case-6 drill, 10 seeds, `--profile vi --vi-herders 1`: **7 converted
  (48/52/34/64/42/38/34 plies) / 1 fifty-move (seed 2) / 2 stalemates
  (seeds 7/9), byte-identical to the session-6 reference** including the
  race-loss gauges' honest `0 burned at end`. Every seed prints
  `unconvertible-sides=0; side-flips=0`: the king-holder side certifies
  "converts" on its first subset (goals-convert=6/8), so the gate adds
  zero builds and zero behavior change where conversion already worked.
- Case-2 seed-5: **same game to the move** — fifty-move in 125 plies,
  47 VI moves, burn-updates=13 (0 burned at end) — but the diagnostics
  now tell the story the postmortems used to reconstruct by hand:
  builds=10 with the sweep continuing past live-unconvertible subsets
  (48 goal states audited across configurations vs 18, all audits
  complete, 0 converting, 489,394 audit probe nodes vs 173,353),
  `unconvertible-sides=2` (the piece side's complete negative, twice),
  side-flips=1 with 0 conversion-gated — the pre-existing hopeless-path
  flip; every gated reconsideration declined (prospect=None / the piece
  mirror never converts) and play correctly kept herding the live
  fallback instead of being silenced. Wall ~43s (was ~13-16s): the
  price of sweeping the whole subset ledger is the honest cost of
  certifying the side-level negative. This entry's line is the new
  case-2 seed-5 reference.
- Motifs: verdicts and odds byte-identical (kh-corner-h/a and
  kh-herd-h4 POSITIVE at 0.500; fm-organic-h/a and fm-deep-h POSITIVE
  at 1.000; ph-contained-root NEGATIVE, all refusals DISPROVEN).

Next, in expected-value order:

1. Adoption pressure for king-holder plans in full games — now the
   natural client of the verdict: plan REPLACEMENT (not just side
   mirroring) should key on the same audited-conversion facts, steering
   a piece plan whose side certifies unconvertible toward a corner
   template instead of merely toward its own theorem-dead mirror.
2. Fifty-move/clock feasibility from the solved MDP (unchanged; drill
   seed 2 is still the standing repro).
3. Multi-pawn race stacking (unchanged).

## King-holder adoption pressure: walking templates and the freeze release (2026-07-17)

Log item 1 built — the corner motif now has a road into positions that
never posed it. A king-holder template only exists once the executioner
stands on its pre-corner square, and every plan built before that point
froze the pawn ranks away; the sides that certify unconvertible had
nothing to steer toward, because their mirrors are the same release
theorem reflected. Adoption closes the loop:

- **Walking templates.** `pawn_mate_templates` emits a PROSPECTIVE
  king-holder template for each b/g-file pawn of theirs still above its
  pre-corner square: corner, cage, entry, seal, far-capture and the new
  closer-park square all fixed by the FINAL arrival; `pawn_walk` counts
  the outstanding Zach pushes (double-push discounted); `walk_blockers`
  counts OUR movable men on the path — the freeze-release debt
  (2·walk + blockers joins setup_distance). Emission is walk
  feasibility: a man of theirs on the path is uncleanable by us (the
  LOWER pawn emits instead, with the shorter walk), a PAWN of ours on
  the path or the arrival square can never leave the file (case 2's b2
  pawn — which is why that battery reference cannot shift), and the
  knight-closer / cage-shade-bishop gates are checked against the final
  geometry. `best_pawn_mate_template` EXCLUDES walking templates: they
  resolve only for a plan already committed to the adoption. Fresh
  plans never start speculative — steering is keyed on the verdict.
- **The trigger.** `_consider_kh_adoption` fires from the same certify
  verdicts that arm the flip, after the flip declines: unconvertible
  keeps the mirror's priority (a converting prospect is a certified
  fact about a posed position; adoption is theorem-backed geometry
  whose audit only reruns at arrival), hopeless takes any feasible
  corner, and the cooldown-expiry reconsideration retries both on one
  cadence. Adoption is one-way (king-mode plans never re-adopt) and
  remembered: `_kh_adoption` survives plan eras, so a promotion
  mid-walk re-commits at the next replan instead of paying a second
  certify sweep. Fired by the drill at MOVE ONE: the piece side's only
  herder subset (the d3 bishop — everything else is holder or cage)
  certifies dead, and the mirror cannot even pose (c4 is our own pawn).
- **Walk choreography.** During the walk the construction order
  INVERTS: the executioner still owes clock-resetting pushes, so every
  pre-arrival move is free — and the parked king is the freeze that
  makes the premature push (the drill's accepted 1/2 race) structurally
  impossible. The march therefore goes FIRST (the cage gate lifts; the
  cage bishop can never need the king's square — arrival and corner
  cage sit on opposite shades), then the cage, then the knight walks to
  its park square. Commitment filters in chain order: walk-clear (only
  freeze-releasing moves while the path is ours), march, cage,
  closer-park (knight-hop distance, not Chebyshev — a chebyshev-adjacent
  square can be three hops away). New regression clauses: never re-block
  the path, never push OUR pawns in king mode (below), early-park veto
  lifted while walking. At `pawn_walk == 0` every gate restores the
  case-6 drill's cage-first order exactly.

Three failures the first drill runs found, all fixed the same session:

1. **Seal-range knight parks strangle the pocket.** The old
   `kh_knight_pull` was SATISFIED at range-2 parks like b4, whose
   coverage of a6/c6 — with a pushed c5 pawn covering b6/d6 — sealed
   the entire rank-six gate their king must cross to reach the {a4,a5}
   pocket: the herd certified dead against our own statics, honestly.
   The template now derives `kh_closer_park_square` — two files inward
   from the corner on the FAR back rank (c8 for a1, f8 for h1; the
   case-6 drill's hand-placed f8 knight IS this square, which is how
   the geometry was discovered) — the walk-phase pull targets it by
   knight-hop distance, and a commitment filter parks it during the
   wait. At arrival the pull reverts to the drill's seal-range form.
2. **Our own pawn pushes strip audited coverage.** The clock-urgent
   irreversible nudge pushed c4-c5 on the transition ply; c5 attacks
   b6/d6 and (with the knight at b4) walled off the herd's own gate. In
   king-holder mode every one of our pawns is a pocket wall or inert,
   so the regression filter now vetoes our pawn moves outright — except
   one that clears a race square the pawn itself blocks, a debt with no
   other payer.
3. **The transition ply ran under the stale plan.** A flip or adoption
   fired inside `_vi_choice` left the rest of that ply's waterfall
   filtered by the plan being abandoned (that is how c4-c5 slipped out:
   the pawn veto was not active yet). The filter chain is now
   `_plan_filtered_moves`, and _choose re-runs it under the new plan
   whenever the plan identity changes mid-choice — side flips included.

And one failure class fixed at the regime level: **funnels outside the
sub-MDP.** King-holder plans spend long stretches on the fallback
search with no policy underneath — the walk's wait (the sub-MDP cannot
exist before the geometry poses; `_vi_choice` is gated on
`pawn_walk == 0`) and every post-arrival stall where the side certified
dead or unconvertible. The session-6 lesson replayed there move for
move: our repetition filter prunes our own second visits, Zach's reply
completes the third occurrence on a state no tally of our choices sees
(walk-phase draw at ply 70; then seeds 5/6/8 drawing AFTER arrival with
the first, walk-only guard). `_filter_wait_funnels` now runs for the
whole king-holder regime: one ply of lookahead over the support pool
against `arena_draw` — the arena's own oracle, so fifty-move landings
are guarded by the same check — dropping any move whose landing or
reply adjudicates. The live herd is untouched (VI reads the pre-guard
candidate list and prices threefold by burning). The guard is
horizon-one by construction: seeds 5/6 still draw through TWO-ply
funnels (guarded-safe move, safe reply, forced continuation, draw), the
known residual.

Results — endgames case 7, the new ADOPTION DRILL
(`8/8/1p1k4/RR6/K1P5/1NPB4/8/8 w`: a COMPLETE piece-holder
construction — Rb5 holder defended, king parked a4, cage Ra5/Nb3/Rb5 —
with the corner kit present and the b-file walkable), 10 seeds,
`--profile vi --vi-herders 1`:

- **2 CONVERTED (64/66 plies) — the first full-pipeline adoption
  conversions ever**: piece side certified dead at move 1, adopted the
  a1 corner, released the freeze (walk-clears=2 every seed), marched
  Kb2 first, caged Bb1, parked the knight (closer-parks 4-8), waited
  out the walk behind the funnel guard, certified the posed corner
  live-and-converting (audits 6/7 at the good roots), herded, and won
  the vacate race. Seed 8 is the guard's direct save: with the
  walk-only guard it drew by repetition at ply 56; guarded, it
  converted at 66.
- 3 releases offered across the battery, 2 won, 1 lost (seed 0: the
  premature-push branch promoted and the game died chasing the rook) —
  consistent with the audited 1/2.
- 5 fifty-move: the herd's binding constraint again (clock feasibility,
  log item 2) — including two seeds with LIVE converting roots
  (0.40/0.50) that ran out of plies mid-herd, and three where the kh
  side itself certified live-but-unconvertible at the root their king's
  walk-phase wanderings produced (audits 0/1-0/8: the pocket approach
  matters, and nothing herds him during the walk yet).
- 2 repetition: the two-ply funnels above.
- Choreography reliability: every seed fired exactly one adoption and
  completed the full construction (2 marches, 2 clears, 1 cage build).

Suite 48 -> 54: walking-template emission and vetoes (the case-2 b2
stability fact is now a test), the move-one hopeless-adopt trigger and
its one-way guard, sticky re-adoption, the walk-order inversions (march
pre-cage and early-park during the walk, both restored at arrival),
walk-clear commitment, the funnel guard against a fifty-move landing,
and the sub-MDP walk gate (no builds before the geometry poses).

Full battery:

- Case-6 drill, 10 seeds: **byte-identical to the session-6/7
  reference** — 7 converted (48/52/34/64/42/38/34 plies), seed 2
  fifty-move, seeds 7/9 stalemate. The widened funnel guard and the
  king-mode pawn veto are live in every one of those games and changed
  nothing: the drill never wanted a pawn push and never chose a
  guarded funnel.
- Case-2 seed-5: **same game to the move** — fifty-move in 125 plies,
  47 VI moves, burn-updates=13 (0 at end), builds=10,
  unconvertible-sides=2, side-flips=1 (0 gated), 48 goals audited
  0-converting, 489,394 audit probe nodes, wall ~46s — with
  kh-adoptions=0 by construction: our b2 pawn vetoes the b6
  executioner's walk at emission (regression 22b states that fact as a
  test), so every adoption attempt correctly declines. The
  transition-ply refilter did not disturb the reference flip.
- Motifs: verdicts and odds byte-identical (kh-corner-h/a and
  kh-herd-h4 POSITIVE at 0.500; fm-organic-h/a and fm-deep-h POSITIVE
  at 1.000; ph-contained-root NEGATIVE, all refusals DISPROVEN).

Next, in expected-value order:

1. Fifty-move/clock feasibility from the solved MDP — promoted again:
   it owns five of the seven case-7 losses (two with LIVE converting
   roots of 0.40/0.50 that simply ran out of herd plies), plus the
   standing case-6 seed-2 repro.
2. Walk-phase defender pressure: the kh side's convertibility at
   arrival depends on where their king wandered during the walk
   (audits 0/1-0/8 at bad roots vs 6/7 at good ones), and nothing
   herds him while the sub-MDP cannot exist. Candidate: a lightweight
   defender gradient toward the pocket approach during the wait.
3. Deeper funnel pricing for the fallback regime: case-7 seeds 5/6
   still draw through two-ply funnels the horizon-one guard cannot
   see. The principled fix is a solved wait-phase MDP (or burning
   generalized off-policy).
4. Adoption from the standard fixtures: cases 1-5 all veto on our own
   intact b2/g2 pawns. Real full games shed pawns constantly, so the
   practical route is executioner selection during the strip phase —
   prefer preserving THEIR b/g pawns on files where OUR pawn has
   already died. Multi-pawn race stacking (unchanged).

### Review follow-up (2026-07-18, all four taken)

External review of the adoption work: three P1s and one P2, every one
verified against a concrete repro, and the fixes DOUBLED the drill.

1. **Adoption memory leaked across games (P1).** The arena reuses bot
   instances, and the rewind branch — the game boundary — reset the
   plan but not `_kh_adoption`, so game N+1 could re-commit game N's
   corner without ever certifying a side. The boundary now clears it;
   in-game plan resets still keep it (that is its purpose: promotions
   mid-walk re-commit without a second sweep).
2. **A parked closer could wander off during the walk (P1).** The park
   commitment stood down at hop distance zero, so the knight was free
   to drift while the pawn still walked — and Zach's final push could
   land with the closer displaced, the walking filters switching off,
   and the walk-0 pull pointing back at the seal-range squares that
   strangle the pocket. The regression filter now rejects any increase
   in the parked hop distance while `pawn_walk > 0`.
3. **The pawn-veto exception read the race_clear boolean (P1).** With
   race debt on TWO squares (pawns on f2 and h2 of the h-corner),
   clearing either leaves the boolean false, so both required pushes
   stayed vetoed while any stable move existed. The exception now
   counts occupied race squares and admits any strict decrease — which
   also correctly rejects h2-h3, a push the boolean framing miscounts:
   it merely trades escape-square debt for entry-square debt.
4. **Reply stalemates were invisible to the funnel guard (P2).**
   `arena_draw` leaves stalemate to the arena's separate check, so a
   support reply that stalemates US read as safe. The guard now checks
   `is_stalemate()` after each reply; mate of our king stays welcome.

Suite 54 -> 55 (one folded check: the game-boundary clear via the
planner-profile sticky path, the pinned closer on the reviewer's
walking fixture, and the counted-debt f2-f3/h2-h3 pair). Full battery:

- **Case-7 drill, 10 seeds: 4 CONVERTED (68/76/86/106 plies) / 2
  stalemate / 2 fifty-move / 2 max-plies — conversion rate doubled by
  the pinned closer.** 7 races offered, 4 won, right at the audited
  1/2; every converting seed shows closer-parks=3 exactly (the minimal
  hop route, then pinned) where the wandering build showed 4-8. This
  entry's numbers are the new case-7 reference.
- Case-6 drill: byte-identical to the reference again — all ten
  outcomes at the exact plies (the new clauses are walk-gated or
  debt-neutral there).
- Case-2 seed-5: same game to the move (fifty-move in 125, 47 VI
  moves, builds=10, 48 goals audited 0-converting, 489,394 audit
  probe nodes, kh-adoptions=0 by construction).
- Motifs: untouched by these diffs (no bot code on that path).

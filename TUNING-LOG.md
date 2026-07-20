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

## Clock feasibility from the solved MDP (2026-07-18)

Log item 1 built — the item sessions 4, 6 and 8 kept promoting: the herd
regime is all quiet moves, so the fifty-move rule caps every reversible
era at 100 plies, and the discounted policy could not see the cliff
(gamma prices time softly; the seed-2 repro spent all 100 plies herding
with a legal clock-resetting pawn push standing vetoed the whole game).
The solved graph now carries two hitting-time statistics per state, and
play prices `remaining = 100 - halfmove_clock` against them everywhere
the clock can kill a converting side.

The statistics (`_compute_hit_stats`, once per build, after the solve):

- **min_hit** — plies to the nearest positively seeded terminal when
  EVERY reply cooperates (min over children at our nodes and their
  nodes alike; one unit-edge backward BFS over the parent lists).
  Exact, solver-independent, and still a sound LOWER bound after any
  repetition burn, because burning only removes paths — which is what
  makes `min_hit + overhead > remaining` a certificate that the era
  cannot finish (overhead 2 = the release ply at clock <= 98 plus the
  mating reply; deeper race tails are priced exactly by the release
  scorer's own draw-law probes). The bound also holds per child, so it
  is a sound candidate veto.
- **exp_hit** — expected plies to absorption under the greedy
  stationary policy, conditioned on hitting: p (absorption probability)
  and m (mass E[plies x 1{hit}]) iterated by the same parent-driven
  worklist as the values, both monotone from a zero start, honesty flag
  `hit_converged`. Advisory by design (pristine graph, one fixed
  policy). Computed ONLY when the root converts: every consumer sits
  behind that condition, and churning p/m over case-2's 614k-state
  non-converting graphs bought +50% wall (69s) for numbers nothing
  reads.

What play does with them (all of it gated on `root_converts` — a side
with nothing to convert to does not race the clock; the audit-negative
machinery already owns that case):

1. **Gates.** Hard: `min_hit + overhead > remaining` — a certificate,
   and one that only hardens as the era runs (min_hit falls at most one
   ply per ply). Soft: `exp_hit * 1.5 + overhead > remaining` —
   headroom for hitting-time variance, advisory. Profile knobs
   `vi_clock_overhead=2`, `vi_clock_soft_factor=1.5`.
2. **Candidate veto.** Ranked herder moves whose child cannot reach a
   converting terminal inside the era (child `min_hit + 1 + overhead >
   remaining`) are pruned before the near-optimal window forms: their
   true value under the clock is 0 whatever the pristine graph says.
   All candidates pruned -> zero-fallback, honestly.
3. **Certified clock resets.** On the flip-cooldown cadence, a
   hard/soft-flagged side first tries to MANUFACTURE time: a quiet,
   non-checking, non-capturing pawn push that (a) still resolves the
   committed plan with no construction metric regressed (race debt
   counted, walk untouched, holder/cage/runway kept), (b) leaves
   Zach's pool free of forced captures and reply-stalemate traps (the
   capture and funnel guards replayed where the push bypasses them),
   and (c) whose hypothetical rebuild — rooted at the pushed position,
   same optimism as a flip prospect, and CRITICALLY with the active
   policy's herder subset, not the greedy one (the greedy hypothetical
   priced the wrong continuation and refused 3/3 on the calibration
   fixture; the sweep's chosen subset carries over verbatim since a
   push moves no herder) — certifies live AND converting. One push
   buys a fresh 100-ply era for a side that has proven it can finish,
   given time. The session-8 c4-c5 lesson is the refusal case: a push
   that seals the herd's own geometry builds live-but-unconvertible
   and is refused by exactly the audit that discovered the original
   disaster.
4. **Reconsideration cascade.** After a refused reset: the mirror flip
   (any live prospect under hard — like hopeless, there is nothing to
   stay for; positively-converting only under soft), then the corner
   adoption (hard only — the one-way replacement stays reserved for
   the certificate). All prospects now face an era-feasibility gate of
   their own: `min_hit_root + overhead <= remaining` (0 = stats made
   no claim, never condemns) — the mirror herds inside the SAME era,
   so an unfinishable prospect is refused with the long back-off
   whatever its audit says.
5. **MDP-aware release relaxation.** At remaining <=
   `vi_clock_relax_at` (20), a refused strict race re-scores with
   unlimited losing replies — any race with a winning reply beats the
   adjudication's certain zero — UNLESS the active policy maps the
   position and affirms the herd still fits (min_hit AND soft-factored
   exp_hit inside the budget), in which case the strict standard holds
   and the herd goes and gets the better goal. The calibration fixture
   drew the boundary exactly: at remaining 16 with the audited 1/2
   vacate goal four plies away the naive threshold took a 1/3 lottery;
   the MDP-aware rule herds Ra2 to the 1/2, and first takes the 1/3
   (Kh1) at remaining <= 7 where nothing better fits.

Suite 55 -> 59: hitting-time exactness pinned on two solved graphs
(fm-organic-h absorbs in exactly 1 ply; kh-herd-h4's root is exactly
(4, 4.0) with children {3, 7, HIT_INF}); the relaxation boundary above;
the reset pair — spare-a2 fixture at remaining 4 plays the certified
a2-a3 (2 hypothetical builds), the no-spare variant refuses f4-f5
honestly (it breaks the pocket), prunes all 4 ranked candidates as
unfinishable and falls through — a blind push is never played; and the
flip decision table extended with the feasibility gate (min_hit 99
refused at cooldown 16, boundary 97 accepted).

Full battery, byte-identical where the clock never binds:

- **Case-6 drill, 10 seeds: 7 converted at the EXACT reference plies
  (48/52/34/64/42/38/34), seeds 7/9 stalemate — and the standing
  seed-2 fifty-move repro is now fully diagnosed instead of blind:
  soft fired 15 plies, hard 3, 23 candidates pruned, 5 reset builds
  attempted and every one honestly refused** (the drill's only pushes
  are the f-pawns, and pushing them breaks the pocket per the same
  audit that scores every conversion; the converting builds' expected
  herds ran 36-67 plies against a budget the wandering had already
  spent — the herd genuinely did not fit, and this fixed geometry has
  no time to manufacture). The loss stands, correctly diagnosed as
  unsalvageable-in-era rather than unseen.
- **Case-7 drill, 10 seeds: the exact reference distribution — 4
  converted at the exact reference plies (68/76/86/106), 2 stalemate
  (101/111), 2 fifty-move (170/110), 2 max-plies.** Both fifty-moves
  are the unconvertible-at-arrival family (kh audits 0/1 and 0/8 —
  log item "walk-phase defender pressure", not clock), and the gates
  stay correctly OFF there. Seed 9's converting side shows the layer
  probing on cadence (soft=4, one reset build, refused). The
  post-review reference no longer contains a live-converting clock
  death for the layer to convert — the pinned-closer fix already ate
  those — so its value here is prophylaxis plus diagnostics.
- **Case-2 seed-5: same game to the move** (fifty-move in 125, 47 VI
  moves, builds=10, 48 goals audited 0-converting, 489,394 audit probe
  nodes) with every clock gauge inert (min-hit=n/a, hard/soft/pruned/
  relaxed/resets all 0) — the layer prices converting sides only, so
  the unconvertible reference cannot shift by construction.
- **Motifs: byte-identical** (kh-corner-h/a and kh-herd-h4 POSITIVE at
  0.500; fm-organic-h/a and fm-deep-h POSITIVE at 1.000;
  ph-contained-root NEGATIVE).

Next, in expected-value order:

1. Walk-phase defender pressure — unchanged, and now clearly the
   largest loss family: case-7's fifty-moves are arrivals whose pocket
   approach audits 0/N because nothing herds their king during the
   walk. Candidate: a lightweight defender gradient toward the pocket
   approach during the wait.
2. Deeper funnel pricing for the fallback regime (two-ply funnels
   behind the horizon-one guard; case-7 seeds 5/6 in the pre-review
   battery).
3. Executioner selection at strip time (standard fixtures 1-5 all veto
   their walks on our own intact b2/g2 pawns; real games shed pawns —
   prefer THEIR b/g pawns on files where OURS died). Multi-pawn race
   stacking.
4. Horizon-aware steering (the true clock-in-state product policy) —
   only if live-converting clock deaths reappear in a battery; today
   none remain, and the gates/reset/relaxation cover the observed
   cases at a fraction of the state-space cost.

### Review follow-up (2026-07-18, all five taken)

External review of the clock layer: four P1s and one P2, all verified
against the code and taken.

1. **A uniform +2 finish overhead was unsound per terminal kind (P1).**
   A FORCED_MATE terminal is Zach to move with every reply mating us —
   its tail is exactly ONE ply — while a goal owes the release plus the
   mating reply. The uniform bound falsely rejected forced-mate
   finishes one ply from the cliff (fm-organic-h at halfmove 98: one
   quiet move reaches clock 99 and hxg2# wins, but 1+2 > 2 read
   hard-infeasible and the child veto pruned the winning line). The
   statistics are now FINISH-INCLUSIVE: every positively seeded
   terminal seeds the BFS distance and the p/m mass at its
   `_TERMINAL_TAILS` cost (forced mate 1, goals 2), every gate compares
   `min_hit`/`exp_hit` against `remaining` directly, and the
   `vi_clock_overhead` knob is gone — the tails are structural facts,
   not tunables. For goal-seeded graphs the hard arithmetic is
   unchanged (reach+2 = finish); the FM boundary case now fits, pinned
   in the suite.
2. **The reset hypothetical certified an unreachable root (P1).** After
   our push it is Zach's turn; flipping the hypothetical back to us
   certified (us, zk, herders) with his king unmoved — a state that is
   not even in the reachable graph (every our-turn successor follows
   one of OUR herder moves, so zk cannot have changed first). Builds
   now take ``root_theirs``: the graph roots at the pushed position
   with Zach to move, its children are exactly the real post-reply
   states, and ``reply_fit_fraction`` reads the per-reply finish
   evidence (fraction of replies from which a converting terminal still
   fits a fresh era). Acceptance: under a HARD flag any fitting reply
   beats the certain zero; under the advisory SOFT flag every reply
   must fit — the side retains real value, so a push into a
   coin-flip-dead continuation is refused. The their-turn root's
   failure memory carries a turn flag so it can never contaminate the
   our-turn rooted-fingerprint ledger.
3. **Incomplete hit estimates could affirm "fits" (P1).** The stats
   were computed once at build under the same deadline as the solve,
   never refreshed, and the release-relaxation branch read them without
   checking ``converged``/``hit_converged`` — and the RATIO m/p of two
   truncated monotone quantities can err in either direction, so a
   half-baked exp_hit could suppress the near-cliff lottery.
   Affirmation now requires both honesty flags, and ``solve_more``
   recomputes the stats whenever a resumed solve reaches convergence
   (cheap exactly where it fires often: non-converting graphs skip the
   p/m pass). The SOFT TRIGGER stays deliberately flag-free — a
   spurious flag only costs cadenced reconsideration builds, while
   gating it would silence the cascade precisely on the big graphs
   where the solver labors.
4. **Refused reset pushes leaked into the fallback (P1).** On a hard
   clock every VI candidate prunes away, `_vi_choice` returns None, and
   the clock-urgent negamax nudge REWARDS irreversible moves — in
   piece mode, where no blanket pawn veto exists, it picked exactly the
   push the audit had just refused (white-box control: the 13b fixture
   plus a spare h2 pawn at clock 70 plays the unaudited h2-h3). Every
   scanned push that fails certification now lands in
   ``_vi_reset_refused`` (replaced wholesale each scan, cleared with
   the plan era), and ``_filter_refused_resets`` keeps the set out of
   the modeled/negamax fallbacks — vetoes counted, never emptying the
   menu, with the proof-based probe and herd-search exempt (a PROVEN
   net that spends the push is a win, not a leak).
5. **The reset scan had no total budget (P2).** Each stable candidate
   received a fresh ``vi_build_ms``; several candidates could multiply
   the advertised limit. One shared deadline now bounds the whole scan,
   each hypothetical gets only the remaining slice, and candidates the
   budget never reaches stay unjudged — never refused.

Suite 59 -> 60 (23a re-pinned finish-inclusive with the FM boundary and
a their-turn-root build asserting ``reply_fit_fraction`` == 1.0; 23c
asserts the recorded refusals; 23d's infeasible stub moved to 101 —
with tails, 100 fits a fresh era exactly; new 23e pins the piece-mode
leak: control picks h2-h3, the refusal set vetoes both pushes and
negamax picks Rc1, an all-refused set never empties the menu). Full
battery on the fixed code:

- Case-6: all ten outcomes at the exact reference plies. Seed-2's
  diagnostics moved honestly with the semantics: soft=23 (the tail now
  folds into the soft expectation, firing ~2 plies earlier), hard=3,
  pruned=23, resets 0-of-7 builds — every candidate push still refused
  by the their-turn-root audit.
- Case-7: the exact reference distribution and plies (68/76/86/106
  conversions). Seed-9's converting side: soft=8, resets 0-of-3, game
  identical to the move.
- Case-2 seed-5: same game to the move, every clock gauge inert.
- Motifs: byte-identical verdicts and odds.

## Review hardening rounds and re-pinned battery references (2026-07-18/19)

Four further review rounds landed on the clock/burn layer after the
last logged battery, three of them without a battery entry — so the
seed-2 and case-2 references below this section's battery block are
the ones that count now. The rounds, in order:

- **57bd823 (four findings)** — affirmative tails, same-decision
  vetoes: the conversion audit records each converting goal's PROVEN
  completion tail and a second BFS (`fit_hit`) plus the exp_hit seed
  mass price affirmations with it (`_TERMINAL_TAILS` stays the
  rejection floor); deadline-truncated p/m passes get one dedicated
  retry per value basis (`refresh_hit_stats`); herd search ranks below
  the solved sub-MDP and draws from the reset-filtered menu; reset
  vetoes are same-decision evidence — cleared on entry, re-armed with
  the whole uncertified scan domain when the flags arm.
- **7f04ebd (three findings)** — honest tiers all the way down:
  conversion-required flips demand a nonzero `fit_hit_root` inside the
  budget; fit_hit and the p/m pass treat burned states as BARRIERS and
  `_set_burned` stales `hit_converged` on ANY set movement;
  `clock_soft` requires converged + hit_converged (a truncated p/m
  ratio errs both ways — fresh mid-herd builds armed the cascade on
  move one of a 100-ply era from junk exp ~89).
- **94d739c (one finding)** — burns are priced where they are read:
  the era recount runs BEFORE the release affirmation and the clock
  gates, so every affirmative consumer prices THIS decision's burn
  set; the 23i rook tour drives the failure end to end (a herd whose
  every converting goal just burned read the stale fit of 10 and
  suppressed the lottery).
- **956f00e + 41d62fd (two findings + follow-up)** — exact reachability
  over epsilons: the ranking's 1e-9 zero cutoff treated
  Bellman-tolerance residue as real value after a total burn (a
  DECREASING re-solve stops inside the 1e-6 tolerance, leaving crumbs
  up to tolerance/(1-gamma): measured 5.66e-6 on the burned kh
  fixture at gamma 0.96, 4.98e-5 on the burned 14d proxy fixture at
  0.99). The certificate is `_seed_reach` — burn-aware reachability
  from whatever terminals `_terminal_seed_value()` currently seeds
  positive, computed unconditionally beside min_hit — read by
  `child_value_live` and pruned (`vi_crumb_pruned`) BEFORE the floor
  window anchors; fit_hit stays conversion-only (an affirmation off
  proxy seeds would promise a finish nothing audited); the follow-up
  made it tier-agnostic because a live-but-unconvertible proxy policy
  OUTLIVES the flip/adoption cascade and burns like any other. Also:
  the near-cliff release affirmation gates on `policy.contains(board)`
  BEFORE the recount — a cached policy that no longer maps can never
  answer `hit_estimates`, and the old order paid a recount plus up to
  a `vi_build_ms` re-solve per decision for an affirmation that was
  never coming. Suite 60 -> 68 across the rounds (23f through 23l).

Full battery on 41d62fd, with a baseline control at 94d739c (the
commit before the last two rounds) on every seed that diverged from
the stale log — **the control matched HEAD on all 12 compared games,
outcomes AND plies, so every divergence from the older entries belongs
to the three previously unlogged rounds, none to the newest two**:

- **Case-6, 10 seeds**: 7 converted at the exact reference plies
  (48/52/34/64/42/38/34), seeds 7/9 stalemate — unchanged. Seed 2
  stays fifty-move but the game is NEW: fifty-move in 100 plies, ~3s,
  soft=0 / hard=3 / pruned=23 / resets 0-of-1, exp-hit=n/a,
  zero-value=3, crumb-pruned=0. The old logged seed-2 diagnostics
  (soft=23, resets 0-of-7) belong to 5e7ef30-era code: with the honest
  soft gate, the truncated p/m pass on this graph keeps the cascade
  dark, so the game never spends the reset scans and dies at the raw
  adjudication. Diagnosis unchanged (unsalvageable-in-era); the repro
  is just cheaper now.
- **Case-7, 10 seeds**: 4 converted at the exact reference plies
  (68/76/86/106 — seeds 2/5/6/7); losses: seeds 1/3 stalemate
  (101/111 = lost races), seeds 0/4 fifty-move (170/110), seeds 8/9
  max-plies (240). **Seed 0 is the only game in the entire battery
  that exercised the new filter** — kh adoption to a 0/19-audit
  arrival, 9 burn updates with 7 burned at end, crumb-pruned=31 over
  zero-value=3 decisions. The baseline control played the same
  position by noise-walking the crumbs (zero-value=0, played=30 vs 47)
  to the SAME fifty-move at ply 170: the filter changed the route, not
  the outcome, and the gauges now tell the truth about it.
- **Case-2 seed-5**: fifty-move in 225 plies, 98 VI moves, builds=12
  (5 failed pawn-not-frozen), burn-updates=30 (20 at end), root 0.000,
  side-flips=1 (prospect 0.0), crumb-pruned=0 — identical at the
  baseline, so this too is the affirmative-tier rounds' game, not the
  newest commits'. The logged 125-ply / 47-VI-move reference is
  5e7ef30-era; THIS is the reference now.
- **Motifs**: verdicts and odds byte-identical (kh-corner-h/a and
  kh-herd-h4 POSITIVE 0.500; fm-organic-h/a and fm-deep-h POSITIVE
  1.000; ph-contained-root NEGATIVE, all refusals DISPROVEN).

Loss ledger after re-pinning, unchanged in shape: case-7's fifty-moves
and max-plies are unconvertible or 0/N-audit arrivals — nothing herds
their king during the walk — so next-steps order stands: (1)
walk-phase defender pressure, (2) deeper funnel pricing (two-ply
funnels), (3) executioner selection at strip time, (4) multi-pawn
stacking.

## Walk-phase defender pressure: the funnel potential and the delivery schedule (2026-07-19)

The ledger's top loss family: during a king-holder adoption's pawn walk
the sub-MDP cannot exist, the piece-mode herding fallbacks never engage
a king-holder template (their engagement preconditions are piece-holder
facts — `holding_blocker`, a three-piece cage), and the wait plies fall
to the plain negamax, whose menu-shrinking eval has no location sense.
Where their king stands when the pawn lands decides the side's
certification, and nothing steered it.

PGN forensics on the pinned baseline battery (all ten case-7 games
replayed move by move) turned "audits 0/N vs 6/7" into named geometry:

- Seeds 0 and 6 were a one-square A/B experiment: both arrived with
  the king on e5; seed 6's Rf6+Rf8 left the d7 lane open (live root,
  converted), seed 0's Rf6+Rf7 sealed it, completing a two-square
  {e5,e6} prison far from the pocket — a 0-goal component and the
  fifty-move. The wait's own eval BUILT that prison: a tiny menu
  scores well anywhere on the board.
- Seeds 1/3/4 were caught north of accidental rook walls (b8/a8/b7
  behind Ra7/Rc7, or Ra5 sitting on the descent corridor itself) — the
  dead and 0/N-audit arrivals. Seed 1's stalemate was not a lost race
  (releases=0); it was the north box.
- Every converting seed's king descended b7 > a6 > a5 > a4 — through
  a5, the drill's own rook start square: the corridor opened only when
  the negamax happened to wander the rook off it.
- Seed 9's walk took 173 plies (no fence at all), then ran out of
  game with a live converting root.

Mechanism: `walk_pressure_move` (planning.py) — one ply of our choice
against Zach's complete modeled pool, argmin of expected funnel
potential, ties to the lexically smallest UCI so replays are exact.
`walk_pressure_cost` prices, for THEIR king: chebyshev distance to the
seal square (the pocket mouth); blocked squares on its pocketward side
(doors — a fence must never form in front); the descent corridor's
integrity while he still needs it; the walk as a delivery schedule; and
our men on the fixed race squares (the audit's race_clear predicate,
priced per square). Checks are never special-cased: the expectation
prices them — a check empties the push from his pool and usually
scatters him, so only a check that genuinely funnels survives the
argmin. Gate (bot.py): profile flag `walk_pressure` (VI only),
king-holder plan, `pawn_walk > 0` — plus a stall arm for the posed
construction whose side certified dead or unconvertible with no live
policy move (hold established, cage complete, defender not delivered).
It slots after `_vi_choice` returns None and replaces only the negamax
pick; the certify/flip/adoption cascade, the reset-veto filter, the
release scorer, and the exact probe all run upstream, unchanged. The
chooser ranks the already commitment-filtered menu, so chore plies gain
a fence-aware tie-break while pure waits get the actual pressure.

Four drill batteries iterated the potential; each falsification is a
keeper lesson:

1. **A flat finish bonus rushed the pawn home dead.** 30/rank taught
   the chooser to shrink his pool anywhere (pool-shrink raises the
   push odds) and the arrivals collapsed to plies 7-23 with his king
   still north of the walls — the dead-arrival family it was built to
   prevent, 2/10. The walk is the HERDING WINDOW: every push resets
   the fifty-move clock, so the pawn must land LAST, not fast.
2. **The schedule reframe alone changed nothing.** Premature term
   25 x max(0, min(3, D-1) - walk), finish shrunk to 4: byte-identical
   games on the failing seeds. The fence value itself was the
   accelerator — the expectation mechanically rewards cutting his far
   replies (the average improves with every wall) — and rank-five rook
   posts raked the corridor into a5 from across the board. Every
   0/5-unconvertible arrival had a waiter on or raking a5/a6; the two
   converts kept the lane pristine (Re1 posts) and the sub-MDP did the
   descent itself from c6-north arrivals, live 6/7.
3. **A flat corridor charge lost every argmin it was meant to win.**
   8 per lane square (a5/a6 for the a1 corner — case-6's h5 pocket-top
   and h6 door, mirrored), gated on D>1 because a sealed lane is spent
   geometry once he stands at the mouth (the baseline's Re5 with the
   king already on a4 audited 6/7). Arrivals cleaned up into
   Rb7/Rd7+Re1 poses with live roots — and the losses moved downstream
   to live-side stalemates, while the fast-walk seeds stayed
   byte-identical: their walks end inside the chore choreography,
   every pressure ply is a chore tie-break, and Ra5 — the corridor
   squatter — is never in any chore menu, so the charge was constant
   across every candidate. The walls-behind reward was removed
   entirely here (its fence value was exactly the poison); the sub-MDP
   is the ratchet, the wait's job is to deliver a clean board.
4. **Freeze scaling made the charge win where it can.** Charge x
   (4 - min(3, walk)): nearly free at walk three, prohibitive at walk
   one and during the posed stall. Seeds with real wait plies steered
   clean and converted — seed 0 (fifty-move@170 at baseline, its e5
   prison) CONVERTED in 56; seed 3 (stalemate@111 at baseline, 21 dead
   certs) CONVERTED in 106.

One more device was built, measured, and DROPPED: a "roomy" tier in
the wait-funnel guard preferring moves that leave Zach two options
(stalemates arrive forced — each wait ply shrinks his pool and the
one-ply gives_stalemate filter only sees the final move of the
squeeze). The mechanism is real — seed 1's death in the pinned battery
is exactly a wait-squeeze stalemate at a live 6/7 root — but the
battery refuted the guard: stalemates went UP (3 to 5) because the
squeezes that matter are policy-built (the live herd shrinking his
pool IS herding) and sit outside the guard's reach, while the tier
reshuffled every volatile post-arrival outcome. It retires until the
post-arrival item can price the squeeze properly.

Results — case-7 adoption drill, 10 seeds, `--profile vi
--vi-herders 1`, the NEW REFERENCE: **3 converted (56/106/72 plies,
seeds 0/3/5 — each a full pipeline: pressure-steered walk, live 6/7
certification, policy herd, one audited release, probe-proven mate;
releases=1 and probes-hit=1 in all three)**. Losses: seeds 1/8
stalemate (57/71) at LIVE 6/7 arrival roots (0.171/0.157) and seed 7
stalemate (31, live 6/10) — the post-arrival stall family; seed 9
fifty-move (152) at a live-but-0/7 root (0.211, corridor-clean — the
honest counterexample that the geometric potential is a proxy); seeds
2/4 fifty-move (118/108) and seed 6 repetition (36) — the fast-roll
family, 0/5 arrivals whose walks ended inside the chores (seed 4
arrives at ply 7; nothing had a wait ply to steer).

Arrival taxonomy, the number this feature owns: baseline 5
live-converting / 2 unconvertible / 3 DEAD arrivals; now **6
live-converting / 4 unconvertible / 0 dead** — the prison and
north-box families are extinct, and arrivals happen at plies 7-51
(baseline: up to 173). Headline honesty: the baseline converted 4/10
(seeds 2/5/6/7). Post-arrival live-side outcomes are VOLATILE under
any wait perturbation — across the four iterations the convert set
reshuffled ({2,5,6,7} to {1} to {3,9} to {0,3,5} to {5,9}) while
arrival quality improved monotonically — and the three baseline
converts that regressed (2/6/7) are fast-roll or post-arrival deaths
whose walks offered nothing to steer. Their fix is the next item; a
wait-phase heuristic cannot reach them.

Full battery: case-6, 10 seeds — **byte-identical to the reference**
(7 converted at 48/52/34/64/42/38/34, seed 2 fifty-move@100, seeds 7/9
stalemate; structurally guaranteed: case-6 never walks, and no case-6
game ever certifies a side negative — checked across all ten logs, so
the stall arm cannot fire). Case-2 seed-5 (default herders, solo run)
— **same game to the move** (fifty-move in 225, 98 VI moves,
builds=12 with 5 failed pawn-not-frozen, burn-updates=30 with 20 at
end, root 0.000, side-flips=1 at prospect 0.0), `walk-pressure=0` and
`kh-adoptions=0` by construction (the b2 pawn vetoes the walking
template at emission). Motifs: verdicts and odds byte-identical
(kh-corner-h/a and kh-herd-h4 POSITIVE 0.500; fm-organic-h/a and
fm-deep-h POSITIVE 1.000; ph-contained-root NEGATIVE).

Suite 67 -> 70 by runtime PASS count (24a-24c; the previous entry's
"68" miscounted its own additions — seven checks 23f-23l on top of 60
is 67, which is what the pre-change suite prints). 24a white-boxes
every potential term with exact deltas: approach dominance, the door
charge, the freeze-scaled lane pair (exactly 24.0 at walk one against
an off-lane post), the mouth pair (exactly 0.0 — spent geometry), the
race debt (exactly 25.0), and the schedule inversion both ways
(landing while far costs, landing at the mouth pays). 24b pins the
argmin (clearing the corridor rook beats parking it on the entry
square) and the double-push walk arithmetic; 24c pins the gate end to
end (a vi bot's wait ply matches the direct call on the same filtered
menu; the planner profile never consults the chooser).

Next, in expected-value order:

1. Post-arrival recovery for unconvertible and stalled sides — the
   static-relocation device: move the corridor-raking rook (or
   whatever static the audit blames), re-certify hypothetically (the
   clock-reset pattern applied to statics), adopt the relocated pose
   on a positive verdict. Owns the fast-roll family (chore-end poses
   with Ra5/Re5 rakes), the live-side stalemates (seeds 1/8: the
   goal-stall wait squeeze), seed 9's corridor-clean 0/7, and the
   volatility itself — post-arrival no-policy play is the last regime
   with nothing certified under it. Audit-in-the-loop (hypothetical
   arrival certification during the walk) is the same device pointed
   at wait plies, if any preventable bad arrivals survive it.
2. Deeper funnel pricing for the fallback regime (two-ply funnels;
   seed 6's repetition@36 on a live-fallback herd).
3. Executioner selection at strip time (standard fixtures 1-5 all
   veto their walks on our own intact b2/g2 pawns). Multi-pawn race
   stacking.

### Review follow-up (2026-07-19, both taken)

External review of the walk-pressure work: one P1, one P2, both
verified against concrete positions and taken.

1. **Zach reply draws were scored as live positions (P1).** The
   chooser's reply loop special-cased only checkmate; stalemate and
   every arena adjudication fell through to the geometric potential.
   The funnel guard strips most such candidates upstream, but its
   all-trapped fallback hands them back exactly at the fifty-move
   cliff, where EVERY quiet reply adjudicates — and priced
   geometrically, a certain draw could outrank a live lottery, the
   precise inversion the clock layer's relaxed release exists to
   prevent. The verified repro (now suite 24d): halfmove 98, his king
   a6, Rb5-b6+ forces the lone evasion Ka5 — delivered to the
   corridor, a beautiful leaf of ~14 — and the game is drawn on the
   spot at halfmove 100, while quiet Rh8-h7 leaves Zach exactly the
   clock-resetting push (his only legal quiet move) at a worse-looking
   leaf of ~89. The old argmin checked him into the draw. Reply draws
   now cost `_PRESSURE_DRAW` (10k, the jackpot's mirror): any live
   continuation beats any certain draw, and partial-draw lotteries
   rank by draw probability first, geometry second.
2. **The walk recount followed the wrong pawn of a doubled pair
   (P2).** `_pressure_walk` scanned for the first walking pawn on the
   target file; with doubled walkers the rear pawn's count shadowed
   the committed walker's (the rear pawn's own template is rejected by
   the path-block veto at emission, so the target is always the front
   pawn). The drill's black walkers dodged the bug only because
   ascending square order happens to visit the front pawn first —
   mirror-color games and the planned multi-pawn stacking would not.
   The recount now follows the committed pawn itself: root square, one
   push ahead, or two pushes ahead from the home rank (the double-push
   case the review's suggested fix would itself have missed) —
   between root and leaf exactly one reply has happened, so nothing
   else can hold those squares. White-boxed in 24b: doubled white
   walkers b2+b4 committed to b4 read two (the rear pawn's three
   shadowed it before), and after the walker's own push the count
   tracks its successor square.

Suite 70 -> 71 (24b extended in place, 24d new). Full battery byte-identical
across the board — case-7 all ten PGNs match the just-pinned
reference exactly (no drill ply ever scored a drawing reply: the
funnel guard's trapped tier caught them all before the chooser, and
the walking file is never doubled), case-6 at the exact reference
plies, case-2 seed-5 the same game to the move (solo run,
builds=12 with 5 failed pawn-not-frozen), motifs byte-identical.

## Post-arrival static relocation: move the blamed rook, certified (2026-07-19)

The walk-pressure session's ledger said it plainly: a king-holder side
that certifies live-but-unconvertible is poisoned by PLACEMENT, not
subset choice — the sweep already tried every herder subset, so what
remains fixable is where the frozen men stand. The fast-roll seeds all
arrived with a rook on or raking the descent corridor (their walks end
inside the chore choreography, and no chore menu ever contains the
squatter), and one mobile herder can never lift a frozen seal. Play
then herded a doomed fallback until the clock or a funnel took the
game.

The device: `_consider_static_relocation`, ranking BELOW the mirror
flip and the corner adoption in the unconvertible cascade (a certified
fact about a posed mirror, then the theorem-backed replacement, THEN
one quiet repair move). It scans quiet non-checking moves of our
non-king, non-pawn pieces standing outside the active herder subset,
under the clock-reset discipline: the plan must still resolve with no
construction metric regressed and no new race debt; Zach's reply pool
must hold neither a forced capture nor an adjudication trap; and a
hypothetical rebuild rooted AFTER the move with Zach to move —
carrying the active subset verbatim, since a relocation moves no
herder — must certify live AND converting, meeting the
conversion-gated flip's era-feasibility and affirmative-fit standards
plus at least one fitting reply. Nothing less than a converting
verdict is accepted: the side being left is worth zero, but a
merely-live relocated pose trades zero for zero and a tempo.
Candidates are ordered by the walk-pressure funnel potential of the
landed position — the geometric prior spends the build budget on
corridor-clean poses first — and capped at eight per scan (the
audition, not the shortlist: a pose the top eight geometric picks
cannot certify is not rescued by number twenty-three, and the uncapped
scan re-verified two dozen refusals on every cadence expiry — seed 4
spent 189 builds saying no; the cap halves it and the games are
byte-identical). One `vi_build_ms` deadline bounds each scan; refusals
set nothing — the flip's own cooldown paces re-scans, and the
position-dependence doctrine (their king drifts, pockets open) is why
re-scans exist at all. A played relocation records its (from, to) pair
for the game and bars the exact inverse: the rebuild that follows may
sweep to a different verdict than the carried-subset hypothetical, and
the memory keeps that disagreement from ping-ponging the piece.
Piece-holder plans never scan — their unconvertibility is the release
theorem, and no relocation refutes a theorem (this is also the case-2
reference's shield: its cadence hits the same call).

Fired end to end, the poster child is the battery's own seed 2: the
Rb5+Re5 arrival certifies 0/5-unconvertible at ply 17, the mirror
cannot pose (c1 is no corner), the adoption is already committed —
and on the SECOND hypothetical build the scan certifies 10. Rb8, off
the rank-five rake and onto the north-cap post of every converting
arrival. The policy then herds with knight checks (Nd6-b7-c5), his
king descends c6 > b6 > a5 > a4 > a3, 19. Ka1 vacates, 20. Nb6 seals,
and 20...b2# lands the textbook corner mate at ply 40 — the fastest
case-7 conversion ever recorded, converting a seed that was a
fifty-move loss in every prior battery.

Results — case-7, 10 seeds, `--profile vi --vi-herders 1`, the NEW
REFERENCE: **4 converted (56/40/106/72 plies, seeds 0/2/3/5)**; six
games with zero relocations are byte-identical to the walk-pressure
reference (0/1/3/5/7/8 — the device is perfectly inert where no side
certifies unconvertible); seed 6 relocates once and trades its
repetition@36 for a stalemate@111 (the relocated pose went live and
herded 75 more plies before the live-side stall family took it); seed
9 relocates once mid-game and still meets its fifty-move at the same
ply by clock coincidence; seed 4 refuses every audition (96 capped
builds) — its chore-end pose needs more than one repair move (knight
AND rook both stand wrong), the honest one-move-horizon residual.

Full battery: case-6 byte-identical (no case-6 game certifies a side
negative, so the cascade never reaches the device); case-2 seed-5 solo
— same game to the move with `relocations=0/0` (the theorem gate);
motifs byte-identical. Suite 71 -> 74: 25a pins the seed-2 pose end to
end (certify-unconvertible, flip and adoption decline, Rb5-b8 on build
two), 25b the candidate domain (active herders untouchable, the cage
never survives the stability recheck, a played relocation's exact
inverse is barred while the rest of the rook's menu stays open), 25c
the piece-holder theorem gate at zero builds.

Next, in expected-value order:

1. Live-side post-arrival stalls — now clearly the largest loss family
   (seeds 1/7/8 stalemate at live 6/7-6/10 roots; the goal-stall wait
   squeeze and the forced-stalemate landing). The relocation device
   deliberately does not touch live sides; their fix likely wants the
   release-refusal reasons surfaced (why do audited-converting goals
   refuse every race at play time?) before any new machinery.
2. Multi-move repairs (seed 4: rook AND knight both misplaced; the
   one-move relocation horizon cannot compose them).
3. Deeper funnel pricing (two-ply funnels; unchanged), executioner
   selection at strip time, multi-pawn stacking (unchanged).

## The relocation rides the era: repetition carriage and the charged ply (2026-07-19)

Review round on the relocation device, two P1s taken, both the same
blind spot: the hypothetical rebuild treated a REVERSIBLE quiet move
like the reset's pawn push. The push earns its stackless copy — an
irreversible move opens a fresh era and a fresh clock — but a
relocation resets nothing: the game's twice-seen positions and its
spent quiet plies both follow the piece to the new square, and the
rebuild priced neither.

First, the era. `copy(stack=False)` dropped the reversible-era
history, so the rebuilt policy priced twice-seen graph states as
fresh — and the candidate loop never asked whether the landing ITSELF
already stood at two occurrences. On a shuttled era (Rb5-b8 played
into its third occurrence) the scan certified and returned a move the
arena adjudicated drawn before Zach could reply: a certified instant
half point from the device whose whole purpose is escaping zeros. Two
repairs. The candidate filter now pushes each landing on the REAL
board and rejects any `arena_draw` verdict — the game history is on
that board, so this is the arena's own adjudication, and it retires
the fifty-move brink for free (every relocation is quiet, so at clock
99 the domain honestly empties). And the hypothetical now carries the
stack, so the probe runs `apply_repetition_history` after its build
and burns every twice-seen era state before the gate reads anything
affirmative: a landing at one prior occurrence roots the rebuild one
re-entry from the draw, the burn cuts the root off from every proven
finish, `fit_hit_root` reads zero, and the gate refuses. The
freshness discipline mirrors play: `solve_more` recomputes the
hitting stats when a value-moving burn reconverges, the dedicated
refresh covers a burn that moved no Bellman value, and a drain the
scan budget cannot finish refuses the candidate outright. The bar is
the SOLVE's convergence, never the advisory exp tail's — the fit
flood-fill is deadline-free and exact whenever it recomputes, and on
the battery pose the exp pass stays honestly unconverged while fit
and fraction are proven facts.

Second, the ply. `remaining` was measured on the pre-move board while
every hitting stat starts at the post-relocation root — and the quiet
relocation spends one era ply getting there. The certified Rb8
rebuild proves fit 15; at halfmove 85 the pre-move measure still said
fifteen remaining and accepted a finish that owed fifteen plies with
fourteen left. `remaining` is now `100 - hypothetical.halfmove_clock`,
read off the pushed board beside the build it gates. The flip keeps
its pre-move read — its hypothetical re-poses the SAME root; this one
is a ply later.

Suite 74 -> 77. 25d builds the shuttled eras end to end: the
third-occurrence landing drops out of the domain while its stackless
twin keeps it (pinning the exclusion on history, not geometry), and
on the once-seen era the scan burns Rb8 down and certifies b5d5 on
build three instead — the device still rescues the pose, just not
through the repeat. 25e pins the boundary: halfmove 84 certifies Rb8
on two builds, 85 refuses it and every other audition (eight builds,
no certificate, the fallbacks play on). Battery: the four case-7
games that run the scan at all (seeds 2/4/6/9) replayed against a
HEAD control — byte-identical PGNs and identical gauges (2 converts
@40 with relocations=1/2, 4 refuses its 96 auditions to the same
fifty-move@108, 6 relocates once into the same stalemate@111, 9
relocates once to the same fifty-move@152): the reference relocations
all fire at low clocks inside fresh eras, so the new gates are
provably inert where they should be and the constructed suite eras
prove they fire where they must. The six no-scan seeds, case-6,
case-2 seed-5, and the motifs are untouched by construction — this
round changes only the scan and its candidate filter, no solver or
audit code. Next-steps order unchanged: live-side post-arrival
stalls, multi-move repairs, funnel pricing / executioner selection /
multi-pawn stacking.

## Release audit: the live-side stalls are lost coin flips, not refusals (2026-07-19)

The last entry's top item carried a question written before the walk-
pressure and relocation rounds settled the references: why do audited-
converting goals refuse every race at play time? Instrumenting the
release path answers it with data, and the answer is that they never
do. The premise is stale: the final references contain no goal-stall
wait squeeze at all (vi_goal_stalls=0 in every stall-family game — the
squeeze lived in session 10's discarded iterations, not in what
shipped). Every live-side stalemate in the battery is the SAME single
event, and it is not a refusal. It is the corner template's designed
endgame — the vacate race — offered at exactly its audited odds,
accepted at exactly its audited odds, and lost on the coin.

The instrument, all behind a new opt-in `--release-audit` flag
(`LoseBot(release_audit=True)`), all read-only: `score_release_moves`
grows a `detail_out` that records one verdict per candidate release —
"scored" with its W/L/pool odds, "no-winning", "over-losing", or the
landing adjudication that refused it before scoring — with identical
decisions whether or not it is supplied. The policy grows three
read-only accessors: `conversion_table()` (every audited win-kind
terminal with its graph state, race fraction, and proven tail — the
odds the build promised), `state_view(board)` (which graph state a
pose maps onto, its kind, value, burn, and audited fraction), and
`audit_board(board)` (the clean reconstruction the audit scored: same
placement, build-time clock, no history). The bot records one event
per release scan — pose, clock, per-candidate verdicts, the state
view, and a TWIN rescore of the same strict scan on the audit_board
reconstruction, so any play/twin disagreement isolates exactly what
the era's clock and repetition history changed. Flag off, batteries
are provably untouched: seeds 1/7/8 PGNs byte-identical with the flag
on vs off, gauges identical to the digit; case-2 seed-5 and the
motifs byte-identical vs a HEAD-worktree control (wall-ms aside);
case-6 at its exact reference plies.

What the data says, seed by seed. The audited conversion tables for
every stall game have one shape: every goal state is `goal-vacate` at
zk=a4 — the delivered pose, one row per herder post — and every
converting row is EXACTLY f=0.500 with tail 6. Seed 1 (rook herder):
6/7 at 0.500, Rb5 at 0.000. Seeds 7 and 6 (knight herder): 6/10 at
0.500. Seed 2, the converted control: 1/20 at 0.500 (only the Nd7
post converts — the knight must reach the b6 seal in one hop). There
is no better-than-half goal anywhere in the family, and the policy's
value at the delivered pose reads 0.500 — the discounted root values
(0.171/0.157/0.083/0.097) are that coin seen from afar. At the
release ply every game shows the same line: state=goal-vacate
(v=0.500 f=0.500), chosen=b2a1 1W/1L/2P, twin=b2a1 1W/1L/2P,
candidate-for-candidate agreement between play and the clean board.
The pool is {Ka3, b2+}: Ka3 steps onto the defense square and the
probe proves the net (Nb6 seals a4, b2# is his only move); b2+ pushes
early, Kxb2 is our only non-stalemating reply, and the capture bares
his king into an instant stalemate — the "forced-stalemate landing"
is the LOSS branch landing, not a refusal artifact. Zach drew b2+ in
seeds 1/6/7/8 and Ka3 in seed 2 (20...b2# at ply 40, the fastest
conversion on record). Eight vacate races were offered across the
ten-seed battery; four won (seeds 0/2/3/5), four lost (1/6/7/8). The
4/10 conversion rate IS the audited coin performing exactly to
specification.

The refusal machinery, where it does fire, is right. Seed 8's king
touched a4 at ply 64 with the rook off rank 5: the scan refused
b2a1 as over-losing (1W/2L/3P — a5 open adds a third reply), the twin
agreed, the pose mapped to an INTERIOR state (v=0.369, not a goal),
the policy re-sealed rank 5 (Rd7-d5+), and four plies later the true
goal-vacate pose accepted its 1W/1L/2P. Strict max-losing=1 is doing
exactly its job: it refuses loose poses and tightens them into the
audited race. And the audit's f=0.000 rows are geometry, not noise:
with the dynamic rook on b5, the vacated b3 opens the b-file and OUR
OWN rook guards b2 — after Ka3, Nb6, b2+ the "mate" dies to Rxb2, so
the probe scores 0W/2L (verified directly). The zero knight posts
(Nd4/Nd6/Na7/Nc7...) cannot reach the b6 seal inside the probe
window. The release theorem's shadow reaches into the king-holder
family too: any of our pieces re-attacking the arrival square refutes
the mate, which is why the walk-pressure funnel electing rank-5 rook
posts (session 10's poison) produced 0/5 arrivals.

The structural fact this closes on: the a1-corner vacate race is
capped at one half BY CONSTRUCTION. The vacate legalizes the push —
b2 empties, so b3-b2+ is always in the pool — and the funnel that
makes the pose a goal (every quiet reply enters the defense zone)
means the only other reply is Ka3. One winning, one losing, pool
two, forever: no herder placement, wait choice, or steering can buy
a better fraction inside this template, because the defense square
is the only in-zone quiet step and the push is unremovable. The cap
is not a bug to fix but a design ceiling to raise, and the lever is
already on the list: the losing half is only terminal because the
arrival square is undefended at push time (Kxb2 burns the lone
executioner). A second their-pawn covering b2 — multi-pawn stacking,
with executioner selection at strip time keeping adjacent b/c-file
pawns alive for it — makes Kxb2 illegal: the winning branch keeps
its mate and the losing branch stops losing (the defended pawn
survives, the race renews instead of ending). That converts the
one-shot coin into a repeatable one and is now the family's whole
expected-value story.

Suite 77 -> 80. 26a pins the vacate scan itself on the stall pose
(b2a1 scored 1W/1L/2P, the b3-pawn bars a2/c2 so the menu is two
moves, b2c1 refuses no-winning, detail_out changes nothing). 26b
pins flag parity end to end (audit and plain bots choose the same
b2a1; the event records the accepted odds and honestly reports an
unmapped state — the release fires before any policy build on a
fresh bot). 26c builds the policy two herding steps out and pins the
whole audit surface: the a4/Rd5 row at exactly 0.5, state_view
mapping the delivered board onto that row and refusing an off-graph
king, audit_board reconstructing the audited placement.

Same-day review round, one P2 taken: the once-per-policy table
ledger keyed on id(policy), and id() is reusable the moment a
discarded policy is collected — a teardown/rebuild-heavy run showed
hundreds of distinct policies sharing a couple of ids, each REBUILT
policy's table silently suppressed behind a dead one's ghost while
its events kept recording. The ledger is now a WeakSet of the policy
objects themselves: weak identity keeps exact once-per-instance
dumps for a live policy, retains no dead graphs (the reviewer's
constraint — strong refs would pin every superseded sub-MDP for the
game's lifetime), and a ledger that drains on collection can never
suppress a successor whatever id the allocator hands out next.
Suite 80 -> 81: 26d pins the mechanism deterministically — two scans
of one live policy dump one table, and after the policy's last
strong ref drops the ledger reads empty while the dumped table
stays. Instrumented seed 1 replayed identical (game, gauges, and
audit lines) — the fix only changes who remembers the dump.

Next, in expected-value order:

1. Multi-pawn stacking + executioner selection at strip time —
   promoted from the tail of the list: the vacate race's 1/2 cap is
   structural, every live-side loss is that cap realized, and a
   defended arrival square is the one lever that raises it (the
   losing branch stops being terminal). Design work: a corner
   template variant whose walls admit a second THEIR-pawn guarding
   the arrival square, and strip-phase preferences that keep such
   pawn pairs alive.
2. Multi-move repairs (seed 4: rook AND knight both misplaced; the
   one-move relocation horizon cannot compose them; unchanged).
3. Deeper funnel pricing (two-ply funnels; unchanged).

## Multi-pawn stacking: the renewable race, plus executioner selection at strip time (2026-07-19)

The last entry's design question — a corner variant whose walls admit a
second their-pawn GUARDING the arrival square — has a theorem-shaped
answer, and it is no. A guard must attack b2 from a3 or c3; a3 is the
entry square, and a c3 guard checks the king-holder on b2, so no herd
can even run. Parking the guard one rank up (c4) requires freezing it
with one of our men on c3, and every freezer type fails its own way:
our pawn locks the guard out of c3 forever (it never guards, and the
lost race still ends all-pawns-frozen dead — adjudicated 0.500-no-gain
on `2N5/8/8/7R/k1p5/1pP5/1K6/1B6 w`); a knight on c3 attacks a4, the
goal square itself; a rook on c3 PINS the executioner at delivery (the
b3 push opens rank 3 onto the king that just stepped to a3, so b2# is
illegal exactly when it matters); a dark bishop on c3 refutes the mate
with Bxb2. The realizable second their-pawn is not a guard at all — it
is the SAME-FILE REAR PAWN, and its mechanism is renewal, not defense.

The doubled-executioner stack (their b3+b4): the rear pawn is frozen by
its own front pawn — their-pawn statics already satisfy the solver's
freeze rule, so no solver change at all — and it is inert through the
whole race (both its capture squares stay empty by template). Race 1 is
the audited coin unchanged. The LOSING branch stops being terminal:
after the early push, Kxb2 eats the spent executioner, the rear pawn is
Zach's entire quiet pool (his king is boxed by the same walls that made
the pose a goal), it walks down one square, re-freezes against the
re-holding king, and the identical corner race re-poses one pawn
shorter. Both the capture and the push reset the fifty-move clock; the
renewal costs ~4 plies. Adjudicated end to end with the release scorer
on `2N5/8/2N5/8/kpP5/1p6/1K6/1B6 w` (and the kingside mirror): race 1
scores 1W/1L/2P, the renewal pool is exactly [b4b3], the mid-walk
template resolves (walk 1, blockers 0) across the executioner's death,
race 2 scores 1W/1L/2P with its win branch probe-PROVEN via Nb6. The
race EV lifts 1/2 -> 3/4 (7/8 at depth 3) — the first number past the
structural cap. A VI-level stacked pose (`1NN5/8/N7/8/kpP5/1p6/1K6/1B5R
w`, rook herder h1, roam pocket {a4,a5}) builds with ZERO pool
mismatches and audits 7/7 goal-vacate terminals at the coin, complete.
All three are permanent motif fixtures (kh-stack-a/-h/-a-herd);
verdicts of the seven originals byte-identical.

Two wall facts the adjudication forced, both now encoded:

1. **Rear food.** The far-capture rule climbs the stack: at the
   delivery zugzwang every non-mating move outranks the mate in Zach's
   pool, so any of OUR men on a rear pawn's far-side capture square is
   an escape valve exactly when the net closes — with our c3 pawn under
   a b3+b4 stack, the audit refuses every retreat (bxc3 leaks the
   zugzwang; that pawn was the baseline fixture's b4 WALL, which is why
   the first stacked fixture attempt scored NEGATIVE). Encoded as
   `kh_rear_food_squares` (the far-file ladder above far-capture:
   c3, then c4 at depth 3), folded into race_clear, `_kh_race_debt`
   (counted, so the pawn-veto exception stays sound: c2-c3 is a debt
   swap and stays vetoed; c3-c4 clears at depth 2), and the
   walk-pressure race billing.
2. **The race-2 b4 wall must be knight-class.** Once the rear walks
   down, b4 opens, and every rook wall fails its own way: rank-4 posts
   check the goal king through the vacated square, b-file posts
   re-attack the arrival at delivery (the audit's 0.000-row geometry),
   and an occupying rook is force-captured at the zugzwang (a capture
   is Zach's preferred non-mating move; defense is irrelevant — the
   mate evaporates either way). A knight on the c6/d5/a6 family walls
   b4 while touching nothing critical; c4-pawn-defended d5 is even
   king-proof. The solver needs no telling — herder-inclusive goal
   classification already routes a knight herder to walling posts —
   but the drill must SUPPLY the knight.

Template/plan machinery: `stack_rears` on every king-holder template
(loose-column scan capped at 2 — gaps compact under the same uniform
pushes that walk the front pawn); a stacked file outranks a bare one
BEFORE distance in both `best_pawn_mate_template` and the adoption
chooser (no setup-step count buys EV like a second coin); walking
templates now tolerate THEIR pawn on the arrival square (the spent
executioner mid-renewal, emitted as arrival_blocked) so the committed
plan keeps resolving through the renewal window instead of being
replaced by a piece plan at the worst ply. And the drill's first wreck
became a commitment filter: at the renewal check, adversarial negamax
refuses Kx(arrival) whenever a herder hangs in the continuation and
resolves the check by EATING A COLUMN PAWN WITH A PIECE instead (the
Rxb3 wreck — rook seal posts live on the renewal file by construction).
`_filter_renewal_capture`: in check under a king-holder plan with their
pawn on the arrival square, a legal king retake of the arrival IS the
move — it eats the spent pawn, re-holds the freeze square, and resets
the clock in one tempo. It runs after the stalemate-strip, so the
bare-executioner references (where Kx instantly stalemates and the old
games already avoided or were forced into it) are untouched by
construction.

Executioner selection at strip time (the feature's other half,
`_executioner_term`): their pawns are not equal, and the strip is where
capture choices happen. Gated on their_pieces > 0 — once they are
king+pawns the plan machinery owns pawn preferences, so every endgame
reference is untouched by construction. Per corner-capable file (b/g
only): +40 for a surviving their-pawn (corner material), +60 per
same-file rear behind it (audited renewal equity, capped 2), -30 when
OUR pawn sits below their front pawn (the emission veto in waiting —
pawns cannot leave files, so the file stays dead until ours does).
Knobs zero-defaulted (v03 and all pre-stack profiles byte-identical),
set in CURRENT and inherited by the template/planner/vi chain.
Ordering, not precision: rear > front > generic pawn, everything far
below piece values so the strip itself is never distorted.

New STACK DRILL (endgames case 8, `2N5/8/2k5/3N1B2/1pP5/1p6/8/2K4R w`,
`--profile vi --vi-herders 1`): the doubled pair at the pre-corner,
king one step off the arrival, bishop one move off the cage, closer
pre-parked c8 (case-6 convention), Nd5+Rh1 the herder pool (the knight
doubles as the race-2 b4 wall — c4-defended, so his king can never
eat it even when forced), c4 the rear-safe b5 wall. A --vi-herders 2
experiment was measured and dropped: two-herder graphs at this open
pose run 510-716k states (the state-cap failures at 200k left the
renewal ply policyless — 20.Ba2 wrecked the pose from the fallback;
with --vi-state-cap 700000, now a CLI override on endgames AND arena,
builds succeed but cost 24s each and the game wandered to max-plies
anyway). One herder + statics is the shape: seed 0's race 2 shows the
policy relocating the rook OFF the renewal file to c5 and firing the
vacate behind the Nd5 wall — the adjudicated geometry, discovered by
the solver in-game.

Results, 10 seeds: **3 CONVERTED (26/48/42 plies — seed 3's 26 is the
fastest conversion ever recorded, beating relocation's 40)**, and the
renewal pipeline is live end to end: 10 vacate races offered across 8
seeds, 3 won; seeds 0/2/7 lost race 1, renewed through Kxb2 + the
forced rear walk, and were offered race 2 in-game (all three lost the
second coin too — stalemate@51, max-plies wander, stalemate@47 — the
1/8 tail realized, n=3); seeds 1/3/4/9 had the premature push land
DURING construction and the renewal capture ate it on the spot, the
rear inheriting the template (seed 3 then converted — the stack as
construction insurance, unplanned but exactly the audited mechanism).
Losses: 3 double-lost coins, 2 repetitions (28/58 plies — rook two-ply
shuttles, the known deeper-funnel-pricing family, now with a 28-ply
repro), 1 herd clock death (fifty@100), 1 single coin lost after the
construction heal (@29). renewal-captures fired in 7 of 10 seeds.

Reference batteries, all verified against a base-commit (675e069)
control worktree at outcome-and-ply level: case-6 7/10 at the exact
reference plies (48/52/34/64/42/38/34; fifty@100; stalemates 61/51 =
control), case-7 4/10 exact (0@56/2@40/3@106/5@72; losses
57/108/31/71/111/152 = control for every seed), case-2 seed-5
fifty@225 with identical build/flip/goal gauges and renewal-captures=0,
motif verdicts byte-identical. The new paths are unreachable without a
second same-file their-pawn, and no reference position has one.
Selftest suite 81 -> 86: the posed stack template (rears, food square,
race_clear flip, baseline-zero), the renewal chain end to end, the
stacked herd build+audit (7/7, zero mismatches), the strip term's
arithmetic AND its their_pieces gate, rear-food billed as race debt.

Next, in expected-value order:

1. Deeper funnel pricing — now owns four battery losses (case-8 seeds
   1/4 with a 28-ply repro, case-7 residual family) and is the largest
   remaining draw engine. The principled fix is still a solved
   wait-phase MDP or burning generalized off-policy.
2. Full-game stacking validation: the strip terms are live in CURRENT;
   measure whether real strips now deliver b/g pawns (and pairs) into
   the endgame, and whether the adoption/stack machinery fires from
   organic positions (arena vs Zach, the real conversion metric).
3. Multi-move repairs (case-7 seed 4; unchanged).
4. Stack donation engineering (forcing cxb recaptures to CREATE
   doubled files against a never-capturing opponent) — speculative,
   only the strip terms' organic stacks come free today.

## Lichess field notes: the first human opponents (2026-07-20)

The bridge is live: BOT account **LoseBotAI**, lichess-bot pinned by
commit SHA in `Dockerfile.lichess` (the project's git tags died in 2020
and the newest one pins python-chess 0.24 — bump SHAs deliberately; any
replacement `homemade.py` must keep an `ExampleEngine` class because
`test_bot/homemade.py` imports it unconditionally). Casual standard
challenges only, rapid 10+0 through unlimited; wrapper env knobs and a
clock governor in `lichess/homemade.py`; ops details in the README's
lichess section. Default engine after game 1: `LOSEBOT_PROFILE=vi
LOSEBOT_MODEL=zach`. Every game lands in `lichess/game_records/`
(gitignored) — the first corpus of real mate-avoidant humans.

Three games against the author playing the anti-losebot recipe:

- **sNiyNb4S** — aborted before the bot's first turn: 30s abort fuse +
  a 165-char greeting lichess silently refused to send (cap is 140
  after `{me}` expands). Both fixed (fuse 120s; smoke test measures
  every greeting at a 20-char username).
- **BnQ263xT** (`current`, model-free) — the strip and squeeze WORK on
  a human: fed pieces, stripped him to K+pawn, squeezed him to
  mobility 1, even manufactured its own executioner (102.Rb2 axb2 —
  the strip-time exec terms shopping) and preserved it 44 moves. But
  the generalist carries no construction machinery, so it shuffled
  checks and promoted TWO OF ITS OWN QUEENS (clock_urgent +
  irreversible_move_bonus walking pawns to promotion = fifty-move
  survival without a plan) until the human resigned: 1-0, the one
  result the bot exists to avoid. The generalist can shop but cannot
  build — hence the vi default.
- **R9tSLBLK** (`vi` + `zach`) — fifty-move draw at move 115, the
  honest Zach-class stall, and the vi discipline is visible: it held a
  completely free c2 pawn through the entire final 50 moves because
  every reset scan honestly certified nothing converting (contrast the
  queen-promotion farce above), and its final move 115.Qc4 offered
  queen + their-capture clock reset one ply after the clock hit 100.
  The real failure was upstream: it donated the rook (45.Rb5+ Kxb5)
  and bishop (48.Bb2+ Kxb2) into forced king captures, reaching Q+K by
  move 48 — a lone queen is the release theorem's favorite meal and
  one free piece cannot be cage, closer, and herder at once. The
  certify sweep was right; the material was already gone.

**The structural discovery: Zach never captures, so a donation has
never once been punished in the arena — the training opponent cannot
even express the failure mode.** Humans take the gifts. Every
shed-our-men instinct implicitly assumed the offer dangles forever;
against accepting opponents the bot strips ITSELF below construction
minimum. Secondary finding: 59.Qxb3+ ate their b3 pawn one step from
the b2 renewal square — check_bonus (40) outbid exec_file_bonus (40).
Deliberately NOT a bug: 65.Qxh1 ate their fresh promotion — against a
mate-avoidant opponent their queen is zugzwang-immune shuffle fuel and
eating it is model-consistent (whether to PRESERVE their queen against
blunder-prone humans who might eventually mate with it is an
opponent-classification question, not an eval fix).

Next for the human frontier, in expected-value order (the Zach-program
list above remains valid for the drills):

1. **Donation guard / herder-material floor**: while their side is
   strippable-but-unconverted, veto or price moves that drop our free
   pieces below what any resolvable template family requires (cage +
   closer + herder; templates.py knows the sets). Acceptance test:
   45.Rb5+ and 48.Bb2+ of R9tSLBLK must not both pass.
2. **A sloppy-human opponent model** in opponents.py: Zach's
   mate-avoidance BUT captures hanging material (parameterize capture
   probability; "terrible but takes pieces occasionally"). Wire as
   `opponent_model="sloppy"` through the probe menus; arena A/B
   against it as the second benchmark beside Zach. Honest scope
   warning: the herding sub-MDP's frozen-statics premise BREAKS under
   a capturing kernel (their king can eat the cage; capture edges
   explode the state space) — model the strip/midgame phases first and
   keep vi herding Zach-scoped; a capture-tolerant sub-MDP is new
   solver work, not a knob.
3. **Exec-preservation vs check_bonus weighting** (the 59.Qxb3+
   family): their b/g pawns adjacent to renewal squares should outbid
   a quiet check.
4. **Corpus protocol**: every PGN in `lichess/game_records/` gets a
   post-game read (`losebot.analyze` + eyeball) and its findings land
   in this log. Three games in, each one taught something the arena
   never could.

## Donation guard / herder-material floor: the field profile (2026-07-20)

Takes items 1 and 3 of the human-frontier list above. The structural
discovery stands: Zach never captures, so no arena game ever priced a
donation, and R9tSLBLK's human stripped the bot below construction
minimum. The fix is a material floor derived from what templates.py
already knows a conversion needs, wired in three layers and carried by
a new profile so every audited Zach-world reference stays untouched.

**The floor predicates (templates.py).** `kh_viable_files(board, us)`:
the corner files (b/g) whose executioner material THEY still hold — a
their-pawn on the file no further than the pre-corner square, or a
their-pawn on an ADJACENT file that can still capture onto it at or
above (donor-inclusive, validated by the exhibit game itself: the a6
pawn became the b3 executioner via 57...axb4). Deliberately more
permissive than emission — our men on the path are transient, their
pieces are strip targets — because it prices what material can still
be PROTECTED, not what can pose today. `kh_supported_files`: viable ∩
emission's own material gates per file — a knight-class closer exists
and a bishop of the cage square's shade exists, the cage square
derived as square(file, corner rank), exactly `_kh_squares`' geometry,
so the shade map cannot drift (b needs light, g needs dark, for a
White bot; mirrored otherwise). `free_piece_count`: our non-king
non-pawn men — any resolvable family needs THREE at once (frozen cage
+ parked closer + at least one mobile herder; `herder_subsets` returns
nothing for a side with nothing left to move). One free piece cannot
be cage, closer, and herder — the R9tSLBLK lone queen, restated as
arithmetic.

**The filter (bot.py `_filter_donation_guard`, gauge
`donation_vetoes`).** Runs before every plan filter and fallback, so
everything downstream draws from a menu that cannot spend the floor;
only the exact selfmate probe outranks it by placement (a PROVEN net
that spends a piece is a win), and the release scan never draws from a
filtered menu. While kh_viable_files is nonempty, one reply deep and
structural — LEGALITY is the opponent model here, deliberately, since
a human eats what Zach never would:

- TYPE floor: with a supported family in hand, veto any move that
  leaves none — our own capture eating the last family's pawn stock
  (the 59.Qxb3+ shape), or any immediate reply that recaptures the
  last role piece (21.Nxd4 cxd4 spent the final closer on a strip the
  queen could have made later; the scan also rechecks replies whose
  capturer is a pawn, because a pawn capture changes THEIR files).
- COUNT floor: at or below three free pieces, veto any non-strip move
  that lets a reply eat one (45.Rb5+ Kxb5, 48.Bb2+ Kxb2 — the log's
  own acceptance pair). Captures of their mobile pieces are exempt:
  finishing the strip outranks the count floor (their promoted queen
  must die — 65.Qxh1 stays model-consistent, pinned by selftest), and
  the type floor still polices WHICH piece pays.

Never empties: when every candidate donates, the unfiltered menu
stands and the eval terms carry the gradient. A live subtlety the
suite pinned: the guard is also a DEFENSE gradient — on the move-21
board it keeps exactly the knight-saving moves (Nh4/Ne1), because
ignoring a standing threat to the last closer fails the same one-reply
scan that refuses spending it.

**The eval floor (heuristics.py).** Bonuses, not penalties — killing
the geometry must never read as a cure for missing material, which is
precisely how 59.Qxb3+ slipped past no_template_penalty (the d-pawn's
release-theorem-dead PIECE templates kept a target alive while the
real family died). `floor_supported_bonus` when some family is
supported, `floor_family_bonus` per spare family, `floor_herder_bonus`
while the three-piece reserve stands and viability survives; both
phases, constant while the floor holds so only the boundary carries
gradient. Negamax's deliberately adversarial opponent nodes make the
boundary visible at depth 2: the leaf after their recapture shows the
floor fallen — the donation was never invisible to search, it was
UNDERPRICED (our_man_value 25 vs their minor at strip scale 288, so
shedding the last knight always looked profitable).

**The field profile + bridge default.** `field` = vi + donation_guard
+ floor terms (900/60/300: no single strip prize buys the toolkit —
their queen at strip scale is 810; narrowing to one family outbids a
generic executioner file (40) but yields to a piece win (288); losing
the herder outbids a check plus a typical menu swing). The lichess
bridge default flips to `LOSEBOT_PROFILE=field`; `vi` remains the
audited arena-exact control, selectable by env. Zero-defaulted knobs
everywhere else: current/v03/template/planner/herding/vi are
byte-identical dataclasses, and the endgames gauge line prints only
when vetoes fired, so reference stdout is untouched by construction.

**Secondary finding 1 resolved by design, not by reweighting.** The
"check_bonus (40) outbid exec_file_bonus (40)" framing dissolved under
reconstruction: at move 59 their_pieces == 0, so the exec term was
gated off entirely — there was no 40-vs-40 auction, there was NO
k+p-phase term pricing the executioner at all, and the menu-shrink of
a check is what actually outbid nothing. The floor terms are that
missing k+p analog (the eval delta at the 59 boundary is 1200, not
40), and CURRENT's audited strip weights stay exactly as pinned.

**Acceptance + references.** Selftest 86 -> 92: the floor predicates
(donor-inclusive viability, per-file shades), the acceptance pair
(field chooses Qc5+ — a pawn-defended check, the guard tells sound
checks from donations structurally — over 45.Rb5+, and Qc6 over
48.Bb2+), the move-21 closer save, the counterfactual Qxb3 veto plus
the 1200/1260 eval boundary and vi == silenced-field equality, the
strip exemption with the never-empty contract, and the knob gate
returning the untouched list object under vi. Full reference battery
(case-6 seeds 0-9, case-7 seeds 0-9, case-8 seeds 0-9, case-2 seed-5,
motifs) run against a base-commit (c770c38) control worktree in the
same pypy3 image, both sides fresh: all 31 endgame stdouts
byte-identical once the wall-clock tokens are stripped (the [Ns] game
timer and the vi build-ms gauge — the raw diffs contain those lines
and nothing else), every outcome, ply count, and vi gauge equal;
per-case PGNs byte-identical raw where the per-case filename is
stable (case-2's single seed and each drill case's final seed — the
endgames writer overwrites game_00N seed to seed); motif verdicts,
state/edge counts, and terminal tallies byte-identical (four bare
build-ms tokens aside).

Next for the field frontier:

1. **Pin a field baseline battery**: the drills under `--profile
   field` (the guard can veto fence hugs the Zach-world policies use
   freely, so field's drill numbers are ITS reference, not vi's) and a
   full-game field-vs-Zach arena A/B to measure what the floor costs
   against the opponent that never punishes.
2. **The sloppy-human model** (unchanged from the list above) — the
   guard is structural insurance; a capture-probable kernel is the
   principled complement.
3. **Corpus protocol continues**: the next accepting human should die
   with the toolkit intact — that game is the guard's real acceptance
   test.

**Field notes addendum — GlcYtgKz (2026-07-20), the pre-guard control
game.** Bot as BLACK for the first time, same human, and — by four
minutes — the OLD image: losebot-lichess built 22:55, the guard
committed 00:24, game started 00:28 on the unmerged main. So this is
not the guard's acceptance test; it is a second control, and it
replays the R9tSLBLK catalogue almost line for line. Replaying every
Black move through the field build's actual filter (full legal menu,
membership of the played move):

- Four vetoes, each confirmed by the human's very next capture:
  17...Ba6 (the light bishop — the g-family's cage on the mirrored
  shade map, b8 dark/g8 light — donated to Bxa6 with the dark bishop
  already dead since move 13: type floor), 29...Nc4 (knight hung at
  free=3: count floor), 30...Nf4+ (last-knight donation check at
  free=2), and 31...h5+ (fails to save the still-hanging knight —
  the defense gradient, not just a donation veto).
- Every allowance is the designed one: 11...Bxb4+ (bishop eats their
  QUEEN; the recapture arrives two plies later through 12...d4, and
  the b-family narrowing to g is family_bonus territory, not a veto),
  15...Qxe2+ (queen for knight — strip-exempt, the queen is not floor
  material), 19...Rd3+ (rook spent at free 4->3: the surplus
  allowance), 40...Rxg3+ (rook for rook at free=1 — the strip must
  finish), 45...Kxe2/55...Kxd3 (eating their donated pieces), and
  93...Qxg4+ passing UNVETOED because the floor was already dead —
  honest inertness, same as real-game move 59 of R9tSLBLK.
- The executioner-eating shape RECURRED: 93...Qxg4+ ate their last
  g-pawn and the viable column went g -> none — the 59.Qxb3+ family's
  second occurrence in two games. It is a family, not an incident.
- New pin of what the floor protects against: from move 41 the bot
  had ZERO pieces, self-promoted 63...b1=Q under clock pressure, and
  spent 56 consecutive moves giving queen checks until the human
  resigned (0-1 — the second resignation win in three full games).
  The guard's thesis is that this state is never REACHED; this game
  is the queen-form portrait of the dead-floor stall.

The floor predicates tracked the whole arc correctly as Black (viable
bg -> g at move 72 when the b-stock ran out, g -> none at 93; typed g
while the light bishop lived). Next live game needs the image rebuilt
from the guard commit — until then every game is a control.

**Field notes — vfGeEKhy (2026-07-20), the guard's first live game.**
Image rebuilt from the merge at 00:41, game started 00:43, bot as
Black, same human. Result: **1/2-1/2 by repetition at move 183 —
final halfmove clock 93, the bot still holding rook + knight + dark
bishop.** The guard's headline numbers all landed:

- **The count floor held the entire game**: free pieces 7 -> 3 and
  then pegged at exactly three from move 41 to the end (the control
  game hit ZERO by move 41). No donation checks of floor material
  ever appeared; the only voluntary spends were the designed
  allowances — 10...Qf3+ Kxf3 (the queen is not floor material; the
  bot ran the human recipe's own queen dump), 136...Rf4+ Kxf4 at
  free=4 (surplus spend that is ALSO a their-capture fifty-move
  reset, the 115.Qc4 device played with a rook), and every strip
  capture: their queen eaten free (5...Nxg4), both knights, both
  rooks, the bishop by pawn recapture, and the fresh promotion
  refused at Qd8 and eaten only when it hung for free (65...Rxf6 —
  the model-consistency clause working as written).
- **Replay through the filter: zero played moves vetoed** (the live
  bot obeyed its own guard; 1026 candidate vetoes across the full
  legal menus show how hard it was steering), and the draw is the
  honest certified kind — no resignation win, no self-queen farce
  (117...e1=R, a rook underpromotion, was its one promotion).

**The new finding — family selection.** The type floor kept A
toolkit, not THE toolkit. 24...Bb7 donated the light bishop to Rxb7
for nothing — legal under the guard as a NARROWING (typed bg -> b),
because the b-family still read viable through DONOR pawns (a2/c4)
after white's own b-pawn traded off at 18-19. Then the bot's own
27...Rxa3+ ate the a-donor, and 44.c5-45.c6 walked the c-donor OUT
of donor range (rank > 4 cannot land at-or-above the pre-corner)
straight to 47.c8=Q: typed collapsed to none at move 45 and the
last 138 moves were certified-honest shuffling — knight, rook, and
the WRONG-SHADE bishop in perfect attendance on a g5 executioner
posed one square from pre-corner, needing exactly the light bishop
donated 120 moves earlier. Three follow-ups, in value order:

1. **Stock-quality weighting**: at move 24 the g-family had TWO
   on-file pawns (g3/g4) and the b-family was donor-only — grade
   floor_family_bonus (and the narrowing decision) by stock quality
   the way the exec term already grades front/rear, so donating the
   on-file family's bishop while keeping a donor-only family prices
   as what it is.
2. **Free-donation arm of the type veto**: a non-capture move that
   hangs the last bishop of an ON-FILE-viable family's shade could
   be vetoed even when a donor-only family survives (the count
   tier's R9tSLBLK acceptance case keeps donor-inclusive viability —
   this refinement touches only type-tier narrowing).
3. **Donor-range dynamics**: a donor one push from leaving range
   (44.c5) is stock about to evaporate; viability could discount or
   the eval could taper it, so the search sees the promotion train
   coming.

With the guard live, the CONSOLIDATED next list for the field
frontier, in expected-value order (supersedes the list above the
addenda):

1. **Family selection** — the three follow-ups just listed, as one
   feature: the floor must keep the toolkit whose executioner stock
   actually survives, not whichever one the first donation happened
   to spare. Acceptance: at vfGeEKhy move 24, Bb7 must price (or
   veto) as donating the live g-family's cage.
2. **Pin a field baseline battery** (case-6/7/8 + case-2 seed-5 +
   motifs under `--profile field`): the guard can veto fence hugs
   the Zach-world policies use freely, so field's drill numbers are
   ITS reference, not vi's — plus a field-vs-Zach arena A/B for what
   the floor costs against the opponent that never punishes.
3. **The sloppy-human opponent model** (opponents.py: Zach's
   mate-avoidance, parameterized capture probability; strip/midgame
   scope only — the herding sub-MDP's frozen-statics premise breaks
   under capturing kernels, so vi herding stays Zach-scoped).
4. **Corpus protocol continues**: every game in
   `lichess/game_records/` gets its replay-through-the-filter read
   and lands here. The guard's remaining acceptance test is a human
   who keeps their b/g pawns — the corner construction has still
   never posed against a live opponent.

## Review follow-up on the stack feature: realizable executioners only (2026-07-20)

The multi-pawn-stacking review landed four fixes, all verified against
the geometry rather than taken on faith:

1. **`_executioner_term` now prices only realizable corner material**
   (review P2, accepted). The old term keyed on the most advanced b/g
   pawn even past the pre-corner square and counted every same-file
   companion as renewal equity: a black b2+b4 column priced +100 while
   the template layer correctly emits b4 with stack_rears=0 (b2 is the
   spent executioner of the renewal window — no template is ever
   emitted for a pawn past pre-corner, and kh_viable_files already
   excludes it), and a lone b2 priced +40 with no king-holder target
   in existence. The term now selects the most advanced pawn at or
   behind the pre-corner rank (the same predicate kh_viable_files
   applies), counts rears strictly behind THAT candidate, and keys the
   our-pawn block veto on it too — which also repairs the veto in the
   mixed case (b2+b4 with our pawn on b3: the old front=b2 scan looked
   below rank 1 and saw nothing). Spent-past-pre-corner columns price
   as zero. Battery 27d pins the three shapes: b2+b4=40, b2-alone=0,
   b3+b2 renewal window=40.

2. **The renewal filter is exercised for real** (review P2, accepted).
   Battery 27b previously hand-pushed Kxb2, so _filter_renewal_capture
   could rot undetected. The check now builds a vi LoseBot, installs
   the committed king-holder plan, resolves it across the renewal
   window (arrival_blocked pose), and runs the ACTUAL
   _plan_filtered_moves chain at the in-check ply: a1b2 must be the
   sole survivor on both filter outputs and vi_renewal_captures must
   read 1; the chain then continues from the filter's own move.

3. **The exec knobs gate independently** (review P3, accepted). The
   term fired only when exec_file_bonus was nonzero, so zeroing the
   file bonus silently killed exec_stack_bonus and
   exec_blocked_penalty too. evaluate() now gates on any of the three.
   No live profile is affected (the chain inherits all three from
   CURRENT as a block; v03 zeroes all three), so every reference is
   byte-identical — this is future-tuning hygiene only.

4. **The stack-drill comment recommends one herder again** (review
   P3, accepted). The case-8 fixture comment said "Run with
   --vi-herders 2", contradicting this log and the README: the
   two-herder experiment was measured and dropped (510-716k-state
   graphs), and one mobile herder + statics is the shape.

Verification: selftest 92/92 (27b now shows filter=['a1b2']
renewals=1; 27d shows the three new spent-pawn prices), and case-8
seed-0 replays its exact reference — stalemate@51, releases=2,
renewal-captures=1. The endgame drills cannot see the eval change
(their_pieces > 0 gate; the drills start at king+pawns), so only
strip-phase play on positions with a spent b/g pawn moves — the leak
the fix exists to close.

## Family selection: the floor is tiered by stock class (2026-07-20)

vfGeEKhy's finding, taken. The donation guard held the floor all game
— never below three free pieces, typed support to the end — but it
held A toolkit, not THE toolkit. At move 24 the pose carried on-file
executioners g3/g4 (their pawns, which leave the g-file only by
capturing one of our men — a donation we would have to choose)
against a donor-only b-family (a3/c4, each one quiet push of THEIRS
from exiting the capture window), and the guard passed 24...Bb7
because after 25.Rxb7 the donor-only family still counted as support.
Our own 27...Rxa3+ then ate one donor, 44.c5-47.c8=Q ran the other
out of the window, and the game dance-drew 138 certified-dead moves
with a g5 executioner posed against the wrong-shade bishop.

The fix names what the old floor could not: stock class.

- templates.py: `kh_onfile_files` (kh_viable_files' same-file arm
  alone, without the donor arm) and `kh_floor_tier` — 2 while some
  supported family's executioner stands on its file, 1 while every
  supported family rests on lent donor pawns, 0 with no supported
  family at all. On-file stock is a family we hold; donor-only stock
  is a family they lend.
- bot.py: the type arm of `_filter_donation_guard` vetoes tier DROPS
  instead of support extinction — the trigger structure is unchanged
  (self-break check after our own move, the one-reply recapture
  scan), only the predicate tightened. The Qxb3 shape gains its
  tier-level analog: eating their last on-file executioner while only
  donor stock remains is a 2 -> 1 downgrade, vetoed, where the old
  floor saw support surviving and shrugged.
- heuristics.py + profiles.py: the supported bonus splits by tier.
  `floor_supported_bonus` (900) now prices on-file support only; the
  new zero-defaulted `floor_donor_bonus` (450) prices donor-only
  support. The 450 gap outbids any minor at strip scale (288), so no
  piece win buys the on-file family's kit, while their queen (810)
  still does — the strip must finish, and the filter's type arm
  polices which piece pays. The gap also reaches a donation channel
  the piece-scoped filter never scans: baiting their on-file
  executioner into capturing our PAWN off the file is invisible to
  the veto (pawn victims are not floor material) but now prices as a
  tier drop at the adversarial leaf.

At the move-24 pose the fix does something better than veto one move.
The pose had a standing Rxb8 threat on the closer all along; the old
guard funneled 31 legal moves to 6 survivors and the bot picked the
one that paid with the wrong coin. The new guard funnels to 5 — Na6,
Nc6 (the closer steps out), Bb4, Bb6, Rb6 (the b-file blocked with
b-family or count material) — every one an answer to the threat that
keeps tier 2. Bb7 was the sixth: a b-file block that spent the
g-family's cage to buy the donor-only b-family's future.

Verification:

- selftest 97/97 (was 92). 29a pins the tier predicates on the game
  poses (move-24 = 2, one Bb7 Rxb7 exchange later = 1, counter_59's
  posed executioner = 2, dead_59 and R9tSLBLK move-45 = 0). 29b is
  the log's own acceptance test: at the move-24 pose 24...Bb7 is
  vetoed and the five tier-2 answers are the exact survivor set (26
  vetoes counted). 29c pins the freedom the tier preserves: the donor
  family's bishop is spendable at tier 2, the on-file family's is
  not. 29d pins the Qxb3 donor analog: Rxg4 (last on-file pawn,
  donors remain) vetoed, Rxh4+ (the donor, on-file cover holds) kept.
  29e pins the eval gap: 1200 vs 750 through a silenced field profile
  (900+300 herder vs 450+300), and vi evaluates the tier-1 pose
  byte-identically to silenced field, so the donor knob gates with
  the rest.
- vfGeEKhy replayed through the new filter: across all 183 played
  Black moves exactly ONE verdict changes — 24...Bb7, VETOED. The
  move-40 rook loss stays allowed (the count floor's designed
  fourth-piece boundary), the move-136 rook loss stays allowed (tier
  0 by then; the guard is honestly inert once the floor is gone).
  The R9tSLBLK acceptance pair is count-arm work and unchanged;
  65.Qxh1 is unchanged (their queen is not executioner stock).
- Full reference battery vs bf97462, both sides run fresh in the same
  pypy3 image: case-2 seed-5, case-6/7/8 seeds 0-9, and motifs — all
  32 stdouts byte-identical modulo wall-clock tokens ([Ns], build=Nms,
  motifs' bare NNNms), with case-8 seed-0 replaying its pinned
  reference (stalemate@51, releases=2, renewal-captures=1). Identity
  is by construction (the donor knob zero-defaults, the filter change
  sits behind donation_guard) and now by measurement.

Of the finding's three directions this takes the first two: stock-
quality weighting is the tiered eval, and the free-donation arm is
the tier veto (the recapture scan already reached Bxb7; only the
predicate was blind). Donor-range tapering — gradient WITHIN tier 1
as donors dwindle, advance, or stand blocked — is deliberately NOT
taken: the tier fix removes the estate-bet that made the c4 train
fatal, the boundary where a donor family dies outright was always
priced at the adversarial leaf, and a finer donor-count gradient
needs corpus evidence before it earns a knob. It moves to the watch
list below.

The field-frontier list now reads (supersedes the vfGeEKhy list):

1. **Pin a field baseline battery**: the field profile now diverges
   from vi by design (the guard filters, the floor prices), so the
   drills need field-profile reference numbers of their own, plus a
   field-vs-Zach arena A/B to measure what the floor costs against
   the opponent that never punishes. Do this BEFORE the next tuning
   round touches a field knob — today the selftest poses are the only
   pinned field behavior.
2. **The sloppy-human opponent model** (strip/midgame scope only; vi
   herding stays Zach-scoped — the frozen-statics premise breaks
   under capturing kernels).
3. **Corpus protocol continues**: every game in
   `lichess/game_records/` gets its replay-through-the-filter read
   and lands here. Watch items for the next accepting human: does the
   tier hold the right family under pressure; does donor-range
   tapering earn its knob (a tier-1 game that dies to a donor train
   the way vfGeEKhy did); and the standing one — a human who keeps
   their b/g pawns, because the corner construction has still never
   posed against a live opponent.

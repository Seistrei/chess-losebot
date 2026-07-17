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

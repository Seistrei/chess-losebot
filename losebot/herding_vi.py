"""Exact value iteration over the frozen-cage herding sub-MDP.

Against a fixed stochastic opponent policy (Zach samples uniformly from
``support_zach``), herding is not adversarial search: it is a Markov decision
process. During the herd phase almost every piece is static — our king parked
on the checked square, the holder frozen on the arrival square, the cage and
pawn blockers in place, the opponent reduced to a king plus frozen pawns. The
only dynamic units are THEIR KING and one or two of OUR free pieces (the
"herders"). That sub-MDP is small enough to solve exactly.

States are (side to move, their king square, herder placement). Our edges are
quiet herder moves; their edges are Zach's uniform pool, which in this regime
is exactly the quiet king moves — computed from bitboard attack maps without
touching python-chess. Whenever the fast pool is empty the state is classified
on a real reconstructed board with ``support_zach`` itself (stalemate, forced
mate, or a forced capture that breaks the statics), so the model can never
silently diverge from the arena's Zach.

Goal states (value 1) are where the surrounding machinery takes over:
- their king adjacent to the arrival square with every quiet reply staying
  adjacent (contained: the probe/release logic finishes), or
- every quiet reply entering the defense zone (the pre-release race state).
Draws, stalemates, and static-breaking captures are value 0.

When the arrival square is held by OUR KING (the one holder type the release
theorem does not kill: a defended arrival square only bars a king capture,
so king-steps-aside is a clean release), the two goals above are structurally
unreachable — every defense-zone square is adjacent to the arrival square and
therefore king-attacked, so their king can never enter the zone while the
hold stands. Those graphs get a third goal instead, classified against the
hypothetically *vacated* position (our king moved from the arrival square to
the template's checked square): a state is GOAL_VACATE when the vacate is
legal and every post-vacate quiet reply enters the defense zone. The mating
pawn's own premature push (legal the moment the king steps off) is not a
king move and is deliberately absent from this proxy; the conversion audit
scores the actual vacate with ``score_release_moves``, where the push shows
up as the losing side of the race.

The herd phase is all quiet moves, so the arena's fifty-move rule caps an
era at 100 plies — a budget the discounted values cannot see (gamma prices
time softly; the cliff is hard). Hitting-time statistics per state close
the gap, all FINISH-INCLUSIVE: distances are seeded at per-terminal tail
costs (the plies the win still owes past arrival), so they measure plies
to COMPLETE the win, not to reach a proxy. The tails come in two tiers,
because rejection and affirmation need opposite conservatism. ``min_hit``
seeds each terminal at its ``_TERMINAL_TAILS`` floor — the cheapest finish
any terminal of that kind could have — and takes the min over children at
our nodes and their nodes alike (a unit-edge backward BFS): exact,
solver-independent, and still a sound lower bound after any repetition
burn (burning only removes paths), which makes ``min_hit > remaining`` a
certificate that this era cannot finish and the per-child form a sound
candidate veto. It must never AFFIRM: a goal's audited win can owe more
plies than the floor (a king-holder vacate race spends closer moves the
floor cannot see). ``fit_hit`` is the same BFS seeded at each terminal's
PROVEN completion tail — recorded by the conversion audit from its
accepted race, a conservative upper bound where the probe proved early —
so ``fit_hit <= remaining`` is the sound form for affirmative decisions:
suppressing the near-cliff lottery, certifying a clock reset's per-reply
fits. Unlike ``min_hit``, the affirmative statistics treat burned states
as BARRIERS (a path through a twice-seen position draws, proving no
finish) and go stale the moment the burn set moves. ``exp_hit`` is the
expected plies to finish under the greedy stationary policy, conditioned
on hitting and seeded with the same proven tails (it feeds affirmations
too) — advisory by design (one fixed policy, not the play that follows),
computed at build time, recomputed when a resumed solve first converges,
and retried on a dedicated budget when the build deadline truncated it
(``refresh_hit_stats``; a truncation behind a converged solve would
otherwise be permanent). Consumers that AFFIRM — and the advisory soft
clock trigger, whose truncated ratio can err either way — require the
``converged`` + ``hit_converged`` honesty flags; only the min_hit
certificates may speak from a half-solved graph.

Those goals are proxies — they stop one move short of the release and the
actual selfmate. The conversion audit closes the gap: every reachable goal
terminal is reconstructed on a real board and scored with the same release
probe the bot uses at play time, so ``root_converts`` reports whether any
reachable terminal actually finishes the game — a FORCED_MATE terminal (a
conversion by definition), or a goal that releases into an acceptable race.
It is a positive fact (all explored states are root-reachable) while
``root_live`` keeps its proxy meaning; its absence is a verdict only when
``conversion_complete``. Once anything converts, terminal values become
real win probabilities — forced mates 1, audited goals their race odds,
refused and *unchecked* goals 0, since a known conversion must outrank an
unknown proxy. With no converting terminal anywhere, the flat proxy values
are kept and the mismatch is reported rather than silently played into.

The dead/live certificate is pure graph reachability, not a numeric result:
our nodes maximize, their nodes average a full support with positive weights,
and every non-goal terminal is 0, so the exact fixpoint has V(state) > 0 iff
a goal terminal is reachable from it. ``root_live`` is therefore computed by
one backward BFS from the goal terminals over the completed graph — exact,
O(states + edges), and immune to solver deadlines. Discounted value iteration
(asynchronous, parent-driven worklist, resumable across moves) is only used
to *rank* moves; ``converged`` reports honestly whether those ranks are
final. A partial solve can degrade play, never a certificate.

Play time adds the arena's threefold rule to the model. Every sub-MDP state
is one real position (the statics never move), and the arena draws the third
occurrence of a position whichever side is to move — including an our-turn
position reached by ZACH's reply, which no tally of our own move choices can
see (the drill's Rf5/Rf7 shuttle: both rook moves were fresh, the funnel
state was not). ``apply_repetition_history`` therefore recounts the game's
reversible era each move, maps every position onto a graph state, and clamps
each twice-seen state to value 0: re-entering it IS the draw, so it is a
losing terminal for as long as the era lasts. The decrease propagates through
the same worklist solver (discounted Bellman is a sup-norm contraction, so
resuming from clamped values converges from any start), and an irreversible
move resets the era and lifts the burns. The build-time certificates are
deliberately untouched: burning prices play, never deadness.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from itertools import combinations
import time

import chess

from .search import ProofStatus, arena_draw, selfmate_status, support_zach
from .templates import PawnMateTemplate

# Terminal kinds. NORMAL_* states are non-terminal.
NORMAL_OUR = 0
NORMAL_THEIR = 1
GOAL_CONTAINED = 2
GOAL_RACE = 3
FORCED_MATE = 4
STALEMATE = 5
CAPTURE_BREAK = 6
DEAD_END = 7
MATED_THEM = 8
GOAL_VACATE = 9

_TERMINAL_NAMES = {
    GOAL_CONTAINED: "goal-contained",
    GOAL_RACE: "goal-race",
    FORCED_MATE: "forced-mate",
    STALEMATE: "stalemate",
    CAPTURE_BREAK: "capture-break",
    DEAD_END: "dead-end",
    MATED_THEM: "mated-them",
    GOAL_VACATE: "goal-vacate",
}

# Build failures that depend on the current dynamic placement rather than the
# static configuration; retrying them next move is cheap and meaningful.
POSITION_DEPENDENT_FAILURES = frozenset({"root-already-terminal"})

_WIN_KINDS = (GOAL_CONTAINED, GOAL_RACE, FORCED_MATE, GOAL_VACATE)

# Sentinel for "no positively seeded terminal reachable" in min_hit arrays.
HIT_INF = 1 << 30

# Plies still owed AFTER a positively seeded terminal is reached, per
# terminal kind — the FLOOR the min_hit lower bound folds in. A
# FORCED_MATE terminal is Zach to move with every reply mating us: the
# arena adjudicates draws before his reply, so the terminal itself must
# sit at clock <= 99 and the tail is exactly one ply. A goal terminal is
# our turn: the cheapest conceivable finish is the release push (its
# landing must be at clock <= 99) plus an immediately mating reply — two
# plies. Races whose winning replies need probe-proven continuations owe
# more; the conversion audit records each converting goal's PROVEN tail
# and the AFFIRMATIVE statistics (fit_hit, exp_hit) seed with that
# instead. A floor is only ever sound for hard rejection — a uniform
# tail falsely rejected forced-mate finishes one ply from the cliff
# (review P1 — fm-organic-h at halfmove 98: one quiet move reaches clock
# 99 and hxg2# still wins), and the bare floor falsely AFFIRMED
# king-holder finishes whose audited race owes closer moves past the
# release (review P1 — the Kh1/Kh3/Ng6/g2# branch is a four-ply tail).
_TERMINAL_TAILS = {
    FORCED_MATE: 1,
    GOAL_CONTAINED: 2,
    GOAL_RACE: 2,
    GOAL_VACATE: 2,
}

# Depth, in our own moves, of the release scorer's per-reply continuation
# probes. A winning reply is an immediate mate or a PROVEN selfmate within
# this many of our moves, so an accepted race completes within
# release + reply + 2 * probe_n plies of its goal — the conservative
# affirmative tail whenever the audit did not record a tighter one.
_RELEASE_PROBE_N = 2
_GOAL_TAIL_CAP = 2 + 2 * _RELEASE_PROBE_N

# Herder preference: rooks cut files (the classic boxing tool), bishops hold
# diagonals cheaply, knights tempo, queens last (they widen branching without
# herding better than a rook here).
_HERDER_PREFERENCE = {
    chess.ROOK: 0,
    chess.BISHOP: 1,
    chess.KNIGHT: 2,
    chess.QUEEN: 3,
}


@dataclass
class BuildReport:
    ok: bool
    reason: str = ""
    herders: tuple = ()
    states: int = 0
    edges: int = 0
    updates: int = 0
    root_value: float = 0.0
    build_ms: float = 0.0
    terminals: dict = field(default_factory=dict)
    pool_mismatches: int = 0
    slow_pool_checks: int = 0
    # The certificate (exact, from backward reachability over the completed
    # graph) and the solver's honesty flag (False when value iteration hit
    # its deadline or update limit before draining the worklist).
    root_live: bool = False
    converged: bool = False
    # Conversion audit. root_live means a *proxy* goal terminal is reachable;
    # these fields report whether any reachable terminal actually finishes
    # the game in our favor: a FORCED_MATE terminal (a real conversion, no
    # release needed), or a proxy goal whose release probe accepts a race.
    # root_converts=True is a positive fact (every explored state is
    # root-reachable). conversion_complete=False means the audit deadline
    # expired before every goal was visited OR some goal's refusal leaned on
    # an UNKNOWN reply probe (conversion_unknowns counts those): either way
    # the absence of a converting goal is unknown, never a verdict —
    # negative verdicts require conversion_complete. Probes are
    # depth-bounded, so even a complete all-refused audit is "no conversion
    # provable at this depth", not an exact impossibility — an honest flip
    # trigger, not a reachability fact. conversion_nodes bills every audit
    # probe, refusals included.
    goal_states: int = 0
    forced_mates: int = 0
    conversion_checked: int = 0
    converting_goals: int = 0
    conversion_nodes: int = 0
    conversion_unknowns: int = 0
    conversion_complete: bool = False
    root_converts: bool = False
    # Clock feasibility: hitting-time statistics over the completed graph,
    # finish-inclusive (each positively seeded terminal is seeded at a
    # per-kind tail, so the numbers are plies to COMPLETE the win).
    # min_hit_root seeds the _TERMINAL_TAILS floor and takes best-case
    # Zach — a sound lower bound on the quiet plies this era still needs,
    # so min_hit_root > remaining certifies the era cannot finish; it may
    # never affirm. fit_hit_root seeds each terminal's audit-proven
    # completion tail instead — the sound bound for affirmative reads.
    # 0 means no positively seeded terminal is reachable at all (or the
    # stats were never computed): callers must read 0 as unknown, never
    # as "instant". exp_hit_root is the expected plies to finish under
    # the greedy stationary policy conditioned on hitting, seeded with
    # the proven tails (0.0 = not available), and hit_converged reports
    # whether that iteration drained before its cap.
    min_hit_root: int = 0
    fit_hit_root: int = 0
    exp_hit_root: float = 0.0
    hit_converged: bool = False


def _piece_attacks(piece_type: int, square: int, occupied: int) -> int:
    if piece_type == chess.KNIGHT:
        return chess.BB_KNIGHT_ATTACKS[square]
    if piece_type == chess.KING:
        return chess.BB_KING_ATTACKS[square]
    attacks = 0
    if piece_type in (chess.BISHOP, chess.QUEEN):
        attacks |= chess.BB_DIAG_ATTACKS[square][
            chess.BB_DIAG_MASKS[square] & occupied
        ]
    if piece_type in (chess.ROOK, chess.QUEEN):
        attacks |= chess.BB_RANK_ATTACKS[square][
            chess.BB_RANK_MASKS[square] & occupied
        ] | chess.BB_FILE_ATTACKS[square][
            chess.BB_FILE_MASKS[square] & occupied
        ]
    return attacks


def _herding_geometry(board: chess.Board, us: chess.Color, arrival: int):
    """Blockers, cage reserve, defense zone, and ranked herder candidates.

    Shared by the policy build and the subset enumeration so the two can
    never disagree about which pieces are free to herd. Returns a reason
    string on failure instead of the tuple.
    """
    them = not us
    their_king = board.king(them)
    our_king = board.king(us)
    if their_king is None or our_king is None:
        return "missing-king"

    step = 8 if them == chess.WHITE else -8
    their_pawns = list(board.pieces(chess.PAWN, them))
    blocker_squares = set()
    for pawn in their_pawns:
        front = pawn + step
        if 0 <= front < 64:
            blocker_squares.add(front)

    # The caller gates on our_king_steps == 0, so our king stands on the
    # checked square and its neighborhood is the cage reserve.
    cage_squares = set(chess.SquareSet(chess.BB_KING_ATTACKS[our_king]))

    # Squares whose Chebyshev distance to the arrival square is <= 1:
    # standing there is defender_steps == 0.
    defense_zone = frozenset(
        square for square in range(64)
        if chess.square_distance(square, arrival) <= 1
        and square != arrival
    )
    zone_bb = 0
    for square in defense_zone:
        zone_bb |= chess.BB_SQUARES[square]

    candidates = []
    for square, piece in board.piece_map().items():
        if piece.color != us:
            continue
        if piece.piece_type in (chess.KING, chess.PAWN):
            continue
        if square == arrival:
            continue  # the holder never herds
        if square in blocker_squares:
            continue  # freeze-blockers must not move
        if square in cage_squares:
            continue  # the cage reserve stays put
        # A piece that currently covers defense-zone squares seals the
        # door shut for as long as it is static. Prefer it as a herder so
        # its coverage becomes something the policy can move out of the
        # way — that is usually what opens the zone at all.
        covers_zone = bool(board.attacks_mask(square) & zone_bb)
        candidates.append((
            0 if covers_zone else 1,
            _HERDER_PREFERENCE.get(piece.piece_type, 9),
            square,
            piece.piece_type,
        ))
    candidates.sort()
    return step, their_pawns, blocker_squares, cage_squares, defense_zone, candidates


def herder_subsets(board: chess.Board, target: PawnMateTemplate,
                   max_herders: int,
                   candidate_cap: int = 8) -> tuple[list[tuple], bool]:
    """Enumerate the maximal herder subsets for this static configuration.

    Deadness is monotone in the herder set: an unchosen candidate is frozen
    where it stands, and any trajectory of a smaller subset is replayable by
    a larger one that simply never moves the extra piece — occupancy,
    attacks, pools, and terminal classification are all identical along it.
    A side may therefore only be declared dead once every *maximal* subset
    (size = min(max_herders, candidates)) is certified dead; smaller subsets
    are covered by implication. The build's own greedy preference comes
    first, so the common live case still costs one build.

    Returns ``(subsets, complete)``. The enumeration itself is never
    silently truncated — builds are the expensive part and the caller's
    sweep deadline bounds those — but ``candidate_cap`` still guards the
    combinatorial blowup of a freakish position. When it bites, ``complete``
    is False and no all-dead sweep over the returned subsets may be read as
    a hopeless certificate: an omitted candidate could be the live one.
    """
    geometry = _herding_geometry(board, board.turn, target.arrival_square)
    if isinstance(geometry, str):
        return [], True
    all_candidates = geometry[-1]
    candidates = all_candidates[:candidate_cap]
    complete = len(all_candidates) <= candidate_cap
    size = min(max(0, max_herders), len(candidates))
    if size == 0:
        return [], complete
    subsets = [
        tuple((square, ptype) for _, _, square, ptype in combo)
        for combo in combinations(candidates, size)
    ]
    return subsets, complete


class HerdingPolicy:
    """A solved herding sub-MDP bound to one static piece configuration."""

    def __init__(self, us: chess.Color, target: PawnMateTemplate,
                 gamma: float):
        self.us = us
        self.them = not us
        self.gamma = gamma
        self.arrival = target.arrival_square
        self._target = target
        self.report = BuildReport(ok=False)
        # Conversion audit results: goal-terminal index -> probability that
        # the best acceptable release converts (0.0 = probed and refused).
        self._conversion: dict[int, float] = {}
        # goal-terminal index -> proven completion tail in plies (release,
        # reply, and the continuation depth its winning replies actually
        # needed), recorded for converting goals only. Seeds the
        # affirmative hitting statistics; absent entries fall back to the
        # conservative _GOAL_TAIL_CAP.
        self._conversion_tail: dict[int, int] = {}
        self._stripped = False
        # King-holder mode (set by _split_board): our king is the arrival
        # holder, goals are classified against the hypothetically vacated
        # position, with the king on _vacate_square (the checked square).
        self._king_holder = False
        self._vacate_square: int | None = None

        # Static configuration (filled by build).
        self.static_map: dict[int, chess.Piece] = {}
        self.herder_types: tuple[int, ...] = ()
        self.halfmove_clock = 0
        # The root state tuple; first element False for a their-turn root.
        self._root_state: tuple | None = None
        # (arrival, herder-type multiset, static placement) — herder squares
        # excluded because they wander. Scopes any negative memory a caller
        # keeps to exactly the configuration that was certified. The rooted
        # variant appends the dynamic root (their king + herder squares):
        # reachable-graph size is a property of the root, so state-cap and
        # timeout failures must be remembered per root, never per config —
        # one oversized root would otherwise permanently suppress a later
        # affordable root of the same static configuration.
        self.fingerprint: tuple | None = None
        self.rooted_fingerprint: tuple | None = None

        # Graph.
        self._index: dict[tuple, int] = {}
        self._states: list[tuple] = []
        self._kind: list[int] = []
        self._children: list[list[int]] = []
        self._parents: list[list[int]] = []
        self._values: list[float] = []
        self._live: bytearray | None = None

        # Resumable solver state (seeded on the first _solve call).
        self._worklist: deque | None = None
        self._queued: bytearray | None = None

        # Hitting-time statistics (computed once at build, after the solve).
        self._min_hit: list[int] | None = None
        self._fit_hit: list[int] | None = None
        self._seed_reach: bytearray | None = None
        self._exp_hit: list[float] | None = None
        # One dedicated retry of a deadline-truncated p/m pass per value
        # basis (see refresh_hit_stats).
        self._hit_refresh_spent = False

        # Play-time repetition burn: states whose position the current
        # reversible era has already seen twice. Entering one again is the
        # arena's threefold draw, so their values are pinned at 0 until the
        # era resets. Kept separate from the graph so certificates and the
        # build-time solve never depend on game history.
        self._burned: bytearray | None = None
        self._burned_set: set[int] = set()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, board: chess.Board, target: PawnMateTemplate,
              max_herders: int, state_cap: int, time_budget_ms: int,
              gamma: float, herders: tuple | None = None,
              max_updates: int | None = None,
              validate_pools: bool = False,
              skip_fingerprints=(),
              model: str | None = "zach",
              race_max_losing: int = 1,
              conversion_ms: int = 3_000,
              conversion_probe_cap: int = 6_000,
              root_theirs: bool = False) -> "HerdingPolicy":
        """Explore, certify, solve, and conversion-audit one configuration.

        ``herders`` forces an explicit subset (as enumerated by
        ``herder_subsets``) instead of the greedy pick. ``max_updates`` caps
        value-iteration work per call (tests). ``validate_pools`` cross-checks
        every explored opponent pool against ``support_zach`` — slow, for
        tests and audits only. ``skip_fingerprints`` aborts right after the
        cheap split when the configuration (or this exact root of it) is one
        the caller already knows it cannot afford to explore. ``model`` and
        ``race_max_losing`` feed the conversion audit's release probes;
        ``conversion_ms`` caps the audit's wall clock so it cannot starve
        the solver, and ``conversion_probe_cap`` is the per-reply node cap
        of its release probes (research audits raise it so refusals rest on
        DISPROVEN, not budget exhaustion).

        ``root_theirs`` roots the graph at the given position with THEIR
        side to move (the board's side to move is then the opponent, and
        the herding side is the other color). The clock-reset device needs
        this: after our pawn push it is Zach's turn, and certifying the
        skipped-turn position with our side to move would speak about a
        root the game can never reach (review P1) — the their-turn root's
        children are exactly the real post-reply states, so root_live,
        root_converts and the hitting stats quantify the actual
        continuation, and ``reply_fit_fraction`` reads the per-reply
        evidence directly.
        """
        policy = cls(not board.turn if root_theirs else board.turn,
                     target, gamma)
        started = time.monotonic()
        deadline = started + time_budget_ms / 1000.0

        reason = policy._split_board(
            board, max_herders, forced=herders, root_theirs=root_theirs
        )
        if reason is None and (
            policy.fingerprint in skip_fingerprints
            or policy.rooted_fingerprint in skip_fingerprints
        ):
            reason = "skipped-unbuildable"
        if reason is None:
            reason = policy._explore(board, state_cap, deadline)
        if reason is None and validate_pools:
            policy._validate_all_pools()
        if reason is None and policy.report.pool_mismatches:
            reason = "zach-pool-mismatch"
        if reason is None:
            policy.report.ok = True
            # The certificate never depends on the solver: reachability over
            # the completed graph is exact whatever the deadline does below.
            policy.report.root_live = policy._compute_live()
            audit_deadline = min(
                deadline, time.monotonic() + conversion_ms / 1000.0
            )
            policy._audit_conversions(
                audit_deadline, model, race_max_losing, conversion_probe_cap
            )
            policy._solve(deadline, max_updates)
            policy._compute_hit_stats(deadline)
        else:
            policy.report.reason = reason
        policy.report.states = len(policy._states)
        policy.report.build_ms = (time.monotonic() - started) * 1000.0
        return policy

    def _split_board(self, board: chess.Board, max_herders: int,
                     forced: tuple | None = None,
                     root_theirs: bool = False) -> str | None:
        """Choose herders, freeze everything else, precompute attack tables."""
        us, them = self.us, self.them
        geometry = _herding_geometry(board, us, self.arrival)
        if isinstance(geometry, str):
            return geometry
        step, their_pawns, _, _, defense_zone, candidates = geometry
        their_king = board.king(them)
        self._defense_zone = defense_zone

        if forced is None:
            chosen = [
                (square, ptype)
                for _, _, square, ptype in candidates[:max(0, max_herders)]
            ]
        else:
            allowed = {(square, ptype) for _, _, square, ptype in candidates}
            chosen = list(forced)
            if not chosen or any(entry not in allowed for entry in chosen):
                return "invalid-herder-subset"
        if not chosen:
            return "no-free-herders"
        herder_squares = {square for square, _ in chosen}

        self.static_map = {
            square: piece
            for square, piece in board.piece_map().items()
            if square != their_king and square not in herder_squares
        }
        self.halfmove_clock = board.halfmove_clock

        # Every opponent pawn must be frozen by a STATIC unit; a pawn blocked
        # only by a wandering herder would silently gain a quiet push.
        for pawn in their_pawns:
            front = pawn + step
            if not (0 <= front < 64):
                return "pawn-can-promote"
            if front not in self.static_map:
                return "pawn-not-frozen"

        self.herder_types = tuple(ptype for _, ptype in chosen)
        self._root_herders = tuple(sorted(
            (ptype, square) for square, ptype in chosen
        ))
        self._root_zk = their_king
        self._root_state = (not root_theirs, their_king, self._root_herders)
        self.fingerprint = (
            self.arrival,
            tuple(sorted(self.herder_types)),
            tuple(sorted(
                (square, piece.piece_type, piece.color)
                for square, piece in self.static_map.items()
            )),
        )
        # A their-turn root reaches a different state set than the our-turn
        # root of the same placement, so its failure memory must not be
        # shared; the flag is appended only in that case to keep the
        # default tuple shape (and every existing pin) unchanged.
        self.rooted_fingerprint = (
            self.fingerprint, their_king, self._root_herders
        ) if not root_theirs else (
            self.fingerprint, their_king, self._root_herders, True
        )

        # Precomputed static tables.
        self.static_occ = 0
        self._static_fixed_attacks = 0
        self._static_sliders: list[tuple[int, int]] = []
        for square, piece in self.static_map.items():
            self.static_occ |= chess.BB_SQUARES[square]
            if piece.color != us:
                continue  # their pawns attack nothing that gates king moves?
            if piece.piece_type == chess.PAWN:
                self._static_fixed_attacks |= chess.BB_PAWN_ATTACKS[us][square]
            elif piece.piece_type == chess.KNIGHT:
                self._static_fixed_attacks |= chess.BB_KNIGHT_ATTACKS[square]
            elif piece.piece_type == chess.KING:
                self._static_fixed_attacks |= chess.BB_KING_ATTACKS[square]
            else:
                self._static_sliders.append((square, piece.piece_type))

        # King-holder mode: our king itself freezes the mating pawn from the
        # arrival square, and the goal semantics must reason about the
        # position AFTER the king steps aside to the template's checked
        # square. If that hypothetical vacate could never be legal
        # (no checked square on the target, destination occupied by a
        # static, or covered by a static of theirs), the mode stays off and
        # the graph honestly has no goals.
        holder = self.static_map.get(self.arrival)
        self._king_holder = (
            holder is not None
            and holder.color == us
            and holder.piece_type == chess.KING
        )
        self._vacate_square = None
        if self._king_holder:
            vacate = getattr(self._target, "checked_square", None)
            their_static_attacks = 0
            for square, piece in self.static_map.items():
                if piece.color != them:
                    continue
                if piece.piece_type != chess.PAWN:
                    # A static opponent piece is outside this model's regime;
                    # refuse the mode rather than mis-certify around it.
                    their_static_attacks = ~0
                    break
                their_static_attacks |= chess.BB_PAWN_ATTACKS[them][square]
            if (
                vacate is None
                # The vacate is one king step off the arrival square; an
                # ad-hoc target whose checked square is further away would
                # classify goals through an impossible teleport.
                or chess.square_distance(vacate, self.arrival) != 1
                or vacate in self.static_map
                or their_static_attacks & chess.BB_SQUARES[vacate]
            ):
                self._king_holder = False
            else:
                self._vacate_square = vacate
                vac_bb = chess.BB_SQUARES[vacate]
                arr_bb = chess.BB_SQUARES[self.arrival]
                self._static_occ_vacated = (self.static_occ & ~arr_bb) | vac_bb
                fixed = 0
                for square, piece in self.static_map.items():
                    if piece.color != us:
                        continue
                    if piece.piece_type == chess.PAWN:
                        fixed |= chess.BB_PAWN_ATTACKS[us][square]
                    elif piece.piece_type == chess.KNIGHT:
                        fixed |= chess.BB_KNIGHT_ATTACKS[square]
                    elif piece.piece_type == chess.KING:
                        fixed |= chess.BB_KING_ATTACKS[
                            vacate if square == self.arrival else square
                        ]
                self._static_fixed_attacks_vacated = fixed

        return None

    # ------------------------------------------------------------------
    # Move generation on bitboards
    # ------------------------------------------------------------------

    def _white_attacks(self, herders: tuple) -> int:
        """Squares our units attack. Their king is deliberately absent from
        the occupancy so sliders see through it (king-danger semantics)."""
        occupied = self.static_occ
        for _, square in herders:
            occupied |= chess.BB_SQUARES[square]
        attacks = self._static_fixed_attacks
        for square, ptype in self._static_sliders:
            attacks |= _piece_attacks(ptype, square, occupied)
        for ptype, square in herders:
            attacks |= _piece_attacks(ptype, square, occupied)
        return attacks

    def _their_quiet_moves(self, zk: int, herders: tuple) -> list[int]:
        """Zach's fast-path pool: quiet king moves to unattacked squares."""
        occupied = self.static_occ | chess.BB_SQUARES[zk]
        for _, square in herders:
            occupied |= chess.BB_SQUARES[square]
        moves_bb = (
            chess.BB_KING_ATTACKS[zk]
            & ~occupied
            & ~self._white_attacks(herders)
        )
        return list(chess.scan_forward(moves_bb))

    def _their_quiet_moves_vacated(self, zk: int, herders: tuple) -> list[int]:
        """Zach's quiet king pool AFTER the hypothetical king vacate.

        Their king is deliberately absent from the attack occupancy, exactly
        as in ``_white_attacks``: a slider whose ray the vacate opens onto
        their king must keep attacking the squares BEHIND it (the king
        cannot step backward along the ray out of check). Including the king
        as a blocker admitted exactly that illegal retreat.
        """
        occupied = self._static_occ_vacated
        for _, square in herders:
            occupied |= chess.BB_SQUARES[square]
        attacks = self._static_fixed_attacks_vacated
        for square, ptype in self._static_sliders:
            attacks |= _piece_attacks(ptype, square, occupied)
        for ptype, square in herders:
            attacks |= _piece_attacks(ptype, square, occupied)
        moves_bb = (
            chess.BB_KING_ATTACKS[zk]
            & ~(occupied | chess.BB_SQUARES[zk])
            & ~attacks
        )
        return list(chess.scan_forward(moves_bb))

    def _our_moves(self, zk: int, herders: tuple):
        """Yield (herder_index, from_sq, to_sq, next_herders). Quiet only."""
        occupied = self.static_occ | chess.BB_SQUARES[zk]
        for _, square in herders:
            occupied |= chess.BB_SQUARES[square]
        for i, (ptype, square) in enumerate(herders):
            targets = _piece_attacks(ptype, square, occupied) & ~occupied
            rest = herders[:i] + herders[i + 1:]
            for to_sq in chess.scan_forward(targets):
                next_herders = tuple(sorted(rest + ((ptype, to_sq),)))
                yield i, square, to_sq, next_herders

    # ------------------------------------------------------------------
    # Real-board reconstruction (slow path + validation)
    # ------------------------------------------------------------------

    def board_for(self, zk: int, herders: tuple, our_move: bool) -> chess.Board:
        board = chess.Board(None)
        for square, piece in self.static_map.items():
            board.set_piece_at(square, piece)
        board.set_piece_at(zk, chess.Piece(chess.KING, self.them))
        for ptype, square in herders:
            board.set_piece_at(square, chess.Piece(ptype, self.us))
        board.turn = self.us if our_move else self.them
        board.castling_rights = 0
        board.halfmove_clock = self.halfmove_clock
        return board

    def _classify_slow(self, zk: int, herders: tuple) -> int:
        """Their turn, no quiet king moves: ask the real Zach pool."""
        self.report.slow_pool_checks += 1
        board = self.board_for(zk, herders, our_move=False)
        legal = list(board.legal_moves)
        if not legal:
            # Either we stalemated them or (a herder having delivered an
            # unavoidable mate) checkmated them: both are misère losses.
            return MATED_THEM if board.is_check() else STALEMATE
        pool = support_zach(board)
        if not pool:
            return FORCED_MATE  # every legal reply checkmates us
        for move in pool:
            if not board.is_capture(move):
                # Our fast path believed there were no quiet moves. A quiet
                # pool move here means the bitboard model diverged from Zach.
                self.report.pool_mismatches += 1
                break
        return CAPTURE_BREAK

    def _validate_pool(self, zk: int, herders: tuple) -> None:
        """Compare the fast pool with support_zach on one real board."""
        board = self.board_for(zk, herders, our_move=False)
        expected = {
            move.to_square
            for move in support_zach(board)
            if board.piece_type_at(move.from_square) == chess.KING
            and not board.is_capture(move)
        }
        also_quiet_nonking = any(
            board.piece_type_at(move.from_square) != chess.KING
            and not board.is_capture(move)
            for move in support_zach(board)
        )
        fast = set(self._their_quiet_moves(zk, herders))
        if fast != expected or also_quiet_nonking:
            self.report.pool_mismatches += 1

    def _validate_all_pools(self) -> None:
        """Cross-check every explored opponent pool against support_zach.

        The routine build only validates the root pool and the empty-pool
        slow path, so "0 mismatches" there is evidence, not proof, that the
        bitboard model matches the arena's Zach on interior states. This
        sweep reconstructs a real board for every their-turn state and is
        therefore slow: tests and audits, not arena builds.
        """
        for state, kind in zip(self._states, self._kind):
            if kind != NORMAL_THEIR:
                continue
            _, zk, herders = state
            self._validate_pool(zk, herders)

    # ------------------------------------------------------------------
    # Goal classification
    # ------------------------------------------------------------------

    def _classify_our_state(self, zk: int, herders: tuple) -> int:
        """Terminal classification for a state with US to move."""
        if self._king_holder:
            return self._classify_vacate_state(zk, herders)
        in_zone = zk in self._defense_zone
        pool = self._their_quiet_moves(zk, herders)
        if in_zone:
            if all(square in self._defense_zone for square in pool):
                # Contained: adjacent to the arrival square and unable to
                # leave the defense zone. Probe/release machinery takes over.
                return GOAL_CONTAINED
            return NORMAL_OUR
        if pool and all(square in self._defense_zone for square in pool):
            # Every quiet reply steps into the defense zone: the release
            # race can be offered from here.
            return GOAL_RACE
        return NORMAL_OUR

    def _classify_vacate_state(self, zk: int, herders: tuple) -> int:
        """King-holder goal: does stepping aside start a winnable race?

        The vacate must be playable right now — destination unoccupied and
        not adjacent to their king (static occupancy and their static pawn
        attacks were checked once at build time) — and every post-vacate
        quiet reply must enter the defense zone. The premature pawn push
        the vacate legalizes is not a king move and is invisible to this
        proxy by design; the conversion audit scores the actual vacate with
        ``score_release_moves``, where the push is the losing side of the
        race.
        """
        vacate = self._vacate_square
        if chess.square_distance(zk, vacate) <= 1:
            return NORMAL_OUR
        for _, square in herders:
            if square == vacate:
                return NORMAL_OUR
        pool = self._their_quiet_moves_vacated(zk, herders)
        if pool and all(square in self._defense_zone for square in pool):
            return GOAL_VACATE
        return NORMAL_OUR

    # ------------------------------------------------------------------
    # Graph exploration
    # ------------------------------------------------------------------

    def _state_index(self, state: tuple, kind: int,
                     queue: deque | None) -> int:
        index = self._index.get(state)
        if index is not None:
            return index
        index = len(self._states)
        self._index[state] = index
        self._states.append(state)
        self._kind.append(kind)
        self._children.append([])
        self._parents.append([])
        self._values.append(0.0)
        if queue is not None and kind in (NORMAL_OUR, NORMAL_THEIR):
            queue.append(index)
        return index

    def _explore(self, board: chess.Board, state_cap: int,
                 deadline: float) -> str | None:
        root_state = self._root_state
        if root_state[0]:
            root_kind = self._classify_our_state(
                self._root_zk, self._root_herders
            )
        else:
            # Their-turn root (the clock-reset hypothetical): a nonempty
            # quiet pool is a normal opponent node; an empty one means the
            # root itself is terminal — including FORCED_MATE, which the
            # exact probe upstream owns (our push forcing every reply to
            # mate is a selfmate-in-1 the probe plays before any reset
            # scan runs), so refusing it here loses nothing.
            quiet = self._their_quiet_moves(
                self._root_zk, self._root_herders
            )
            root_kind = (
                NORMAL_THEIR if quiet
                else self._classify_slow(self._root_zk, self._root_herders)
            )
        if root_kind not in (NORMAL_OUR, NORMAL_THEIR):
            return "root-already-terminal"

        queue: deque = deque()
        self._state_index(root_state, root_kind, queue)
        self._validate_pool(self._root_zk, self._root_herders)

        edges = 0
        checked = 0
        while queue:
            checked += 1
            if checked % 512 == 0 and time.monotonic() > deadline:
                return "build-timeout"
            if len(self._states) > state_cap:
                return "state-cap"
            index = queue.popleft()
            our_move, zk, herders = self._states[index]
            children = self._children[index]

            if our_move:
                for _, _, _, next_herders in self._our_moves(zk, herders):
                    child_state = (False, zk, next_herders)
                    child_index = self._index.get(child_state)
                    if child_index is None:
                        quiet = self._their_quiet_moves(zk, next_herders)
                        if quiet:
                            kind = NORMAL_THEIR
                        else:
                            kind = self._classify_slow(zk, next_herders)
                        child_index = self._state_index(
                            child_state, kind, queue
                        )
                    children.append(child_index)
                    self._parents[child_index].append(index)
                    edges += 1
                if not children:
                    self._kind[index] = DEAD_END
            else:
                for to_sq in self._their_quiet_moves(zk, herders):
                    child_state = (True, to_sq, herders)
                    child_index = self._index.get(child_state)
                    if child_index is None:
                        kind = self._classify_our_state(to_sq, herders)
                        child_index = self._state_index(
                            child_state, kind, queue
                        )
                    children.append(child_index)
                    self._parents[child_index].append(index)
                    edges += 1
                # A their-turn state with no quiet moves was classified on
                # creation and never queued, so children cannot be empty here.

        self.report.edges = edges
        return None

    # ------------------------------------------------------------------
    # Certificate: exact reachability, independent of the solver
    # ------------------------------------------------------------------

    def _compute_live(self) -> bool:
        """Backward BFS from the goal terminals over the completed graph.

        Our nodes maximize, their nodes average a full support with positive
        weights, and every non-goal terminal is worth 0 — so in the exact
        fixpoint V(state) > 0 iff the state can reach a goal terminal. That
        makes dead/live a graph property, decidable without a single Bellman
        update and immune to solver deadlines and tolerances.
        """
        live = bytearray(len(self._states))
        stack = [
            index for index, kind in enumerate(self._kind)
            if kind in _WIN_KINDS
        ]
        for index in stack:
            live[index] = 1
        while stack:
            index = stack.pop()
            for parent in self._parents[index]:
                if not live[parent]:
                    live[parent] = 1
                    stack.append(parent)
        self._live = live
        root = self._index.get(self._root_state)
        return root is not None and bool(live[root])

    # ------------------------------------------------------------------
    # Conversion audit: do the reachable goals actually release?
    # ------------------------------------------------------------------

    def _release_plausible(self, zk: int, herders: tuple) -> bool:
        """Cheap ordering heuristic: can the holder retreat anywhere that
        stops attacking the arrival square? A retreat that keeps attacking
        it refutes the mate itself (the retreated holder just captures the
        checking pawn — their king's defense only bars OUR KING). Purely a
        probe-ordering hint: multi-tempo escapes, interpositions, and checks
        make static geometry unsound as a verdict, so the exact probe always
        gets the final word."""
        holder = self.static_map.get(self.arrival)
        if holder is None:
            return True
        if holder.piece_type == chess.KING:
            # A king's re-attack of the vacated arrival square never refutes
            # the mate: the defender that makes this state a goal also bars
            # the king capture — that is the point of the king-holder motif.
            # Every king retreat is worth probing.
            return True
        occupied = self.static_occ | chess.BB_SQUARES[zk]
        for _, square in herders:
            occupied |= chess.BB_SQUARES[square]
        vacated = occupied & ~chess.BB_SQUARES[self.arrival]
        arrival_bb = chess.BB_SQUARES[self.arrival]
        retreats = (
            _piece_attacks(holder.piece_type, self.arrival, occupied)
            & ~occupied
        )
        for retreat in chess.scan_forward(retreats):
            after = vacated | chess.BB_SQUARES[retreat]
            if not (
                _piece_attacks(holder.piece_type, retreat, after)
                & arrival_bb
            ):
                return True
        return False

    def _audit_conversions(self, deadline: float, model: str | None,
                           race_max_losing: int,
                           probe_cap: int = 6_000) -> None:
        """Score the actual release at every reachable goal terminal.

        ``root_live`` certifies that a proxy goal is reachable; this audit
        asks whether any reachable terminal actually *converts*. FORCED_MATE
        terminals convert by definition (every legal reply mates us — no
        release needed). Proxy goals convert when the holder has a retreat
        whose scored race the release machinery would accept: each goal
        terminal is reconstructed on a real board and scored with the same
        ``score_release_moves`` the bot uses at play time, so the audit
        predicts exactly what play would discover on arrival. Every explored
        state is root-reachable, so one converting terminal makes
        ``root_converts`` a positive fact about the root.

        A goal refused while any of its reply probes returned UNKNOWN is a
        budget artifact, not a verdict: it counts in ``conversion_unknowns``
        and forces ``conversion_complete=False``, so downstream negatives
        stay inadmissible exactly as if the audit had been cut short.
        """
        goal_indices = []
        forced_mates = 0
        for index, kind in enumerate(self._kind):
            if kind in (GOAL_CONTAINED, GOAL_RACE, GOAL_VACATE):
                goal_indices.append(index)
            elif kind == FORCED_MATE:
                forced_mates += 1
        self.report.forced_mates = forced_mates
        self.report.goal_states = len(goal_indices)
        self.report.root_converts = forced_mates > 0
        if not goal_indices:
            self.report.conversion_complete = True
            return
        # Probe plausible releases first so a tight deadline is spent where
        # a positive fact could still be found.
        goal_indices.sort(
            key=lambda index: not self._release_plausible(
                self._states[index][1], self._states[index][2]
            )
        )
        complete = True
        nodes = [0]
        for index in goal_indices:
            if time.monotonic() > deadline:
                complete = False
                break
            _, zk, herders = self._states[index]
            board = self.board_for(zk, herders, our_move=True)
            unknowns = [0]
            choice = score_release_moves(
                board, self._target, model, race_max_losing,
                probe_cap=probe_cap, nodes_out=nodes,
                unknown_out=unknowns,
            )
            self.report.conversion_checked += 1
            if choice is None:
                self._conversion[index] = 0.0
                if unknowns[0]:
                    self.report.conversion_unknowns += 1
                continue
            self._conversion[index] = choice.winning / choice.pool
            self._conversion_tail[index] = choice.tail
            self.report.converting_goals += 1
        self.report.conversion_nodes = nodes[0]
        self.report.conversion_complete = (
            complete and self.report.conversion_unknowns == 0
        )
        self.report.root_converts = forced_mates > 0 or any(
            fraction > 0.0 for fraction in self._conversion.values()
        )

    def conversion_table(self) -> list[dict]:
        """The audit's verdict at every win-kind terminal, as plain data.

        Release-audit diagnostics only — never read by play. One row per
        goal/forced-mate terminal: the graph state (their king square,
        herder placements), the terminal kind, and the audited race
        fraction and proven tail. ``fraction`` is None for a goal the
        audit deadline never reached (distinct from an audited 0.0
        refusal); FORCED_MATE rows report 1.0 by definition. Empty on a
        stripped certificate.
        """
        rows: list[dict] = []
        if self._stripped:
            return rows
        for index, kind in enumerate(self._kind):
            if kind not in _WIN_KINDS:
                continue
            _, zk, herders = self._states[index]
            if kind == FORCED_MATE:
                fraction: float | None = 1.0
            else:
                fraction = self._conversion.get(index)
            rows.append({
                "index": index,
                "kind": _TERMINAL_NAMES[kind],
                "zk": chess.square_name(zk),
                "herders": " ".join(
                    chess.piece_symbol(ptype).upper() + chess.square_name(sq)
                    for ptype, sq in herders
                ),
                "fraction": fraction,
                "tail": self._conversion_tail.get(index),
                "burned": index in self._burned_set,
            })
        return rows

    def state_view(self, board: chess.Board) -> dict | None:
        """Diagnostic view of the graph state a position maps onto.

        Release-audit instrumentation: answers "where does the graph
        think this pose sits" — the state's kind (goal terminals by
        name, non-terminals as "interior"), its current value, whether
        the era has burned it, and its audited conversion when it is a
        goal. None when the position does not map into the explored
        graph (itself the diagnostic: play is off the audited map).
        Read-only; never called by play.
        """
        if self._stripped:
            return None
        state = self._dynamic_state(board)
        if state is None:
            return None
        index = self._index.get(state)
        if index is None:
            return None
        kind = self._kind[index]
        if kind == FORCED_MATE:
            fraction: float | None = 1.0
        else:
            fraction = self._conversion.get(index)
        return {
            "index": index,
            "kind": _TERMINAL_NAMES.get(kind, "interior"),
            "zk": chess.square_name(state[1]),
            "value": self._values[index] if self._values else None,
            "burned": index in self._burned_set,
            "fraction": fraction,
            "tail": self._conversion_tail.get(index),
        }

    def audit_board(self, board: chess.Board) -> chess.Board | None:
        """The clean reconstruction the conversion audit scores for this
        position's graph state: same placement, the build-time halfmove
        clock, no repetition history. Rescoring a release on it isolates
        what the era added — anything play refuses here that the twin
        accepts is the clock or the history talking, not the geometry.
        None off-graph. Release-audit diagnostics; never called by play.
        """
        if self._stripped:
            return None
        state = self._dynamic_state(board)
        if state is None or state not in self._index:
            return None
        _, zk, herders = state
        return self.board_for(zk, herders, our_move=True)

    # ------------------------------------------------------------------
    # Asynchronous value iteration (parent-driven worklist, resumable)
    # ------------------------------------------------------------------

    def _terminal_seed_value(self, index: int) -> float:
        """The value a terminal seeds (and is restored to when un-burned).

        Once ANY terminal converts (a forced mate, or an audited goal),
        terminal values become real win probabilities: FORCED_MATE is 1
        (it converts by definition), audited goals get their race odds,
        and everything else — refused goals AND goals the audit deadline
        never reached — seeds 0. A known conversion must outrank an
        unknown proxy; defaulting the unchecked to 1.0 would steer the
        policy at exactly the goals the plausible-first ordering ranked
        least likely to release. With no converting terminal anywhere,
        keep the flat proxy values: zeroing everything would silence the
        policy without offering a better move, and root_converts already
        reports the mismatch honestly.
        """
        kind = self._kind[index]
        if kind not in _WIN_KINDS:
            return 0.0
        if not self.report.root_converts or kind == FORCED_MATE:
            return 1.0
        return self._conversion.get(index, 0.0)

    def _enqueue(self, index: int) -> None:
        if not self._queued[index]:
            self._queued[index] = 1
            self._worklist.append(index)

    def _enqueue_parents(self, index: int) -> None:
        for parent in self._parents[index]:
            self._enqueue(parent)

    def _seed_solver(self) -> None:
        terminals: dict[str, int] = {}
        self._worklist = deque()
        self._queued = bytearray(len(self._values))
        for index, kind in enumerate(self._kind):
            if kind in (NORMAL_OUR, NORMAL_THEIR):
                continue
            name = _TERMINAL_NAMES[kind]
            terminals[name] = terminals.get(name, 0) + 1
            if kind in _WIN_KINDS:
                value = self._terminal_seed_value(index)
                if value <= 0.0:
                    continue
                self._values[index] = value
                self._enqueue_parents(index)
        self.report.terminals = terminals

    def _solve(self, deadline: float, max_updates: int | None = None) -> None:
        if self._worklist is None:
            self._seed_solver()
        values = self._values
        kinds = self._kind
        children = self._children
        parents = self._parents
        gamma = self.gamma
        worklist = self._worklist
        queued = self._queued

        updates = 0
        tolerance = 1e-6
        limit = (
            max_updates if max_updates is not None
            else 80 * max(1, len(values))
        )
        burned = self._burned
        while worklist and updates < limit:
            updates += 1
            if updates % 4096 == 0 and time.monotonic() > deadline:
                break
            index = worklist.popleft()
            queued[index] = 0
            if burned is not None and burned[index]:
                continue  # pinned at 0 while re-entry would draw
            kids = children[index]
            if not kids:
                continue
            if kinds[index] == NORMAL_OUR:
                best = 0.0
                for kid in kids:
                    value = values[kid]
                    if value > best:
                        best = value
                new_value = gamma * best
            else:
                total = 0.0
                for kid in kids:
                    total += values[kid]
                new_value = gamma * total / len(kids)
            if abs(new_value - values[index]) <= tolerance:
                continue
            values[index] = new_value
            for parent in parents[index]:
                if not queued[parent]:
                    queued[parent] = 1
                    worklist.append(parent)

        self.report.updates += updates
        # Honest convergence: an empty worklist is the only finished state.
        self.report.converged = not worklist
        root = self._index.get(self._root_state)
        if root is not None:
            self.report.root_value = values[root]

    def solve_more(self, time_budget_ms: int,
                   max_updates: int | None = None) -> bool:
        """Continue an unfinished solve; returns True once converged.

        Resuming across moves is sound from any starting values: discounted
        Bellman is a sup-norm contraction, so the worklist converges to the
        current system's fixpoint whether values approach it from below (a
        cut-short build) or from above (a repetition burn just lowered
        states other values still route through). The certificate was never
        the solver's job.
        """
        if self._stripped or not self.report.ok or self.report.converged:
            return self.report.converged
        deadline = time.monotonic() + time_budget_ms / 1000.0
        self._solve(deadline, max_updates)
        while (
            max_updates is None
            and not self.report.converged
            and time.monotonic() < deadline
        ):
            # The per-call update cap is a pacing valve, not a budget: keep
            # draining until the fixpoint or the clock, whichever is first.
            self._solve(deadline, None)
        if self.report.converged:
            # The build's hitting stats may have priced half-baked values
            # (same deadline as the solve) — refresh them now that the
            # greedy policy is real, so affirmative consumers gated on
            # converged + hit_converged read numbers that mean something
            # (review P1). Non-converting graphs skip the expensive pass
            # inside, so this is cheap exactly where it fires often.
            self._compute_hit_stats(deadline)
        return self.report.converged

    def refresh_hit_stats(self, time_budget_ms: int) -> bool:
        """Retry a deadline-truncated p/m pass behind a finished solve.

        The build shares one deadline between exploration, audit, solver,
        and hitting stats, so value iteration can converge while the p/m
        pass is cut short — and with ``converged`` True, ``solve_more``
        never runs again to trigger the recompute, leaving ``exp_hit``
        truncated for the policy's whole life (review P1). One dedicated
        full-budget retry per value basis: the pass restarts from zero,
        so a second identical budget would redo identical work — the
        spent flag clears whenever the stats are recomputed on new values
        (burn re-solves, resumed builds). Returns ``hit_converged``.
        """
        if self._stripped or not self.report.ok or not self.report.converged:
            return self.report.hit_converged
        if self.report.hit_converged or self._hit_refresh_spent:
            return self.report.hit_converged
        deadline = time.monotonic() + time_budget_ms / 1000.0
        self._compute_hit_stats(deadline)
        if not self.report.hit_converged:
            self._hit_refresh_spent = True
        return self.report.hit_converged

    # ------------------------------------------------------------------
    # Clock feasibility: hitting-time statistics
    # ------------------------------------------------------------------

    def _affirm_tail(self, index: int) -> int:
        """Proven completion tail for a positively seeded terminal.

        A FORCED_MATE owes exactly the one mating reply. A converting
        goal owes what its audited race proved (``ReleaseChoice.tail``);
        a goal seeded without an audit record — the flat proxy values of
        a non-converting graph — owes the conservative cap. Affirmative
        numbers may overstate a finish, never understate it.
        """
        if self._kind[index] == FORCED_MATE:
            return 1
        return self._conversion_tail.get(index, _GOAL_TAIL_CAP)

    def _compute_hit_stats(self, deadline: float) -> None:
        """Hitting-time statistics for the fifty-move feasibility gates.

        All statistics are FINISH-INCLUSIVE — seeded at per-terminal tail
        costs, the plies the win still owes past arrival, so a state's
        number compares against ``remaining`` directly. The tails come in
        two tiers because rejection and affirmation need opposite
        conservatism (review P1: a uniform overhead falsely rejected
        forced-mate finishes at the cliff, and the bare floor falsely
        affirmed goals whose audited race owes more than the cheapest
        conceivable finish).

        min_hit: plies to complete the win when EVERY reply cooperates —
        min over children at our nodes and their nodes alike, i.e. a
        unit-edge backward BFS from terminals seeded at the
        ``_TERMINAL_TAILS`` floor, over the parent lists. Exact,
        independent of the solver, and still a sound lower bound after
        any repetition burn (burning only removes paths), which is what
        makes ``min_hit > remaining`` a certificate that the era cannot
        finish and the per-child form a sound candidate veto. Never an
        affirmation. Computed unconditionally: it is one O(V+E) pass.

        fit_hit: the same backward pass seeded at each terminal's PROVEN
        completion tail (``_affirm_tail``), so ``fit_hit <= remaining``
        is the sound affirmative form — the finish it promises is one the
        audit actually proved, or a conservative bound on it. Burned
        states are barriers here and in the p/m pass below (review P1:
        entering a twice-seen position IS the draw, so a route through
        one proves nothing), and ``_set_burned`` stales these statistics
        on any set movement so they recompute on the new barriers.
        Computed only when the root converts, like exp_hit: affirmative
        consumers are all behind that condition, and without a conversion
        there is no proven finish to price.

        exp_hit: expected plies to finish under the greedy stationary
        policy (argmax child value; min_hit, then index as tie-breaks),
        conditioned on hitting. p is the absorption probability and m the
        mass E[plies * 1{hit}] (proven tail included via the seed mass),
        iterated by the same parent-driven worklist discipline as the
        values — both are monotone from a zero start, so the iteration
        converges from below and cutting it short (update cap or the
        build deadline) is reported honestly in ``hit_converged``; note
        the RATIO m/p of two truncated quantities can err in either
        direction, which is why every consumer — the affirmations and
        the advisory soft trigger alike (review P1: an early pass
        commonly reads inf, and a junk-armed cascade spends resets and
        flips, not just builds) — must require the honesty flags.
        Advisory by design: one fixed greedy policy, not the play that
        actually follows, even though the pass does respect the current
        burn barriers. Computed only
        when the root converts: every consumer is behind that same
        condition, and churning p/m over a large non-converting graph
        bought pure wall clock — the case-2 reference paid ~50% for
        numbers nothing reads. Recomputed when a resumed solve first
        converges, and retried once on a dedicated budget when truncation
        outlived a converged solve (``refresh_hit_stats``, review P1).
        ``hit_converged`` is trivially True when the pass is skipped.
        """
        # Any recompute prices a fresh value basis: the dedicated-retry
        # ledger starts over (see refresh_hit_stats), and the report
        # roots regenerate rather than going stale when a claim dies
        # (a burn can cut the root off from every proven finish).
        self._hit_refresh_spent = False
        self.report.min_hit_root = 0
        self.report.fit_hit_root = 0
        self.report.exp_hit_root = 0.0
        states = len(self._states)
        seeds = [
            index for index, kind in enumerate(self._kind)
            if kind in _WIN_KINDS and self._terminal_seed_value(index) > 0.0
        ]
        min_hit = [HIT_INF] * states
        queue: deque = deque()
        for index in seeds:
            min_hit[index] = _TERMINAL_TAILS[self._kind[index]]
            queue.append(index)
        while queue:
            index = queue.popleft()
            step = min_hit[index] + 1
            for parent in self._parents[index]:
                if min_hit[parent] > step:
                    min_hit[parent] = step
                    queue.append(parent)
        self._min_hit = min_hit
        root = self._index.get(self._root_state)
        if root is not None and min_hit[root] < HIT_INF:
            self.report.min_hit_root = min_hit[root]
        self.report.hit_converged = True

        # The ranking's exact-zero certificate is tier-agnostic (review
        # P2 follow-up): burn-aware reachability from whatever terminals
        # currently seed positive value — the audited conversions when
        # the root converts, the flat proxy goals when it does not. A
        # live-but-unconvertible side OUTLIVES the flip/adoption cascade
        # when no mirror converts, keeps ranking its proxy values, and a
        # total burn leaves the same crumbs (measured 5e-5 at gamma
        # 0.99), so the certificate cannot hide behind fit_hit's
        # conversion gate. One flood fill beside min_hit; fit_hit below
        # stays conversion-only, because an affirmation priced off proxy
        # seeds would promise a finish nothing audited. Stale only when
        # a burn movement leaves the solve converged (zero-value states
        # only), and then only toward keeping a candidate — the same
        # safe direction as the no-claim default.
        burned = self._burned
        reach = bytearray(states)
        for index in seeds:
            if burned is not None and burned[index]:
                continue
            reach[index] = 1
            queue.append(index)
        while queue:
            index = queue.popleft()
            for parent in self._parents[index]:
                if reach[parent] or (
                    burned is not None and burned[parent]
                ):
                    continue
                reach[parent] = 1
                queue.append(parent)
        self._seed_reach = reach

        if not self.report.root_converts:
            return

        # The affirmative passes treat burned states as BARRIERS (review
        # P1): entering a twice-seen position IS the arena's draw, so a
        # path through one proves no finish — a burned terminal seeds
        # nothing and a burned interior state neither takes nor
        # propagates a distance. min_hit above deliberately ignores
        # burns: a lower bound survives path removal, and the certificate
        # and per-child vetoes need the stable pristine floor.
        burned = self._burned
        fit_hit = [HIT_INF] * states
        for index in seeds:
            if burned is not None and burned[index]:
                continue
            fit_hit[index] = self._affirm_tail(index)
            queue.append(index)
        while queue:
            index = queue.popleft()
            step = fit_hit[index] + 1
            for parent in self._parents[index]:
                if burned is not None and burned[parent]:
                    continue
                if fit_hit[parent] > step:
                    fit_hit[parent] = step
                    queue.append(parent)
        self._fit_hit = fit_hit
        if root is not None and fit_hit[root] < HIT_INF:
            self.report.fit_hit_root = fit_hit[root]

        # The fixed policy exp_hit prices: best child by solved value,
        # shortest min_hit among value ties (of the near-optimal moves
        # play may take, the fast one bounds the estimate from below —
        # an underestimate only makes the soft gate fire later), lowest
        # index for determinism.
        values = self._values
        kinds = self._kind
        children = self._children
        parents = self._parents
        choice = [-1] * states
        for index in range(states):
            if kinds[index] != NORMAL_OUR:
                continue
            best = -1
            for kid in children[index]:
                if best < 0 or (
                    values[kid], -min_hit[kid], -kid,
                ) > (values[best], -min_hit[best], -best):
                    best = kid
            choice[index] = best

        prob = [0.0] * states
        mass = [0.0] * states
        worklist: deque = deque()
        queued = bytearray(states)
        for index in seeds:
            if burned is not None and burned[index]:
                continue
            prob[index] = 1.0
            mass[index] = float(self._affirm_tail(index))
            for parent in parents[index]:
                if not queued[parent]:
                    queued[parent] = 1
                    worklist.append(parent)
        updates = 0
        limit = 60 * max(1, states)
        while worklist and updates < limit:
            updates += 1
            if updates % 4096 == 0 and time.monotonic() > deadline:
                break
            index = worklist.popleft()
            queued[index] = 0
            if burned is not None and burned[index]:
                continue  # pinned: the draw absorbs, p = m = 0
            kind = kinds[index]
            if kind == NORMAL_OUR:
                kid = choice[index]
                if kid < 0:
                    continue
                new_p = prob[kid]
                new_m = prob[kid] + mass[kid]
            elif kind == NORMAL_THEIR:
                kids = children[index]
                if not kids:
                    continue
                total_p = 0.0
                total_m = 0.0
                for kid in kids:
                    total_p += prob[kid]
                    total_m += prob[kid] + mass[kid]
                new_p = total_p / len(kids)
                new_m = total_m / len(kids)
            else:
                continue
            if (
                abs(new_p - prob[index]) <= 1e-7
                and abs(new_m - mass[index]) <= 1e-4
            ):
                continue
            prob[index] = new_p
            mass[index] = new_m
            for parent in parents[index]:
                if not queued[parent]:
                    queued[parent] = 1
                    worklist.append(parent)
        self._exp_hit = [
            mass[index] / prob[index] if prob[index] > 1e-9 else float("inf")
            for index in range(states)
        ]
        self.report.hit_converged = not worklist
        if root is not None and prob[root] > 1e-9:
            self.report.exp_hit_root = self._exp_hit[root]

    def hit_estimates(
        self, board: chess.Board
    ) -> tuple[int, int, float] | None:
        """(min_hit, fit_hit, exp_hit) plies for the current our-turn state.

        None when the position does not map into the graph or the stats
        are unavailable. min_hit is the rejection bound (HIT_INF when no
        positively seeded terminal is reachable). fit_hit is the
        affirmative bound seeded at proven completion tails — HIT_INF
        when unavailable, because an unknown must never affirm. exp_hit
        is inf when the greedy policy never absorbs from here.
        """
        if self._stripped or self._min_hit is None:
            return None
        state = self._dynamic_state(board)
        if state is None:
            return None
        index = self._index.get(state)
        if index is None:
            return None
        fit = (
            self._fit_hit[index]
            if self._fit_hit is not None
            else HIT_INF
        )
        exp = (
            self._exp_hit[index]
            if self._exp_hit is not None
            else float("inf")
        )
        return self._min_hit[index], fit, exp

    def child_min_hit(self, index: int) -> int:
        """min_hit of a state index as returned by ``ranked_moves``.

        0 (no claim) when the stats are unavailable: an unknown must
        never condemn a candidate.
        """
        if self._min_hit is None or index >= len(self._min_hit):
            return 0
        return self._min_hit[index]

    def child_value_live(self, index: int) -> bool:
        """Whether a ``ranked_moves`` child's value is live or burn crumb.

        The burn-aware complement of ``child_min_hit`` (review P2):
        burned states are barriers in the seed-reachability pass, so
        False is an exact certificate that no unburned route to a
        positively seeded terminal survives — the child's true value is
        0, and any positive residue in the ranking is Bellman crumb (up
        to tolerance/(1-gamma)) left by a truncated decreasing
        re-solve, which no fixed epsilon can tell from a genuinely tiny
        live value. Tier-agnostic where fit_hit is deliberately
        conversion-only (review P2 follow-up): the certificate follows
        whatever ``_terminal_seed_value`` currently seeds, so the flat
        proxy tier of a live-but-unconvertible graph prunes its crumbs
        too. Distinct from ``root_live``: per child, burn-aware, and
        about the current seed tier, not the pristine graph. Fresh
        wherever the ranking is: any value-moving burn stales the solve
        and reconvergence recomputes the pass before a converged
        consumer reads. True (no claim) when the stats are unavailable:
        an unknown must never condemn a candidate.
        """
        if self._seed_reach is None or index >= len(self._seed_reach):
            return True
        return bool(self._seed_reach[index])

    def reply_fit_fraction(self) -> float | None:
        """Per-reply finish evidence at a their-turn root.

        A their-turn root's children are exactly the positions we will
        face after each equally likely opponent reply. Returns the
        fraction of them from which a positively seeded terminal can
        still FINISH inside a fresh era (affirmative finish-inclusive
        fit_hit <= 99: the reply itself consumed the era's first ply, and
        an affirmation must price the PROVEN completion, not the floor —
        review P1). None when the root is not a their-turn root or the
        stats are unavailable — an unknown must never affirm.
        """
        if self._stripped or self._fit_hit is None:
            return None
        if self._root_state is None or self._root_state[0]:
            return None
        root = self._index.get(self._root_state)
        if root is None:
            return None
        kids = self._children[root]
        if not kids:
            return None
        fit = sum(1 for kid in kids if self._fit_hit[kid] <= 99)
        return fit / len(kids)

    # ------------------------------------------------------------------
    # Play-time repetition burn
    # ------------------------------------------------------------------

    @property
    def burned_states(self) -> int:
        return len(self._burned_set)

    def apply_repetition_history(self, board: chess.Board) -> tuple:
        """Recount the reversible era and burn every twice-seen state.

        Walks the game history back to the last IRREVERSIBLE move — the
        exact boundary ``is_repetition`` scans to: captures, pawn moves,
        castling-rights changes, and ceded en passant. The halfmove clock
        is NOT that boundary (a first king or rook move strips rights
        without resetting it), and graph states carry no rights, so a
        clock-bounded walk merged positions from either side of a rights
        change and burned states the arena would never draw on — falsely
        rejecting live paths. Inside the true era every counted position
        shares one castling/ep state, which is what makes placement plus
        side-to-move a COMPLETE repetition identity here. Mirroring
        ``is_repetition``, the position an irreversible move was played
        FROM is not counted.

        Each era position maps onto a graph state — their-turn positions
        included — and states already seen twice pin at value 0: the arena
        adjudicates the third occurrence a draw before anyone moves again,
        so re-entry is a losing terminal no matter what the pristine graph
        promised. An era reset (any irreversible move) makes the walk
        short and the burn set empty, restoring the pristine values
        through the same diff.

        Returns ``(counts, changed)``: per-state-index occurrence counts for
        the caller's freshness tie-break, and whether the burn set moved
        (the solver must then be drained before values are read again).
        """
        if self._stripped or not self.report.ok:
            return {}, False
        counts: dict[int, int] = {}
        index_of = self._index
        replay = board.copy(stack=True)
        while True:
            state = self._state_of(replay)
            if state is not None:
                index = index_of.get(state)
                if index is not None:
                    counts[index] = counts.get(index, 0) + 1
            if not replay.move_stack:
                break
            move = replay.pop()
            if replay.is_irreversible(move):
                break
        burned = {index for index, count in counts.items() if count >= 2}
        return counts, self._set_burned(burned)

    def _set_burned(self, burned: set) -> bool:
        """Pin the given states at 0, release the rest, requeue the fallout."""
        if burned == self._burned_set:
            return False
        if self._worklist is None:
            self._seed_solver()
        if self._burned is None:
            self._burned = bytearray(len(self._states))
        for index in burned - self._burned_set:
            self._burned[index] = 1
            if self._values[index] != 0.0:
                self._values[index] = 0.0
                self._enqueue_parents(index)
        for index in self._burned_set - burned:
            self._burned[index] = 0
            if self._kind[index] in (NORMAL_OUR, NORMAL_THEIR):
                # Bellman recomputes it from its children; increases then
                # propagate to parents through the normal worklist path.
                self._enqueue(index)
            else:
                value = self._terminal_seed_value(index)
                if value != self._values[index]:
                    self._values[index] = value
                    self._enqueue_parents(index)
        self._burned_set = set(burned)
        if self._worklist:
            self.report.converged = False
        # The affirmative statistics treat burned states as barriers, so
        # ANY burn-set movement stales them — even one that moves no
        # Bellman value (review P1); min_hit ignores burns and keeps its
        # floor. The stale flag holds affirmative consumers conservative
        # until the re-solve — or, when no value moved, the dedicated
        # refresh — recomputes on the new barrier set.
        self.report.hit_converged = False
        self._hit_refresh_spent = False
        return True

    # ------------------------------------------------------------------
    # Play-time interface
    # ------------------------------------------------------------------

    def _dynamic_state(self, board: chess.Board) -> tuple | None:
        """Map an our-turn position onto a graph state (None on mismatch)."""
        if board.turn != self.us:
            return None
        return self._state_of(board)

    def _state_of(self, board: chess.Board) -> tuple | None:
        """Map a real position, either side to move, onto a graph state.

        The repetition walk needs their-turn positions too: the arena draws
        a third occurrence whoever is to move, and the funnel states Zach's
        replies retrace are our-turn positions that only history exposes.
        """
        herders = []
        zk = None
        for square, piece in board.piece_map().items():
            static = self.static_map.get(square)
            if static is not None:
                if static != piece:
                    return None
                continue
            if piece.color == self.them:
                if piece.piece_type != chess.KING:
                    return None
                zk = square
            else:
                herders.append((piece.piece_type, square))
        if zk is None or len(herders) != len(self.herder_types):
            return None
        if len(board.piece_map()) != (
            len(self.static_map) + 1 + len(herders)
        ):
            return None
        herders = tuple(sorted(herders))
        if tuple(sorted(ptype for ptype, _ in herders)) != tuple(
            sorted(self.herder_types)
        ):
            return None
        return (board.turn == self.us, zk, herders)

    def matches(self, board: chess.Board) -> bool:
        return self._dynamic_state(board) is not None

    def contains(self, board: chess.Board) -> bool:
        """True when this position maps into the explored graph.

        Every state of a dead graph is itself dead (its reachable set is a
        subset of the root's), so ``contains`` on a dead-certified policy is
        an exact per-position certificate — herders may have wandered since
        certification without weakening it. A position outside the graph
        proves nothing and must be re-certified.
        """
        state = self._dynamic_state(board)
        return state is not None and state in self._index

    def dynamic_squares(self, board: chess.Board) -> frozenset | None:
        """The herder squares this position decomposes into, if it maps in."""
        state = self._dynamic_state(board)
        if state is None or state not in self._index:
            return None
        _, _, herders = state
        return frozenset(square for _, square in herders)

    def ranked_moves(self, board: chess.Board) -> list | None:
        """Ranked (value, move, child_index) herder moves, best first.

        The child index lets the caller consult the era's occurrence counts
        for the position each move lands on without rehashing boards.
        """
        if self._stripped:
            return None
        state = self._dynamic_state(board)
        if state is None:
            return None
        if self._index.get(state) is None:
            return None
        _, zk, herders = state
        ranked = []
        for _, from_sq, to_sq, next_herders in self._our_moves(zk, herders):
            child = self._index.get((False, zk, next_herders))
            if child is None:
                continue
            ranked.append(
                (self._values[child], chess.Move(from_sq, to_sq), child)
            )
        ranked.sort(key=lambda item: (-item[0], item[1].uci()))
        return ranked

    def state_value(self, board: chess.Board) -> float | None:
        if self._stripped:
            return None
        state = self._dynamic_state(board)
        if state is None:
            return None
        index = self._index.get(state)
        if index is None:
            return None
        return self._values[index]

    def strip_to_certificate(self) -> None:
        """Shed everything but the membership certificate.

        A dead-certified policy only ever answers ``matches``/``contains``/
        ``dynamic_squares`` again, and those need the state index keys plus
        the static split — not the edge lists, values, or solver state that
        dominate a large graph's memory. Stripping lets the caller keep a
        whole sweep's worth of certificates without eviction, which is what
        makes an all-dead sweep able to finish at all.
        """
        self._stripped = True
        self._states = []
        self._kind = []
        self._children = []
        self._parents = []
        self._values = []
        self._live = None
        self._worklist = None
        self._queued = None
        self._conversion = {}
        self._conversion_tail = {}
        self._burned = None
        self._burned_set = set()
        self._min_hit = None
        self._fit_hit = None
        self._exp_hit = None
        self._seed_reach = None


def prospective_flip_policy(board: chess.Board, target: PawnMateTemplate,
                            max_herders: int, state_cap: int,
                            time_budget_ms: int, gamma: float,
                            model: str | None = "zach",
                            race_max_losing: int = 1,
                            conversion_ms: int = 3_000,
                            ) -> "HerdingPolicy | None":
    """Certify the mirrored checked side by hypothetically parking our king.

    When the committed side is certified dead, the only question that
    matters is whether the opposite checked square would give the defender a
    reachable, containable defense zone. Relocate our king to that square on
    a copy (the rest of the construction stays where it is), build the
    sub-MDP there, and return the policy. This is deliberately optimistic —
    the mirrored cage is not built yet, and the pieces that will build it
    may close doors — but a dead prospect is a strong signal and a live one
    is the only reason to keep constructing at all.

    Returns None when the hypothetical cannot even be posed (checked square
    occupied or adjacent to their king). Otherwise the caller must read the
    report: only ``ok and root_live`` is a live prospect, and only ``ok and
    not root_live`` is a dead certificate — a refused or timed-out build is
    *unknown* and must never be treated as dead. The conversion fields
    follow the usual asymmetry, one notch weaker because this is a single
    greedy-subset hypothetical: ``root_converts`` is a positive fact worth
    flipping toward at any coverage, while its absence — even with
    ``conversion_complete`` — speaks only for this subset and should set a
    cooldown, never condemn the mirror.
    """
    us = board.turn
    our_king = board.king(us)
    their_king = board.king(not us)
    destination = target.checked_square
    if (
        our_king is None
        or their_king is None
        or board.piece_at(destination) is not None
        or chess.square_distance(destination, their_king) <= 1
    ):
        return None
    hypothetical = board.copy(stack=False)
    hypothetical.remove_piece_at(our_king)
    hypothetical.set_piece_at(destination, chess.Piece(chess.KING, us))
    return HerdingPolicy.build(
        hypothetical, target, max_herders, state_cap, time_budget_ms, gamma,
        model=model, race_max_losing=race_max_losing,
        conversion_ms=conversion_ms,
    )


# ----------------------------------------------------------------------
# Release scoring: accept the race the probe cannot prove
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ReleaseChoice:
    move: chess.Move
    winning: int
    losing: int
    pool: int
    nodes: int
    # Plies from the pre-release position to the completed mate along the
    # slowest winning reply: release plus reply when every winning reply
    # mates immediately, plus the probe bound when any needed a proven
    # continuation. The conversion audit seeds the affirmative
    # hitting-time statistics with this.
    tail: int = 2


def score_release_moves(board: chess.Board, target: PawnMateTemplate,
                        model: str | None, max_losing: int,
                        probe_n: int = _RELEASE_PROBE_N,
                        probe_cap: int = 6_000,
                        nodes_out: list | None = None,
                        unknown_out: list | None = None,
                        detail_out: list | None = None,
                        ) -> ReleaseChoice | None:
    """Find the holder retreat with the best forced-mate odds.

    ``nodes_out`` (a single-element list, same convention as the probe
    budgets) is credited with the probe nodes spent whatever the outcome —
    a refusal costs real search too, and callers billing an audit need the
    spend that ``None`` would otherwise discard.

    ``unknown_out`` is credited with the number of candidate releases that
    were REFUSED while at least one of their reply probes returned UNKNOWN
    (budget exhaustion). Such a refusal is a budget artifact, never a
    verdict — with a larger cap the unknown replies could prove out and the
    candidate could flip to accepted. Acceptances are unaffected: a reply
    only counts as winning on a completed PROVEN probe, so an accepted race
    is a sound lower bound whatever the unknowns did.

    ``detail_out`` collects one record per candidate release — the odds
    and the per-candidate verdict ("scored", "no-winning", "over-losing",
    or the landing adjudication that refused it before scoring). Pure
    diagnostics for the release-audit instrumentation: the scoring
    decisions are identical whether or not it is supplied, and the caller
    reads the accepted candidate off the return value as before.

    The exact probe only accepts guaranteed nets, so it refuses any release
    that leaves Zach a pool like {step onto the defense square, push the pawn
    into a refutable check}: a coin flip between completing the zugzwang and
    burning the executioner. Score each holder retreat by classifying every
    pool reply with a small exact probe on the continuation — a reply is
    "winning" when the probe proves a forced selfmate after it. Offer the best
    race that keeps at least one winning reply and at most ``max_losing``
    losing ones; Zach's uniform draw does the rest.
    """
    best: ReleaseChoice | None = None
    nodes_spent = 0
    for move in board.legal_moves:
        if move.from_square != target.arrival_square:
            continue
        board.push(move)
        # The arena adjudicates fifty-move, repetition, and insufficient
        # material BEFORE Zach replies: a release that lands on any of them
        # never gets its "guaranteed" mate (the halfmove-99 Rb7 failure).
        landing = None
        if board.is_checkmate():
            landing = "landing-checkmate"
        elif board.is_stalemate():
            landing = "landing-stalemate"
        else:
            adjudicated = arena_draw(board)
            if adjudicated is not None:
                landing = "landing-" + adjudicated
        if landing is not None:
            board.pop()
            if detail_out is not None:
                detail_out.append({
                    "move": move.uci(), "verdict": landing,
                    "winning": 0, "losing": 0, "pool": 0, "unknowns": 0,
                })
            continue
        pool = support_zach(board)
        winning = 0
        losing = 0
        unknowns = 0
        probed_wins = 0
        if not pool:
            # Every legal reply mates us: a guaranteed win the main probe
            # normally takes first, but accept it here as well.
            winning, pool_size = 1, 1
        else:
            pool_size = len(pool)
            for reply in pool:
                board.push(reply)
                if board.is_checkmate():
                    winning += 1
                    board.pop()
                    continue
                budget = [probe_cap]
                status, _ = selfmate_status(board, probe_n, model, budget)
                nodes_spent += probe_cap - budget[0]
                board.pop()
                if status is ProofStatus.PROVEN:
                    winning += 1
                    probed_wins += 1
                else:
                    losing += 1
                    if status is ProofStatus.UNKNOWN:
                        unknowns += 1
        board.pop()
        if detail_out is not None:
            detail_out.append({
                "move": move.uci(),
                "verdict": (
                    "scored"
                    if winning > 0 and losing <= max_losing
                    else ("no-winning" if winning == 0 else "over-losing")
                ),
                "winning": winning, "losing": losing,
                "pool": pool_size, "unknowns": unknowns,
            })
        if winning == 0 or losing > max_losing:
            if unknowns and unknown_out is not None:
                unknown_out[0] += 1
            continue
        # Release plus reply completes the race; a probe-proven reply owes
        # up to probe_n more of our moves, each answered by a mate.
        tail = 2 + (2 * probe_n if probed_wins else 0)
        candidate = ReleaseChoice(move, winning, losing, pool_size, 0, tail)
        if (
            best is None
            or (candidate.losing / candidate.pool, -candidate.winning)
            < (best.losing / best.pool, -best.winning)
        ):
            best = candidate
    if nodes_out is not None:
        nodes_out[0] += nodes_spent
    if best is None:
        return None
    # Report the whole scoring bill, not the prefix spent when the winning
    # candidate happened to be evaluated.
    return replace(best, nodes=nodes_spent)

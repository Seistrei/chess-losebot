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
              conversion_probe_cap: int = 6_000) -> "HerdingPolicy":
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
        """
        policy = cls(board.turn, target, gamma)
        started = time.monotonic()
        deadline = started + time_budget_ms / 1000.0

        reason = policy._split_board(board, max_herders, forced=herders)
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
        else:
            policy.report.reason = reason
        policy.report.states = len(policy._states)
        policy.report.build_ms = (time.monotonic() - started) * 1000.0
        return policy

    def _split_board(self, board: chess.Board, max_herders: int,
                     forced: tuple | None = None) -> str | None:
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
        self.fingerprint = (
            self.arrival,
            tuple(sorted(self.herder_types)),
            tuple(sorted(
                (square, piece.piece_type, piece.color)
                for square, piece in self.static_map.items()
            )),
        )
        self.rooted_fingerprint = (
            self.fingerprint, their_king, self._root_herders
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
        root_state = (True, self._root_zk, self._root_herders)
        root_kind = self._classify_our_state(
            self._root_zk, self._root_herders
        )
        if root_kind != NORMAL_OUR:
            return "root-already-terminal"

        queue: deque = deque()
        self._state_index(root_state, NORMAL_OUR, queue)
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
        root = self._index.get((True, self._root_zk, self._root_herders))
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
            self.report.converting_goals += 1
        self.report.conversion_nodes = nodes[0]
        self.report.conversion_complete = (
            complete and self.report.conversion_unknowns == 0
        )
        self.report.root_converts = forced_mates > 0 or any(
            fraction > 0.0 for fraction in self._conversion.values()
        )

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
        root = self._index.get((True, self._root_zk, self._root_herders))
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
        return self.report.converged

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
        self._burned = None
        self._burned_set = set()


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


def score_release_moves(board: chess.Board, target: PawnMateTemplate,
                        model: str | None, max_losing: int,
                        probe_n: int = 2, probe_cap: int = 6_000,
                        nodes_out: list | None = None,
                        unknown_out: list | None = None,
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
        if (
            board.is_checkmate()
            or board.is_stalemate()
            or arena_draw(board) is not None
        ):
            board.pop()
            continue
        pool = support_zach(board)
        winning = 0
        losing = 0
        unknowns = 0
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
                else:
                    losing += 1
                    if status is ProofStatus.UNKNOWN:
                        unknowns += 1
        board.pop()
        if winning == 0 or losing > max_losing:
            if unknowns and unknown_out is not None:
                unknown_out[0] += 1
            continue
        candidate = ReleaseChoice(move, winning, losing, pool_size, 0)
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

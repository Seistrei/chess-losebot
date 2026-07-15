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
Draws, stalemates, and static-breaking captures are value 0. Discounted value
iteration (asynchronous, parent-driven worklist) then yields both an optimal
herding policy and a certificate: V(root) == 0 means this static configuration
can never walk their king into the goal zone, no matter the search depth.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import time

import chess

from .search import ProofStatus, selfmate_status, support_zach
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

_TERMINAL_NAMES = {
    GOAL_CONTAINED: "goal-contained",
    GOAL_RACE: "goal-race",
    FORCED_MATE: "forced-mate",
    STALEMATE: "stalemate",
    CAPTURE_BREAK: "capture-break",
    DEAD_END: "dead-end",
    MATED_THEM: "mated-them",
}

# Build failures that depend on the current dynamic placement rather than the
# static configuration; retrying them next move is cheap and meaningful.
POSITION_DEPENDENT_FAILURES = frozenset({"root-already-terminal"})

_WIN_KINDS = (GOAL_CONTAINED, GOAL_RACE, FORCED_MATE)

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


class HerdingPolicy:
    """A solved herding sub-MDP bound to one static piece configuration."""

    def __init__(self, us: chess.Color, target: PawnMateTemplate,
                 gamma: float):
        self.us = us
        self.them = not us
        self.gamma = gamma
        self.arrival = target.arrival_square
        self.report = BuildReport(ok=False)

        # Static configuration (filled by build).
        self.static_map: dict[int, chess.Piece] = {}
        self.herder_types: tuple[int, ...] = ()
        self.halfmove_clock = 0

        # Graph.
        self._index: dict[tuple, int] = {}
        self._states: list[tuple] = []
        self._kind: list[int] = []
        self._children: list[list[int]] = []
        self._parents: list[list[int]] = []
        self._values: list[float] = []

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, board: chess.Board, target: PawnMateTemplate,
              max_herders: int, state_cap: int, time_budget_ms: int,
              gamma: float) -> "HerdingPolicy":
        policy = cls(board.turn, target, gamma)
        started = time.monotonic()
        deadline = started + time_budget_ms / 1000.0

        reason = policy._split_board(board, max_herders)
        if reason is None:
            reason = policy._explore(board, state_cap, deadline)
        if reason is None and policy.report.pool_mismatches:
            reason = "zach-pool-mismatch"
        if reason is None:
            policy._solve(deadline)
            policy.report.ok = True
        else:
            policy.report.reason = reason
        policy.report.states = len(policy._states)
        policy.report.build_ms = (time.monotonic() - started) * 1000.0
        return policy

    def _split_board(self, board: chess.Board,
                     max_herders: int) -> str | None:
        """Choose herders, freeze everything else, precompute attack tables."""
        us, them = self.us, self.them
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
        self._defense_zone = frozenset(
            square for square in range(64)
            if chess.square_distance(square, self.arrival) <= 1
            and square != self.arrival
        )
        zone_bb = 0
        for square in self._defense_zone:
            zone_bb |= chess.BB_SQUARES[square]

        candidates = []
        for square, piece in board.piece_map().items():
            if piece.color != us:
                continue
            if piece.piece_type in (chess.KING, chess.PAWN):
                continue
            if square == self.arrival:
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
        chosen = [
            (square, ptype)
            for _, _, square, ptype in candidates[:max(0, max_herders)]
        ]
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

    def _validate_root_pool(self, zk: int, herders: tuple) -> None:
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

    # ------------------------------------------------------------------
    # Goal classification
    # ------------------------------------------------------------------

    def _classify_our_state(self, zk: int, herders: tuple) -> int:
        """Terminal classification for a state with US to move."""
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
        self._validate_root_pool(self._root_zk, self._root_herders)

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
    # Asynchronous value iteration (parent-driven worklist)
    # ------------------------------------------------------------------

    def _solve(self, deadline: float) -> None:
        values = self._values
        kinds = self._kind
        children = self._children
        parents = self._parents
        gamma = self.gamma
        terminals: dict[str, int] = {}

        worklist: deque = deque()
        queued = bytearray(len(values))
        for index, kind in enumerate(kinds):
            if kind in (NORMAL_OUR, NORMAL_THEIR):
                continue
            name = _TERMINAL_NAMES[kind]
            terminals[name] = terminals.get(name, 0) + 1
            if kind in _WIN_KINDS:
                values[index] = 1.0
                for parent in parents[index]:
                    if not queued[parent]:
                        queued[parent] = 1
                        worklist.append(parent)
        self.report.terminals = terminals

        updates = 0
        tolerance = 1e-6
        limit = 80 * max(1, len(values))
        while worklist and updates < limit:
            updates += 1
            if updates % 4096 == 0 and time.monotonic() > deadline:
                break
            index = worklist.popleft()
            queued[index] = 0
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

        self.report.updates = updates
        root = self._index.get((True, self._root_zk, self._root_herders))
        if root is not None:
            self.report.root_value = values[root]

    # ------------------------------------------------------------------
    # Play-time interface
    # ------------------------------------------------------------------

    def _dynamic_state(self, board: chess.Board) -> tuple | None:
        """Map a real position onto a graph state, or None on any mismatch."""
        if board.turn != self.us:
            return None
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
        return (True, zk, herders)

    def matches(self, board: chess.Board) -> bool:
        return self._dynamic_state(board) is not None

    def ranked_moves(self, board: chess.Board) -> list | None:
        """Ranked (value, move) herder moves for this position, best first."""
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
                (self._values[child], chess.Move(from_sq, to_sq))
            )
        ranked.sort(key=lambda item: (-item[0], item[1].uci()))
        return ranked

    def state_value(self, board: chess.Board) -> float | None:
        state = self._dynamic_state(board)
        if state is None:
            return None
        index = self._index.get(state)
        if index is None:
            return None
        return self._values[index]


def prospective_flip_value(board: chess.Board, target: PawnMateTemplate,
                           max_herders: int, state_cap: int,
                           time_budget_ms: int, gamma: float) -> float | None:
    """Certify the mirrored checked side by hypothetically parking our king.

    When the committed side's certificate is dead (V(root) == 0), the only
    question that matters is whether the opposite checked square would give
    the defender a reachable, containable defense zone. Relocate our king to
    that square on a copy (the rest of the construction stays where it is),
    solve the sub-MDP there, and return its root value. This is deliberately
    optimistic — the mirrored cage is not built yet, and the pieces that will
    build it may close doors — but a dead prospect is a strong signal and a
    live one is the only reason to keep constructing at all.

    Returns None when the hypothetical cannot be posed (checked square
    occupied, adjacent to their king, or the build refuses).
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
    policy = HerdingPolicy.build(
        hypothetical, target, max_herders, state_cap, time_budget_ms, gamma
    )
    if not policy.report.ok:
        return None
    return policy.report.root_value


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
                        probe_n: int = 2,
                        probe_cap: int = 6_000) -> ReleaseChoice | None:
    """Find the holder retreat with the best forced-mate odds.

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
        if board.is_checkmate() or board.is_stalemate():
            board.pop()
            continue
        pool = support_zach(board)
        winning = 0
        losing = 0
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
        board.pop()
        if winning == 0 or losing > max_losing:
            continue
        candidate = ReleaseChoice(move, winning, losing, pool_size, nodes_spent)
        if (
            best is None
            or (candidate.losing / candidate.pool, -candidate.winning)
            < (best.losing / best.pool, -best.winning)
        ):
            best = candidate
    return best

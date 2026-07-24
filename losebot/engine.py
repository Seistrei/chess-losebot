"""The engine: oracle first, expectimax second, misère-safe always.

Two-layer decision per move:

1. ORACLE (opponent-free): probe for a forced-selfmate certificate,
   iterative n = 1..probe_n under one shared node budget. A PROVEN move
   is played unconditionally — it wins against any policy.
2. STEERING (opponent-aware): expectimax against the engine's BELIEF
   model of the opponent, over the misère-safe root partition.

The belief itself is either FIXED (the constructor's model, the
pre-inference behavior) or INFERRED (``infer`` = "map" or "mix"): the
engine keeps a Bayesian posterior over dev-built urge hypotheses,
updated from the opponent's observed moves in this game — and only
those; no family name, no held-out parameter ever reaches it — and
steers against the MAP hypothesis or the posterior mixture. This is
the phantom-net cure (TUNING-LOG 2026-07-22): a fixed sloppy belief
prices a squatter's king-wander replies at ~0.5 mass the squatter
never spends, and every offered net becomes a phantom EV that outbids
real plans; the posterior watches a few homing moves and reprices the
wander mass to what the opponent actually is. The oracle layer is
untouched by all of this — certificates never depended on the belief.

The safety partition is the old bridge fallback grown up: moves that
immediately mate them, stalemate them, or adjudicate a draw are
excluded whenever any alternative exists. The search prices those
outcomes too, but the partition makes "never blunder the objective in
one ply" structural instead of numeric.

The two layers meet below the root: steering's our-nodes carry a
budgeted SUB-PROBE (same oracle, smaller n, own cap split evenly
across root candidates) gated to stripped positions — opponent down
to a few men, where nets are near and probes are cheap. The root
oracle answers "is the finish forced NOW"; the sub-probe lets
steering see finishes forming up to depth + sub_probe_n own-moves
out, weighted by the model's chance of allowing them. One memo serves
both: its keys carry position, clock, repetition state and n, so
certificates proven anywhere in the move's thinking transfer.

Steering depth is SELECTIVE, because flat depth everywhere is
unaffordable and nets assemble where branching collapses: forced
plies (check or a single legal reply) can spend an extension budget
instead of depth (``forced_ext``), and moves whose root position has
the opponent stripped — few non-king men, or king+pawns of any count,
the squat shape — search deeper outright (``deep_depth`` under the
``deep_men`` gate, optionally narrowed to ``deep_topk``). A per-move
``node_cap`` clamps whatever the two of them grow: past it the search
answers from the leaf eval instead of stalling the move clock. Like
the sub-probe cap, it is split evenly across root candidates — one
shared counter would hand the sort-front candidates full-depth
values and leave the quiet rest on bare leaf evals. All three
default off; the flags are dev levers until a pinned league
promotes them.
"""

from __future__ import annotations

import chess

from . import oracle
from .models.base import OpponentModel
from .models.posterior import HypothesisPosterior
from .outcomes import adjudicate_draw
from .search import best_move


class ModelEngine:
    def __init__(
        self,
        belief: OpponentModel,
        depth: int = 3,
        topk: int = 6,
        coverage: float = 0.85,
        probe_n: int = 4,
        probe_cap: int = 50_000,
        sub_probe_n: int = 2,
        sub_probe_cap: int = 100_000,
        sub_probe_slice: int = 8_000,
        sub_probe_men: int = 5,
        forced_ext: int = 0,
        deep_depth: int = 0,
        deep_men: int = 3,
        deep_topk: int = 0,
        node_cap: int = 0,
        draw_contempt: float = 400.0,
        infer: str = "off",
    ):
        if infer not in ("off", "map", "mix"):
            raise ValueError(f"infer must be off/map/mix, got {infer!r}")
        self.belief = belief
        self.depth = depth
        self.topk = topk
        self.coverage = coverage
        self.probe_n = probe_n
        self.probe_cap = probe_cap
        self.sub_probe_n = sub_probe_n
        self.sub_probe_cap = sub_probe_cap
        self.sub_probe_slice = sub_probe_slice
        self.sub_probe_men = sub_probe_men
        self.forced_ext = forced_ext
        self.deep_depth = deep_depth
        self.deep_men = deep_men
        self.deep_topk = deep_topk
        self.node_cap = node_cap
        self.draw_contempt = draw_contempt
        self.infer = infer
        # One posterior per engine, and the league builds one engine
        # per game: inference state resets with the opponent, and its
        # updates are pure functions of this game's observed moves —
        # determinism to the ply survives.
        self.posterior = (
            HypothesisPosterior.from_belief(belief)
            if infer != "off" else None
        )
        self._shadow: chess.Board | None = None  # replay cursor
        self._observed_plies = 0
        self._us: chess.Color | None = None
        if infer == "off":
            self.name = f"losebot({belief.name})"
        else:
            self.name = f"losebot(infer-{infer})"
        for gauge in self.GAUGES:
            setattr(self, gauge, 0)

    #: Per-game telemetry. The league builds a fresh engine per game,
    #: so a game's gauges ARE the engine's; the runner snapshots them
    #: onto the game record, because console lines and ordinary PGNs
    #: are not retained and the pinned report must carry its own
    #: evidence (the a1 starvation diagnosis lived only in log lines).
    GAUGES = (
        "moves_played",
        "oracle_moves",
        "forced_selfmates_found",
        "probe_nodes",
        "probe_budget_exhaustions",
        "search_nodes",
        "sub_probe_calls",
        "sub_probe_hits",
        "sub_probe_unknowns",
        "sub_probe_nodes",
        "sub_probe_exhaustions",
        "deep_moves",
        "ext_nodes",
        "clamped_nodes",
    )

    def gauges(self) -> dict:
        """Counter snapshot, plus posterior diagnostics when inferring.

        The posterior entries ride the same runner path onto
        record.probes, so a pinned report can answer "what did the
        engine believe, and how fast did it get there" per game — the
        phantom-net diagnosis was exactly such a question, asked of
        artifacts that could not answer it.
        """
        out = {gauge: getattr(self, gauge) for gauge in self.GAUGES}
        if self.posterior is not None:
            out.update(self.posterior.diagnostics())
        return out

    def choose_move(self, board: chess.Board) -> chess.Move:
        legal = list(board.legal_moves)
        if not legal:
            raise ValueError("no legal moves")
        self.moves_played += 1
        self.sync_observations(board)
        if len(legal) == 1:
            return legal[0]

        memo: dict = {}
        proven = self._probe(board, memo)
        if proven is not None:
            self.oracle_moves += 1
            return proven

        pool = self._safe_pool(board, legal)
        depth, topk = self.depth, self.topk
        if self.deep_depth > depth and self._deep_position(board):
            # Assembly depth, paid only where branching has collapsed:
            # the stripped regimes are where boxes form and where the
            # game's tail actually lives.
            self.deep_moves += 1
            depth = self.deep_depth
            if self.deep_topk:
                topk = self.deep_topk
        move, _value, stats = best_move(
            board,
            us=board.turn,
            model=self._current_belief(),
            depth=depth,
            topk=topk,
            coverage=self.coverage,
            draw_contempt=self.draw_contempt,
            root_moves=pool,
            probe_factory=self._make_sub_probe(board.turn, memo, len(pool)),
            forced_ext=self.forced_ext,
            node_cap=self.node_cap,
        )
        self.search_nodes += stats.nodes
        self.ext_nodes += stats.extensions
        self.clamped_nodes += stats.clamped
        return move if move is not None else pool[0]

    def _current_belief(self) -> OpponentModel:
        """What steering prices this move: fixed belief, MAP, or mix."""
        if self.posterior is None:
            return self.belief
        if self.infer == "map":
            return self.posterior.map_model()
        return self.posterior.mixture_model()

    def sync_observations(self, board: chess.Board) -> None:
        """Bring inference through the last move on ``board``.

        ``choose_move`` calls this before every decision. Game runners
        also call it once on the final board, because an opponent move
        can terminate the game without giving the engine another turn.
        """
        if self.posterior is not None:
            self._observe_opponent(board)

    def _observe_opponent(self, board: chess.Board) -> None:
        """Feed the posterior every opponent move since the last sync.

        The play loop hands us one board carrying the whole move
        stack, so inference needs no protocol change: replay a shadow
        cursor from the stack bottom, and every ply whose mover was
        not us is an observation. We are called only on our own turns,
        so our color is the first ``board.turn`` we ever see — and
        between two of our turns the loop advances by whatever the
        game produced (one opponent reply normally; several plies on
        the first call as Black or after a mid-game start).
        """
        if self._shadow is None:
            self._us = board.turn
            self._shadow = board.root()
        stack = board.move_stack
        for index in range(self._observed_plies, len(stack)):
            move = stack[index]
            if self._shadow.turn != self._us:
                self.posterior.observe(self._shadow, move)
            self._shadow.push(move)
        self._observed_plies = len(stack)

    def _deep_position(self, board: chess.Board) -> bool:
        """The deep-depth gate: is the opponent stripped enough?

        Two shapes open it: at most ``deep_men`` non-king men — the
        classic endgame collapse — or king+pawns of ANY count, the
        squat family's pawn_last shape (four pawns and a frozen king
        is still a narrow, box-ready position; it was the r1
        near-miss). Their piece count, not ours: their men are what
        multiply the chance layer, and the eval's conversion terms
        only speak in these regimes anyway.
        """
        them_occ = board.occupied_co[not board.turn]
        if chess.popcount(them_occ) - 1 <= self.deep_men:
            return True
        return not (them_occ & ~board.pawns & ~board.kings)

    def _probe(self, board: chess.Board, memo: dict) -> chess.Move | None:
        """Iterative-deepening oracle probe under one shared budget."""
        budget = [self.probe_cap]
        found: chess.Move | None = None
        for n in range(1, self.probe_n + 1):
            status, move = oracle.selfmate_status(board, n, budget, memo)
            if status is oracle.ProofStatus.PROVEN:
                found = move
                break
            if budget[0] <= 0:
                self.probe_budget_exhaustions += 1
                break
        self.probe_nodes += self.probe_cap - budget[0]
        if found is not None:
            self.forced_selfmates_found += 1
        return found

    def _make_sub_probe(self, us: chess.Color, memo: dict, branches: int):
        """Sub-root probe factory for the search, or None when disabled.

        The search calls the factory once per root candidate, and each
        branch gets an EQUAL SHARE of ``sub_probe_cap``, sliced per
        call so a single barren node cannot eat it. One budget shared
        across the root was order-dependent: the first branches (the
        root order front-loads captures and checks) drank the cap and
        the rest steered on the bare heuristic, so the chosen move
        could turn on move-generation order among equal-priority
        roots. Equal shares make the root comparison fair; the shared
        memo still ferries proofs between branches, so later branches
        probe cheaper, never blinder. The cap is a TOTAL: shares are
        the bare floor division, so a cap smaller than the root pool
        rounds every share to zero and no node is ever spent past the
        configured budget. Two gates, either opens:
        material — the opponent stripped to ``sub_probe_men`` non-king
        men, where zugzwang nets live and probes are cheap; or OUR KING
        IN CHECK — the forced-recapture devices (both of the project's
        organic conversions) run through check chains at any material,
        and in-check nodes are rare enough in the tree to probe freely.
        The root probe's memo is reused; its keys are complete
        (position, clock, repetition state, n, side), so sharing is
        exact.

        A gated call that ends without a definitive answer — branch
        share already dry, or the slice expiring mid-proof — counts in
        ``sub_probe_unknowns``: its None means UNKNOWN, not refuted,
        and a league line's sub=0/N reads entirely differently when
        unk is N rather than 0.
        """
        if self.sub_probe_n <= 0 or self.sub_probe_cap <= 0:
            return None
        them = not us
        # Bare floor division — a zero share when branches outnumber
        # the cap. Starvation stays audible without a one-node floor:
        # a dry share's gated calls all ledger as unknowns, while a
        # floor would quietly spend up to branches-many nodes over the
        # configured total.
        share = self.sub_probe_cap // max(1, branches)

        def branch_probe():
            remaining = [share]

            def probe(board: chess.Board) -> int | None:
                if (chess.popcount(board.occupied_co[them]) - 1
                        > self.sub_probe_men and not board.is_check()):
                    return None
                self.sub_probe_calls += 1
                if remaining[0] <= 0:
                    self.sub_probe_unknowns += 1
                    return None
                slice_budget = [min(remaining[0], self.sub_probe_slice)]
                granted = slice_budget[0]
                found_n = None
                truncated = False
                for n in range(1, self.sub_probe_n + 1):
                    status, _move = oracle.selfmate_status(
                        board, n, slice_budget, memo
                    )
                    if status is oracle.ProofStatus.PROVEN:
                        found_n = n
                        break
                    if status is oracle.ProofStatus.UNKNOWN:
                        truncated = True
                        break
                    if slice_budget[0] <= 0:
                        # Refuted at this n just as the slice died:
                        # deeper n were never asked.
                        truncated = n < self.sub_probe_n
                        break
                spent = granted - slice_budget[0]
                remaining[0] -= spent
                self.sub_probe_nodes += spent
                if remaining[0] <= 0:
                    self.sub_probe_exhaustions += 1
                if truncated:
                    self.sub_probe_unknowns += 1
                if found_n is not None:
                    self.sub_probe_hits += 1
                return found_n

            return probe

        return branch_probe

    def _safe_pool(self, board: chess.Board,
                   legal: list[chess.Move]) -> list[chess.Move]:
        """Moves that do not end the game against us on the spot.

        Baring their king counts: a mate-less opponent is the dead draw
        the eval calls worst, and the 2026-07-21 dev league watched the
        engine strip to it and then burn a bishop just to reset the
        draw clock over the corpse. Same partition rank as the one-ply
        stalemate — structural, not priced.
        """
        clean = []
        them = not board.turn
        for move in legal:
            board.push(move)
            accident = (
                board.is_checkmate()          # we mated them
                or board.is_stalemate()       # we suffocated them
                or adjudicate_draw(board) is not None
                or chess.popcount(board.occupied_co[them]) == 1  # bared them
            )
            board.pop()
            if not accident:
                clean.append(move)
        return clean or legal

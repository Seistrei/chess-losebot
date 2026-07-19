"""LoseBot: picks moves to force its own checkmate.

Per move: (1) never deliver mate or stalemate if any alternative exists,
(2) run an exact forced-selfmate probe (deeper when the opponent is reduced),
(3) otherwise fall back to heuristic misère negamax."""

import time

import chess

from .herding_vi import (
    POSITION_DEPENDENT_FAILURES,
    HerdingPolicy,
    herder_subsets,
    prospective_flip_policy,
    score_release_moves,
)
from .planning import herding_move, modeled_herding_move
from .profiles import EngineProfile, get_profile, probe_limits
from .search import (
    ProofStatus,
    arena_draw,
    gives_mate,
    gives_stalemate,
    negamax,
    selfmate_status,
    support_zach,
)
from .templates import (
    ConstructionPlan,
    PawnMateTemplate,
    best_pawn_mate_template,
    kh_bishop_distance,
    pawn_mate_templates,
)


def _closer_park_hop(board: chess.Board, us: chess.Color,
                     park: chess.Square) -> int | None:
    """Knight-hop distance of our nearest knight to the park square."""
    knights = board.pieces(chess.KNIGHT, us)
    if not knights:
        return None
    return min(
        chess.square_knight_distance(square, park) for square in knights
    )


def _kh_race_debt(board: chess.Board, us: chess.Color,
                  target: PawnMateTemplate) -> int:
    """Occupied race squares still owed — race_clear, counted.

    Mirrors the template's race_clear conditions exactly: any occupant on
    the corner or the escape, OUR men on the entry and far-capture
    squares. Counting instead of the boolean lets a pawn push that clears
    ONE debt through the king-mode pawn veto even while another debt
    remains (review P1: with pawns on both f2 and h2, neither clearing
    push flipped the boolean, so both stayed vetoed forever).
    """
    debt = 0
    if board.piece_at(target.checked_square) is not None:
        debt += 1
    if board.piece_at(target.kh_escape_square) is not None:
        debt += 1
    for square in (target.kh_entry_square, target.kh_far_capture_square):
        piece = board.piece_at(square)
        if piece is not None and piece.color == us:
            debt += 1
    return debt


class LoseBot:
    def __init__(self, depth: int = 2, opponent_model: str | None = None,
                 name: str = "losebot", profile: str = "current",
                 probe_cap: int | None = None,
                 max_probe_n: int | None = None,
                 vi_herders: int | None = None):
        self.depth = depth
        self.opponent_model = opponent_model
        self.name = name
        self.profile: EngineProfile = get_profile(profile)
        self.probe_cap = probe_cap
        self.max_probe_n = max_probe_n
        self.vi_herders = vi_herders
        self.forced_selfmates_found = 0
        self.probe_nodes = 0
        self.probe_budget_exhaustions = 0
        self.deepest_probe_completed = 0
        self.deep_probe_skips = 0
        self.plan: ConstructionPlan | None = None
        self.plans_created = 0
        self.plan_invalidations = 0
        self.best_plan_distance: int | None = None
        self.hold_moves_filtered = 0
        self.plan_regressions_filtered = 0
        self.forced_herding_choices = 0
        self.plan_repetitions_filtered = 0
        self.herd_search_nodes = 0
        self.herd_search_hits = 0
        self.herd_search_exhaustions = 0
        self.modeled_herding_hits = 0
        self.modeled_herding_replies = 0
        self.modeled_herding_nodes = 0
        self.modeled_herding_cache_hits = 0
        self.modeled_herding_memo_entries = 0
        self.modeled_herding_candidates_pruned = 0
        self.modeled_herding_incomplete = 0
        self._last_seen_ply: int | None = None

        # Value-iteration herding state and diagnostics. Negative memory is
        # held as the dead-certified policies themselves: a position is only
        # "known dead" if it maps into one of their explored graphs, so the
        # verdict is scoped to exactly the frozen configuration (and herder
        # subset) that was certified and can never be inherited by a rebuilt
        # plan or a different arrangement.
        self._vi_policy: HerdingPolicy | None = None
        self._vi_dead_policies: list[HerdingPolicy] = []
        # State-cap/timeout memory holds rooted fingerprints only
        # (fingerprint + dynamic root): graph size is a property of the
        # root, and no number of oversized roots proves the next one
        # unaffordable.
        self._vi_unbuildable: set[tuple] = set()
        self._vi_next_flip_ply = 0
        # The active policy's side-level conversion verdict: True when the
        # certify sweep completed and every live subset's audit completed
        # with nothing converting. Keyed to the same era as the policy.
        self._vi_side_unconvertible = False
        # King-holder adoption memory: (pawn_file, checked_side) of the last
        # corner adoption, surviving plan eras deliberately — a promotion
        # mid-walk invalidates the plan, and without this the rebuilt piece
        # plan would have to re-certify its side unconvertible before
        # re-steering at the same corner. Feasibility is re-checked at every
        # use, so a stale target can only cost the one resolve that fails.
        self._kh_adoption: tuple[int, int] | None = None
        # While the herd is clock-flagged, the certified reset scan is the
        # only sanctioned pawn pusher: this set holds every quiet push the
        # CURRENT decision did not certify — refused, unjudged, and
        # unscanned alike — and keeps them out of the heuristic fallbacks,
        # whose clock-urgent nudge rewards exactly those pushes. Armed
        # when the clock flags arm, cleared at the next VI decision:
        # refusals are audited against one root and must not outlive it
        # (review P1). Only the exact selfmate probe outranks the veto —
        # a PROVEN mating line that spends a push is a win, not a leak.
        self._vi_reset_refused: set[chess.Move] = set()
        self.vi_builds = 0
        self.vi_build_failures = 0
        self.vi_build_ms = 0.0
        self.vi_states = 0
        self.vi_edges = 0
        self.vi_updates = 0
        self.vi_root_value: float | None = None
        self.vi_pool_mismatches = 0
        self.vi_moves_played = 0
        self.vi_state_misses = 0
        self.vi_zero_fallbacks = 0
        self.vi_goal_stalls = 0
        self.vi_releases = 0
        self.vi_release_nodes = 0
        self.vi_side_flips = 0
        self.vi_conversion_flips = 0
        self.vi_unconvertible_sides = 0
        self.vi_kh_adoptions = 0
        self.vi_walk_clears = 0
        self.vi_closer_parks = 0
        self.vi_wait_funnel_guards = 0
        self.vi_flip_value: float | None = None
        self.vi_king_marches = 0
        self.vi_capture_guards = 0
        self.vi_cage_builds = 0
        self.vi_last_failure = ""
        self.vi_dead_certificates = 0
        self.vi_resolves = 0
        self.vi_goal_states = 0
        self.vi_forced_mates = 0
        self.vi_converting_goals = 0
        self.vi_conversion_checked = 0
        self.vi_conversion_nodes = 0
        self.vi_conversion_incomplete = 0
        # Repetition burn: how often the era recount moved the burn set,
        # and the active policy's current burned-state gauge.
        self.vi_burn_updates = 0
        self.vi_burned_states = 0
        # Clock feasibility: plies flagged by the hard/soft gates, ranked
        # candidates vetoed as unfinishable, releases accepted only under
        # the relaxed near-cliff standards, certified clock-reset pushes
        # played (and the hypothetical builds spent vetting them), plus
        # the last build's hitting-time estimates for the battery lines.
        self.vi_clock_hard_plies = 0
        self.vi_clock_soft_plies = 0
        self.vi_clock_pruned = 0
        self.vi_clock_relaxed_releases = 0
        self.vi_clock_resets = 0
        self.vi_clock_reset_builds = 0
        self.vi_clock_reset_vetoes = 0
        self.vi_hit_refreshes = 0
        self.vi_min_hit_root: int | None = None
        self.vi_exp_hit_root: float | None = None

    def _reset_vi_state(self) -> None:
        """Drop herding certificates along with the plan they were built for.

        Certificates are already self-scoping (a dead policy only ever
        matches the exact frozen configuration it certified), so this is
        about bounded memory and hygiene, not correctness: a new plan era
        starts with an empty ledger instead of dragging dead graphs around.
        """
        self._vi_policy = None
        self._vi_dead_policies.clear()
        self._vi_unbuildable.clear()
        self._vi_next_flip_ply = 0
        self._vi_side_unconvertible = False
        self._vi_reset_refused.clear()
        # The gauge describes the ACTIVE policy's burn set; dropping the
        # policy must drop it too or a replan followed by game end reports
        # burned states no live policy contains. vi_burn_updates stays
        # cumulative like every other counter.
        self.vi_burned_states = 0

    def _update_construction_plan(self, board: chess.Board,
                                  their_pieces: int) -> None:
        if not self.profile.stateful_plan:
            return
        if their_pieces != 0:
            # A promotion or other surviving mobile piece ends the
            # king-and-pawns phase. Continuing to preserve its old cage made
            # the planner ignore the new piece while it chased our king.
            if self.plan is not None:
                self.plan_invalidations += 1
                self.plan = None
                self._reset_vi_state()
            return

        target = (
            self.plan.resolve(board, board.turn)
            if self.plan is not None
            else None
        )
        if target is None:
            replacement = best_pawn_mate_template(board, board.turn)
            remembered = self._resolve_kh_adoption(board)
            if remembered is not None and (
                replacement is None or not replacement.king_holder
            ):
                # A remembered corner adoption outranks a fresh piece plan:
                # the piece side would only re-certify unconvertible and
                # re-steer here, at the cost of a full sweep. A posed
                # king-holder best template still wins over the memory —
                # it is real, not speculative.
                if self.plan is not None:
                    self.plan_invalidations += 1
                self.plan = remembered
                self.plans_created += 1
                self.vi_kh_adoptions += 1
                self._reset_vi_state()
                target = self.plan.resolve(board, board.turn)
            elif replacement is None:
                if self.plan is not None:
                    self.plan_invalidations += 1
                    self.plan = None
                    self._reset_vi_state()
                return
            else:
                if self.plan is not None:
                    self.plan_invalidations += 1
                self.plan = ConstructionPlan.from_template(
                    replacement, len(board.move_stack)
                )
                self.plans_created += 1
                self._reset_vi_state()
                target = replacement

        distance = target.setup_distance
        if self.best_plan_distance is None:
            self.best_plan_distance = distance
        else:
            self.best_plan_distance = min(self.best_plan_distance, distance)

    def planned_target(self, board: chess.Board,
                       us: chess.Color) -> PawnMateTemplate | None:
        if self.plan is None:
            return None
        return self.plan.resolve(board, us)

    def _filter_plan_regressions(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        if current is None or not self.profile.stateful_plan:
            return moves

        us = board.turn
        # Three occupants are the construction reserve. Surplus cage pieces
        # remain free to give forcing checks and herd the reluctant king.
        minimum_cage = min(current.cage_occupancy, 3)
        race_debt = (
            _kh_race_debt(board, us, current) if current.king_holder else 0
        )
        park_distance = (
            _closer_park_hop(board, us, current.kh_closer_park_square)
            if current.king_holder and current.pawn_walk > 0
            else None
        )
        stable: list[chess.Move] = []
        for move in moves:
            board.push(move)
            future = self.planned_target(board, us)
            future_debt = (
                _kh_race_debt(board, us, current)
                if current.king_holder
                and board.piece_type_at(move.to_square) == chess.PAWN
                else race_debt
            )
            moved_park = (
                _closer_park_hop(board, us, current.kh_closer_park_square)
                if park_distance is not None
                else None
            )
            board.pop()
            if future is None:
                continue
            if (
                current.king_holder
                and board.piece_type_at(move.from_square) == chess.PAWN
                and future_debt >= race_debt
            ):
                # In king-holder mode every one of our pawns is either a
                # pocket wall or inert: a push can only strip audited
                # coverage (the clock-urgent c4-c5 push attacked b6/d6 and
                # sealed the herd's own rank-six gate). The one exception
                # is a push that strictly reduces the occupied race-square
                # debt the pawn itself owes — counted, not the race_clear
                # boolean, so clearing one debt is not vetoed for the
                # crime of not clearing them all (review P1).
                continue
            if (
                park_distance is not None
                and moved_park is not None
                and moved_park > park_distance
            ):
                # The parked closer stays parked for the rest of the walk:
                # a wander the commitment filter would have to walk back
                # can be interrupted by the pawn's arrival, freezing the
                # seal unservable (review P1).
                continue
            if future.our_king_steps > current.our_king_steps:
                continue
            if future.cage_occupancy < minimum_cage:
                continue
            if (
                not current.runway_blocked
                and future.runway_blocked
                and not future.king_holder
                and future.our_king_steps >= current.our_king_steps
            ):
                # A transient runway block is the only way through when the
                # march must cross the runway square (Kc4-b4-a4 with a5
                # covered by the executioner): permit it for marching steps,
                # forbid it for everything else. King-holder templates are
                # exempt: their "runway" square IS the corner cage square,
                # and blocking it with the bishop is the construction.
                continue
            if (
                future.king_holder
                and future.pawn_walk == 0
                and future.our_king_steps == 0
                and current.our_king_steps > 0
                and future.cage_occupancy < future.required_cage
            ):
                # The king takes the arrival square LAST. Post-park play is
                # all reversible, so parking before the cage exists burns
                # fifty-move clock the herd and the race will need. During
                # a walk the ordering inverts: the executioner still owes
                # clock-resetting pushes, so an early park is free — and it
                # is the one freeze that makes the premature push (the
                # accepted 1/2 race of the drill) structurally impossible.
                continue
            if (
                future.king_holder
                and future.pawn_walk > 0
                and future.walk_blockers > current.walk_blockers
            ):
                # Never park a piece back onto the walk path: every blocker
                # is a Zach push the adoption cannot collect.
                continue
            if (
                current.holding_blocker_defended
                and not future.holding_blocker_defended
                and not current.ready_to_release
            ):
                continue
            stable.append(move)

        if stable:
            self.plan_regressions_filtered += len(moves) - len(stable)
            return stable
        return moves

    def _filter_wait_funnels(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        """Never hand Zach a move that adjudicates the game drawn.

        King-holder plans spend long stretches on the fallback search with
        no solved policy underneath: the walk's wait (the sub-MDP cannot
        exist before the geometry poses) and every post-arrival stall
        where the side certified dead or unconvertible and _vi_choice
        returns None. The repetition filter prunes our own second visits,
        but the arena draws the THIRD occurrence and Zach's reply can
        complete it on an our-turn position no tally of our own choices
        sees (the session-6 funnel lesson replayed outside the sub-MDP —
        the drill's walk-phase ply-70 repetition, then seeds 5/6/8 drawing
        the same way AFTER arrival). One ply of lookahead over his support
        pool against the arena's own adjudication oracle closes that door
        for the whole king-holder regime. The live herd is untouched:
        _vi_choice reads the pre-guard candidate list and prices threefold
        exactly by burning.
        """
        if not self.profile.vi_herding or current is None:
            return moves
        if not current.king_holder:
            return moves
        fresh: list[chess.Move] = []
        for move in moves:
            board.push(move)
            trapped = arena_draw(board) is not None
            if not trapped:
                for reply in support_zach(board):
                    board.push(reply)
                    # arena_draw leaves stalemate to the arena's separate
                    # check, so a reply that stalemates US must be caught
                    # here explicitly (review P2). A reply that MATES us
                    # is the win and never trips is_stalemate.
                    trapped = (
                        board.is_stalemate()
                        or arena_draw(board) is not None
                    )
                    board.pop()
                    if trapped:
                        break
            board.pop()
            if not trapped:
                fresh.append(move)
        if fresh and len(fresh) < len(moves):
            self.vi_wait_funnel_guards += len(moves) - len(fresh)
            return fresh
        return moves

    def _filter_forced_captures(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        """Never squeeze their pool down to non-mating captures.

        A pool of nothing but captures makes Zach eat the construction: a
        king capture removes a cage piece or herder, a pawn capture walks the
        executioner off its file (the bxc5 failure), and a sacrifice check
        with one forced recapture donates a major for a single step of
        herding (the game_005 carousel). The one forced capture worth having
        — a capture that checkmates us — is untouched, because support_zach
        drops mating moves and leaves that pool empty, not capture-only.
        """
        if not self.profile.vi_herding or current is None:
            return moves
        guarded: list[chess.Move] = []
        for move in moves:
            board.push(move)
            pool = support_zach(board)
            forced_capture = bool(pool) and all(
                board.is_capture(reply) for reply in pool
            )
            board.pop()
            if not forced_capture:
                guarded.append(move)
        if guarded and len(guarded) < len(moves):
            self.vi_capture_guards += len(moves) - len(guarded)
            return guarded
        return moves

    def _filter_walk_clear(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        """Release the freeze: clear our men off the adopted pawn's walk.

        The walk is the slow, Zach-paced half of the adoption, so it starts
        first — every ply a blocker stands on the path is a push the
        uniform kernel cannot offer. The same dawdling that stalled the
        march and the cage stalls this: no depth-2 gradient trades a check
        for a quiet sidestep, so the clearing is a commitment. Fires only
        while a king-holder plan is walking and blocked; the regression
        filter upstream already forbids re-blocking.
        """
        if not self.profile.vi_herding or current is None:
            return moves
        if (
            not current.king_holder
            or current.pawn_walk == 0
            or current.walk_blockers == 0
        ):
            return moves
        us = board.turn
        clearing: list[chess.Move] = []
        for move in moves:
            board.push(move)
            future = self.planned_target(board, us)
            board.pop()
            if (
                future is not None
                and future.walk_blockers < current.walk_blockers
            ):
                clearing.append(move)
        if clearing:
            self.vi_walk_clears += 1
            return clearing
        return moves

    def _filter_king_march(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        """March the king to its parking square once its precondition holds.

        A depth-2 gradient never executes the march: some check or sacrifice
        always outscores the one-tempo distance gain, and the king shuffles
        while majors get donated (the game_005 carousel). Piece mode marches
        to the checked square once the executioner is held and defended;
        king mode marches to the ARRIVAL square once the corner cage bishop
        is placed — the king takes the arrival square last, so pre-park
        construction can still reset the fifty-move clock. The regression
        filter upstream already removed king steps that would drop the
        holder's defense or the cage reserve.
        """
        if not self.profile.vi_herding or current is None:
            return moves
        if current.our_king_steps <= 0:
            return moves
        if current.king_holder:
            # During a walk the cage gate lifts and the ordering inverts:
            # pending pawn pushes make pre-arrival construction clock-free,
            # and the parked king is the freeze that stops the executioner
            # dead on its pre-corner square — so the king marches FIRST.
            # The cage bishop can never need the king's square (arrival and
            # corner cage sit on opposite shades), so nothing is walled in.
            if (
                current.pawn_walk == 0
                and current.cage_occupancy < current.required_cage
            ):
                return moves
        elif (
            not current.holding_blocker
            or not current.holding_blocker_defended
        ):
            return moves
        us = board.turn
        king = board.king(us)
        if king is None:
            return moves
        marching: list[chess.Move] = []
        for move in moves:
            if move.from_square != king:
                continue
            board.push(move)
            future = self.planned_target(board, us)
            board.pop()
            if (
                future is not None
                and future.our_king_steps < current.our_king_steps
            ):
                marching.append(move)
        if marching:
            self.vi_king_marches += 1
            return marching
        return moves

    def _filter_cage_build(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        """Commit tempo to completing the cage while its gate is shut.

        The herding sub-MDP refuses to engage below the template's cage
        requirement, and the gradient dawdles over the last occupant the
        same way it dawdled over the march. Piece mode builds around the
        parked king; king mode routes the cage-colored bishop to the corner
        square BEFORE the king parks (the king takes the arrival square
        last), accepting distance progress because the route is usually
        multi-tempo.
        """
        if not self.profile.vi_herding or current is None:
            return moves
        us = board.turn
        if current.king_holder:
            if current.cage_occupancy >= current.required_cage:
                return moves
            baseline = kh_bishop_distance(board, us, current)
            completing = []
            routing = []
            for move in moves:
                board.push(move)
                future = self.planned_target(board, us)
                if future is not None:
                    if future.cage_occupancy > current.cage_occupancy:
                        completing.append(move)
                    elif (
                        future.cage_occupancy == 0
                        and kh_bishop_distance(board, us, future) < baseline
                    ):
                        routing.append(move)
                board.pop()
            # Landing the bishop dominates approaching it: the fallback
            # search cannot rank the two (an adversarial premature-push
            # line washes every candidate to the same template loss), so
            # the commitment must.
            building = completing or routing
            if building:
                self.vi_cage_builds += 1
                return building
            return moves
        if (
            current.our_king_steps != 0
            or current.cage_occupancy >= 3
            or not current.holding_blocker
            or not current.holding_blocker_defended
        ):
            return moves
        building = []
        for move in moves:
            board.push(move)
            future = self.planned_target(board, us)
            board.pop()
            if (
                future is not None
                and future.cage_occupancy > current.cage_occupancy
            ):
                building.append(move)
        if building:
            self.vi_cage_builds += 1
            return building
        return moves

    def _filter_closer_park(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        """Walk the knight closer to its park square while the pawn walks.

        The release probe needs the closer ONE hop from the seal-cover
        square at race time, but every seal-range park attacks the pocket
        or the gate their king must cross (the b4-knight failure certified
        the herd dead against our own statics). The template's park square
        is the unique out-of-the-way one-hop station, and the walk is the
        one phase where knight tempo is free — pending pawn pushes reset
        the clock, and the herd has not started. Fires after the freeze
        release, the march, and the cage: the park is the last chore.
        """
        if not self.profile.vi_herding or current is None:
            return moves
        if (
            not current.king_holder
            or current.pawn_walk == 0
            or current.walk_blockers > 0
            or current.our_king_steps > 0
            or current.cage_occupancy < current.required_cage
        ):
            return moves
        us = board.turn
        park = current.kh_closer_park_square
        baseline = _closer_park_hop(board, us, park)
        if baseline is None or baseline == 0:
            return moves
        parking: list[chess.Move] = []
        for move in moves:
            if board.piece_type_at(move.from_square) != chess.KNIGHT:
                continue
            board.push(move)
            future = self.planned_target(board, us)
            moved = _closer_park_hop(board, us, park)
            board.pop()
            if future is not None and moved is not None and moved < baseline:
                parking.append(move)
        if parking:
            self.vi_closer_parks += 1
            return parking
        return moves

    def _filter_forced_herding(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        current: PawnMateTemplate | None,
    ) -> list[chess.Move]:
        if (
            current is None
            or not current.holding_blocker
            or current.defender_steps <= 0
        ):
            return moves

        us = board.turn
        forcing: list[chess.Move] = []
        for move in moves:
            board.push(move)
            if not board.is_check():
                board.pop()
                continue
            replies = list(board.legal_moves)
            worst_distance = -1
            valid = bool(replies)
            for reply in replies:
                board.push(reply)
                future = self.planned_target(board, us)
                board.pop()
                if future is None:
                    valid = False
                    break
                worst_distance = max(worst_distance, future.defender_steps)
            board.pop()
            if valid and worst_distance < current.defender_steps:
                forcing.append(move)

        if forcing:
            self.forced_herding_choices += 1
            return forcing
        return moves

    def _filter_plan_repetitions(
        self,
        board: chess.Board,
        moves: list[chess.Move],
    ) -> list[chess.Move]:
        if not self.profile.stateful_plan:
            return moves
        fresh: list[chess.Move] = []
        for move in moves:
            board.push(move)
            repeats = board.is_repetition(2)
            board.pop()
            if not repeats:
                fresh.append(move)
        if fresh:
            self.plan_repetitions_filtered += len(moves) - len(fresh)
            return fresh
        return moves

    def _vi_choice(
        self,
        board: chess.Board,
        target: PawnMateTemplate | None,
        safe: list[chess.Move],
    ) -> chess.Move | None:
        """Race-release when the defender is delivered; otherwise follow the
        solved herding sub-MDP. Returns None to fall through the waterfall."""
        # Reset-push vetoes are evidence about ONE audited root: whatever
        # the previous decision recorded is stale against this position
        # (review P1). The clock-flag block below re-arms the set whenever
        # this decision is flagged.
        self._vi_reset_refused.clear()
        if target is None:
            return None
        if target.king_holder:
            # A walking adoption has no posed geometry yet: the sub-MDP's
            # frozen-pawn contract cannot hold while the walk is the point,
            # so certification, flips, and releases all wait for arrival.
            if target.pawn_walk > 0:
                return None
            # King mode engages once the king holds the arrival square, the
            # corner bishop is caged, and the corner itself is free for the
            # vacate. Occupied race squares are left to the build and the
            # audit: they price the actual position honestly.
            if (
                target.our_king_steps > 0
                or target.cage_occupancy < target.required_cage
                or board.piece_at(target.checked_square) is not None
            ):
                return None
        elif (
            target.our_king_steps > 0
            or target.cage_occupancy < 3
            or not target.holding_blocker
            or not target.holding_blocker_defended
            or target.runway_blocked
        ):
            return None

        # Quiet plies left before the arena's fifty-move adjudication: the
        # whole clock-feasibility layer prices this one number against the
        # solved graph's hitting times.
        remaining = 100 - board.halfmove_clock

        # The exact probe already refused a guaranteed net this move. With
        # the defender adjacent (or one step out), offer the best scored race
        # instead of tempoing forever. This deliberately bypasses the hold
        # filter: a scored release is the point of having held at all.
        if target.defender_steps <= 1:
            choice = score_release_moves(
                board, target, self.opponent_model,
                self.profile.vi_race_max_losing,
            )
            if choice is None and remaining <= self.profile.vi_clock_relax_at:
                # Near the cliff a refused strict race is re-scored with
                # unlimited losing replies: any race with a winning reply
                # beats the certain zero of the adjudication. But a worse
                # lottery must not preempt a better one the herd can still
                # reach — when the active policy maps this position and
                # affirms that a converting goal FINISHES inside the
                # budget (affirmative finish-inclusive fit_hit as the
                # bound — the min_hit floor may reject but never affirm,
                # since the audited race can owe more plies than the
                # cheapest conceivable finish (review P1) — and exp_hit
                # with the soft headroom), the strict standard holds and
                # the herd goes and gets it. Affirmation demands honest
                # numbers: the solve and the p/m pass must both have
                # converged, because a truncated exp_hit can understate
                # and wrongly suppress the lottery (review P1). Only
                # without a full affirmation — no policy, off-graph,
                # unconverged stats, or a herd that no longer fits — is
                # the best positive lottery taken now.
                fits = False
                policy = self._vi_policy
                if (
                    policy is not None
                    and policy.arrival == target.arrival_square
                    and policy.report.ok
                    and policy.report.root_live
                    and policy.report.root_converts
                    and policy.report.converged
                ):
                    if not policy.report.hit_converged:
                        # A p/m pass truncated behind a converged solve
                        # would otherwise leave this affirmation dark for
                        # the policy's whole life — solve_more never runs
                        # again (review P1). Retry it exactly where it is
                        # consumed; single-shot per value basis.
                        if policy.refresh_hit_stats(
                            self.profile.vi_build_ms
                        ):
                            self.vi_hit_refreshes += 1
                    hits = (
                        policy.hit_estimates(board)
                        if policy.report.hit_converged
                        else None
                    )
                    if hits is not None:
                        _, fit_hit, exp_hit = hits
                        fits = (
                            fit_hit <= remaining
                            and exp_hit * self.profile.vi_clock_soft_factor
                            <= remaining
                        )
                if not fits:
                    choice = score_release_moves(
                        board, target, self.opponent_model, 64,
                    )
                    if choice is not None:
                        self.vi_clock_relaxed_releases += 1
            if choice is not None:
                self.vi_releases += 1
                self.vi_release_nodes += choice.nodes
                return choice.move
            if target.defender_steps == 0:
                self.vi_goal_stalls += 1
                return None

        limit = (
            self.vi_herders
            if self.vi_herders is not None
            else self.profile.vi_max_herders
        )
        policy = self._vi_policy
        if (
            policy is None
            or policy.arrival != target.arrival_square
            or not policy.matches(board)
            or (
                not policy.report.ok
                and policy.report.reason in POSITION_DEPENDENT_FAILURES
            )
        ):
            policy, verdict = self._certify_herding(board, target, limit)
            self._vi_policy = policy
            self._vi_side_unconvertible = verdict == "unconvertible"
            self.vi_burned_states = 0  # fresh builds carry no burns yet
            if verdict == "hopeless":
                # Every maximal herder subset of this frozen configuration
                # is certified dead: the side is hopeless as built, so the
                # only remaining questions are the mirrored checked square
                # (live there is enough — here there is nothing to keep)
                # and, failing that, a corner adoption: a walkable king-
                # holder template beats staying on a certified-dead side.
                if not self._consider_side_flip(board, limit):
                    self._consider_kh_adoption(board)
                return None
            if verdict == "unconvertible":
                # The side herds but provably cannot finish at audit depth:
                # abandon it only for a mirror that positively converts —
                # or replace the plan outright with a corner king-holder
                # adoption, the one construction family the release theorem
                # does not price at zero. The mirror flip keeps priority
                # because its prospect is a certified fact about a posed
                # position; the adoption is theorem-backed geometry whose
                # audit only reruns once the walk delivers the pawn.
                self.vi_unconvertible_sides += 1
                if self._consider_side_flip(
                    board, limit, require_conversion=True
                ):
                    return None
                if self._consider_kh_adoption(board):
                    return None
        if policy is None or not policy.report.ok:
            return None
        if not policy.report.root_live:
            return None
        # Clock feasibility, read off the solved graph. Only a converting
        # side races the clock at all: with nothing to convert to, hitting
        # a proxy goal sooner changes nothing, and the audit-negative
        # machinery (flips, adoption) already owns that case. The hard
        # gate is a certificate — min_hit is best-case Zach, so failing it
        # means this era CANNOT finish and only hardens as the clock runs.
        # The soft gate is the expected herd not fitting, with headroom
        # for hitting-time variance; it arms the same reconsideration
        # cadence, never a verdict.
        clock_hard = clock_soft = False
        clock_veto = policy.report.root_converts
        if clock_veto:
            if policy.report.converged and not policy.report.hit_converged:
                # The build shares one deadline across solver and p/m
                # pass, and solve_more never runs on a converged solve —
                # without this, a truncated exp_hit is permanent: the
                # release affirmation stays dark and the soft gate reads
                # stale numbers for the policy's whole life (review P1).
                # One dedicated retry per value basis, priced like any
                # resume.
                if policy.refresh_hit_stats(self.profile.vi_build_ms):
                    self.vi_hit_refreshes += 1
            hits = policy.hit_estimates(board)
            if hits is not None:
                min_hit, _, exp_hit = hits
                if min_hit > remaining:
                    clock_hard = True
                    self.vi_clock_hard_plies += 1
                elif (
                    exp_hit * self.profile.vi_clock_soft_factor > remaining
                ):
                    # One-sided by construction: a truncated p/m pass can
                    # misprice exp_hit, but a spurious soft flag only
                    # costs cadenced reconsideration builds, while gating
                    # it on the honesty flags would suppress the cascade
                    # exactly on the big graphs where the solver labors.
                    clock_soft = True
                    self.vi_clock_soft_plies += 1
        if clock_hard or clock_soft:
            # While flagged, the certified reset scan is the only
            # sanctioned pusher: bar every quiet push this decision has
            # not certified from the fallbacks — refused, unjudged, and
            # unscanned alike (review P1: unjudged pushes reached the
            # fallback, and a cooldown-skipped scan left stale refusals
            # standing in for fresh ones). The scan lifts the one push it
            # certifies; the filter never empties a menu.
            self._vi_reset_refused = set(
                self._reset_push_candidates(board)
            )
        if len(board.move_stack) >= self._vi_next_flip_ply:
            if self._vi_side_unconvertible:
                # The prospect's convertibility is position-dependent (their
                # king drifts, forced-mate pockets open), so an unconvertible
                # side re-probes the mirror whenever the cooldown expires —
                # certification only reruns on rebuilds, which a stable herd
                # never triggers. A declined flip retries the corner adoption
                # on the same cadence: its feasibility is position-dependent
                # too (a path piece of theirs moves off, a bishop survives).
                if self._consider_side_flip(
                    board, limit, require_conversion=True
                ):
                    return None
                if self._consider_kh_adoption(board):
                    return None
            elif clock_hard or clock_soft:
                # The side converts but the era's budget cannot (hard) or
                # probably will not (soft) fit the remaining herd. In
                # preference order: manufacture time — a certified pawn
                # push resets the clock and KEEPS the proven side — then
                # the mirror, then the corner adoption. A hard-dead side
                # is worth zero this era, so like the hopeless case there
                # is nothing to stay for and any feasible live mirror
                # will do; under the advisory soft gate leaving still
                # demands a positively converting prospect, and the
                # one-way adoption stays reserved for the certificate.
                reset = self._consider_clock_reset(
                    board, target, limit, policy,
                    require_all_replies=clock_soft,
                )
                if reset is not None:
                    self.vi_clock_resets += 1
                    return reset
                if self._consider_side_flip(
                    board, limit, require_conversion=not clock_hard
                ):
                    return None
                if clock_hard and self._consider_kh_adoption(board):
                    return None
        # Price the arena's threefold rule into the values before reading
        # them: every state whose position this era has already seen twice
        # is a draw on re-entry, and Zach's replies can funnel play into
        # one from successors that are themselves fresh (the Rf5/Rf7
        # shuttle drew on an our-turn position no successor tally of our
        # own choices could see). Burning re-solves the sub-MDP with those
        # states as losing terminals, so the ranking below already routes
        # around — or honestly zeroes — every funnel.
        counts, burn_changed = policy.apply_repetition_history(board)
        if burn_changed:
            self.vi_burn_updates += 1
        self.vi_burned_states = policy.burned_states
        if not policy.report.converged:
            # The certificate is exact regardless; the *ranking* is not.
            # Keep solving across moves rather than following a half-baked
            # value table into the fallbacks' arms.
            before = policy.report.updates
            policy.solve_more(self.profile.vi_build_ms)
            self.vi_updates += policy.report.updates - before
            self.vi_resolves += 1
            self.vi_root_value = policy.report.root_value
            if not policy.report.converged:
                return None

        ranked = policy.ranked_moves(board)
        if ranked is None:
            self.vi_state_misses += 1
            self._vi_policy = None
            self.vi_burned_states = 0
            return None
        # Take the candidates within ONE OPTIMAL PLY of the best value
        # (floor = top * gamma) and prefer the successor this era has
        # entered least: burning already zeroed the continuations that MUST
        # repeat, so the tie-break only needs room to dodge second visits —
        # the ones that arm future burns. The window earns its keep there;
        # any wider and it spends the fifty-move clock on freshness detours
        # (the old absolute 0.05 admitted ~13-ply regressions at
        # herd-typical values and the freed games died at ply 100). The
        # arena_draw check keeps the one law the clockless sub-MDP cannot
        # price: a quiet move that lands on the fifty-move adjudication.
        safe_set = set(safe)
        top_value = None
        floor = 0.0
        candidates: list[tuple[int, float, chess.Move]] = []
        for value, move, child in ranked:
            if value <= 1e-9:
                break
            if move not in safe_set:
                continue
            if (
                clock_veto
                and policy.child_min_hit(child) + 1 > remaining
            ):
                # Even with perfect Zach luck this continuation cannot
                # FINISH inside the era (the child's min_hit already
                # counts the terminal tail; +1 is our own move): its true
                # value under the clock is 0 whatever the pristine graph
                # says. min_hit stays a lower bound under burning, so the
                # veto never cuts a finishable line.
                self.vi_clock_pruned += 1
                continue
            if top_value is None:
                top_value = value
                floor = value * self.profile.vi_gamma
            elif value < floor:
                break
            board.push(move)
            drawn = arena_draw(board) is not None
            board.pop()
            if drawn:
                continue
            candidates.append((counts.get(child, 0), value, move))
        if candidates:
            candidates.sort(key=lambda item: (item[0], -item[1]))
            return candidates[0][2]
        self.vi_zero_fallbacks += 1
        return None

    def _absorb_vi_report(self, report) -> None:
        self.vi_builds += 1
        self.vi_build_ms += report.build_ms
        self.vi_states += report.states
        self.vi_edges += report.edges
        self.vi_updates += report.updates
        self.vi_pool_mismatches += report.pool_mismatches
        self.vi_root_value = report.root_value
        self.vi_goal_states += report.goal_states
        self.vi_forced_mates += report.forced_mates
        self.vi_converting_goals += report.converting_goals
        self.vi_conversion_checked += report.conversion_checked
        self.vi_conversion_nodes += report.conversion_nodes
        if report.ok and not report.conversion_complete:
            self.vi_conversion_incomplete += 1
        if report.ok:
            self.vi_min_hit_root = report.min_hit_root or None
            self.vi_exp_hit_root = report.exp_hit_root or None
        if not report.ok:
            self.vi_build_failures += 1
            self.vi_last_failure = report.reason

    def _certify_herding(
        self,
        board: chess.Board,
        target: PawnMateTemplate,
        limit: int,
    ) -> tuple[HerdingPolicy | None, str]:
        """Sweep the maximal herder subsets and pass a side-level verdict.

        Deadness is a property of one frozen configuration AND one herder
        subset, so a single dead build never condemns the side; the same
        asymmetry governs conversion. Walk the maximal subsets (greedy
        preference first): a live subset whose audit found a conversion
        wins outright — positives are facts at any coverage — while a
        merely live subset is kept as the fallback and the sweep continues
        hunting a convertible one. Verdicts, from best to worst:

        - "converts": the returned policy is live and its audit found a
          converting terminal (the common case still costs one build).
        - "live": a live fallback, but the side-level negative is not
          provable — the sweep or some live subset's audit was cut short
          (deadline, or UNKNOWN-tainted refusals in the audit's case).
        - "unconvertible": complete sweep, at least one live subset, and
          every live subset's audit completed with nothing converting.
          Play can still herd the fallback; the verdict is the honest flip
          trigger, not a reachability fact (audit probes are depth-capped).
        - "hopeless": complete sweep, every subset certified dead.
        - "unknown": nothing usable — no candidates, a configuration-level
          refusal, or an exhausted sweep with no live subset. Never a
          verdict about the side.
        """
        deadline = time.monotonic() + self.profile.vi_build_ms / 1000.0
        build_options = dict(
            model=self.opponent_model,
            race_max_losing=self.profile.vi_race_max_losing,
            conversion_ms=self.profile.vi_conversion_ms,
        )
        subsets, complete = herder_subsets(board, target, limit)
        if not subsets:
            # No candidates at all: build once for the diagnostic reason.
            policy = HerdingPolicy.build(
                board, target, limit, self.profile.vi_state_cap,
                self.profile.vi_build_ms, self.profile.vi_gamma,
                **build_options,
            )
            self._absorb_vi_report(policy.report)
            return policy, "unknown"

        # Subsets already certified dead at this exact position (herders may
        # have wandered since certification; contains() covers that).
        dead_squares = set()
        for dead in self._vi_dead_policies:
            squares = dead.dynamic_squares(board)
            if squares is not None:
                dead_squares.add(squares)

        fallback: HerdingPolicy | None = None
        negatives_complete = True
        for subset in subsets:
            if frozenset(square for square, _ in subset) in dead_squares:
                continue
            remaining_ms = (deadline - time.monotonic()) * 1000.0
            if remaining_ms <= 0:
                complete = False
                break
            fair_budget = remaining_ms >= self.profile.vi_build_ms / 2
            policy = HerdingPolicy.build(
                board, target, limit, self.profile.vi_state_cap,
                int(remaining_ms), self.profile.vi_gamma, herders=subset,
                skip_fingerprints=self._vi_unbuildable,
                **build_options,
            )
            report = policy.report
            if report.reason == "skipped-unbuildable":
                complete = False
                continue
            self._absorb_vi_report(report)
            if report.ok:
                if report.root_live:
                    if report.root_converts:
                        return policy, "converts"
                    if fallback is None:
                        fallback = policy
                    if not report.conversion_complete:
                        negatives_complete = False
                    continue
                # The ledger must be able to hold a whole sweep's worth of
                # certificates: evicting mid-sweep made later sweeps rebuild
                # earlier subsets forever and the hopeless verdict never
                # arrived. Stripped certificates are cheap to keep, and the
                # cap is comfortably above any real enumeration.
                policy.strip_to_certificate()
                self._vi_dead_policies.append(policy)
                if len(self._vi_dead_policies) > 64:
                    self._vi_dead_policies.pop(0)
                self.vi_dead_certificates += 1
                continue
            if report.reason in ("state-cap", "build-timeout"):
                # Could not certify. Reachable-graph size is a property of
                # the dynamic root, so remember the failure per root ONLY —
                # no strike count ever graduates to a config-wide skip: two
                # oversized roots say nothing about a third, and an
                # unbuildable subset already blocks the hopeless verdict,
                # so broader memory could only save wall time the sweep
                # deadline bounds anyway. (A timeout on a starved budget is
                # not remembered at all: it gets retried once earlier
                # subsets are answered from cache. State-cap is
                # budget-independent.)
                oversized = report.reason == "state-cap" or fair_budget
                if oversized and policy.rooted_fingerprint is not None:
                    self._vi_unbuildable.add(policy.rooted_fingerprint)
                complete = False
                continue
            # Configuration-level refusal (pawn not frozen, root already
            # terminal, pool mismatch, ...). With no fallback in hand this
            # ends the sweep as before. Past a live fallback the reason must
            # be subset-dependent (a configuration-wide one would have
            # refused the fallback's build too), so treat the subset as
            # unresolved rather than discarding a live policy over it.
            if fallback is None:
                return policy, "unknown"
            complete = False
        if fallback is not None:
            if complete and negatives_complete:
                return fallback, "unconvertible"
            return fallback, "live"
        return None, "hopeless" if complete else "unknown"

    def _consider_side_flip(self, board: chess.Board, limit: int,
                            require_conversion: bool = False) -> bool:
        """Probe the mirrored checked square; True when the plan flips.

        Only a completed build may speak: a good prospect re-commits the
        plan to the mirror, a genuine dead certificate backs off for a while
        (the construction shifts and may reopen it), and anything transient
        — unposable hypothetical, refused or timed-out build — is unknown,
        never dead. The old code marked the mirror dead on every non-live
        outcome, so one slow or unlucky build could kill both flanks for
        the rest of the game.

        ``require_conversion`` is the audited-conversion gate: abandoning a
        LIVE side is only worth it for a mirror that positively converts
        (a fact at any audit coverage), while a hopeless side keeps taking
        any live prospect — there is nothing to stay for. A live prospect
        refused under the gate backs off long when its audit completed (an
        honest negative at this depth) and short when the audit was cut
        short or UNKNOWN-tainted (more budget could flip it); the prospect
        is a single greedy-subset hypothetical either way, so a refusal
        only ever sets a cooldown, never a verdict about the mirror.
        """
        ply = len(board.move_stack)
        if self.plan is None or ply < self._vi_next_flip_ply:
            return False
        mirrored = ConstructionPlan(
            pawn_file=self.plan.pawn_file,
            checked_side=-self.plan.checked_side,
            created_ply=ply,
            holder_mode=self.plan.holder_mode,
        )
        mirrored_target = mirrored.resolve(board, board.turn)
        prospect = None
        if mirrored_target is not None:
            prospect = prospective_flip_policy(
                board,
                mirrored_target,
                limit,
                self.profile.vi_state_cap,
                self.profile.vi_build_ms,
                self.profile.vi_gamma,
                model=self.opponent_model,
                race_max_losing=self.profile.vi_race_max_losing,
                conversion_ms=self.profile.vi_conversion_ms,
            )
        if prospect is not None and prospect.report.ok:
            report = prospect.report
            self.vi_flip_value = report.root_value
            # The mirror herds inside the SAME era, so a prospect whose
            # best-case finish (min_hit_root is finish-inclusive) cannot
            # fit the remaining fifty-move budget is worthless whatever
            # its audit says. min_hit_root 0 means the stats made no
            # claim and must never condemn.
            feasible = (
                report.min_hit_root == 0
                or report.min_hit_root <= 100 - board.halfmove_clock
            )
            if report.root_live and feasible and (
                not require_conversion or report.root_converts
            ):
                self.plan = mirrored
                self.vi_side_flips += 1
                if require_conversion:
                    self.vi_conversion_flips += 1
                self._reset_vi_state()
                return True
            if not feasible and report.root_live:
                # Live but unfinishable in this era — a refusal that only
                # hardens as the clock runs. Long back-off.
                self._vi_next_flip_ply = ply + 16
                return False
            if report.root_live and not report.conversion_complete:
                # Live but conversion unknown: a starved audit, not a
                # refusal — retry sooner than a genuine negative.
                self._vi_next_flip_ply = ply + 8
                return False
            self._vi_next_flip_ply = ply + 16
            return False
        self.vi_flip_value = None
        self._vi_next_flip_ply = ply + 8
        return False

    def _consider_clock_reset(
        self,
        board: chess.Board,
        target: PawnMateTemplate,
        limit: int,
        policy: HerdingPolicy | None = None,
        require_all_replies: bool = False,
    ) -> chess.Move | None:
        """Manufacture era time: a certified pawn push resets the clock.

        The herd regime is all quiet moves, so the era's 100-ply budget
        is hard — and when the solved sub-MDP says the remaining budget
        cannot (min_hit) or probably will not (exp_hit) fit the herd, the
        one device that creates time WITHOUT abandoning a proven side is
        an irreversible move that preserves the construction. Blind
        pushes are exactly what the king-mode pawn veto exists for (the
        c4-c5 push sealed the herd's own rank-six gate), so a reset must
        certify, in three layers: the pushed position still resolves the
        committed plan without regressing any construction metric; Zach's
        reply pool stays free of forced captures and reply-stalemate traps
        (the funnel and capture guards replayed here, where the push
        bypasses them); and a hypothetical rebuild rooted at the pushed
        position WITH ZACH TO MOVE — his reply comes before our next
        turn, so an our-turn root would certify a state the game never
        reaches (review P1: the skipped-turn root was not even in the
        reachable graph) — certifies live and converting, with per-reply
        finish evidence read through ``reply_fit_fraction``: the
        their-turn root's children are exactly the real post-reply
        states, any fitting reply beats the certain zero under a hard
        flag, and under the advisory soft flag every reply must still
        fit (``require_all_replies``) — the side retains real value, so
        a push into a coin-flip-dead continuation is refused. One
        certified push buys a fresh 100 plies for a side that has
        already proven it can finish, given time.

        Certification is the only path a push takes into play while the
        herd is clock-flagged: the caller has already barred the whole
        scan domain from this decision's fallbacks (the veto arms with
        the clock flags), so a refused or unjudged candidate stays vetoed
        without any bookkeeping here, and the one certified push is
        lifted out of the veto as it is chosen (review P1: on a hard
        clock the VI candidates all prune away, and the heuristic
        fallback — whose clock-urgent nudge REWARDS irreversible moves —
        must not play a push the audit refused OR never judged; piece
        mode has no blanket pawn veto). One shared ``vi_build_ms``
        deadline bounds the whole scan (review P2); candidates the budget
        never reaches were never certified, which is the only fact the
        fallbacks may use.
        """
        us = board.turn
        plan = self.plan
        if plan is None:
            return None
        pre_debt = (
            _kh_race_debt(board, us, target) if target.king_holder else 0
        )
        # The hypothetical must price the continuation play would actually
        # keep: the certify sweep may have chosen a non-greedy herder
        # subset (the greedy one can audit non-converting while a later
        # subset converts), and a push moves no herder, so the active
        # subset carries over verbatim. Greedy is only the fallback when
        # the active policy cannot name its herders here.
        forced = None
        if policy is not None:
            squares = policy.dynamic_squares(board)
            if squares is not None:
                forced = tuple(sorted(
                    (square, board.piece_type_at(square))
                    for square in squares
                ))
        deadline = time.monotonic() + self.profile.vi_build_ms / 1000.0
        for move in self._reset_push_candidates(board):
            board.push(move)
            future = plan.resolve(board, us)
            stable = (
                future is not None
                and future.our_king_steps <= target.our_king_steps
                and future.cage_occupancy >= target.cage_occupancy
                and future.pawn_walk == target.pawn_walk
                and future.walk_blockers <= target.walk_blockers
                and (not target.holding_blocker or future.holding_blocker)
                and (
                    not target.holding_blocker_defended
                    or future.holding_blocker_defended
                )
                and (target.runway_blocked or not future.runway_blocked)
            )
            if stable and target.king_holder:
                stable = _kh_race_debt(board, us, future) <= pre_debt
            if stable:
                pool = support_zach(board)
                if pool and all(board.is_capture(reply) for reply in pool):
                    stable = False
                for reply in pool if stable else ():
                    board.push(reply)
                    trapped = board.is_stalemate()
                    board.pop()
                    if trapped:
                        stable = False
                        break
            board.pop()
            if not stable:
                continue
            remaining_ms = (deadline - time.monotonic()) * 1000.0
            if remaining_ms < 250.0:
                break  # scan budget exhausted: the rest stay uncertified
            hypothetical = board.copy(stack=False)
            hypothetical.push(move)
            resolved = plan.resolve(hypothetical, us)
            if resolved is None:
                continue
            self.vi_clock_reset_builds += 1
            probe = HerdingPolicy.build(
                hypothetical, resolved, limit,
                self.profile.vi_state_cap, int(remaining_ms),
                self.profile.vi_gamma, herders=forced,
                model=self.opponent_model,
                race_max_losing=self.profile.vi_race_max_losing,
                conversion_ms=self.profile.vi_conversion_ms,
                root_theirs=True,
            )
            report = probe.report
            fraction = probe.reply_fit_fraction()
            if (
                report.ok
                and report.root_live
                and report.root_converts
                and fraction is not None
                and (
                    fraction >= 1.0
                    if require_all_replies
                    else fraction > 0.0
                )
            ):
                self._vi_reset_refused.discard(move)
                return move
        return None

    def _reset_push_candidates(
        self, board: chess.Board
    ) -> list[chess.Move]:
        """Quiet pawn pushes in the clock-reset scan's domain.

        Captures and promotions live outside it (they change material and
        end the pawn phase — other machinery owns them). A checking push
        forces replies the same-root hypothetical does not model, and
        forcing the king was never a reset's job; mating and stalemating
        pushes are never played at all. Legal-move order, so the scan's
        budget spends deterministically.
        """
        return [
            move
            for move in board.legal_moves
            if board.piece_type_at(move.from_square) == chess.PAWN
            and not board.is_capture(move)
            and move.promotion is None
            and not board.gives_check(move)
            and not gives_mate(board, move)
            and not gives_stalemate(board, move)
        ]

    def _resolve_kh_adoption(
        self, board: chess.Board
    ) -> ConstructionPlan | None:
        """Re-pose the remembered corner adoption if it still resolves."""
        if self._kh_adoption is None:
            return None
        pawn_file, checked_side = self._kh_adoption
        plan = ConstructionPlan(
            pawn_file=pawn_file,
            checked_side=checked_side,
            created_ply=len(board.move_stack),
            holder_mode="king",
        )
        if plan.resolve(board, board.turn) is None:
            return None
        return plan

    def _consider_kh_adoption(self, board: chess.Board) -> bool:
        """Replace a certified-negative piece plan with a corner adoption.

        The release theorem prices every completed piece-holder construction
        at zero, and its mirror is the same theorem reflected — so when a
        side certifies unconvertible (or hopeless) and the gated flip has
        declined, the remaining move is a plan REPLACEMENT: commit to the
        corner king-holder template of some walkable b/g-file pawn and start
        the freeze-release choreography. Feasibility here is the template
        emission itself (corner geometry, knight closer, cage-shade bishop,
        walkable path); the conversion audit re-arbitrates once the pawn
        arrives and the construction poses. Walking templates rank by the
        same setup metric, so a pawn already at its pre-corner square is
        preferred over any walk.
        """
        if self.plan is None or self.plan.holder_mode == "king":
            return False
        us = board.turn
        candidates = [
            target
            for target in pawn_mate_templates(board, us)
            if target.king_holder
        ]
        if not candidates:
            return False
        best = min(
            candidates,
            key=lambda target: (
                target.setup_distance,
                target.pawn_square,
                target.checked_square,
            ),
        )
        self.plan = ConstructionPlan.from_template(
            best, len(board.move_stack)
        )
        self._kh_adoption = (self.plan.pawn_file, self.plan.checked_side)
        self.plans_created += 1
        self.vi_kh_adoptions += 1
        self._reset_vi_state()
        return True

    def choose_move(self, board: chess.Board) -> chess.Move:
        ply = len(board.move_stack)
        if self._last_seen_ply is not None and ply < self._last_seen_ply:
            self.plan = None
            self.best_plan_distance = None
            # A rewind is a game boundary, and the arena reuses bot
            # instances across games. Adoption memory is scoped to the
            # game whose audited verdicts earned it: without this, game
            # N+1 would re-commit game N's corner without ever certifying
            # a side (review P1). In-game plan resets keep it — that is
            # its purpose (promotions mid-walk).
            self._kh_adoption = None
            self._reset_vi_state()
        self._last_seen_ply = ply
        # No repetition tally lives here anymore: _vi_choice recounts the
        # game's reversible era from the board itself each move, which sees
        # the positions Zach's replies created — the ones a tally of our
        # own choices structurally missed — and resets with the era.
        return self._choose(board)

    def _filter_refused_resets(
        self, moves: list[chess.Move]
    ) -> list[chess.Move]:
        """Keep uncertified reset pushes away from the heuristic
        fallbacks.

        The clock-reset scan is the only sanctioned pusher while a herd
        is clock-flagged: an uncertified push would otherwise reach the
        fallbacks with the veto evidence discarded, and the clock-urgent
        nudge rewards exactly that push (review P1 — piece mode has no
        blanket pawn veto). The set is armed with the clock flags,
        holds every quiet push the current decision did not certify —
        refused, unjudged, and unscanned alike — and is cleared at the
        next VI decision, so a veto never outlives the root it was
        audited against. Only the exact selfmate probe is exempt
        upstream: it returns PROVEN mating lines, and a proven mate that
        spends the push is a win, not a leak (the herd search proves
        mere forced progress, so it draws from the filtered menu). If
        the vetoes would empty the list, the unfiltered moves stand —
        never zero the move menu.
        """
        if not self._vi_reset_refused:
            return moves
        kept = [
            move for move in moves
            if move not in self._vi_reset_refused
        ]
        if kept and len(kept) < len(moves):
            self.vi_clock_reset_vetoes += len(moves) - len(kept)
            return kept
        return moves

    def _plan_filtered_moves(
        self,
        board: chess.Board,
        moves: list[chess.Move],
        planned_now: PawnMateTemplate | None,
    ) -> tuple[list[chess.Move], list[chess.Move]]:
        """The plan-commitment filter chain, in waterfall order.

        Returns ``(safe, safe_for_vi)``. VI keeps the pre-repetition list:
        a herding policy's waiting moves are legitimate second visits, and
        only threefold actually draws — _vi_choice prices threefold exactly
        by burning twice-seen states into the solved values instead of
        vetoing moves up front.
        """
        safe = moves
        if (
            planned_now is not None
            and planned_now.hold_established
            and not planned_now.ready_to_release
        ):
            # Piece mode holds the blocker; king mode holds the king itself.
            # For a king holder the vacate never comes from lifting this
            # filter — _vi_choice's release scoring bypasses it by design.
            held = planned_now.arrival_square
            keep_holding = [m for m in safe if m.from_square != held]
            if keep_holding:
                self.hold_moves_filtered += len(safe) - len(keep_holding)
                safe = keep_holding
        safe = self._filter_plan_regressions(board, safe, planned_now)
        safe_for_vi = safe
        safe = self._filter_plan_repetitions(board, safe)
        safe = self._filter_wait_funnels(board, safe, planned_now)
        safe = self._filter_forced_captures(board, safe, planned_now)
        safe = self._filter_walk_clear(board, safe, planned_now)
        safe = self._filter_king_march(board, safe, planned_now)
        safe = self._filter_cage_build(board, safe, planned_now)
        safe = self._filter_closer_park(board, safe, planned_now)
        safe = self._filter_forced_herding(board, safe, planned_now)
        return safe, safe_for_vi

    def _choose(self, board: chess.Board) -> chess.Move:
        legal = list(board.legal_moves)
        if len(legal) == 1:
            return legal[0]

        # Never mate or stalemate the opponent when we have any alternative.
        safe = [m for m in legal if not gives_mate(board, m)]
        non_stale = [m for m in safe if not gives_stalemate(board, m)]
        safe = non_stale or safe or legal

        # Exact probe, deeper as the opponent runs out of mobile pieces.
        them = not board.turn
        their_pieces = sum(
            1
            for p in board.piece_map().values()
            if p.color == them and p.piece_type not in (chess.PAWN, chess.KING)
        )
        self._update_construction_plan(board, their_pieces)
        planned_now = self.planned_target(board, board.turn)
        base_safe = safe
        safe, safe_for_vi = self._plan_filtered_moves(
            board, base_safe, planned_now
        )
        if board.is_check():
            their_mobility = 99
        else:
            board.push(chess.Move.null())
            their_mobility = board.legal_moves.count()
            board.pop()

        # Budgets are per-move worst cases; deep probes proved to be wasted
        # effort when no net exists, so keep them tight (~1-2s at PyPy speed).
        max_n, cap = probe_limits(
            self.profile, their_pieces, their_mobility
        )
        if self.probe_cap is not None:
            cap = min(cap, self.probe_cap)
        if self.max_probe_n is not None:
            max_n = min(max_n, self.max_probe_n)
        gate_distance = self.profile.deep_probe_template_distance
        if max_n > 1 and gate_distance is not None:
            target = (
                planned_now
                if self.profile.stateful_plan
                else best_pawn_mate_template(board, board.turn)
            )
            # The profile's minimum cage is a piece-holder reserve size; a
            # finished corner cage is exactly one bishop. Gating king-holder
            # targets on the profile knob would blind the exact probe — the
            # only machinery that finds organic multi-move forced selfmates
            # — for the whole lifetime of a king-holder plan.
            min_cage = (
                target.required_cage
                if target is not None and target.king_holder
                else self.profile.deep_probe_min_cage
            )
            if (
                target is None
                or target.setup_distance > gate_distance
                or target.cage_occupancy < min_cage
                or target.arrival_blocked
            ):
                max_n = 1
                self.deep_probe_skips += 1

        budget = [cap]
        memo: dict = {}
        for n in range(1, max_n + 1):
            before = budget[0]
            status, mv = selfmate_status(
                board, n, self.opponent_model, budget, memo
            )
            self.probe_nodes += before - budget[0]
            if status is ProofStatus.PROVEN:
                self.forced_selfmates_found += 1
                return mv
            if status is ProofStatus.UNKNOWN:
                self.probe_budget_exhaustions += 1
                break
            self.deepest_probe_completed = max(self.deepest_probe_completed, n)

        if self.plan is not None and self.profile.vi_herding:
            plan_before = self.plan
            vi_move = self._vi_choice(board, planned_now, safe_for_vi)
            if vi_move is not None:
                self.vi_moves_played += 1
                return vi_move
            if self.plan is not plan_before:
                # A side flip or a corner adoption replaced the plan
                # mid-choice. Refilter the fallback candidates under the
                # NEW plan: the transition ply must already obey the new
                # mode's commitments, or it can leak a move the mode
                # forbids — the ply-zero c4-c5 push that walled off the
                # adopted pocket's own rank-six gate.
                planned_now = self.planned_target(board, board.turn)
                safe, _ = self._plan_filtered_moves(
                    board, base_safe, planned_now
                )
            safe = self._filter_refused_resets(safe)

        if (
            self.plan is not None
            and self.profile.herd_search_depth > 0
            and self.profile.herd_search_cap > 0
        ):
            # Ranks BELOW the solved sub-MDP and its clock machinery:
            # PROVEN here means forced defender progress, not a proven
            # win, so it must not preempt the reset/flip/adoption
            # cascade — and it draws from the reset-filtered menu, so it
            # cannot spend a pawn push the scan did not certify (review
            # P1: the old pre-VI placement could replay a refused push
            # on the strength of a mere herding proof).
            herd = herding_move(
                board,
                self.plan,
                board.turn,
                self.profile.herd_search_depth,
                self.opponent_model,
                self.profile.herd_search_cap,
                moves=safe,
            )
            self.herd_search_nodes += herd.nodes
            if herd.status is ProofStatus.PROVEN and herd.move is not None:
                self.herd_search_hits += 1
                return herd.move
            if herd.status is ProofStatus.UNKNOWN:
                self.herd_search_exhaustions += 1

        if (
            self.plan is not None
            and self.profile.modeled_herding_depth > 0
            and self.profile.modeled_herding_cap > 0
        ):
            modeled = modeled_herding_move(
                board,
                self.plan,
                board.turn,
                safe,
                self.opponent_model,
                self.profile.modeled_herding_depth,
                self.profile.modeled_herding_cap,
                self.profile.modeled_herding_time_ms,
                self.profile.modeled_herding_candidate_limit,
                self.profile.modeled_herding_memoize,
            )
            self.modeled_herding_replies += modeled.replies
            self.modeled_herding_nodes += modeled.nodes
            self.modeled_herding_cache_hits += modeled.cache_hits
            self.modeled_herding_memo_entries += modeled.memo_entries
            self.modeled_herding_candidates_pruned += (
                modeled.candidates_pruned
            )
            if not modeled.complete:
                self.modeled_herding_incomplete += 1
            if modeled.move is not None:
                self.modeled_herding_hits += 1
                return modeled.move

        # Heuristic misère search over the safe moves; look deeper once the
        # squeeze is on and precision starts to matter.
        depth = self.depth + (
            1 if their_mobility <= self.profile.squeeze_mobility else 0
        )
        if (
            self.profile.small_endgame_max_men is not None
            and len(board.piece_map()) <= self.profile.small_endgame_max_men
        ):
            depth += 1  # tiny endgames are where domination valleys live
        root_color = board.turn
        clock_urgent = board.halfmove_clock >= self.profile.clock_urgent_at
        best_move, best_value = safe[0], -float("inf")
        alpha, beta = -float("inf"), float("inf")
        for m in safe:
            # Root nudges against the two draw engines: repeating positions
            # and letting the 50-move clock run dry.
            bonus = 0.0
            board.push(m)
            if board.is_repetition(2):
                bonus -= self.profile.repetition_penalty
            board.pop()
            if clock_urgent and (
                board.is_capture(m)
                or board.piece_type_at(m.from_square) == chess.PAWN
            ):
                bonus += self.profile.irreversible_move_bonus
            board.push(m)
            v = bonus - negamax(board, depth - 1, -beta, -alpha, root_color, 1,
                                self.opponent_model, self.profile, self.plan)
            board.pop()
            if v > best_value:
                best_value, best_move = v, m
            if v > alpha:
                alpha = v
        return best_move

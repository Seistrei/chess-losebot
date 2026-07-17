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
)


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
            if replacement is None:
                if self.plan is not None:
                    self.plan_invalidations += 1
                    self.plan = None
                    self._reset_vi_state()
                return
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
        stable: list[chess.Move] = []
        for move in moves:
            board.push(move)
            future = self.planned_target(board, us)
            board.pop()
            if future is None:
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
                and future.our_king_steps == 0
                and current.our_king_steps > 0
                and future.cage_occupancy < future.required_cage
            ):
                # The king takes the arrival square LAST. Post-park play is
                # all reversible, so parking before the cage exists burns
                # fifty-move clock the herd and the race will need.
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
            if current.cage_occupancy < current.required_cage:
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
        if target is None:
            return None
        if target.king_holder:
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

        # The exact probe already refused a guaranteed net this move. With
        # the defender adjacent (or one step out), offer the best scored race
        # instead of tempoing forever. This deliberately bypasses the hold
        # filter: a scored release is the point of having held at all.
        if target.defender_steps <= 1:
            choice = score_release_moves(
                board, target, self.opponent_model,
                self.profile.vi_race_max_losing,
            )
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
            policy, hopeless = self._certify_herding(board, target, limit)
            self._vi_policy = policy
            self.vi_burned_states = 0  # fresh builds carry no burns yet
            if hopeless:
                # Every maximal herder subset of this frozen configuration
                # is certified dead: the side is hopeless as built, so the
                # only remaining question is the mirrored checked square.
                self._consider_side_flip(board, limit)
                return None
        if policy is None or not policy.report.ok:
            return None
        if not policy.report.root_live:
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
        if not report.ok:
            self.vi_build_failures += 1
            self.vi_last_failure = report.reason

    def _certify_herding(
        self,
        board: chess.Board,
        target: PawnMateTemplate,
        limit: int,
    ) -> tuple[HerdingPolicy | None, bool]:
        """Find a live herder subset, or certify the side hopeless.

        Deadness is a property of one frozen configuration AND one herder
        subset, so a single dead build never condemns the side. Walk the
        maximal subsets (greedy preference first — the common live case
        still costs one build): the first live certificate wins, and a
        completed walk yielding nothing but dead certificates is the only
        outcome that returns hopeless=True. Anything unresolved — sweep
        budget exhausted, a subset too big to explore, a truncated
        enumeration — blocks the hopeless verdict instead of quietly
        counting toward it.
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
            return policy, False

        # Subsets already certified dead at this exact position (herders may
        # have wandered since certification; contains() covers that).
        dead_squares = set()
        for dead in self._vi_dead_policies:
            squares = dead.dynamic_squares(board)
            if squares is not None:
                dead_squares.add(squares)

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
                    return policy, False
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
            # terminal, pool mismatch, ...): no subset choice can fix it.
            return policy, False
        return None, complete

    def _consider_side_flip(self, board: chess.Board, limit: int) -> None:
        """On a hopeless side, probe the mirrored checked square.

        Only a completed build may speak: a live prospect re-commits the
        plan to the mirror, a genuine dead certificate backs off for a while
        (the construction shifts and may reopen it), and anything transient
        — unposable hypothetical, refused or timed-out build — is unknown,
        never dead. The old code marked the mirror dead on every non-live
        outcome, so one slow or unlucky build could kill both flanks for
        the rest of the game.
        """
        ply = len(board.move_stack)
        if self.plan is None or ply < self._vi_next_flip_ply:
            return
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
            self.vi_flip_value = prospect.report.root_value
            if prospect.report.root_live:
                self.plan = mirrored
                self.vi_side_flips += 1
                self._reset_vi_state()
                return
            self._vi_next_flip_ply = ply + 16
            return
        self.vi_flip_value = None
        self._vi_next_flip_ply = ply + 8

    def choose_move(self, board: chess.Board) -> chess.Move:
        ply = len(board.move_stack)
        if self._last_seen_ply is not None and ply < self._last_seen_ply:
            self.plan = None
            self.best_plan_distance = None
            self._reset_vi_state()
        self._last_seen_ply = ply
        # No repetition tally lives here anymore: _vi_choice recounts the
        # game's reversible era from the board itself each move, which sees
        # the positions Zach's replies created — the ones a tally of our
        # own choices structurally missed — and resets with the era.
        return self._choose(board)

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
        # VI keeps the pre-repetition list: a herding policy's waiting moves
        # are legitimate second visits, and only threefold actually draws.
        # _vi_choice prices threefold exactly by burning twice-seen states
        # into the solved values instead of vetoing moves up front.
        safe_for_vi = safe
        safe = self._filter_plan_repetitions(board, safe)
        safe = self._filter_forced_captures(board, safe, planned_now)
        safe = self._filter_king_march(board, safe, planned_now)
        safe = self._filter_cage_build(board, safe, planned_now)
        safe = self._filter_forced_herding(board, safe, planned_now)
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

        if (
            self.plan is not None
            and self.profile.herd_search_depth > 0
            and self.profile.herd_search_cap > 0
        ):
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

        if self.plan is not None and self.profile.vi_herding:
            vi_move = self._vi_choice(board, planned_now, safe_for_vi)
            if vi_move is not None:
                self.vi_moves_played += 1
                return vi_move

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

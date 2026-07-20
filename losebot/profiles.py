"""Versioned LoseBot configurations.

Keeping tuning parameters in named, immutable profiles makes benchmark results
reproducible and prevents a promising configuration from being overwritten by
the next experiment.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class EngineProfile:
    name: str

    # Evaluation weights.
    our_man_value: float
    their_piece_scale: float
    pawn_base: float
    pawn_value: float
    pawn_cap: int
    king_and_pawns_bonus: float
    bare_king_penalty: float
    frozen_pawns_penalty: float
    menu_limit: int
    nonmating_move_penalty: float
    king_move_weight: float
    mating_move_bonus: float
    mating_move_cap: int
    zugzwang_bonus: float | None
    large_menu_penalty: float
    check_bonus: float
    check_escape_bonus: float
    king_target_distance_penalty: float
    own_king_neighbor_bonus: float
    herding_distance_penalty: float
    herding_adjacency_bonus: float
    template_distance_penalty: float
    template_cage_bonus: float
    no_template_penalty: float
    template_runway_penalty: float
    clock_pressure: float
    draw_contempt: float

    # Root/search behavior.
    squeeze_mobility: int
    small_endgame_max_men: int | None
    repetition_penalty: float
    clock_urgent_at: int
    irreversible_move_bonus: float
    deep_probe_template_distance: int | None
    deep_probe_min_cage: int
    stateful_plan: bool
    herding_open_escape_penalty: float
    herding_control_bonus: float
    plan_hold_bonus: float
    plan_unfrozen_penalty: float
    plan_release_block_penalty: float
    plan_undefended_hold_penalty: float
    herd_search_depth: int
    herd_search_cap: int
    modeled_herding_depth: int
    modeled_herding_cap: int
    modeled_herding_time_ms: int
    modeled_herding_candidate_limit: int | None
    modeled_herding_memoize: bool

    # Value-iteration herding (defaulted so the older literal profiles above
    # stay byte-for-byte reproducible without spelling these out).
    vi_herding: bool = False
    vi_max_herders: int = 2
    vi_state_cap: int = 200_000
    vi_build_ms: int = 20_000
    # The herd phase makes no irreversible moves, so the fifty-move rule
    # caps it at 100 plies: discount hard enough that the policy values
    # short routes, not eventual ones.
    vi_gamma: float = 0.96
    vi_race_max_losing: int = 1
    # Per-build cap on the conversion audit (release-probing the reachable
    # goal terminals) so it can never starve exploration or the solver.
    vi_conversion_ms: int = 3_000
    # Clock feasibility from the solved sub-MDP. The herd's era is capped
    # at 100 quiet plies by the fifty-move rule; the hitting stats are
    # finish-inclusive in two tiers (per-terminal tails live in
    # herding_vi — structural facts, not tunables): min_hit seeds the
    # cheapest-conceivable floor and only ever REJECTS (the hard gate
    # min_hit > remaining is a certificate that the era cannot finish),
    # while fit_hit and exp_hit seed the audit-PROVEN completion tails
    # and are what may AFFIRM a finish. The soft gate exp_hit *
    # soft_factor > remaining is advisory headroom for hitting-time
    # variance. relax_at is the remaining-ply threshold at which a
    # refused strict release retries with unlimited losing replies —
    # near the cliff any race with a winning reply beats the fifty-move
    # zero.
    vi_clock_soft_factor: float = 1.5
    vi_clock_relax_at: int = 20
    # King-holder construction pulls: route the cage-colored bishop toward
    # the corner square and keep a knight-class closer in seal range.
    # Defaulted to zero so the pre-king-holder profiles stay byte-for-byte
    # reproducible.
    kh_bishop_pull: float = 0.0
    kh_knight_pull: float = 0.0
    # Walk-phase defender pressure: while a king-holder adoption waits out
    # the Zach-paced pawn walk, nothing else herds their king (the sub-MDP
    # cannot exist before the geometry poses, and the piece-mode herding
    # fallbacks never engage a king-holder template), so wait moves are
    # chosen by expected funnel potential over his modeled pool instead of
    # the plain negamax — whose menu-shrinking eval happily seals him into
    # a two-square prison anywhere on the board, a certified-dead arrival.
    # Off by default: profiles predating the walk stay reproducible.
    walk_pressure: bool = False
    # Executioner selection at strip time (2026-07-19): their b/g pawns
    # are corner material, a same-file rear behind one is audited renewal
    # equity (the doubled-stack vacate race lifts 1/2 -> 3/4), and our own
    # pawn below a walkable their-pawn is the emission veto in waiting.
    # Applied only while their_pieces > 0 — the strip is where capture
    # choices happen; endgame pawn preferences belong to the plan
    # machinery, so every king+pawns reference is untouched by
    # construction. Zero-defaulted for byte-identical older profiles.
    exec_file_bonus: float = 0.0
    exec_stack_bonus: float = 0.0
    exec_blocked_penalty: float = 0.0


CURRENT = EngineProfile(
    name="current",
    our_man_value=25,
    their_piece_scale=0.90,
    pawn_base=55,
    pawn_value=25,
    pawn_cap=3,
    king_and_pawns_bonus=150,
    bare_king_penalty=6000,
    frozen_pawns_penalty=3000,
    menu_limit=10,
    nonmating_move_penalty=14,
    king_move_weight=1.6,
    mating_move_bonus=90,
    mating_move_cap=2,
    zugzwang_bonus=900,
    large_menu_penalty=12,
    check_bonus=40,
    check_escape_bonus=6,
    king_target_distance_penalty=9,
    own_king_neighbor_bonus=6,
    herding_distance_penalty=8,
    herding_adjacency_bonus=120,
    template_distance_penalty=0,
    template_cage_bonus=0,
    no_template_penalty=0,
    template_runway_penalty=0,
    clock_pressure=1.5,
    draw_contempt=400,
    squeeze_mobility=8,
    small_endgame_max_men=9,
    repetition_penalty=80,
    clock_urgent_at=60,
    irreversible_move_bonus=40,
    deep_probe_template_distance=None,
    deep_probe_min_cage=0,
    stateful_plan=False,
    herding_open_escape_penalty=0,
    herding_control_bonus=0,
    plan_hold_bonus=0,
    plan_unfrozen_penalty=0,
    plan_release_block_penalty=0,
    plan_undefended_hold_penalty=0,
    herd_search_depth=0,
    herd_search_cap=0,
    modeled_herding_depth=0,
    modeled_herding_cap=0,
    modeled_herding_time_ms=0,
    modeled_herding_candidate_limit=None,
    modeled_herding_memoize=False,
    # Ordering, not precision: a stack rear outranks a bare executioner
    # outranks a generic pawn, and everything stays far below the piece
    # values so the strip itself is never distorted.
    exec_file_bonus=40,
    exec_stack_bonus=60,
    exec_blocked_penalty=30,
)


# Reconstructed from TUNING-LOG.md. This is intentionally a separate profile,
# not a partial override, so changing CURRENT cannot silently change v0.3.
V03 = EngineProfile(
    name="v03",
    our_man_value=25,
    their_piece_scale=0.90,
    pawn_base=0,
    pawn_value=30,
    pawn_cap=3,
    king_and_pawns_bonus=150,
    bare_king_penalty=6000,
    frozen_pawns_penalty=3000,
    menu_limit=8,
    nonmating_move_penalty=14,
    king_move_weight=1.0,
    mating_move_bonus=90,
    mating_move_cap=2,
    zugzwang_bonus=None,
    large_menu_penalty=12,
    check_bonus=40,
    check_escape_bonus=6,
    king_target_distance_penalty=9,
    own_king_neighbor_bonus=6,
    herding_distance_penalty=0,
    herding_adjacency_bonus=0,
    template_distance_penalty=0,
    template_cage_bonus=0,
    no_template_penalty=0,
    template_runway_penalty=0,
    clock_pressure=1.5,
    draw_contempt=400,
    squeeze_mobility=8,
    small_endgame_max_men=None,
    repetition_penalty=0,
    clock_urgent_at=101,
    irreversible_move_bonus=0,
    deep_probe_template_distance=None,
    deep_probe_min_cage=0,
    stateful_plan=False,
    herding_open_escape_penalty=0,
    herding_control_bonus=0,
    plan_hold_bonus=0,
    plan_unfrozen_penalty=0,
    plan_release_block_penalty=0,
    plan_undefended_hold_penalty=0,
    herd_search_depth=0,
    herd_search_cap=0,
    modeled_herding_depth=0,
    modeled_herding_cap=0,
    modeled_herding_time_ms=0,
    modeled_herding_candidate_limit=None,
    modeled_herding_memoize=False,
)


TEMPLATE = replace(
    CURRENT,
    name="template",
    # Replace the two independent king gradients with one coupled target.
    king_target_distance_penalty=0,
    herding_distance_penalty=0,
    herding_adjacency_bonus=0,
    template_distance_penalty=18,
    template_cage_bonus=8,
    no_template_penalty=3000,
    template_runway_penalty=0,
    deep_probe_template_distance=2,
    deep_probe_min_cage=3,
)


PLANNER = replace(
    TEMPLATE,
    name="planner",
    stateful_plan=True,
    template_distance_penalty=36,
    template_cage_bonus=20,
    template_runway_penalty=220,
    herding_open_escape_penalty=24,
    herding_control_bonus=5,
    plan_hold_bonus=180,
    plan_unfrozen_penalty=120,
    plan_release_block_penalty=400,
    plan_undefended_hold_penalty=300,
    herd_search_depth=2,
    herd_search_cap=10_000,
    modeled_herding_depth=1,
    modeled_herding_cap=1_000,
    modeled_herding_time_ms=250,
    kh_bishop_pull=6.0,
    kh_knight_pull=4.0,
)


HERDING = replace(
    PLANNER,
    name="herding",
    # The first depth-two attempt expanded every legal continuation. This
    # profile retains all forcing checks, beams quiet setup moves, and caches
    # only complete expectimax values under draw-history-safe keys.
    modeled_herding_depth=2,
    modeled_herding_cap=5_000,
    modeled_herding_time_ms=250,
    modeled_herding_candidate_limit=8,
    modeled_herding_memoize=True,
)


VI = replace(
    PLANNER,
    name="vi",
    # Herding is a Markov decision process against the fixed Zach kernel, not
    # an adversarial search: solve the frozen-cage sub-MDP exactly and follow
    # its optimal policy. V(root) == 0 is a certificate that the current
    # static configuration can never walk their king into the goal zone.
    vi_herding=True,
    walk_pressure=True,
)


PROFILES = {
    profile.name: profile
    for profile in (CURRENT, HERDING, PLANNER, TEMPLATE, V03, VI)
}


def get_profile(name: str) -> EngineProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown profile {name!r}; choose one of: {choices}") from exc


def probe_limits(profile: EngineProfile, their_pieces: int,
                 their_mobility: int) -> tuple[int, int]:
    """Return (maximum own moves, node budget) for the exact probe."""
    if profile.name == "v03":
        if their_pieces == 0 and their_mobility <= 10:
            return 4, 300_000
        if their_pieces == 0:
            return 3, 120_000
        if their_pieces <= 1:
            return 2, 60_000
        return 1, 25_000

    if their_pieces == 0 and their_mobility <= 4:
        return 7, 500_000
    if their_pieces == 0 and their_mobility <= 8:
        return 5, 250_000
    if their_pieces == 0:
        return 4, 150_000
    if their_pieces <= 1 and their_mobility <= 12:
        return 3, 120_000
    if their_pieces <= 1:
        return 2, 60_000
    return 1, 25_000

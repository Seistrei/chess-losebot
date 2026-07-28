"""LoseBot on lichess: the homemade-engine bridge for lichess-bot.

lichess-bot creates one engine object per game (`create_engine`) and calls
`search()` once per move with the game board — full move stack included —
plus the clock. The default driver is the MODEL ENGINE (losebot.ModelEngine,
2.0.0a14 defaults): oracle probe first, expectimax steering against an
inferred opponent belief second, misère-safe partition always. Neither
layer is clock-aware, so the bridge owns a small time governor: as the
clock shrinks it clamps the spike knobs (probe caps, sub-probe cap, search
node cap, depth). Budgets cap worst-case spikes; there is no per-move time
target.

BELIEF: the engine starts from the FITTED-HUMAN point prior — the offline
MLE over the first-party live-game corpus (lichess/game_records/, the
eight Iptychs games; models/posterior.py FITTED_HUMAN) — and infers from
there (``infer=map``): a Bayesian posterior over the dev hypothesis set,
updated from the opponent's observed moves in THIS game, steers via its
MAP hypothesis. Fitted-human is dev-side-legal by provenance (fitted from
our own corpus, no held-out preset in its derivation), and the posterior's
prior check enforces the same boundary the CLI does: a held-out belief
cannot anchor inference. Everything else runs the shipped a14 DEFAULTS
(plan_steer 0, eval knobs 0), so the corpus this bridge collects reflects
the engine the league actually pins.

Engine selection is config.yml (`engine.name: "LoseBotEngine"`). Tuning is
environment variables, so experimenting never needs an image rebuild:

  LOSEBOT_BELIEF   inference anchor / fixed belief (default
                   "fitted-human"; any dev preset name also works —
                   zach/sloppy/squat). A held-out name is only legal
                   with LOSEBOT_INFER=off, exactly the CLI's boundary
                   rule. A bad value logs an ERROR and falls back to
                   the default rather than wedging the game.
  LOSEBOT_INFER    off / map / mix (default "map").

  LOSEBOT_PROFILE  } setting ANY of these selects the LEGACY SPECIALIST
  LOSEBOT_MODEL    } bridge (specialists.LoseBot) with its old governor —
  LOSEBOT_DEPTH    } one env line (e.g. LOSEBOT_PROFILE=field) restores
                   the pre-swap driver exactly: profile default "field",
                   model default "zach", depth default 2. The 2026-07-20
                   field notes document those choices.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace

import chess
from chess.engine import PlayResult

from lib.engine_wrapper import MinimalEngine

from losebot.engine import ModelEngine
from losebot.models import make_model
from losebot.models.posterior import FITTED_HUMAN, prior_for_belief
from losebot.models.urges import UrgeModel
from losebot.outcomes import adjudicate_draw

logger = logging.getLogger(__name__)


class ExampleEngine(MinimalEngine):
    """Upstream's example base class. This file replaces lichess-bot's
    homemade.py, but its test_bot/homemade.py still imports ExampleEngine
    from here (get_homemade_engine imports test_bot unconditionally)."""


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def _remaining_seconds(
    board: chess.Board, limit
) -> tuple[float | None, float, bool]:
    """(our clock, increment, is-per-move) in seconds; clock None when
    uncapped. Correspondence and the smoke test pass a fixed per-MOVE
    budget through limit.time — a different affordability question than
    a remaining game clock, so the flag rides along."""
    fixed = getattr(limit, "time", None)
    if fixed is not None:
        return float(fixed), 0.0, True
    if board.turn == chess.WHITE:
        clock, inc = limit.white_clock, limit.white_inc
    else:
        clock, inc = limit.black_clock, limit.black_inc
    return (
        float(clock) if clock is not None else None,
        float(inc) if inc is not None else 0.0,
        False,
    )


def _emergency_move(board: chess.Board) -> chess.Move:
    """Last-resort move on engine failure, misère-safe by the model
    engine's own partition: prefer moves that neither end the game
    against us on the spot (mating or stalemating THEM) nor hand the
    draw rules the game (adjudication, baring their king); failing
    that, at least never mate or stalemate; failing that, anything."""
    legal = list(board.legal_moves)
    them = not board.turn
    fallback = None
    for move in legal:
        board.push(move)
        mate_or_stale = board.is_checkmate() or board.is_stalemate()
        accident = (
            mate_or_stale
            or adjudicate_draw(board) is not None
            or chess.popcount(board.occupied_co[them]) == 1
        )
        board.pop()
        if not accident:
            return move
        if not mate_or_stale and fallback is None:
            fallback = move
    return fallback if fallback is not None else legal[0]


# --------------------------------------------------------------------------
# Model driver: ModelEngine at a14 defaults, fitted-human prior, infer=map.

_DEFAULT_BELIEF = "fitted-human"


def _make_belief(name: str):
    """Resolve a belief name: the corpus-fitted human point, or any
    preset make_model knows. presets.py stays frozen — fitted-human
    lives in posterior.py and is instantiated here, not added there."""
    if name == _DEFAULT_BELIEF:
        return UrgeModel(_DEFAULT_BELIEF, FITTED_HUMAN)
    return make_model(name)


class _ModelDriver:
    """One ModelEngine per game, with the clock governor.

    Governor tiers by budget = clock + 2x increment (the bridge's
    standing pattern), clamping the spike knobs with min() against the
    engine's constructed values. Tier numbers are measurement-backed
    (2026-07-28, protocol-family games at the bridge config, PyPy
    in-image): full config worst case 6.5 s/move (zach g0; sloppy 2.7,
    squat 3.6; means 1.0-1.7), ~98-130k nodes/s — the worst move is
    the all-caps-bound one (probe 50k + sub 75k + node cap 400k), so
    each tier's worst case scales with its cap sum: mid 2.5s measured,
    low 0.4s, emergency 0.05s. TUNING-LOG 2026-07-28 has the full
    table (instruments in games/league/dev-bridge/).
    """

    #: (name, floor of the remaining-clock budget band, knob clamps).
    #: Full config whenever the budget affords its worst case; the
    #: probe_cap rungs mirror the a14 lesson that certificates are the
    #: first thing low clocks pay for (the record's dearest find costs
    #: 49,559 of the 50k cap).
    TIERS = (
        ("full", 180.0, {}),
        ("mid", 60.0, dict(
            probe_n=4, probe_cap=25_000, sub_probe_cap=30_000,
            sub_probe_slice=6_000, node_cap=150_000, depth=3,
        )),
        ("low", 20.0, dict(
            probe_n=3, probe_cap=10_000, sub_probe_cap=10_000,
            sub_probe_slice=4_000, node_cap=60_000, depth=2,
        )),
        ("emergency", 0.0, dict(
            probe_n=1, probe_cap=4_000, sub_probe_cap=0,
            sub_probe_slice=4_000, node_cap=15_000, depth=1,
        )),
    )

    #: A fixed per-MOVE budget (correspondence: 60s/move) affords the
    #: full config once it clears the measured full-tier worst case
    #: with margin; below that it maps through the same clamp table.
    FIXED_TIME_FULL = 30.0

    def __init__(self) -> None:
        belief_name = _env("LOSEBOT_BELIEF", _DEFAULT_BELIEF)
        infer = _env("LOSEBOT_INFER", "map")
        try:
            belief = _make_belief(belief_name)
            if infer not in ("off", "map", "mix"):
                raise ValueError(
                    f"LOSEBOT_INFER must be off/map/mix, got {infer!r}"
                )
            if infer != "off":
                # The CLI's held-out boundary check, verbatim in spirit:
                # inference may only anchor on a dev hypothesis point.
                prior_for_belief(belief)
            self.engine = ModelEngine(belief=belief, infer=infer)
        except (KeyError, ValueError):
            logger.exception(
                "Bad LOSEBOT_BELIEF/LOSEBOT_INFER (%r / %r); "
                "falling back to %s + map",
                belief_name, infer, _DEFAULT_BELIEF,
            )
            self.engine = ModelEngine(
                belief=_make_belief(_DEFAULT_BELIEF), infer="map"
            )
        engine = self.engine
        self._base = {
            "depth": engine.depth,
            "probe_n": engine.probe_n,
            "probe_cap": engine.probe_cap,
            "sub_probe_cap": engine.sub_probe_cap,
            "sub_probe_slice": engine.sub_probe_slice,
            "node_cap": engine.node_cap,
        }
        self._tier = "full"
        self._proven_before = 0
        logger.info(
            "ModelEngine ready: %s (belief=%s, a14 defaults: probe %d@%d, "
            "sub %d, depth %d, node cap %d; plan_steer 0, eval knobs 0)",
            engine.name, engine.belief.name, engine.probe_n,
            engine.probe_cap, engine.sub_probe_cap, engine.depth,
            engine.node_cap,
        )

    def govern(self, board: chess.Board, limit) -> None:
        remaining, inc, fixed = _remaining_seconds(board, limit)
        budget = None if remaining is None else remaining + 2.0 * inc
        if budget is None or (fixed and budget >= self.FIXED_TIME_FULL):
            tier_name, clamps = "full", {}
        else:
            tier_name, clamps = next(
                (
                    (name, knobs)
                    for name, floor, knobs in self.TIERS
                    if budget >= floor
                ),
                (self.TIERS[-1][0], self.TIERS[-1][2]),
            )
        engine, base = self.engine, self._base
        for knob in ("depth", "probe_n", "probe_cap", "sub_probe_cap",
                     "sub_probe_slice"):
            setattr(engine, knob, min(base[knob], clamps.get(knob, base[knob])))
        # node_cap 0 means UNcapped, so min() would read it backwards.
        tier_node_cap = clamps.get("node_cap", base["node_cap"])
        engine.node_cap = (
            tier_node_cap if base["node_cap"] == 0
            else min(base["node_cap"], tier_node_cap)
        )
        if tier_name != self._tier:
            logger.info(
                "Governor tier %s (budget %s): probe %d@%d, sub %d, "
                "depth %d, node cap %d",
                tier_name,
                "uncapped" if budget is None else f"{budget:.0f}s",
                engine.probe_n, engine.probe_cap, engine.sub_probe_cap,
                engine.depth, engine.node_cap,
            )
            self._tier = tier_name

    def choose(self, board: chess.Board) -> chess.Move:
        self._proven_before = self.engine.forced_selfmates_found
        return self.engine.choose_move(board)

    def log_move(self, board: chess.Board, move: chess.Move,
                 elapsed: float) -> None:
        engine = self.engine
        if engine.forced_selfmates_found > self._proven_before:
            logger.info("Forced selfmate net PROVEN — the loss is ours.")
        belief = ""
        if engine.posterior is not None:
            diag = engine.posterior.diagnostics()
            belief = (
                f"; belief {diag['posterior_map']}"
                f"@{diag['posterior_map_weight']:.2f}"
            )
        logger.info(
            "LoseBot played %s in %.1fs (probe %d, search %d, sub %d%s)",
            board.san(move), elapsed, engine.probe_nodes,
            engine.search_nodes, engine.sub_probe_nodes, belief,
        )


# --------------------------------------------------------------------------
# Legacy specialist driver: the pre-swap bridge, selected by its old env
# knobs. Kept byte-for-byte in behavior (2026-07-20 field-notes config).

class _SpecialistDriver:
    def __init__(self) -> None:
        from specialists.bot import LoseBot

        profile = _env("LOSEBOT_PROFILE", "field")
        model = _env("LOSEBOT_MODEL", "zach") or None
        depth = int(_env("LOSEBOT_DEPTH", "2"))
        self.bot = LoseBot(depth=depth, opponent_model=model, profile=profile)
        self._base_profile = self.bot.profile
        self._base = {
            "depth": self.bot.depth,
            "probe_cap": self.bot.probe_cap,
            "max_probe_n": self.bot.max_probe_n,
        }
        self._proven_before = 0
        logger.info(
            "LoseBot (specialist) ready: profile=%s model=%s depth=%d",
            profile, model or "adversarial", depth,
        )

    def govern(self, board: chess.Board, limit) -> None:
        """Clamp spike budgets to the clock. Tiers, not per-move targets:
        the profile's full machinery runs whenever the clock affords its
        worst case (deep probes ARE the bot's teeth in endgames)."""
        remaining, inc, _fixed = _remaining_seconds(board, limit)
        budget = None if remaining is None else remaining + 2.0 * inc
        bot, base = self.bot, self._base_profile
        if budget is None or budget >= 180:
            bot.profile = base
            bot.depth = self._base["depth"]
            bot.probe_cap = self._base["probe_cap"]
            bot.max_probe_n = self._base["max_probe_n"]
            return
        if budget >= 60:
            vi_build, vi_conv, herd_ms = 8_000, 2_000, 150
            depth, probe_n, probe_cap = self._base["depth"], 3, 150_000
        elif budget >= 20:
            vi_build, vi_conv, herd_ms = 3_000, 800, 100
            depth, probe_n, probe_cap = self._base["depth"], 2, 50_000
        else:
            vi_build, vi_conv, herd_ms = 800, 200, 60
            depth, probe_n, probe_cap = 1, 1, 12_000
        bot.profile = replace(
            base,
            vi_build_ms=min(base.vi_build_ms, vi_build),
            vi_conversion_ms=min(base.vi_conversion_ms, vi_conv),
            modeled_herding_time_ms=min(
                base.modeled_herding_time_ms, herd_ms
            ),
        )
        bot.depth = min(self._base["depth"], depth)
        bot.probe_cap = (
            probe_cap
            if self._base["probe_cap"] is None
            else min(probe_cap, self._base["probe_cap"])
        )
        bot.max_probe_n = (
            probe_n
            if self._base["max_probe_n"] is None
            else min(probe_n, self._base["max_probe_n"])
        )

    def choose(self, board: chess.Board) -> chess.Move:
        self._proven_before = self.bot.forced_selfmates_found
        return self.bot.choose_move(board)

    def log_move(self, board: chess.Board, move: chess.Move,
                 elapsed: float) -> None:
        if self.bot.forced_selfmates_found > self._proven_before:
            logger.info("Forced selfmate net PROVEN — the loss is ours.")
        logger.info(
            "LoseBot played %s in %.1fs (probe nodes %d)",
            board.san(move), elapsed, self.bot.probe_nodes,
        )


_LEGACY_ENV = ("LOSEBOT_PROFILE", "LOSEBOT_MODEL", "LOSEBOT_DEPTH")


class LoseBotEngine(MinimalEngine):
    """Bridge a per-game engine into lichess-bot's homemade API."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._driver: _ModelDriver | _SpecialistDriver | None = None
        self._last_ply = -1

    def _ensure_driver(self, board: chess.Board):
        # One engine object per game makes this effectively per-game; the
        # ply-rewind check is insurance against instance reuse and
        # takebacks (a fresh engine simply re-infers and replans from the
        # board's own move stack — always correct).
        if self._driver is None or board.ply() < self._last_ply:
            legacy = any(
                os.environ.get(name, "").strip() for name in _LEGACY_ENV
            )
            self._driver = (
                _SpecialistDriver() if legacy else _ModelDriver()
            )
        self._last_ply = board.ply()
        return self._driver

    def search(self, board: chess.Board, time_limit, ponder: bool,
               draw_offered: bool, root_moves) -> PlayResult:
        try:
            driver = self._ensure_driver(board)
        except Exception:
            # Construction failure leaves _driver None, so the next move
            # retries it; every move in between stays misère-safe.
            logger.exception(
                "Driver construction failed; misère-safe fallback"
            )
            return PlayResult(_emergency_move(board), None)
        started = time.perf_counter()
        try:
            driver.govern(board, time_limit)
            move = driver.choose(board)
        except Exception:
            logger.exception(
                "Engine raised; falling back to a misère-safe legal move"
            )
            move = _emergency_move(board)
        if isinstance(root_moves, list) and root_moves and move not in root_moves:
            # All online-book/egtb sources are disabled in config.yml, so a
            # restriction list should never arrive; honor it if one does.
            move = root_moves[0]
        elapsed = time.perf_counter() - started
        try:
            driver.log_move(board, move, elapsed)
        except Exception:
            logger.exception("Move logging failed")  # never lose the move
        return PlayResult(move, None)

"""LoseBot on lichess: the homemade-engine bridge for lichess-bot.

lichess-bot creates one engine object per game (`create_engine`) and calls
`search()` once per move with the game board — full move stack included,
which the repetition-era machinery reads — plus the clock. LoseBot itself
has no clock awareness, so the bridge owns a small time governor: as the
clock shrinks it swaps in a profile with tighter build/probe budgets.
Budgets cap worst-case spikes (probe nodes, VI builds); there is no
per-move time target.

Engine selection is config.yml (`engine.name: "LoseBotEngine"`). Tuning is
environment variables, so experimenting never needs an image rebuild:

  LOSEBOT_PROFILE  engine profile (default "current" — the generalist.
                   The planner/vi machinery assumes the Zach reply kernel
                   and is off-model against humans; set LOSEBOT_PROFILE=vi
                   LOSEBOT_MODEL=zach deliberately if you want to watch it
                   try anyway.)
  LOSEBOT_MODEL    opponent model for probes/herding. Empty = adversarial:
                   forced-selfmate proofs are then valid against ANY
                   opponent, which is the sound setting for humans.
  LOSEBOT_DEPTH    misère negamax depth (default 2).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace

import chess
from chess.engine import PlayResult

from lib.engine_wrapper import MinimalEngine

from losebot.bot import LoseBot
from losebot.search import gives_mate, gives_stalemate

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
) -> tuple[float | None, float]:
    """Our clock and increment in seconds; (None, 0) when uncapped."""
    fixed = getattr(limit, "time", None)
    if fixed is not None:
        # Correspondence: lichess-bot passes a fixed per-move budget.
        return float(fixed), 0.0
    if board.turn == chess.WHITE:
        clock, inc = limit.white_clock, limit.white_inc
    else:
        clock, inc = limit.black_clock, limit.black_inc
    return (
        float(clock) if clock is not None else None,
        float(inc) if inc is not None else 0.0,
    )


def _emergency_move(board: chess.Board) -> chess.Move:
    """Last-resort move on engine failure: stay misère-legal (never hand
    the opponent a mate or stalemate if any alternative exists)."""
    legal = list(board.legal_moves)
    for move in legal:
        if not gives_mate(board, move) and not gives_stalemate(board, move):
            return move
    return legal[0]


class LoseBotEngine(MinimalEngine):
    """Bridge a per-game LoseBot instance into lichess-bot's engine API."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bot: LoseBot | None = None
        self._base_profile = None
        self._base: dict = {}
        self._last_ply = -1

    def _ensure_bot(self, board: chess.Board) -> LoseBot:
        # One engine object per game makes this effectively per-game; the
        # ply-rewind check is insurance against instance reuse and
        # takebacks (a fresh LoseBot simply replans — always correct).
        if self._bot is None or board.ply() < self._last_ply:
            profile = _env("LOSEBOT_PROFILE", "current")
            model = _env("LOSEBOT_MODEL", "") or None
            depth = int(_env("LOSEBOT_DEPTH", "2"))
            self._bot = LoseBot(
                depth=depth, opponent_model=model, profile=profile
            )
            self._base_profile = self._bot.profile
            self._base = {
                "depth": self._bot.depth,
                "probe_cap": self._bot.probe_cap,
                "max_probe_n": self._bot.max_probe_n,
            }
            logger.info(
                "LoseBot ready: profile=%s model=%s depth=%d",
                profile, model or "adversarial", depth,
            )
        self._last_ply = board.ply()
        return self._bot

    def _govern(self, bot: LoseBot, board: chess.Board, limit) -> None:
        """Clamp spike budgets to the clock. Tiers, not per-move targets:
        the profile's full machinery runs whenever the clock affords its
        worst case (deep probes ARE the bot's teeth in endgames)."""
        remaining, inc = _remaining_seconds(board, limit)
        budget = None if remaining is None else remaining + 2.0 * inc
        base = self._base_profile
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

    def search(self, board: chess.Board, time_limit, ponder: bool,
               draw_offered: bool, root_moves) -> PlayResult:
        bot = self._ensure_bot(board)
        self._govern(bot, board, time_limit)
        proven_before = bot.forced_selfmates_found
        started = time.perf_counter()
        try:
            move = bot.choose_move(board)
        except Exception:
            logger.exception(
                "LoseBot raised; falling back to a misère-safe legal move"
            )
            move = _emergency_move(board)
        if isinstance(root_moves, list) and root_moves and move not in root_moves:
            # All online-book/egtb sources are disabled in config.yml, so a
            # restriction list should never arrive; honor it if one does.
            move = root_moves[0]
        elapsed = time.perf_counter() - started
        if bot.forced_selfmates_found > proven_before:
            logger.info("Forced selfmate net PROVEN — the loss is ours.")
        logger.info(
            "LoseBot played %s in %.1fs (probe nodes %d)",
            board.san(move), elapsed, bot.probe_nodes,
        )
        return PlayResult(move, None)

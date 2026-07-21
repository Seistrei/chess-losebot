"""Run the frozen specialist engine on the new benchmark.

Lazy wrapper around ``specialists.bot.LoseBot`` so the pivot's league
can measure the old engine on the same scoreboard as the new one —
the anchor every future comparison hangs from. Import stays inside the
factory: the new package must not require the specialist tree to run.

Tiers mirror the lichess bridge's spike governor: "fast" is the
bridge's >=60s tier (bounded VI builds and probes — league games are
untimed, and a full-profile game has hit 293s in the arena); "full"
is the arena-exact configuration.
"""

from __future__ import annotations

import chess


class SpecialistPlayer:
    def __init__(self, profile: str = "field", model: str | None = "zach",
                 depth: int = 2, tier: str = "fast"):
        from dataclasses import replace

        from specialists.bot import LoseBot

        self.bot = LoseBot(depth=depth, opponent_model=model, profile=profile)
        self.name = f"specialist-{profile}[{tier}]"
        if tier == "fast":
            base = self.bot.profile
            self.bot.profile = replace(
                base,
                vi_build_ms=min(base.vi_build_ms, 8_000),
                vi_conversion_ms=min(base.vi_conversion_ms, 2_000),
                modeled_herding_time_ms=min(
                    base.modeled_herding_time_ms, 150
                ),
            )
            self.bot.max_probe_n = (
                3 if self.bot.max_probe_n is None
                else min(3, self.bot.max_probe_n)
            )
            self.bot.probe_cap = (
                150_000 if self.bot.probe_cap is None
                else min(150_000, self.bot.probe_cap)
            )

    @property
    def forced_selfmates_found(self):
        return self.bot.forced_selfmates_found

    def choose_move(self, board: chess.Board) -> chess.Move:
        return self.bot.choose_move(board)

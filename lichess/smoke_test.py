"""Offline build-time smoke test for the lichess bridge.

Runs inside the losebot-lichess image with no token and no network: it
validates config.yml against lichess-bot's own loader, instantiates
LoseBotEngine exactly the way lichess-bot's create_engine does, and
plays moves through the real search() entry point — opening, mate
refusal, the low-clock governor tier, and the correspondence path.
A non-zero exit fails the docker build.
"""

import os
import sys
import time

import chess
from chess.engine import Limit

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures += 1


def main() -> int:
    # 1. config.yml survives lichess-bot's validation (token via env, as in
    # production; the placeholder only satisfies the string-type check).
    os.environ.setdefault("LICHESS_BOT_TOKEN", "smoke-test-placeholder")
    from lib import config as lb_config

    conf = lb_config.load_config("config.yml")
    check(
        "config.yml loads and selects the homemade engine",
        conf.engine.protocol == "homemade"
        and conf.engine.name == "LoseBotEngine"
        and conf.challenge.modes == ["casual"],
        f"engine={conf.engine.name}; modes={conf.challenge.modes}",
    )

    # 1b. Live-test regressions (2026-07-20): unlimited correspondence is
    # only accepted at max_days == inf; the abort fuse must outlast a
    # human reading the bot profile before their first move.
    import math

    check(
        "unlimited correspondence is accepted and the abort fuse is humane",
        conf.challenge.max_days == math.inf and conf.abort_time >= 120,
        f"max_days={conf.challenge.max_days}; abort_time={conf.abort_time}",
    )

    # 1c. Lichess silently drops chat messages over 140 characters after
    # {me} expands — and the greeting is the bot's only way to explain
    # itself. Budget for the longest legal username (20 chars).
    long_name = "W" * 20
    for field in ("hello", "goodbye", "hello_spectators",
                  "goodbye_spectators"):
        text = getattr(conf.greeting, field).format(
            me=long_name, opponent=long_name
        )
        check(
            f"greeting.{field} fits lichess chat with a 20-char name",
            len(text) <= 140,
            f"{len(text)} chars",
        )

    # 2. Resolve the class through the production lookup (this also pulls
    # in test_bot/homemade.py, which imports ExampleEngine from our file)
    # and instantiate it with create_engine's exact argument shape.
    from lib.config import Configuration
    from lib.engine_wrapper import get_homemade_engine

    engine_class = get_homemade_engine(conf.engine.name)
    engine = engine_class([], {}, None, Configuration({}), None, False)

    # 3. Opening move on a generous clock: legal, and the full profile
    # (no governor clamps) is in force.
    board = chess.Board()
    started = time.perf_counter()
    result = engine.search(
        board, Limit(white_clock=600.0, black_clock=600.0,
                     white_inc=0.0, black_inc=0.0),
        False, False, None,
    )
    opening_s = time.perf_counter() - started
    check(
        "opening move is legal on a fresh board",
        result.move in board.legal_moves,
        f"{board.san(result.move)} in {opening_s:.1f}s",
    )
    check(
        "generous clock leaves the base profile untouched",
        engine._bot is not None
        and engine._bot.profile is engine._base_profile
        and engine._bot.max_probe_n is None,
        f"profile={engine._bot.profile.name}",
    )

    # 4. The signature property: a mate-in-1 on the board must be refused.
    from losebot.search import gives_mate

    mate_board = chess.Board("6k1/5ppp/8/8/8/8/8/1R4K1 w - - 0 1")
    result = engine.search(
        mate_board, Limit(white_clock=600.0, black_clock=600.0,
                          white_inc=0.0, black_inc=0.0),
        False, False, None,
    )
    check(
        "bridge refuses to deliver an available mate",
        result.move in mate_board.legal_moves
        and not gives_mate(mate_board, result.move),
        f"chose {mate_board.san(result.move)}",
    )

    # 5. Low clock engages the emergency tier (fresh engine per game, as in
    # production; the ply-rewind guard also resets the old one here). The
    # board carries a real move stack, like lichess-bot always provides.
    engine = engine_class([], {}, None, Configuration({}), None, False)
    played = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6"):
        played.push_san(san)
    started = time.perf_counter()
    result = engine.search(
        played, Limit(white_clock=9.0, black_clock=60.0,
                      white_inc=0.0, black_inc=0.0),
        False, False, None,
    )
    low_s = time.perf_counter() - started
    check(
        "low-clock tier clamps depth and probe budgets",
        result.move in played.legal_moves
        and engine._bot.depth == 1
        and engine._bot.max_probe_n == 1
        and engine._bot.probe_cap == 12_000,
        f"{played.san(result.move)} in {low_s:.1f}s; "
        f"depth={engine._bot.depth}; cap={engine._bot.probe_cap}",
    )

    # 6. Correspondence passes a fixed per-move budget through limit.time;
    # a 60s budget lands in the 60-180 governor tier.
    result = engine.search(
        played, Limit(time=60), False, False, None,
    )
    check(
        "correspondence budget maps onto a mid governor tier",
        result.move in played.legal_moves
        and engine._bot.max_probe_n == 3
        and engine._bot.probe_cap == 150_000,
        f"{played.san(result.move)}; cap={engine._bot.probe_cap}",
    )

    print(f"{'ALL PASS' if failures == 0 else f'{failures} FAILURES'}")
    return failures


if __name__ == "__main__":
    sys.exit(main())

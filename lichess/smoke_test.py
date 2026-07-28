"""Offline build-time smoke test for the lichess bridge.

Runs inside the losebot-lichess image with no token and no network: it
validates config.yml against lichess-bot's own loader, instantiates
LoseBotEngine exactly the way lichess-bot's create_engine does, and
plays moves through the real search() entry point — model-engine
defaults (fitted-human belief, infer=map, a14 knobs), posterior
observation through the bridge, mate refusal, every governor tier, the
correspondence path, the emergency fallback, and the one-env-line
specialist fallback. A non-zero exit fails the docker build.
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


def gives_mate_or_stalemate(board: chess.Board, move: chess.Move) -> bool:
    board.push(move)
    ends = board.is_checkmate() or board.is_stalemate()
    board.pop()
    return ends


def ruy_board() -> chess.Board:
    """An 8-ply opening with a real move stack, as lichess-bot provides."""
    board = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6"):
        board.push_san(san)
    return board


def main() -> int:
    # The bridge reads its env knobs at driver construction; the smoke
    # must start from the shipped defaults regardless of build env.
    for name in ("LOSEBOT_PROFILE", "LOSEBOT_MODEL", "LOSEBOT_DEPTH",
                 "LOSEBOT_BELIEF", "LOSEBOT_INFER"):
        os.environ.pop(name, None)

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

    # 1d. The bridge invariants that live in config: a draw denies the
    # loss (never resign, never offer/accept draws), every game lands in
    # game_records/ as corpus, and the bot never seeks games on its own.
    dor = conf.engine.draw_or_resign
    check(
        "draws and resignation are disabled",
        not dor.resign_enabled and not dor.offer_draw_enabled,
        f"resign={dor.resign_enabled}; draw={dor.offer_draw_enabled}",
    )
    check(
        "corpus protocol: PGNs land per-game in game_records/",
        conf.pgn_directory == "game_records"
        and conf.pgn_file_grouping == "game",
        f"dir={conf.pgn_directory}; grouping={conf.pgn_file_grouping}",
    )
    check(
        "matchmaking stays off — the bot waits to be challenged",
        conf.matchmaking.allow_matchmaking is False,
    )

    # 2. Resolve the class through the production lookup (this also pulls
    # in test_bot/homemade.py, which imports ExampleEngine from our file)
    # and instantiate it with create_engine's exact argument shape.
    from lib.config import Configuration
    from lib.engine_wrapper import get_homemade_engine

    import homemade
    from losebot.models.posterior import FITTED_HUMAN

    engine_class = get_homemade_engine(conf.engine.name)
    engine = engine_class([], {}, None, Configuration({}), None, False)

    # 3. Opening move on a generous clock: legal, and the MODEL driver is
    # in force at the shipped a14 defaults — fitted-human belief,
    # inference on, device-plan and eval knobs off.
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
        "bridge never resigns or offers a draw",
        not result.resigned and not result.draw_offered,
    )
    driver = engine._driver
    model = getattr(driver, "engine", None)
    check(
        "default driver is the model engine with the declared belief",
        isinstance(driver, homemade._ModelDriver)
        and model.name == "losebot(infer-map)"
        and model.belief.name == "fitted-human"
        and model.belief.params == FITTED_HUMAN
        and model.posterior is not None,
        f"engine={getattr(model, 'name', None)}; "
        f"belief={getattr(getattr(model, 'belief', None), 'name', None)}",
    )
    check(
        "generous clock leaves the a14 defaults untouched",
        model.depth == 3 and model.probe_n == 4
        and model.probe_cap == 50_000 and model.sub_probe_cap == 75_000
        and model.node_cap == 400_000,
        f"probe {model.probe_n}@{model.probe_cap}; "
        f"sub {model.sub_probe_cap}; node cap {model.node_cap}",
    )
    check(
        "first corpus batch reflects the shipped engine: plan and eval "
        "knobs at defaults",
        model.plan_steer == 0 and model.eval_params is None,
        f"plan_steer={model.plan_steer}; eval_params={model.eval_params}",
    )

    # 4. Inference is live through the bridge: after a search on a board
    # with history, the posterior has observed exactly the opponent's
    # non-forced moves (four Black plies in the Ruy stack).
    engine = engine_class([], {}, None, Configuration({}), None, False)
    played = ruy_board()
    result = engine.search(
        played, Limit(white_clock=600.0, black_clock=600.0,
                      white_inc=0.0, black_inc=0.0),
        False, False, None,
    )
    diag = engine._driver.engine.posterior.diagnostics()
    check(
        "posterior observes the opponent's moves through the bridge",
        result.move in played.legal_moves
        and diag["posterior_observations"] == 4,
        f"observations={diag['posterior_observations']}; "
        f"map={diag['posterior_map']}@{diag['posterior_map_weight']}",
    )

    # 5. The signature property: a mate-in-1 on the board must be refused.
    mate_board = chess.Board("6k1/5ppp/8/8/8/8/8/1R4K1 w - - 0 1")
    result = engine.search(
        mate_board, Limit(white_clock=600.0, black_clock=600.0,
                          white_inc=0.0, black_inc=0.0),
        False, False, None,
    )
    check(
        "bridge refuses to deliver an available mate",
        result.move in mate_board.legal_moves
        and not gives_mate_or_stalemate(mate_board, result.move),
        f"chose {mate_board.san(result.move)}",
    )

    # 6. Every governor tier clamps exactly its declared knobs and still
    # produces a legal move. The engine survives tier changes (fresh
    # engine per game in production, but knobs re-clamp per move), and
    # the ladder must be monotone: no knob grows as the clock shrinks.
    engine = engine_class([], {}, None, Configuration({}), None, False)
    played = ruy_board()
    tiers = {name: knobs for name, _floor, knobs in
             homemade._ModelDriver.TIERS}
    knob_names = ("depth", "probe_n", "probe_cap", "sub_probe_cap",
                  "sub_probe_slice", "node_cap")
    previous = None
    for tier_name, clock in (("mid", 100.0), ("low", 45.0),
                             ("emergency", 9.0)):
        started = time.perf_counter()
        result = engine.search(
            played, Limit(white_clock=clock, black_clock=600.0,
                          white_inc=0.0, black_inc=0.0),
            False, False, None,
        )
        tier_s = time.perf_counter() - started
        model = engine._driver.engine
        expected = dict(tiers[tier_name])
        applied = {name: getattr(model, name) for name in knob_names}
        ok = all(
            applied[name] == expected.get(name, applied[name])
            for name in knob_names
        )
        if previous is not None:
            ok = ok and all(
                applied[name] <= previous[name] for name in knob_names
            )
        check(
            f"{tier_name} tier clamps its knobs and plays a legal move",
            result.move in played.legal_moves and ok,
            f"{played.san(result.move)} in {tier_s:.1f}s; "
            f"probe {applied['probe_n']}@{applied['probe_cap']}; "
            f"sub {applied['sub_probe_cap']}; depth {applied['depth']}; "
            f"node cap {applied['node_cap']}",
        )
        previous = applied

    # 6b. Correspondence passes a fixed per-MOVE budget through
    # limit.time: 60s per move affords the full config (measured
    # worst-case per move clears it with margin); a tiny budget still
    # clamps down.
    result = engine.search(played, Limit(time=60), False, False, None)
    model = engine._driver.engine
    check(
        "correspondence (60s/move) runs the full config",
        result.move in played.legal_moves and model.probe_cap == 50_000
        and model.node_cap == 400_000,
        f"probe {model.probe_n}@{model.probe_cap}",
    )
    result = engine.search(played, Limit(time=10), False, False, None)
    check(
        "a tiny fixed budget still clamps to the emergency tier",
        result.move in played.legal_moves
        and model.probe_cap == tiers["emergency"]["probe_cap"],
        f"probe {model.probe_n}@{model.probe_cap}",
    )

    # 7. The emergency fallback: if the engine raises, the bridge still
    # answers with a legal, misère-safe move through the same search().
    # The first search must be on the SAME board: a lower ply would trip
    # the rewind guard and rebuild the driver, silently discarding the
    # patched choose() and testing nothing.
    engine = engine_class([], {}, None, Configuration({}), None, False)
    engine.search(
        mate_board, Limit(white_clock=9.0, black_clock=600.0,
                          white_inc=0.0, black_inc=0.0),
        False, False, None,
    )
    fired = []

    def _boom(_board):
        fired.append(True)
        raise RuntimeError("smoke-test forced failure")

    engine._driver.choose = _boom
    result = engine.search(
        mate_board, Limit(white_clock=9.0, black_clock=600.0,
                          white_inc=0.0, black_inc=0.0),
        False, False, None,
    )
    check(
        "engine failure falls back to a misère-safe legal move",
        bool(fired)
        and result.move in mate_board.legal_moves
        and not gives_mate_or_stalemate(mate_board, result.move),
        f"raised={bool(fired)}; chose {mate_board.san(result.move)}",
    )

    # 8. One env line restores the legacy specialist bridge, old governor
    # included (the 2026-07-20 field-notes configuration).
    os.environ["LOSEBOT_PROFILE"] = "field"
    try:
        engine = engine_class([], {}, None, Configuration({}), None, False)
        started = time.perf_counter()
        result = engine.search(
            played, Limit(white_clock=9.0, black_clock=60.0,
                          white_inc=0.0, black_inc=0.0),
            False, False, None,
        )
        legacy_s = time.perf_counter() - started
        driver = engine._driver
        check(
            "LOSEBOT_PROFILE=field restores the specialist bridge",
            isinstance(driver, homemade._SpecialistDriver)
            and result.move in played.legal_moves
            and driver.bot.profile.name == "field"
            and driver.bot.depth == 1
            and driver.bot.max_probe_n == 1
            and driver.bot.probe_cap == 12_000,
            f"{played.san(result.move)} in {legacy_s:.1f}s; "
            f"profile={driver.bot.profile.name}; "
            f"depth={driver.bot.depth}; cap={driver.bot.probe_cap}",
        )
    finally:
        del os.environ["LOSEBOT_PROFILE"]

    print(f"{'ALL PASS' if failures == 0 else f'{failures} FAILURES'}")
    return failures


if __name__ == "__main__":
    sys.exit(main())

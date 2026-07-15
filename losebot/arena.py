"""Play matches between bots and report who managed to lose."""

import time
from pathlib import Path

import chess
import chess.pgn


def play_game(white, black, max_plies: int = 300, start_fen: str | None = None):
    """Returns (board, reason, mated_color_or_None)."""
    board = chess.Board(start_fen) if start_fen else chess.Board()
    while True:
        if board.is_checkmate():
            return board, "checkmate", board.turn
        if board.is_stalemate():
            return board, "stalemate", None
        if board.is_insufficient_material():
            return board, "insufficient-material", None
        if board.halfmove_clock >= 100:
            return board, "fifty-move", None
        if board.halfmove_clock >= 8 and board.is_repetition(3):
            return board, "repetition", None
        if len(board.move_stack) >= max_plies:
            return board, "max-plies", None
        bot = white if board.turn == chess.WHITE else black
        board.push(bot.choose_move(board))


def save_pgn(board, white, black, reason, mated, path: Path, game_no: int):
    game = chess.pgn.Game.from_board(board)
    game.headers["Event"] = "Misere chess arena"
    game.headers["White"] = white.name
    game.headers["Black"] = black.name
    if mated is None:
        game.headers["Result"] = "1/2-1/2"
    else:
        game.headers["Result"] = "0-1" if mated == chess.WHITE else "1-0"
    game.headers["Termination"] = (
        f"{reason}; misere winner: "
        + ("none" if mated is None
           else (white.name if mated == chess.WHITE else black.name)
           + " (got mated)")
    )
    path.mkdir(parents=True, exist_ok=True)
    out = path / f"game_{game_no:03d}_{white.name}_vs_{black.name}.pgn"
    with open(out, "w", encoding="utf-8") as f:
        print(game, file=f)


def run_match(white, black, n_games: int, max_plies: int = 300,
              pgn_dir: str | None = None):
    tallies: dict[str, int] = {}
    focal = None
    for bot in (white, black):
        if getattr(bot, "forced_selfmates_found", None) is not None:
            focal = bot
            break

    for i in range(1, n_games + 1):
        t0 = time.monotonic()
        board, reason, mated = play_game(white, black, max_plies=max_plies)
        dt = time.monotonic() - t0
        if mated is None:
            key = f"draw:{reason}"
            outcome = key
        else:
            loser_bot = white if mated == chess.WHITE else black
            key = f"mated:{loser_bot.name}"
            outcome = f"{loser_bot.name} GOT MATED (misere win for it)"
        tallies[key] = tallies.get(key, 0) + 1
        print(
            f"game {i:2d}: {white.name}(W) vs {black.name}(B) -> {outcome} "
            f"in {len(board.move_stack)} plies [{dt:.1f}s]",
            flush=True,
        )
        if pgn_dir:
            save_pgn(board, white, black, reason, mated, Path(pgn_dir), i)

    print("\n=== summary:", white.name, "(W) vs", black.name, "(B) ===")
    for key in sorted(tallies):
        print(f"  {key}: {tallies[key]}/{n_games}")
    if focal is not None:
        wins = tallies.get(f"mated:{focal.name}", 0)
        print(
            f"  {focal.name} successfully LOST {wins}/{n_games} games "
            f"({100.0 * wins / n_games:.0f}%); "
            f"forced selfmates found: {focal.forced_selfmates_found}"
        )
        if getattr(focal, "probe_nodes", None) is not None:
            print(
                f"  exact probe: {focal.probe_nodes} nodes; "
                f"budget exhausted {focal.probe_budget_exhaustions} times; "
                f"deepest completed n={focal.deepest_probe_completed}; "
                f"deep probes skipped {focal.deep_probe_skips} times"
            )
        if getattr(getattr(focal, "profile", None), "stateful_plan", False):
            print(
                f"  construction plans: {focal.plans_created} created; "
                f"{focal.plan_invalidations} invalidated; "
                f"best distance {focal.best_plan_distance}; "
                f"holding moves filtered {focal.hold_moves_filtered}; "
                f"regressions filtered {focal.plan_regressions_filtered}; "
                f"repetitions filtered {focal.plan_repetitions_filtered}; "
                f"forced herds chosen {focal.forced_herding_choices}; "
                f"herd proofs {focal.herd_search_hits}/"
                f"{focal.herd_search_nodes} nodes; "
                f"modeled herds {focal.modeled_herding_hits}/"
                f"{focal.modeled_herding_replies} replies/"
                f"{focal.modeled_herding_nodes} nodes; "
                f"modeled cache {focal.modeled_herding_cache_hits} hits/"
                f"{focal.modeled_herding_memo_entries} entries; "
                f"modeled candidates pruned "
                f"{focal.modeled_herding_candidates_pruned}; "
                f"modeled incomplete {focal.modeled_herding_incomplete}"
            )
        if getattr(getattr(focal, "profile", None), "vi_herding", False):
            root = (
                "n/a"
                if focal.vi_root_value is None
                else f"{focal.vi_root_value:.3f}"
            )
            print(
                f"  vi herding: {focal.vi_builds} builds "
                f"({focal.vi_build_failures} failed"
                f"{': ' + focal.vi_last_failure if focal.vi_last_failure else ''}); "
                f"{focal.vi_states} states; {focal.vi_edges} edges; "
                f"{focal.vi_updates} updates; last root {root}; "
                f"{focal.vi_build_ms:.0f}ms building; "
                f"{focal.vi_moves_played} moves played; "
                f"{focal.vi_state_misses} state misses; "
                f"{focal.vi_zero_fallbacks} zero-value fallbacks; "
                f"{focal.vi_goal_stalls} goal stalls; "
                f"{focal.vi_releases} releases "
                f"({focal.vi_release_nodes} probe nodes); "
                f"{focal.vi_side_flips} side flips; "
                f"{focal.vi_king_marches} king marches; "
                f"{focal.vi_cage_builds} cage builds; "
                f"{focal.vi_capture_guards} capture guards; "
                f"{focal.vi_pool_mismatches} pool mismatches"
            )
    return tallies

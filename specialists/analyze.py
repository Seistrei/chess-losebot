"""Replay a PGN and report the final position plus squeeze statistics."""

import sys

import chess
import chess.pgn


def main(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        game = chess.pgn.read_game(f)
    board = game.board()
    min_black_mobility = 999
    for mv in game.mainline_moves():
        board.push(mv)
        if board.turn == chess.BLACK and not board.is_game_over():
            min_black_mobility = min(min_black_mobility, board.legal_moves.count())
    print("final FEN :", board.fen())
    print("to move   :", "white" if board.turn == chess.WHITE else "black")
    print("checkmate :", board.is_checkmate())
    print("stalemate :", board.is_stalemate())
    print("legal     :", [board.san(m) for m in board.legal_moves])
    print("min black mobility seen:", min_black_mobility)
    print(board)


if __name__ == "__main__":
    main(sys.argv[1])

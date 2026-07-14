# ChessLosebot

A **misère chess** engine: standard chess rules, but the goal is to *get
checkmated*. Built to out-lose Worstfish against opponents that refuse to
deliver mate (like Chess.com's Zach bot).

Everything runs in Docker — no local installs.

## Build

```powershell
docker build -t losebot .
```

## Run

```powershell
# sanity checks (forced-selfmate probe, mate refusal, Zach zugzwang)
docker run --rm losebot

# LoseBot (White) tries to lose to a Zach clone (Black), saving PGNs to .\games
docker run --rm -v "D:\ChessLosebot\games:/app/games" losebot `
  pypy3 -m losebot arena --white losebot --black zach --model zach -n 10 --pgn-dir /app/games

# Baseline: Worstfish (real Stockfish argmin) fails to lose to Zach
docker run --rm losebot pypy3 -m losebot arena --white worstfish --black zach -n 4

# Two dedicated losers fight it out
docker run --rm losebot pypy3 -m losebot arena --white losebot --black worstfish -n 2

# Inspect a finished game
docker run --rm -v "D:\ChessLosebot\games:/app/games" losebot `
  pypy3 -m losebot.analyze /app/games/game_001_losebot_vs_zach.pgn

# Endgame conversion drills (Zach pre-stripped to king+pawns)
docker run --rm losebot pypy3 -m losebot endgames --seed 5
```

## How LoseBot works

1. **Never** delivers mate or stalemate if any alternative exists.
2. **Exact forced-selfmate probe** (`selfmate_in`): finds moves after which
   *every* opponent reply leads to LoseBot being checkmated — the selfmate
   search Worstfish's flipped-Stockfish construction cannot express. Probes
   deepen as the opponent runs out of mobile pieces.
3. **Opponent model** (`--model zach`): restricts the opponent's reply set in
   the probe to the pool Zach actually samples from (never mates if avoidable,
   never captures if avoidable), making forced losses far easier to prove.
4. **Misère negamax** otherwise, with inverted terminals (being mated = +MATE)
   and an eval encoding the human-discovered recipe: eat their mobile pieces
   (they are shuffle fuel), leave them king-and-pawns, walk our king in front
   of their pawns, smother it with our own men, minimize their mobility,
   and treat draws/50-move drift as failure.

## Roadmap

- v1: add Fairy-Stockfish with a `[misere:chess] checkmateValue = win` variant
  as a deep tactical oracle for forced selfmate nets.
- Lichess BOT bridge (lichess-bot) — there is currently no misère bot there.

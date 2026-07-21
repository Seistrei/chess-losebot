# ChessLosebot

A **misère chess** engine: standard chess rules, but the goal is to *get
checkmated*. Built to out-lose Worstfish against opponents that refuse to
deliver mate (like Chess.com's Zach bot) — and, since the 2026-07-21
pivot, to generalize that ability to opponents nobody hand-modeled.

Everything runs in Docker — no local installs.

## The architecture (post-pivot)

The first era of this project hand-built a specialist: exact herding
MDPs, corner templates, chore choreography, a donation guard — all
keyed to specific opponent kernels. It converts its home drills, but
the results forced a verdict: the squat kernel converts 10/10 while
the human-like sloppy kernel converts 0/10 *from the same position*,
and the doctrines the two kernels demand are opposite with no position
predicate to discriminate. The discriminating information lives in the
opponent's policy distribution, so the engine was rebuilt around one.
The full decision record is in `TUNING-LOG.md` ("The pivot").

The new `losebot/` package has three load-bearing ideas:

1. **One parametric opponent family** (`losebot/models/`): every
   opponent is a point in "urge space" (greed, checks, pushes, king
   hunting, corner homing, promotion drive, mercy lapses) over a
   mate-avoidant core. Kernels are presets, not code; new observed
   behavior updates parameters — eventually by fitting to the live
   corpus — never a new doctrine stack. Models expose exact per-move
   probability distributions.
2. **Expectimax steering** (`losebot/search.py`): our nodes maximize,
   opponent nodes take the expectation over the model's distribution.
   Hold vs. lift, cage vs. race — the search prices doctrine questions
   per opponent because the opponent is *in the tree*.
3. **An opponent-free oracle** (`losebot/oracle.py`): exact
   forced-selfmate certificates, valid against ANY reply. The steering
   layer's job is to reach positions where the oracle fires; the
   oracle's job is to make the finish unconditional. "Forced selfmate"
   is the only win the scoreboard fully credits.

Progress is measured by the **frozen league** (`losebot/league/`):
dev families (fair game for tuning) and held-out families (frozen
parameters, report-only), seats alternated, fresh RNG per game, every
game classified by an outcome taxonomy — forced selfmate, mercy mate,
accidental win, stalemates in both directions, each draw kind — and
reported per-family with the worst family given equal billing to the
mean. Generalization claims cite held-out rows, nothing else.

```text
losebot/
  outcomes.py    termination rules + outcome taxonomy (one source of truth)
  oracle.py      exact forced-selfmate probe, no opponent model anywhere
  evaluate.py    asymmetric misère eval (root-as-loser at every leaf)
  search.py      expectimax vs the opponent distribution (top-k truncated)
  engine.py      oracle first, steering second, misère-safe root partition
  models/        the urge family, presets incl. FROZEN held-out params
  league/        play loop, family roster, runner, report, specialist wrapper
specialists/     the frozen first-era engine (Zach herding VI, templates,
                 donation guard) — benchmark teacher + lichess driver
```

## Build

```powershell
docker build -t losebot .
```

## Run

```powershell
# fast self-checks for the new package (also the image's default CMD)
docker run --rm losebot

# one game against a family, from either seat
docker run --rm losebot pypy3 -m losebot play --opponent sloppy --seed 3 --seat black

# the frozen league: the benchmark of record
docker run --rm -v "D:\ChessLosebot\games:/app/games" losebot `
  pypy3 -m losebot league --engine model --belief sloppy --games 10 `
  --out games/league/baseline

# the frozen specialist on the same benchmark (the anchor)
docker run --rm -v "D:\ChessLosebot\games:/app/games" losebot `
  pypy3 -m losebot league --engine specialist --games 4 `
  --out games/league/specialist

# probe any FEN for forced-selfmate certificates
docker run --rm losebot pypy3 -m losebot oracle `
  --fen "8/8/8/R7/8/3PPk1p/6RP/6BK w - - 0 1" --n 3
```

During development, mount the checkout over the baked copy instead of
rebuilding (`MSYS_NO_PATHCONV=1` stops Git Bash mangling the paths):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "D:\ChessLosebot:/app" losebot pypy3 -m losebot selftest
```

## The specialists package

The entire first-era engine lives on, importable and battle-tested,
under `specialists/`: the exact `selfmate_in` probe with the Zach reply
model, misère negamax, construction templates, the herding-sub-MDP
value iteration with dead-side certificates and conversion audits,
king-holder corner machinery, the donation guard / herder-material
floor, and the drill batteries (`endgames`, `motifs`, `arena`). Its
selftest and batteries still run:

```powershell
docker run --rm losebot pypy3 -m specialists selftest
docker run --rm losebot pypy3 -m specialists endgames --profile vi --case 7 --seed 1 --vi-herders 1
docker run --rm losebot pypy3 -m specialists arena --white losebot --black sloppy --model zach --profile field
```

Historical commands in `TUNING-LOG.md` predating the pivot read
`pypy3 -m losebot ...`; substitute `-m specialists`. Its roles now:
the lichess driver (below), the anchor row on the league, a source of
labeled training positions, and the reference implementation of every
theorem the drills proved (release theorem, diagonal seal, vacate-race
odds, donation doctrine).

## Play against it on lichess

The bot runs as a lichess BOT account through the
[lichess-bot](https://github.com/lichess-bot-devs/lichess-bot) bridge
(pinned in `Dockerfile.lichess`; the wrapper is `lichess/homemade.py`).
It accepts casual standard challenges at rapid (10+0) and slower,
correspondence and unlimited included — a bot that plays to lose has no
business in rated pools or bullet.

The bridge still drives the **specialist** (`LOSEBOT_PROFILE=field
LOSEBOT_MODEL=zach` — the donation-guarded profile the first live games
selected; see TUNING-LOG's field notes). The new engine takes over the
bridge once it beats the specialist's held-out league rows — swapping
is one import in `lichess/homemade.py`, and until then every live game
keeps landing in `lichess/game_records/` as fitting data for the urge
family.

One-time setup: create an OAuth token with the `bot:play` scope on the
(already upgraded) BOT account, then

```powershell
copy lichess\lichess.env.example lichess\lichess.env
# paste the token into lichess\lichess.env (gitignored — never commit it)
```

Build and run (the bridge image builds on the engine image and smoke-tests
the wrapper offline during the build):

```powershell
docker build -t losebot .
docker build -f Dockerfile.lichess -t losebot-lichess .

docker run --rm --env-file lichess/lichess.env `
  -v "D:\ChessLosebot\lichess\game_records:/opt/lichess-bot/game_records" `
  losebot-lichess
```

The account is challengeable while that container runs; Ctrl-C finishes
running games first. Every game is archived as PGN in
`lichess/game_records/`.

## Roadmap

- **Fit the urge family to the corpus**: maximum-likelihood urge
  weights from `lichess/game_records/` (and every future live game) —
  the step that turns live games from session-costing exposures into
  training data.
- **Deepen the steering**: memoization, star-pruning at chance nodes,
  quiescence on forced sequences, oracle probes below the root.
- **Deepen the closing**: a dedicated selfmate solver (Popeye) as a
  stronger oracle; the specialists' Zach-modeled probe as a
  family-conditional oracle where a family justifies it.
- **League milestones**: held-out forced-selfmate rate 60% → 80% → 90%,
  worst-family reported alongside every mean; the first *forced* mate
  against a live human remains the standing live bar.

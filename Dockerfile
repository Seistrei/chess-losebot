FROM pypy:3.11-slim

# Real Stockfish for the Worstfish clone (Debian package installs to /usr/games/stockfish)
RUN apt-get update \
 && apt-get install -y --no-install-recommends stockfish \
 && rm -rf /var/lib/apt/lists/*

RUN pypy3 -m pip install --no-cache-dir "chess>=1.10,<2"

WORKDIR /app
COPY losebot ./losebot

CMD ["pypy3", "-m", "losebot", "selftest"]

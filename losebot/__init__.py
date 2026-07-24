"""LoseBot, rebuilt around the opponent instead of around one opponent.

Misère chess: standard rules, and the goal is to get checkmated. The
2026-07 pivot (TUNING-LOG: "The pivot") reorganizes the project around
three parts:

- ``models``   one parametric stochastic family of opponents (urges),
               covering the old kernel zoo as parameter points;
- ``oracle``   exact forced-selfmate certificates, valid against ANY
               reply — the opponent-free closing layer;
- ``search``   expectimax against the model's move distribution — the
               opponent-aware steering layer.

The hand-built specialist engine (Zach herding VI, corner templates,
donation guard) lives on unchanged in the sibling ``specialists``
package: it is the benchmark's teacher and the lichess bridge's
current driver, no longer the primary line of development.
"""

__version__ = "2.0.0a7"

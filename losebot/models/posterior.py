"""Online opponent inference: a Bayesian posterior over urge hypotheses.

The phantom net (TUNING-LOG 2026-07-22) is why this exists: ext squat
g03 logged 629 real oracle certificates and zero closures because every
net stood behind a king-wander reply the fixed sloppy belief prices at
~0.5 mass and the actual squatter (home 1.0) never plays. Phantom EV
(~0.5 x MATE per offer) outbid every real plan for 240 plies. The
plumbing prices exactly what it is told; what it is told about the
opponent is a config constant. This module makes it an inference: keep
a posterior over a small set of urge-parameter HYPOTHESES, update it
after every observed opponent move via each hypothesis's exact
``distribution()`` likelihood — the reason the family exposes exact
per-move probabilities at all — and hand steering the posterior mix
(or its MAP point). A squatter reveals home-urge behavior in a handful
of moves; the wander mass dies with the hypotheses that believed it.
Honest mirages stay untouched: when belief matches opponent (the
funded pin's sloppy-held conversions) the posterior converges to the
same belief and the same offers keep landing.

Protocol note, load-bearing: inference reads ONLY the opponent's
observed moves in the current game — never the family name it plays
under, never a held-out parameter. The hypothesis set below is built
from DEV knowledge alone: the three dev presets, a half-strength
sloppy (the milder-human region between sloppy and zach), the squat
premise on the mirrored corner (corner choice is a family parameter,
not a held-out secret — boards have two king homes), and the squat
premise grafted with sloppy's own greed numbers (a squatter who
accepts gifts is the choreography-era combination, hypothesized here
with dev values only). Held-out presets never appear on this list;
generalizing to them is the posterior's job, not its prior.

Updates are deterministic functions of the observed move sequence
(pure-float log-likelihood accumulation, no RNG, no wall clock), so
league determinism survives: identical configs reproduce to the ply.

Zero-probability observed moves are the one mechanical trap: an urge
family assigns exact zeros (a squat hypothesis gives every non-homing
king step literally no mass), and one off-model move must not zero a
hypothesis forever. Every likelihood is therefore smoothed with an
epsilon of uniform-over-legal: off-model moves cost a hypothesis
heavily (factor ~eps/L against a matched rival) but finitely, and
weights below the prune floor merely sit out of the mixture — they
keep updating and can revive if the evidence swings back.
"""

from __future__ import annotations

import math
from dataclasses import asdict, replace

import chess

from .base import OpponentModel
from .presets import SLOPPY, SQUAT, ZACH
from .urges import UrgeModel, UrgeParams

#: Smoothing mass on uniform-over-legal in every observed-move
#: likelihood. Big enough that a single lapse cannot kill a hypothesis
#: beyond recovery, small enough that a genuinely off-model move still
#: costs ~four orders of magnitude against a matched rival.
EPSILON = 1e-3

#: Posterior weight below which a hypothesis sits out of the mixture
#: (and out of MAP contention only by losing argmax). Never deletion:
#: the log-weight keeps updating, so a benched hypothesis revives the
#: moment the evidence favors it again.
PRUNE = 1e-3

#: A posterior has COLLAPSED when its MAP weight first reaches this;
#: the observation count at that moment is the moves-to-collapse
#: diagnostic the league persists.
COLLAPSE = 0.95

#: The configured belief is a real Bayesian prior, not merely a
#: tie-break hint. Half the mass starts on that exact point; the other
#: half is exploratory mass balanced across broad families and then
#: split across variants within each family. Adding another corner or
#: greed variant therefore does not silently make the squat premise
#: more probable before any evidence arrives.
CONFIGURED_PRIOR_MASS = 0.5


def _scaled(params: UrgeParams, factor: float) -> UrgeParams:
    """Scale every firing probability; structure knobs stay put."""
    return replace(
        params,
        mercy=params.mercy * factor,
        promote=params.promote * factor,
        greed=params.greed * factor,
        trade=params.trade * factor,
        check=params.check * factor,
        push=params.push * factor,
        hunt=params.hunt * factor,
        home=params.home * factor,
    )


#: The dev-pure hypothesis set, in fixed order. The configured belief
#: supplies the prior anchor; order is now only a deterministic
#: tie-break after genuinely equal posterior weights.
HYPOTHESES: tuple[tuple[str, UrgeParams], ...] = (
    ("sloppy", SLOPPY),
    ("sloppy-mild", _scaled(SLOPPY, 0.5)),
    ("zach", ZACH),
    ("squat-k", SQUAT),
    ("squat-q", replace(SQUAT, home_side="queen")),
    ("squat-greedy-k", replace(SQUAT, greed=SLOPPY.greed,
                               trade=SLOPPY.trade)),
    ("squat-greedy-q", replace(SQUAT, home_side="queen",
                               greed=SLOPPY.greed, trade=SLOPPY.trade)),
)

#: Broad families used only to construct the exploratory half of the
#: prior. They do not collapse or otherwise coarsen inference: every
#: hypothesis still accumulates its own likelihood.
HYPOTHESIS_FAMILIES: tuple[str, ...] = (
    "sloppy",
    "sloppy",
    "zach",
    "squat",
    "squat",
    "squat",
    "squat",
)


def prior_for_belief(
    belief: OpponentModel,
    hypotheses: tuple[tuple[str, UrgeParams], ...] = HYPOTHESES,
    families: tuple[str, ...] = HYPOTHESIS_FAMILIES,
    configured_mass: float = CONFIGURED_PRIOR_MASS,
) -> tuple[float, ...]:
    """Build a point-anchored, family-balanced inference prior.

    Inference intentionally ranges over dev-built points only. The
    configured belief must therefore match one of those parameter
    dictionaries (``squat`` matches the ``squat-k`` hypothesis even
    though the display names differ).
    """
    if len(hypotheses) != len(families):
        raise ValueError("every inference hypothesis needs a family")
    if not 0.0 < configured_mass < 1.0:
        raise ValueError("configured prior mass must be between 0 and 1")
    params = getattr(belief, "params", None)
    matches = [
        index
        for index, (_name, hypothesis_params) in enumerate(hypotheses)
        if hypothesis_params == params
    ]
    if not matches:
        supported = ", ".join(name for name, _params in hypotheses)
        raise ValueError(
            f"inference belief {belief.name!r} is not in the dev "
            f"hypothesis set ({supported})"
        )

    counts: dict[str, int] = {}
    for family in families:
        counts[family] = counts.get(family, 0) + 1
    family_mass = 1.0 / len(counts)
    exploratory = [
        family_mass / counts[family]
        for family in families
    ]
    prior = [
        (1.0 - configured_mass) * weight
        for weight in exploratory
    ]
    prior[matches[0]] += configured_mass
    return tuple(prior)


class MixtureModel(OpponentModel):
    """Posterior-weighted mixture of urge hypotheses.

    ``distribution`` merges the components' exact distributions under
    their weights — still a pure function of the position, so search
    chance nodes and reply trimming treat it like any other model.
    """

    def __init__(self, components: list[tuple[UrgeModel, float]]):
        self.name = "mixture"
        self.components = components

    def distribution(
        self, board: chess.Board
    ) -> list[tuple[chess.Move, float]]:
        merged: dict[chess.Move, float] = {}
        for model, weight in self.components:
            for move, prob in model.distribution(board):
                merged[move] = merged.get(move, 0.0) + weight * prob
        return sorted(merged.items(), key=lambda kv: -kv[1])


class HypothesisPosterior:
    """Log-space Bayesian posterior over the hypothesis set."""

    def __init__(
        self,
        hypotheses: tuple[tuple[str, UrgeParams], ...] = HYPOTHESES,
        epsilon: float = EPSILON,
        prune: float = PRUNE,
        collapse: float = COLLAPSE,
        prior: tuple[float, ...] | None = None,
        families: tuple[str, ...] | None = None,
    ):
        if not hypotheses:
            raise ValueError("posterior needs at least one hypothesis")
        if families is None:
            families = (
                HYPOTHESIS_FAMILIES
                if hypotheses == HYPOTHESES
                else tuple(name for name, _params in hypotheses)
            )
        if len(families) != len(hypotheses):
            raise ValueError("every inference hypothesis needs a family")
        prior_was_uniform = prior is None
        if prior is None:
            prior = tuple(1.0 / len(hypotheses) for _ in hypotheses)
        if len(prior) != len(hypotheses):
            raise ValueError("prior length must match hypotheses")
        if any(weight <= 0.0 or not math.isfinite(weight) for weight in prior):
            raise ValueError("every prior weight must be finite and positive")
        total = sum(prior)
        prior = tuple(weight / total for weight in prior)

        self.hypotheses = hypotheses
        self.families = families
        self.models = [UrgeModel(name, params) for name, params in hypotheses]
        self.epsilon = epsilon
        self.prune = prune
        self.collapse = collapse
        self.prior = prior
        self.prior_rule = (
            "uniform-per-hypothesis" if prior_was_uniform else "explicit"
        )
        self.configured_mass: float | None = None
        self.log_w = [math.log(weight) for weight in prior]
        self.observations = 0
        self.collapse_at = 0  # first observation with MAP >= collapse

    @classmethod
    def from_belief(cls, belief: OpponentModel) -> "HypothesisPosterior":
        """Construct the production posterior anchored at ``belief``."""
        posterior = cls(prior=prior_for_belief(belief))
        posterior.prior_rule = "configured-point-plus-family-balanced"
        posterior.configured_mass = CONFIGURED_PRIOR_MASS
        return posterior

    def observe(self, board: chess.Board, move: chess.Move) -> None:
        """Bayes-update on one observed opponent move.

        ``board`` must be the position the opponent moved FROM. Cost is
        one ``distribution()`` per hypothesis per observed move — root
        frequency, not tree frequency; negligible next to search.
        """
        legal = board.legal_moves.count()
        if legal <= 1:
            return  # a forced reply carries no information
        floor = self.epsilon / legal
        for i, model in enumerate(self.models):
            prob = dict(model.distribution(board)).get(move, 0.0)
            self.log_w[i] += math.log(
                (1.0 - self.epsilon) * prob + floor
            )
        peak = max(self.log_w)
        self.log_w = [lw - peak for lw in self.log_w]  # keep floats sane
        self.observations += 1
        if self.collapse_at == 0 and max(self.weights()) >= self.collapse:
            self.collapse_at = self.observations

    def weights(self) -> list[float]:
        raw = [math.exp(lw) for lw in self.log_w]
        total = sum(raw)
        return [w / total for w in raw]

    def map_model(self) -> UrgeModel:
        """The maximum-a-posteriori hypothesis."""
        weights = self.weights()
        best = max(range(len(weights)), key=lambda i: (weights[i], -i))
        return self.models[best]

    def mixture_model(self) -> OpponentModel:
        """The posterior mixture over live (unpruned) hypotheses.

        Pruned components sit out and the survivors renormalize; a
        fully collapsed posterior therefore prices chance nodes at
        single-hypothesis cost — the mixture's early-game overhead
        buys itself back as soon as the opponent shows temperament.
        """
        weights = self.weights()
        live = [
            (model, weight)
            for model, weight in zip(self.models, weights)
            if weight >= self.prune
        ]
        if len(live) == 1:
            return live[0][0]
        total = sum(weight for _, weight in live)
        return MixtureModel(
            [(model, weight / total) for model, weight in live]
        )

    def configuration(self) -> dict:
        """JSON-ready inference configuration for citable reports."""
        return {
            "epsilon": self.epsilon,
            "prune": self.prune,
            "collapse": self.collapse,
            "prior_rule": self.prior_rule,
            "configured_mass": self.configured_mass,
            "hypotheses": [
                {
                    "name": name,
                    "family": family,
                    "params": asdict(params),
                    "prior": prior,
                }
                for (name, params), family, prior in zip(
                    self.hypotheses, self.families, self.prior
                )
            ],
        }

    def diagnostics(self) -> dict:
        """The gauges() payload: what the pinned report keeps.

        Rounded weights, because report.json is the artifact of record
        and sixteen digits of a dead hypothesis is noise, not evidence.
        """
        weights = self.weights()
        map_model = self.map_model()
        return {
            "posterior_observations": self.observations,
            "posterior_collapse_at": self.collapse_at,
            "posterior_live": sum(
                1 for weight in weights if weight >= self.prune
            ),
            "posterior_map": map_model.name,
            "posterior_map_weight": round(
                weights[self.models.index(map_model)], 4
            ),
            "posterior_weights": {
                model.name: round(weight, 4)
                for model, weight in zip(self.models, weights)
            },
        }

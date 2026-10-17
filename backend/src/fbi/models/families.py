"""Every model family the platform knows, active or planned, and why.

A family is ACTIVE when the backtest runs it; PLANNED when the architecture
has a place for it but the data does not justify training it yet - with the
condition that would change that written next to it. Adding a family is a
new entry here, a runner in fbi.backtesting.walkforward and a catalogue entry
in fbi.backtesting.persist; nothing else changes.

No family enters production because it exists: the model gate
(analytics.experiments.research_status) decides, and a family that does not
beat the market stays in RESEARCH.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Family:
    name: str
    registry_family: str
    """models.model_registry.family: baseline | rating | goals | ml | ensemble"""
    status: str
    """active | planned"""
    description: str
    features: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    requirements: str = ""


MNLOGIT_FEATURES = ("elo_diff", "pi_expected_gd", "sot_share_diff", "shot_share_diff", "elo_resid_diff",
                    "rest_diff", "league_home_gd_avg", "is_neutral")
MNLOGIT_SOURCE_FEATURES = ("elo_diff", "pi_expected_gd", "home_sot_share10", "away_sot_share10", "home_shot_share10",
                           "away_shot_share10", "home_elo_resid10", "away_elo_resid10", "home_rest_days",
                           "away_rest_days", "league_home_gd_avg", "is_neutral")
"""The feature-set columns the derived mnlogit inputs are computed from (lineage)."""

FAMILIES: tuple[Family, ...] = (
    Family("base_rates", "baseline", "active",
           "League home/draw/away frequencies over the training window (Laplace-smoothed): the no-skill reference "
           "every model must beat before it is compared with the market."),
    Family("poisson", "goals", "active", "Maher (1982) independent Poisson goals with time decay and shrinkage."),
    Family("dixon_coles", "goals", "active", "Dixon-Coles (1997): Poisson with the low-score dependence correction."),
    Family("elo_ologit", "rating", "active", "Elo V2 difference mapped to 1X2 by an ordered logit."),
    Family("mnlogit", "ml", "active",
           "Multinomial logistic regression (L2 = 1 on standardised features, fixed a priori) on the Elo difference, "
           "the pi-rating goal difference, shot and shot-on-target share differences, Elo-residual form, rest and "
           "the league's home advantage.",
           features=MNLOGIT_FEATURES, required=("elo_diff", "pi_expected_gd")),
    Family("gbm", "ml", "planned",
           "Gradient-boosted trees (CatBoost/LightGBM) on the same features - the strongest goals-only approach in "
           "the 2017 and 2023 soccer prediction challenges.",
           features=MNLOGIT_FEATURES,
           requirements="five or more seasons per competition in the training window (the paid backfill) and the "
                        "'ml' extra installed; expected gain modest (research matrix P2)"),
    Family("ensemble", "ensemble", "planned",
           "A calibrated pool of the active families, weights fitted on the validation season only.",
           requirements="two or more families inside the model confidence set on the validation season; a linear "
                        "pool must be recalibrated (Ranjan & Gneiting 2010)"),
)


def active() -> tuple[Family, ...]:
    return tuple(f for f in FAMILIES if f.status == "active")


def get(name: str) -> Family:
    for f in FAMILIES:
        if f.name == name:
            return f
    raise KeyError(name)


def mnlogit_row(values: dict[str, float | None]) -> list[float | None]:
    """The mnlogit feature vector derived from a fixture's feature set."""

    def diff(a: str, b: str) -> float | None:
        x, y = values.get(a), values.get(b)
        return None if x is None or y is None else float(x) - float(y)

    rest = diff("home_rest_days", "away_rest_days")
    return [
        values.get("elo_diff"),
        values.get("pi_expected_gd"),
        diff("home_sot_share10", "away_sot_share10"),
        diff("home_shot_share10", "away_shot_share10"),
        diff("home_elo_resid10", "away_elo_resid10"),
        None if rest is None else max(-7.0, min(7.0, rest)),
        values.get("league_home_gd_avg"),
        values.get("is_neutral"),
    ]

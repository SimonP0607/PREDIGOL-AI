"""The provider's own prediction is an auxiliary source: no feature, model, backtest, pick, parlay or validation
code may read it, and the user-facing API never serves it (only the admin route does)."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"
MODEL_AND_PICK_DIRS = ("features", "models", "research", "backtesting", "picks", "predictions", "validation",
                       "parlays", "analyst")
NAMES = ("provider_predictions", "apply_predictions", "ProviderPrediction")


def test_no_model_or_pick_code_names_the_providers_prediction() -> None:
    offenders = []
    for d in MODEL_AND_PICK_DIRS:
        for f in (SRC / d).rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            offenders += [f"{f.relative_to(SRC)}: {n}" for n in NAMES if n in text]
    assert offenders == [], offenders


def test_only_the_admin_router_serves_it() -> None:
    routers = SRC / "api" / "routers"
    serving = [f.name for f in routers.glob("*.py") if "provider_prediction" in f.read_text(encoding="utf-8")]
    assert serving == ["center.py"]
    text = (routers / "center.py").read_text(encoding="utf-8")
    route = text[text.index('"/matches/{fixture_id}/provider-prediction"') - 40:]
    assert route.lstrip().startswith("@admin_router.get") or "@admin_router.get(" in route[:60]

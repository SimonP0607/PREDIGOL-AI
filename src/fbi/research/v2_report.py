"""Research V2 as a report a person reads: JSON (complete) and Markdown (the tables)."""

from __future__ import annotations

from typing import Any

from fbi.backtesting.persist import comparison_json, scores_json
from fbi.features.engine import FEATURE_VERSION
from fbi.research.prospective import MIN_SEGMENT
from fbi.research.v2 import V2Result
from fbi.research.v2_record import prospective_role


def _f(x: float | None, digits: int = 4, signed: bool = False) -> str:
    if x is None:
        return "-"
    return f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}"


def _pct(x: float | None, digits: int = 1) -> str:
    return "-" if x is None else f"{100 * x:+.{digits}f}%"


def report_json(result: V2Result) -> dict[str, Any]:
    s = result.session
    ev = s.evaluation
    return {
        "feature_version": FEATURE_VERSION,
        "data_as_of": None if result.data_as_of is None else result.data_as_of.isoformat(),
        "seconds": round(result.seconds, 1),
        "competitions": [{"id": i, "name": n} for i, n in s.competitions],
        "validation_season": s.cfg.validation_season, "test_season": s.cfg.test_season,
        "targets": len(ev.targets), "dataset_hash": ev.dataset_hash,
        "champion": {"key": result.champion.key, "n_common": result.champion.n_common,
                     "logloss": result.champion.logloss},
        "selection": s.selection,
        "models": [{
            "model": e.run.model, "spec": e.run.spec, "coverage": e.coverage, "scores": scores_json(e.own),
            "comparisons": [comparison_json(c) for c in e.comparisons],
            "ou": scores_json(e.ou), "btts": scores_json(e.btts),
            "blends": {k: b.as_json() for k, b in result.blends.get(e.run.model, {}).items()},
            "role": result.roles[e.run.model].role, "role_reason": result.roles[e.run.model].reason,
        } for e in ev.models],
        "audit": None if result.audit is None else result.audit.as_json(),
        "prospective": None if result.prospective is None else result.prospective.as_json(),
        "qualified_models": sum(1 for r in result.roles.values() if r.role == "CHALLENGER"),
    }


def report_markdown(result: V2Result, *, title: str) -> str:
    s = result.session
    ev = s.evaluation
    champ = result.champion
    lines = [f"# {title}", "",
             f"Feature version `{FEATURE_VERSION}` (validated history). Data as of "
             f"{'-' if result.data_as_of is None else result.data_as_of.strftime('%d %b %Y %H:%M UTC')}. "
             f"Validation season {s.cfg.validation_season}, test season {s.cfg.test_season}, "
             f"{len(ev.targets)} test fixtures in {', '.join(n for _, n in s.competitions)}. "
             f"Run time {result.seconds / 60:.1f} min.", "",
             "## E1 - the market champion", "",
             f"Every de-vigged 1X2 baseline on the {champ.n_common} fixtures all of them priced.", "",
             "| Baseline | Log loss | vs champion |", "|---|---:|---:|"]
    best = champ.logloss.get(champ.key, 0.0)
    for key, ll in sorted(champ.logloss.items(), key=lambda kv: kv[1]):
        mark = " **CHAMPION**" if key == champ.key else ""
        lines.append(f"| `{key}`{mark} | {ll:.5f} | {ll - best:+.5f} |")
    lines += ["", "## Models against the champion (1X2, walk-forward, test season)", "",
              "Difference = model minus champion log loss on the fixtures both priced (negative is better), "
              "95% interval resampling match days. Blend weight *w*: 0 = the market alone; its interval above 0 = "
              "the model adds information. Blend: the validation-fitted weight applied to the test season.", "",
              "| Model | Predicted | Log loss | vs champion [95%] | ECE | w (test) [95%] | Blend vs champion [95%] "
              "| Role |", "|---|---:|---:|---|---:|---|---|---|"]
    for e in ev.models:
        m = e.run.model
        c = result.vs_champion(m)
        b = result.blends.get(m, {}).get(champ.key)
        diff = "-" if c is None else (f"{c.logloss_diff.mean:+.4f} [{c.logloss_diff.lo:+.4f}, "
                                      f"{c.logloss_diff.hi:+.4f}]")
        w = "-" if b is None else f"{b.w_test:+.3f} [{b.w_test_lo:+.3f}, {b.w_test_hi:+.3f}]"
        bl = ("-" if b is None or b.diff_mean is None or b.diff_lo is None or b.diff_hi is None else
              f"{b.diff_mean:+.4f} [{b.diff_lo:+.4f}, {b.diff_hi:+.4f}]")
        lines.append(f"| {m} | {len(e.run.predictions)}/{e.n_targets} | {_f(None if e.own is None else e.own.log_loss, 5)}"
                     f" | {diff} | {_f(None if e.own is None else e.own.ece)} | {w} | {bl} | "
                     f"**{result.roles[m].role}** |")
    lines += ["", "Against the price available at pick time (de-vigged average pre-closing odds):", "",
              "| Model | w (test) [95%] | Blend vs pre-closing [95%] |", "|---|---|---|"]
    for e in ev.models:
        b = result.blends.get(e.run.model, {}).get("AVG/pre_closing/shin")
        if b is None:
            continue
        bl = ("-" if b.diff_mean is None or b.diff_lo is None or b.diff_hi is None else
              f"{b.diff_mean:+.4f} [{b.diff_lo:+.4f}, {b.diff_hi:+.4f}]")
        lines.append(f"| {e.run.model} | {b.w_test:+.3f} [{b.w_test_lo:+.3f}, {b.w_test_hi:+.3f}] | {bl} |")
    lines += ["", "Roles, with their evidence:", ""]
    for m, r in result.roles.items():
        lines.append(f"* **{m}** - {r.role}: {r.reason}")
    if result.audit is not None:
        a = result.audit
        lines += ["", "## E0 - the shadow picks' returns: price, edge or luck", "",
                  "Per settled pick, against the last de-vigged consensus before kick-off "
                  f"(median {_f(a.median_minutes_before, 0)} min before): EV at the close = what the bet was worth "
                  "by the market's view; luck = realised minus that. Means per one-unit pick, with standard errors.",
                  "", "| Odds | Picks | Mean odds | Realised ROI | Claimed EV | EV at the close | Luck |",
                  "|---|---:|---:|---|---:|---|---|"]

        def row(label: str, g: dict[str, Any]) -> str:
            return (f"| {label} | {g['n']} | {_f(g['mean_odds'], 2)} | {_pct(g['roi'])} ± {_pct(g['roi_se'])[1:]} | "
                    f"{_pct(g['claimed_ev'])} | {_pct(g['ev_at_close'])} ± {_pct(g['ev_at_close_se'])[1:]} | "
                    f"{_pct(g['luck'])} ± {_pct(g['luck_se'])[1:]} |")

        for k, g in a.by_odds.items():
            lines.append(row(k, g))
        lines.append(row("**all**", a.overall))
        lines += ["", "| Market | Picks | Realised ROI | EV at the close | Luck |", "|---|---:|---|---|---|"]
        for k, g in a.by_market.items():
            lines.append(f"| {k} | {g['n']} | {_pct(g['roi'])} ± {_pct(g['roi_se'])[1:]} | "
                         f"{_pct(g['ev_at_close'])} ± {_pct(g['ev_at_close_se'])[1:]} | "
                         f"{_pct(g['luck'])} ± {_pct(g['luck_se'])[1:]} |")
    if result.prospective is not None:
        p = result.prospective
        lines += ["", f"## Prospective - forecasts stored before kick-off, {p.since:%d %b} to {p.until:%d %b %Y}", "",
                  f"{p.played} matches played and validated, {p.priced} with a closing 1X2 consensus of 2+ books. "
                  f"A segment with fewer than {MIN_SEGMENT} matches is reported, not judged.", "",
                  "| Segment | Model | Matches | Model LL | Close LL | Difference [95%] | w [95%] | Reading |",
                  "|---|---|---:|---:|---:|---|---|---|"]
        for sr in sorted(p.rows, key=lambda x: (x.segment != "all", x.segment, x.model)):
            c = sr.comparison
            if c is None:
                continue
            diff = f"{c.logloss_diff.mean:+.4f} [{c.logloss_diff.lo:+.4f}, {c.logloss_diff.hi:+.4f}]"
            w = "-" if sr.w is None else f"{sr.w[0]:+.2f} [{sr.w[1]:+.2f}, {sr.w[2]:+.2f}]"
            lines.append(f"| {sr.segment} | {sr.model} | {sr.n_common} | {c.model.log_loss:.4f} | "
                         f"{c.baseline.log_loss:.4f} | {diff} | {w} | {prospective_role(sr)[0]} |")
    challengers = [m for m, r in result.roles.items() if r.role == "CHALLENGER"]
    lines += ["", "## Qualification", "",
              (f"Challengers: {', '.join(challengers)} - each waits for an explicit promotion." if challengers else
               "**No model beats the market or adds information to it: qualified picks stay at 0.** Picks remain "
               "shadow (evaluation mode, owner only).")]
    return "\n".join(lines) + "\n"

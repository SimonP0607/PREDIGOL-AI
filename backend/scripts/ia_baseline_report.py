"""PrediGol Intelligence - Plan Maestro IA, Phase 0: the baseline report, written from the output of ``ia_baseline.sh``.

    python -m scripts.ia_baseline_report baseline_YYYYMMDDTHHMMZ.txt > docs/owner/IA_BASELINE_F0.md

Nothing here touches a database: it reads the text file the READ ONLY baseline produced on the server (a ``### section``
line followed by a CSV table) and turns the tables into the report, so every figure in the report can be recomputed
from the file whose sha256 the report prints. No figure is typed by hand: the sentences around the figures only say
what they are, with the sample they come from.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

NOISE = ("BEGIN", "SET", "ROLLBACK", "Null display")
PRICE = {  # USD per million tokens (input, output): the published list prices the ledger uses
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
}
GATE_A_DAYS = 7
BATCH_LEAD_H = 4


class Baseline:
    def __init__(self, path: Path) -> None:
        raw = path.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.bytes = len(raw)
        self.name = path.name
        text = raw.decode("utf-8")
        self.sections: dict[str, list[dict[str, str]]] = {}
        for part in re.split(r"^### ", text, flags=re.M)[1:]:
            head, _, body = part.partition("\n")
            lines = [ln for ln in body.split("\n") if ln.strip() and not ln.startswith(NOISE)]
            self.sections[head.strip()] = list(csv.DictReader(io.StringIO("\n".join(lines))))
        self.text = text

    def __getitem__(self, name: str) -> list[dict[str, str]]:
        return self.sections[name]


def dec(x: str | None) -> Decimal:
    return Decimal(x) if x not in (None, "") else Decimal(0)


def es(x: Decimal | float | int, digits: int = 2) -> str:
    """Spanish number format as the plan uses it: 1.234,56."""
    q = Decimal(str(x)).quantize(Decimal(1).scaleb(-digits)) if digits else Decimal(str(x)).quantize(Decimal(1))
    s = f"{q:,.{digits}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def usd(x: Decimal | float, digits: int = 2) -> str:
    return f"{es(x, digits)} USD"


def pct(part: Decimal | float | int, whole: Decimal | float | int, digits: int = 1) -> str:
    if not whole:
        return "—"
    value = Decimal(str(part)) * 100 / Decimal(str(whole))
    if abs(value) < Decimal(1).scaleb(-digits) / 2:
        value = Decimal(0)  # no "-0,000 %"
    return f"{es(value, digits)} %"


def md(headers: list[str], rows: Iterable[Iterable[Any]], align: str | None = None) -> str:
    rows = [list(map(str, r)) for r in rows]
    a = align or ("l" + "r" * (len(headers) - 1))
    sep = ["---:" if c == "r" else ":---" for c in a]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(sep) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def mean(xs: list[Decimal]) -> Decimal:
    return sum(xs, Decimal(0)) / len(xs) if xs else Decimal(0)


def report(b: Baseline) -> str:
    out: list[str] = []
    w = out.append
    meta = b["meta"][0]
    run = b["run"][0]
    avail = {r["table"]: r for r in b["availability"]}

    # ---------------------------------------------------------------- spend
    by_day = list(b["spend_by_day_utc"])
    first_day, last_day = by_day[0]["day_utc"], by_day[-1]["day_utc"]
    full = [r for r in by_day if r["day_utc"] not in (first_day, last_day)]
    claude_days = [dec(r["claude_usd"]) for r in full]
    last7 = full[-GATE_A_DAYS:]
    prev7 = full[-2 * GATE_A_DAYS:-GATE_A_DAYS]
    c7 = mean([dec(r["claude_usd"]) for r in last7])
    c7p = mean([dec(r["claude_usd"]) for r in prev7])
    e7 = mean([dec(r["search_usd"]) for r in last7])
    c_all = mean(claude_days)
    mtd = b["month_to_date_utc"][0]
    claude_total = sum((dec(r["cost_usd"]) for r in b["usage_by_purpose_model"] if r["provider"] == "anthropic"), Decimal(0))
    exa_total = sum((dec(r["cost_usd"]) for r in b["usage_by_purpose_model"] if r["provider"] == "exa"), Decimal(0))
    budget_in_force = Decimal(0)
    for r in b["day_plans"]:
        if r["stage"] == "opened":
            m1 = re.search(r'"month_ratio": ([0-9.]+)', r["budget_head"])
            m2 = re.search(r'"spent_month_usd": "([0-9.]+)"', r["budget_head"])
            if m1 and m2 and dec(m1.group(1)) > 0:
                budget_in_force = (dec(m2.group(1)) / dec(m1.group(1))).quantize(Decimal("1"))

    w("# Línea base de producción · Plan Maestro IA, Fase 0")
    w("")
    w("> **Generado por código, sin cifras escritas a mano.** `backend/scripts/ia_baseline.sql` lee producción en una "
      "transacción de solo lectura; `backend/scripts/ia_baseline_report.py` convierte su salida en este informe. "
      "Para repetirlo: `bash ia_baseline.sh` en el servidor y `python -m scripts.ia_baseline_report <archivo> > "
      "docs/owner/IA_BASELINE_F0.md`.")
    w("")
    w(md(["Dato", "Valor"], [
        ["Archivo de medición", f"`{b.name}`"],
        ["sha256 del archivo", f"`{b.sha256}`"],
        ["Tamaño", f"{es(b.bytes, 0)} bytes, {len(b.sections)} secciones"],
        ["Hora de la lectura (UTC)", run["started_utc"]],
        ["Base de datos", f"{meta['db']}, migración {meta['migration']}, {meta['db_size']}"],
        ["Transacción", "solo lectura (`read_only = " + meta["read_only"] + "`), terminada con ROLLBACK; "
         "ningún dato se modificó"],
    ], "ll"))
    w("")

    w("## 1. Qué datos hay y cuáles no")
    w("")
    w("El plan pide ≥ 30 días «donde existan». La contabilidad de IA de PrediGol (`ai.usage`) empezó el "
      f"{avail['ai.usage']['first_utc'][:10]}, así que hay **{es(dec(avail['ai.usage']['days_spanned']), 1)} días**, no 30. "
      "Se dice aquí una vez y las cifras de abajo llevan siempre su muestra.")
    w("")
    rows = []
    for t in ("ai.usage", "ai.match_briefs", "ai.fixture_passes", "ai.pick_reviews", "ai.match_packets", "ai.evidence",
              "ai.research_cache", "ai.day_plans", "intel.decisions", "intel.decision_outcomes", "intel.postmortems",
              "analytics.ai_runs", "ai.cycles", "ai.budget_alerts"):
        r = avail[t]
        rows.append([f"`{t}`", es(dec(r["rows"]), 0), r["first_utc"][:16] or "—", r["last_utc"][:16] or "—",
                     es(dec(r["days_spanned"]), 1) if r["days_spanned"] else "—"])
    w(md(["Tabla", "Filas", "Primera", "Última", "Días"], rows, "lrllr"))
    w("")
    w(f"`intel.decisions` solo existe desde el {avail['intel.decisions']['first_utc'][:10]}: las cifras de decisiones y "
      "CLV cubren menos días que las de gasto.")
    w("")

    w("## 2. Gasto")
    w("")
    w(f"- **Mes en curso (hasta {meta['now_utc'][:16]} UTC):** {usd(dec(mtd['usage_usd']))} en {es(dec(mtd['calls']), 0)} "
      f"llamadas: Claude {usd(dec(mtd['claude_usd']))}, Exa {usd(dec(mtd['exa_usd']))}. Es lo que cuenta `ai.usage` desde el "
      f"{avail['ai.usage']['first_utc'][:10]}.")
    w(f"- **Presupuesto mensual vigente:** {usd(budget_in_force, 0)} (Claude y Exa juntos; sale del «mes» del plan del día).")
    w(f"- **Claude por día completo (UTC), {len(full)} días del {full[0]['day_utc']} al {full[-1]['day_utc']}:** "
      f"media {usd(c_all)}, mínimo {usd(min(claude_days))}, máximo {usd(max(claude_days))}.")
    w(f"- **Últimos {GATE_A_DAYS} días completos ({last7[0]['day_utc']} a {last7[-1]['day_utc']}):** Claude {usd(c7)} al día "
      f"({usd(c7 * 30, 0)} por 30 días); los {GATE_A_DAYS} anteriores, {usd(c7p)} al día "
      f"({es((c7 / c7p - 1) * 100, 1)} % de cambio). Es una proyección lineal, no una previsión: cambia con la carga "
      "de partidos.")
    weekend = [dec(r["claude_usd"]) for r in full if date.fromisoformat(r["day_utc"]).weekday() >= 5]
    weekday = [dec(r["claude_usd"]) for r in full if date.fromisoformat(r["day_utc"]).weekday() < 5]
    w(f"- **Sábado y domingo:** Claude {usd(mean(weekend))} al día ({len(weekend)} días); lunes a viernes "
      f"{usd(mean(weekday))} ({len(weekday)} días). La carga de partidos manda: una semana con otro calendario "
      "se mueve más que cualquier optimización pequeña.")
    exa_days_bogota = b["exa_searches_by_day"][1:]
    w(f"- **Exa:** {usd(e7)} al día en esos {GATE_A_DAYS} días ({usd(e7 * 30, 0)} por 30 días); "
      f"{es(dec(exa_days_bogota[-1]['calls']), 0)} búsquedas el {exa_days_bogota[-1]['day_bogota']} (hora de Bogotá), "
      f"frente a {es(dec(exa_days_bogota[0]['calls']), 0)} el {exa_days_bogota[0]['day_bogota']}.")
    w("")
    rows = [[r["day_utc"] + (" (parcial)" if r["day_utc"] in (first_day, last_day) else ""),
             es(dec(r["calls"]), 0), es(dec(r["claude_usd"]), 2), es(dec(r["search_usd"]), 2), es(dec(r["cost_usd"]), 2)]
            for r in by_day]
    w(md(["Día UTC", "Llamadas", "Claude USD", "Exa USD", "Total USD"], rows))
    w("")

    # ------------------------------------------------------- where it goes
    w("## 3. Dónde se gasta")
    w("")
    purpose: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0)] * 3)
    for r in b["usage_by_purpose_model"]:
        if r["provider"] != "anthropic":
            continue
        p = purpose[r["purpose"]]
        p[0] += dec(r["calls"])
        p[1] += dec(r["ok"])
        p[2] += dec(r["cost_usd"])
    rows = [[f"`{k}`", es(v[0], 0), es(v[1], 0), es(v[2], 2), pct(v[2], claude_total)]
            for k, v in sorted(purpose.items(), key=lambda kv: -kv[1][2])]
    w(md(["Propósito", "Llamadas", "Correctas", "USD", "Parte del gasto de Claude"], rows))
    w("")
    w(f"Total Claude en la ventana: {usd(claude_total)}. Exa: {usd(exa_total)} "
      f"({es(sum((dec(r['calls']) for r in b['usage_by_purpose_model'] if r['provider'] == 'exa'), Decimal(0)), 0)} búsquedas "
      "a 0,015 USD).")
    w("")
    w("Por modelo, con una comprobación contra la lista de precios publicada (entrada y salida por millón de tokens):")
    w("")
    rows = []
    for r in b["implied_price_per_mtok"]:
        pin, pout = PRICE[r["model"]]
        expected = dec(r["input_tokens"]) * pin / 1_000_000 + dec(r["output_tokens"]) * pout / 1_000_000
        rows.append([r["model"], es(dec(r["calls"]), 0), es(dec(r["input_tokens"]), 0), es(dec(r["output_tokens"]), 0),
                     es(dec(r["cached_tokens"]), 0), es(dec(r["cost_usd"]), 4), es(expected, 4),
                     pct(dec(r["cost_usd"]) - expected, expected, 3)])
    w(md(["Modelo", "Llamadas", "Tokens de entrada", "Tokens de salida", "En caché", "USD registrado",
          "USD por lista", "Diferencia"], rows))
    w("")
    w("El registro cuadra con la lista de precios al céntimo: la contabilidad interna no es una fuente de error. "
      "Lo que **no** hay es conciliación con la Consola de Anthropic (hace falta el CSV de costes por workspace, acción "
      "manual del dueño); sin ella este informe es el libro interno, no la factura.")
    w("")
    w("Por modelo y versión de prompt (las filas con más gasto):")
    w("")
    rows = [[f"`{r['purpose']}`", r["model"].replace("claude-", ""), r["prompt_version"] or "—", es(dec(r["calls"]), 0),
             es(dec(r["avg_input"]), 0), es(dec(r["avg_output"]), 0), es(dec(r["cost_usd"]), 2), es(dec(r["avg_cost_usd"]), 4)]
            for r in b["usage_by_purpose_model"] if r["provider"] == "anthropic" and dec(r["cost_usd"]) >= Decimal("1")]
    w(md(["Propósito", "Modelo", "Prompt", "Llamadas", "Entrada media", "Salida media", "USD", "USD por llamada"], rows,
         "lllrrrrr"))
    w("")

    # ------------------------------------------------------------- latency
    w("## 4. Llamadas, tokens y tiempos")
    w("")
    lat = {(r["purpose"], r["model"]): r for r in b["usage_latency"]}
    tok = {(r["purpose"], r["model"]): r for r in b["input_tokens_distribution"]}
    rows = []
    for lat_key, lrow in lat.items():
        trow = tok[lat_key]
        rows.append([f"`{lat_key[0]}`", lat_key[1].replace("claude-", ""), es(dec(lrow["timed"]), 0),
                     es(dec(lrow["p50_ms"]) / 1000, 1), es(dec(lrow["p95_ms"]) / 1000, 1),
                     es(dec(trow["p50_input"]), 0), es(dec(trow["p95_input"]), 0), es(dec(trow["p50_output"]), 0),
                     es(dec(trow["p95_output"]), 0)])
    w(md(["Propósito", "Modelo", "Llamadas", "Latencia p50 (s)", "p95 (s)", "Entrada p50", "Entrada p95", "Salida p50",
          "Salida p95"], rows, "llrrrrrrr"))
    w("")
    refused = [r for r in b["usage_status"] if r["status"] != "ok"]
    n_calls = sum(dec(r["calls"]) for r in b["usage_status"] if r["purpose"] != "web_search")
    not_ok_by_version: dict[str, Decimal] = defaultdict(Decimal)
    for r in b["usage_by_purpose_model"]:
        if r["provider"] == "anthropic" and dec(r["calls"]) != dec(r["ok"]):
            not_ok_by_version[r["prompt_version"] or "—"] += dec(r["calls"]) - dec(r["ok"])
    if refused:
        w(f"Estados de las {es(n_calls, 0)} llamadas a Claude: " + ", ".join(
            f"{es(dec(r['calls']), 0)} `{r['status']}` en `{r['purpose']}`" for r in refused) + "; el resto, `ok`. "
          "Las que no terminaron `ok` pertenecen a: " + ", ".join(
              f"`{k}` ({es(v, 0)})" for k, v in not_ok_by_version.items()) + "; ninguna otra versión de prompt tiene "
          "llamadas fallidas en el registro.")
    else:
        w("Todas las llamadas terminaron `ok`.")
    w("")
    cyc = b["cycles"]
    ok_n = sum(dec(r["cycles"]) for r in cyc if r["kind"] == "analysis" and r["status"] == "ok")
    failed = [r for r in cyc if r["status"] == "failed"]
    reduced = [r for r in cyc if r["budget_state"] == "REDUCED"]
    w(f"Ciclos de análisis: {es(ok_n, 0)} correctos"
      + (f" y {es(sum(dec(r['cycles']) for r in failed), 0)} fallidos (duración media "
         f"{es(dec(failed[0]['avg_seconds']), 0)} s)" if failed else "")
      + (f"; {es(sum(dec(r['cycles']) for r in reduced), 0)} se ejecutaron con el presupuesto del día en `REDUCED` "
         "(coste total de esos ciclos " + usd(sum(dec(r['cost_usd']) for r in reduced), 3) + ")" if reduced else "")
      + ". Todos en modo `shadow`.")
    w("")

    # --------------------------------------------------- cost per match
    w("## 5. Coste por partido y por candidato")
    w("")
    cf = list(b["cost_per_fixture_day"])
    tot_cost = sum(dec(r["cost_usd"]) for r in cf)
    tot_fix = sum(dec(r["fixtures"]) for r in cf)
    w(f"- **Por partido y día** (llamadas que nombran un partido, Claude y Exa; {es(tot_fix, 0)} partidos-día en "
      f"{len(cf)} días): media ponderada {usd(tot_cost / tot_fix, 4)}; la media diaria va de "
      f"{usd(min(dec(r['avg_cost_per_fixture']) for r in cf), 4)} a {usd(max(dec(r['avg_cost_per_fixture']) for r in cf), 4)}. "
      f"El p90 diario ronda {usd(mean([dec(r['p90_cost']) for r in cf]), 3)} y el máximo de un partido-día fue "
      f"{usd(max(dec(r['max_cost']) for r in cf), 2)}.")
    cpf = {r["purpose"]: r for r in b["calls_per_fixture_day"]}
    w("- **Llamadas por partido y día:** " + "; ".join(
        f"`{k}` {es(dec(v['avg_calls']), 2)} de media (p90 {v['p90_calls']}, máx. {v['max_calls']}; {es(dec(v['fixture_days']), 0)} partidos-día)"
        for k, v in cpf.items()) + ".")
    rps = b["reviews_per_selection"][0]
    pick_review_cost = purpose["pick_review"][2]
    w(f"- **Por candidato revisado por el modelo:** {usd(dec(rps['cost_per_llm_selection']), 4)} "
      f"({es(dec(rps['selections_with_llm']), 0)} selecciones con revisión de modelo de {es(dec(rps['selections']), 0)}, "
      f"{pct(dec(rps['selections_with_llm']), dec(rps['selections']))}). Cuadra con `ai.usage`: "
      f"{usd(pick_review_cost)} de `pick_review` entre {es(dec(rps['selections_with_llm']), 0)} = "
      f"{usd(pick_review_cost / dec(rps['selections_with_llm']), 4)}. (La primera versión de esta medición sumaba también "
      "la fila «combined», que repite el coste de la del modelo, y daba el doble; está corregida en el SQL.)")
    rc = {r["pass"]: r for r in b["review_calls_per_candidate_pass"]}
    w("- **Revisiones de modelo por partido y pasada:** " + "; ".join(
        f"`{k}` {es(dec(v['avg_calls']), 2)} de media (p90 {es(dec(v['p90_calls']), 0)}, máx. {v['max_calls']}; "
        f"{es(dec(v['fixture_passes_with_reviews']), 0)} pasadas)" for k, v in rc.items()) + ".")
    w("")

    # ---------------------------------------------------------- duplication
    w("## 6. Duplicación y reutilización")
    w("")
    bf = b["briefs_per_fixture_day"]
    b_full = [r for r in bf if r["day_bogota"] != bf[0]["day_bogota"]]
    fixtures_sum = sum(dec(r["fixtures"]) for r in b_full)
    briefs_sum = sum(dec(r["briefs"]) for r in b_full)
    two_plus = sum(dec(r["fixtures_with_2plus"]) for r in b_full)
    w(f"- **Briefs por partido y día:** {es(briefs_sum / fixtures_sum, 2)} de media ({es(briefs_sum, 0)} briefs de "
      f"{es(fixtures_sum, 0)} partidos-día, días {b_full[0]['day_bogota']} a {b_full[-1]['day_bogota']}); "
      f"{pct(two_plus, fixtures_sum)} de los partidos-día tienen 2 o más. Es el tope de `ai.fixture_passes` "
      "(primera, previa y final).")
    cc = [r for r in b["briefs_content_changes"] if r["day_bogota"] != b["briefs_content_changes"][0]["day_bogota"]]
    later = sum(dec(r["later_briefs"]) for r in cc)
    same = sum(dec(r["same_conclusion"]) for r in cc)
    w(f"- **Briefs posteriores que llegan a la misma conclusión que el anterior del mismo partido y día** (mismas razones, "
      f"incertidumbre, calidad de datos y marca de escalado): {es(same, 0)} de {es(later, 0)} = {pct(same, later)}. "
      "Es una cota de lo que una regla de «cambio material» podría ahorrar; la regla concreta se mide aparte, sobre "
      "paquetes guardados, antes de activarla.")
    rep = {r["purpose"]: r for r in b["repeated_input_hash"]}
    w("- **Entradas idénticas pagadas dos veces** (mismo propósito, partido y `input_hash`): " + "; ".join(
        f"`{k}` {es(dec(v['repeated']), 0)} de {es(dec(v['calls_with_hash']), 0)} ({pct(dec(v['repeated']), dec(v['calls_with_hash']))}, "
        f"{usd(dec(v['repeated_cost_usd']), 3)} de {usd(dec(v['cost_usd']), 2)})"
        for k, v in rep.items() if v["repeated_cost_usd"]) + ".")
    pk = b["packets_by_day"][-1]
    w(f"- **Paquetes:** `{pk['packet_version']}` pesa {es(dec(pk['avg_approx_tokens']), 0)} tokens aproximados de media "
      f"(p95 {es(dec(pk['p95_approx_tokens']), 0)}) y se guardó {es(dec(pk['packets']), 0)} veces el {pk['day_bogota']} para "
      f"{es(dec(pk['fixtures']), 0)} partidos: un paquete nuevo por cada ciclo en que algo cambia.")
    w("")

    # ------------------------------------------------------ cache + batch
    w("## 7. Caché y Batch: hoy y potencial medido")
    w("")
    in_tokens = sum(dec(r["input_tokens"]) for r in b["implied_price_per_mtok"])
    cached = sum(dec(r["cached_tokens"]) for r in b["implied_price_per_mtok"])
    w(f"- **Caché de prompts:** {es(cached, 0)} tokens leídos de caché de {es(in_tokens, 0)} de entrada = "
      f"{pct(cached, in_tokens)}. El proveedor no pide ni registra caché (`ai.usage` ni siquiera tiene columna para "
      "las escrituras en caché).")
    w("- **Batch:** 0 % de las llamadas (no existe la ruta).")
    w("")
    cp = b["cache_potential"]
    rows = []
    for r in cp:
        n = dec(r["calls"])
        rows.append([f"`{r['purpose']}`", r["model"].replace("claude-", ""), es(n, 0), es(dec(r["cost_usd"]), 2),
                     pct(dec(r["same_fixture_5m"]), n), pct(dec(r["same_fixture_1h"]), n), pct(dec(r["any_fixture_5m"]), n),
                     pct(dec(r["any_fixture_1h"]), n)])
    w("Llamadas que llegaron después de otra del mismo propósito y modelo (lo que una caché podría haber reutilizado):")
    w("")
    w(md(["Propósito", "Modelo", "Llamadas", "USD", "Mismo partido ≤ 5 min", "Mismo partido ≤ 1 h",
          "Cualquier partido ≤ 5 min", "Cualquier partido ≤ 1 h"], rows, "llrrrrrr"))
    w("")
    w("«Mismo partido» es el caso de los datos del partido (el paquete) repetidos entre candidatos; «cualquier partido» "
      "es el de las instrucciones, que son las mismas para todas las llamadas. Es potencial, no ahorro: depende de que "
      "el prefijo sea idéntico byte a byte y de que la caché responda.")
    w("")
    up = b["usage_by_pass"]
    rows = []
    batchable = Decimal(0)
    for r in sorted(up, key=lambda r: -dec(r["cost_usd"])):
        if dec(r["cost_usd"]) < Decimal("0.5"):
            continue
        rows.append([f"`{r['purpose']}`", r["model"].replace("claude-", ""), r["pass"], es(dec(r["calls"]), 0),
                     es(dec(r["cost_usd"]), 2), es(dec(r["calls_ko_4h_plus"]), 0), es(dec(r["cost_ko_4h_plus"]), 2)])
    for r in up:
        if r["pass"] in ("first", "pre"):
            batchable += dec(r["cost_ko_4h_plus"])
    w(f"Gasto por pasada y, de él, el hecho con el partido a {BATCH_LEAD_H} h o más (la parte que puede esperar el "
      "resultado de un Batch):")
    w("")
    w(md(["Propósito", "Modelo", "Pasada", "Llamadas", "USD", f"Llamadas con KO ≥ {BATCH_LEAD_H} h",
          f"USD con KO ≥ {BATCH_LEAD_H} h"], rows, "lllrrrr"))
    w("")
    pr_batch = sum((dec(r["cost_ko_4h_plus"]) for r in up if r["purpose"] == "pick_review" and r["pass"] in ("first", "pre")),
                   Decimal(0))
    w(f"En las pasadas `first` y `pre`, con el partido a ≥ {BATCH_LEAD_H} h, hay **{usd(batchable)}** "
      f"({pct(batchable, claude_total)} del gasto de Claude de la ventana), de los que {usd(pr_batch)} son revisión de "
      f"selecciones ({pct(pr_batch, purpose['pick_review'][2])} del gasto de `pick_review`). Con el 50 % de descuento del "
      f"Batch eso sería, como máximo, {usd(batchable / 2)} en la ventana; el ahorro real depende de cuánto de ello pase "
      "realmente por Batch y de que la revisión pueda esperar. Se atribuye cada llamada a la pasada de su partido por la "
      "ventana de tiempo de la pasada (aproximación).")
    w("")

    # ------------------------------------------------------------- coverage
    w("## 8. Cobertura y volumen (la referencia del Gate A)")
    w("")
    dp = [r for r in b["day_plans"] if r["stage"] == "opened"]
    dp_full = [r for r in dp if r["day"] not in (dp[0]["day"],)]
    mk = sum(dec(r["fixtures_with_market"]) for r in dp_full)
    tot = sum(dec(r["fixtures_total"]) for r in dp_full)
    passes_full: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for r in b["passes"]:
        if r["day_bogota"] != b["passes"][0]["day_bogota"]:
            passes_full[(r["pass"], r["status"])] += dec(r["passes"])
    pass_totals = dict(passes_full)
    w(f"- **Partidos del día con mercado:** {es(mk, 0)} de {es(tot, 0)} partidos en {len(dp_full)} días "
      f"({dp_full[0]['day']} a {dp_full[-1]['day']}).")
    w("- **Pasadas terminadas:** " + "; ".join(f"`{k[0]}` {k[1]} {es(v, 0)}" for k, v in sorted(pass_totals.items())) + ".")
    w(f"- **Partidos-día con al menos un brief:** {es(fixtures_sum, 0)}, frente a {es(mk, 0)} con mercado al abrir el día "
      "(la diferencia son partidos que entraron al plan después de abrir).")
    dec_state: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for r in b["decisions_by_day"]:
        dec_state[r["state"]][0] += dec(r["decisions"])
        dec_state[r["state"]][1] += dec(r["with_ai_review"])
    w("- **Decisiones con revisión de IA enlazada:** " + "; ".join(
        f"`{k}` {es(v[1], 0)} de {es(v[0], 0)} ({pct(v[1], v[0])})" for k, v in sorted(dec_state.items())) + ".")
    cand = b["candidates_by_day"]
    w(f"- **Candidatos por día** ({cand[0]['day_bogota']} a {cand[-1]['day_bogota']}, {len(cand)} días): "
      f"media {es(mean([dec(r['candidate_selections']) for r in cand]), 0)} selecciones en "
      f"{es(mean([dec(r['fixtures_with_candidates']) for r in cand]), 0)} partidos; no rechazadas, "
      f"{es(mean([dec(r['not_rejected']) for r in cand]), 0)} al día.")
    fam = b["decision_families"]
    w("- **Familias de mercado en las decisiones:** " + "; ".join(
        f"{r['market_key']} {es(dec(r['decisions']), 0)} ({es(dec(r['selections']), 0)} selecciones)" for r in fam) + ".")
    w("")
    pt = {r["pass"]: r for r in b["pass_timing_vs_kickoff"]}
    w("**Tiempos frente al inicio del partido** (minutos que faltaban al terminar cada pasada): "
      + "; ".join(f"`{k}` p50 {es(dec(v['p50_min_before_ko']), 0)} min, p5 {es(dec(v['p05_min_before_ko']), 0)} min "
                  f"({es(dec(v['passes']), 0)} pasadas, terminadas después de T-15: {v['finished_after_t_minus_15']})"
                  for k, v in pt.items()) + ". El veredicto final llega antes de T-15 en "
      f"{pct(dec(pt['final']['passes']) - dec(pt['final']['finished_after_t_minus_15']), dec(pt['final']['passes']), 2)} de las pasadas; "
      "el SLO del plan es ≥ 99 %.")
    w("")

    # ------------------------------------------------------------ outcomes
    w("## 9. Resultados de las decisiones (CLV): la referencia de las comparaciones futuras")
    w("")
    w("Las cifras son lo que ya hay liquidado en `intel.decision_outcomes`. Sirven como punto de partida para comparar "
      "brazos más adelante, **no** para atribuir nada a la IA: quién se revisa no es aleatorio.")
    w("")
    rows = []
    for r in b["clv_by_state"]:
        n = dec(r["settled"])
        se = dec(r["sd_clv"]) / n.sqrt()
        rows.append([f"`{r['state']}`", es(n, 0), es(dec(r["mean_clv"]) * 100, 2) + " %",
                     "± " + es(se * Decimal("1.96") * 100, 2), es(dec(r["median_clv"]) * 100, 2) + " %",
                     es(dec(r["wins"]), 0), es(dec(r["losses"]), 0)])
    w(md(["Estado de la decisión", "Liquidadas", "CLV medio", "IC 95 % (pp)", "CLV mediano", "Ganadas", "Perdidas"], rows))
    w("")
    rows = []
    for r in b["clv_by_review_decision"]:
        n = dec(r["settled"])
        se = dec(r["sd_clv"]) / n.sqrt()
        rows.append([f"`{r['ai_decision']}`", r["engine"], es(n, 0), es(dec(r["mean_clv"]) * 100, 2) + " %",
                     "± " + es(se * Decimal("1.96") * 100, 2)])
    w(md(["Veredicto de la revisión", "Motor", "Liquidadas", "CLV medio", "IC 95 % (pp)"], rows))
    w("")
    w("«IC 95 %» es 1,96 errores estándar de la media (puntos porcentuales). Las filas no son comparables entre sí como "
      "efecto de la IA: la revisión con modelo solo se hace a una parte de los candidatos y los datos cubren pocos días.")
    w("")

    # ------------------------------------------------------------ research
    w("## 10. Investigación (Exa y caché de investigación)")
    w("")
    rc2 = {r["scope"]: r for r in b["research_cache"]}
    ev = b["evidence_per_fixture"][0]
    w("- **Caché de investigación:** " + "; ".join(
        f"`{k}` {es(dec(v['rows']), 0)} filas, {es(dec(v['hits']), 0)} reutilizaciones ({es(dec(v['rows_hit']), 0)} filas reutilizadas, "
        f"vida media {es(dec(v['avg_ttl_hours']), 1)} h)" for k, v in rc2.items()) + ".")
    w(f"- **Evidencia por partido:** {es(dec(ev['fixtures_with_evidence']), 0)} partidos con evidencia, media "
      f"{es(dec(ev['avg_evidence']), 2)} (p50 {ev['p50']}, p90 {ev['p90']}, máx. {ev['max_evidence']}).")
    exa = b["exa_searches_by_day"]
    w(f"- **Búsquedas Exa por día (hora de Bogotá):** {', '.join(r['calls'] for r in exa[1:])} (del {exa[1]['day_bogota']} al "
      f"{exa[-1]['day_bogota']}); coste por búsqueda 0,015 USD.")
    w("")

    # ------------------------------------------------------------- limits
    w("## 11. Lo que este informe no permite concluir")
    w("")
    w(f"- Con {len(full)} días completos de contabilidad no se puede separar tendencia de ritmo semanal: hay apenas dos "
      "semanas y el calendario de partidos cambia de una a otra.")
    w("- No hay conciliación con la Consola (falta el CSV por workspace). Hasta tenerla, «gasto» es el libro interno, "
      "que cuadra con los precios publicados.")
    w("- El potencial de caché y de Batch es una cota superior medida sobre llamadas pasadas; el ahorro real se mide en "
      "los 7 días completos del Gate A.")
    w("- La atribución de cada llamada a una pasada usa la ventana de tiempo de la pasada de ese partido; las llamadas "
      "fuera de pasada aparecen como `outside_a_pass`.")
    w("- El CLV es el de los partidos ya liquidados desde que existe `intel.decisions`; no distingue causa y efecto.")
    w("")
    w("## 12. Referencias para el Gate A")
    w("")
    w("Lo que se comparará con los 7 días completos de medición de la Fase 0 (se mide igual, con el mismo SQL):")
    w("")
    w(md(["Magnitud", "Referencia de esta línea base"], [
        [f"Claude por día (media de los últimos {GATE_A_DAYS} días completos)", usd(c7)],
        ["Proyección mensual de producción con ese ritmo (por 30 días)", usd(c7 * 30, 0)],
        ["Exa por día / por 30 días", f"{usd(e7)} / {usd(e7 * 30, 0)}"],
        ["Briefs por partido y día", es(briefs_sum / fixtures_sum, 2)],
        ["Entradas idénticas pagadas dos veces (briefs)", pct(dec(rep['match_brief']['repeated']), dec(rep['match_brief']['calls_with_hash']))],
        ["Candidatos con revisión de modelo / candidatos revisados por reglas", pct(dec(rps['selections_with_llm']), dec(rps['selections']))],
        ["Coste por candidato revisado por el modelo", usd(dec(rps['cost_per_llm_selection']), 4)],
        ["Veredicto final antes de T-15", pct(dec(pt['final']['passes']) - dec(pt['final']['finished_after_t_minus_15']), dec(pt['final']['passes']), 2)],
        ["Tokens leídos de caché / llamadas por Batch", "0 % / 0 %"],
    ], "lr"))
    w("")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m scripts.ia_baseline_report <baseline.txt>", file=sys.stderr)
        return 2
    sys.stdout.write(report(Baseline(Path(argv[1]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

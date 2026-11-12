#!/usr/bin/env bash
# IA-037 · 05 · El precio del libro reconstruido desde RAW: paridad con el consenso guardado y comparación con decision-v1 (era de refrescos).
# Solo lectura. Necesita la función psq: psql en el contenedor de PostgreSQL con
#   PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=95000" (una sentencia a la vez, salida separada por |).
# Las fechas son las de la medición del 11-nov-2026 (ventana de 30 días UTC); cámbialas para otra ventana.
# Los ficheros intermedios van a $LAB en el servidor; el análisis corre en la imagen del backend sin red (docker run --network none)
# y lee el crudo (RAW) montado en solo lectura. Borra $LAB al terminar.
LAB=${LAB:-/tmp/lab_ia037}
RAW=${RAW:-/srv/predigol/raw}
mkdir -p $LAB; L=$LAB
# 1) todas las consultas (capturas y refrescos) de los partidos con algún refresco, con la ruta de su cuerpo en RAW
psq -c "\copy (with fx as (select distinct provider_fixture_id pid from market.book_asks), f as (select f.id, f.provider_fixture_id pid, f.kickoff_at from core.fixtures f join fx on fx.pid=f.provider_fixture_id), a as (select 'capture' kind, provider_fixture_id pid, asked_at, results, payload_hash from market.odds_asks where provider_fixture_id in (select pid from fx) union all select 'refresh', provider_fixture_id, asked_at, results, payload_hash from market.book_asks) select f.id fixture_id, f.pid, f.kickoff_at, a.kind, a.asked_at, a.results, a.payload_hash, p.file_path from a join f on f.pid=a.pid left join raw.ingestion_payloads p on p.hash=a.payload_hash where a.asked_at < f.kickoff_at and a.asked_at >= f.kickoff_at - interval '4 days' order by f.id, a.asked_at) to stdout with csv header" > $L/asks.csv
# 2) las filas de decision-v1 de la era de refrescos
psq -c "\copy (select d.id, d.fixture_id, f.provider_fixture_id pid, d.known_at, d.kickoff_at, d.checkpoint, d.market_key, d.selection, d.line, d.odds, d.p_market, d.n_bookmakers, d.price_at from intel.decisions d join core.fixtures f on f.id=d.fixture_id where d.decision_version='decision-v1' and d.known_at >= '2026-11-09T23:08Z' and d.known_at < '2026-11-11T14:00Z' and d.checkpoint<>'selection' and d.price_at is not null order by d.id) to stdout with csv header" > $L/rows.csv
# 3) el consenso guardado de esos partidos (Shin) para la prueba de paridad: as_of de cada captura
psq -c "\copy (select m.fixture_id, m.market_key, m.selection, m.line, m.as_of, m.best_odds, m.p_fair, m.n_bookmakers from market.market_consensus m where m.devig_method='shin' and m.fixture_id in (select f.id from core.fixtures f where f.provider_fixture_id in (select distinct provider_fixture_id from market.book_asks)) and m.as_of >= '2026-11-05') to stdout with csv header" > $L/cons.csv
wc -l $L/asks.csv $L/rows.csv $L/cons.csv
cat > $L/analisis.py <<'PY'
import logging, structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
import csv, gzip, json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fbi.providers.api_football.normalize import iter_odds
from fbi.market.consensus import BookQuote, consensus
from fbi.domain.market_probability import DevigMethod

CORE = {"1X2", "OU", "BTTS", "AH", "DC"}
REFRESH_START = datetime(2026, 11, 9, 23, 8, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 11, 13, 30, tzinfo=timezone.utc)  # la hora de la medición: ningún pase después
Q = Decimal("0.01")

def ts(s):
    return datetime.fromisoformat(s.replace(" ", "T")) if s else None

asks = defaultdict(list)
kick = {}
pid_of = {}
for r in csv.DictReader(open("/lab/asks.csv")):
    fid = int(r["fixture_id"]); kick[fid] = ts(r["kickoff_at"]); pid_of[fid] = int(r["pid"])
    asks[fid].append((ts(r["asked_at"]), r["kind"], int(r["results"]), r["payload_hash"], r["file_path"]))
for v in asks.values():
    v.sort()

cache = {}
problems = defaultdict(int)
def body_prices(h, path, pid, ko):
    """consensus (Shin) of the core markets of one body, as market_consensus computes it: (market, sel, line) -> (best, p_fair, n)."""
    if h in cache:
        return cache[h]
    out, upd = None, None
    try:
        env = json.loads(gzip.open("/raw/" + path, "rb").read().decode("utf-8"))
        body = env.get("body") or {}
        for e in body.get("response") or []:
            if isinstance(e, dict) and e.get("update"):
                upd = ts(str(e["update"]).replace("Z", "+00:00"))
        qs = [q for q in iter_odds(body, kickoff_at=ko, captured_at=ko - timedelta(hours=1), payload_hash=h, source="prematch")
              if q.provider_fixture_id == pid and q.market_key in CORE]
        rows = consensus([BookQuote(q.provider_bookmaker_id, q.market_key, q.selection, Decimal(q.line), q.odds_decimal) for q in qs],
                         methods=(DevigMethod.SHIN,))
        out = {(r.market_key, r.selection, Decimal(r.line).quantize(Q)): (float(r.best_odds), float(r.p_fair), int(r.n_bookmakers)) for r in rows}
    except FileNotFoundError:
        problems["missing_file"] += 1
    except Exception as exc:
        problems[type(exc).__name__] += 1
    cache[h] = (out, upd)
    return cache[h]

def in_force(fid, at, kinds):
    """the newest ask of these kinds at or before at: (asked_at, kind, results, hash, path) or None"""
    best = None
    for a in asks[fid]:
        if a[0] <= at and a[1] in kinds:
            best = a
    return best

def pct(xs, q):
    xs = sorted(xs)
    return None if not xs else round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)

# --- A) parity: the capture body rebuilt from RAW against the stored consensus at the capture's as_of
cons = defaultdict(dict)
for r in csv.DictReader(open("/lab/cons.csv")):
    cons[(int(r["fixture_id"]), ts(r["as_of"]))][(r["market_key"], r["selection"], Decimal(r["line"]).quantize(Q))] = (float(r["best_odds"]), float(r["p_fair"]), int(r["n_bookmakers"]))
par_n = par_eq = par_sel = 0; par_dp = []; par_do = []
for fid, xs in asks.items():
    for at, kind, res, h, path in xs:
        if kind != "capture" or res <= 0 or at < datetime(2026, 11, 5, tzinfo=timezone.utc):
            continue
        stored = None
        for (f2, as_of), v in cons.items():
            if f2 == fid and abs((as_of - at).total_seconds()) <= 120:
                stored = v
        if stored is None:
            continue
        rebuilt, _ = body_prices(h, path, pid_of[fid], kick[fid])
        if rebuilt is None:
            continue
        par_n += 1
        common = set(stored) & set(rebuilt)
        par_sel += len(common)
        same = all(abs(stored[k][0] - rebuilt[k][0]) < 1e-9 and abs(stored[k][1] - rebuilt[k][1]) < 5e-6 for k in common)
        par_eq += same and len(common) == len(stored)
        par_dp += [abs(stored[k][1] - rebuilt[k][1]) * 100 for k in common]
        par_do += [abs(stored[k][0] / rebuilt[k][0] - 1) * 100 for k in common]
print("A paridad capturas (cuerpo RAW -> consenso) frente al consenso guardado: cuerpos", par_n, "identicos", par_eq,
      "selecciones", par_sel, "max dp pp", pct(par_dp, 1.0), "max dodds %", pct(par_do, 1.0))

# --- B) the rows of decision-v1 in the refresh era: the book's price at known_at against the decision's
rows = list(csv.DictReader(open("/lab/rows.csv")))
n = found = with_refresh = 0
dodds, dp, moved3, withdrawn = [], [], 0, 0
age_dec, age_book = [], []
for r in rows:
    fid = int(r["fixture_id"]); at = ts(r["known_at"])
    if fid not in asks:
        problems["row_fixture_without_asks"] += 1
        continue
    n += 1
    last_any = in_force(fid, at, {"capture", "refresh"})
    if last_any is not None and last_any[2] <= 0:
        withdrawn += 1
    nonempty = [a for a in asks[fid] if a[0] <= at and a[2] > 0]
    if not nonempty:
        continue
    book = nonempty[-1]
    age_dec.append((at - ts(r["price_at"])).total_seconds() / 60)
    age_book.append((at - book[0]).total_seconds() / 60)
    if book[1] != "refresh":
        continue
    with_refresh += 1
    prices, _ = body_prices(book[3], book[4], pid_of[fid], kick[fid])
    k = (r["market_key"], r["selection"], Decimal(r["line"]).quantize(Q))
    if not prices or k not in prices:
        problems["refresh_row_selection_missing"] += 1
        continue
    found += 1
    bo, bp, bn = prices[k]
    o, p = float(r["odds"]), float(r["p_market"])
    dodds.append(abs(bo / o - 1) * 100); dp.append(abs(bp - p) * 100)
    moved3 += abs(bo / o - 1) > 0.03
print("B filas era refrescos:", n, "con refresco vigente:", with_refresh, "seleccion hallada en el refresco:", found,
      "ultima consulta vacia:", withdrawn)
print("  |dcuota| % p50/p90/max", pct(dodds, .5), pct(dodds, .9), pct(dodds, 1.0), "| |dp| pp p50/p90/max", pct(dp, .5), pct(dp, .9), pct(dp, 1.0),
      "| filas con |dcuota|>3 %:", moved3)
print("  edad decision p50/p90", pct(age_dec, .5), pct(age_dec, .9), "| edad libro p50/p90", pct(age_book, .5), pct(age_book, .9))

# --- C) every 15-min pass of the decide job, from the refresh start: the capture's price against the book's
BANDS = ((60, "a 0-1h"), (180, "b 1-3h"), (360, "c 3-6h"), (720, "d 6-12h"), (1440, "e 12-24h"), (2160, "f 24-36h"))
def band(m):
    for lim, name in BANDS:
        if m < lim:
            return name
    return None
acc = defaultdict(lambda: {"n": 0, "cap": [], "book": [], "refresh": 0, "same_body": 0, "dp": [], "do": [], "moved3": 0, "upd_book": []})
for fid, xs in asks.items():
    ko = kick[fid]
    t = max(ko - timedelta(hours=36), REFRESH_START + timedelta(minutes=15))
    t = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0) + timedelta(minutes=15)
    while t <= min(ko - timedelta(minutes=10), NOW):
        m = (ko - t).total_seconds() / 60
        b = band(m)
        cap = [a for a in xs if a[0] <= t and a[1] == "capture" and a[2] > 0]
        anyk = [a for a in xs if a[0] <= t and a[2] > 0]
        if b and cap and anyk and (t - cap[-1][0]) <= timedelta(hours=36):
            s = acc[b]; s["n"] += 1
            s["cap"].append((t - cap[-1][0]).total_seconds() / 60); s["book"].append((t - anyk[-1][0]).total_seconds() / 60)
            if anyk[-1][1] == "refresh":
                s["refresh"] += 1
                if anyk[-1][3] == cap[-1][3]:
                    s["same_body"] += 1
                pc, _ = body_prices(cap[-1][3], cap[-1][4], pid_of[fid], ko)
                pb, upd = body_prices(anyk[-1][3], anyk[-1][4], pid_of[fid], ko)
                if upd is not None:
                    s["upd_book"].append((t - upd).total_seconds() / 60)
                if pc and pb:
                    common = set(pc) & set(pb)
                    s["dp"] += [abs(pc[k][1] - pb[k][1]) * 100 for k in common]
                    s["do"] += [abs(pb[k][0] / pc[k][0] - 1) * 100 for k in common]
                    s["moved3"] += sum(1 for k in common if abs(pb[k][0] / pc[k][0] - 1) > 0.03)
        t += timedelta(minutes=15)
print("C pases cada 15 min desde el inicio de los refrescos (partidos con refresco):")
print("  franja | pases | edad captura p50/p90 | edad libro p50/p90 | pases con refresco vigente | mismo cuerpo | selecciones comparadas | |dp| pp p50/p90 | |dcuota| % p50/p90 | sel. |dcuota|>3% | edad sello proveedor del libro p50")
for b in sorted(acc):
    s = acc[b]
    print(" ", b, s["n"], pct(s["cap"], .5), pct(s["cap"], .9), pct(s["book"], .5), pct(s["book"], .9), s["refresh"], s["same_body"], len(s["dp"]),
          pct(s["dp"], .5), pct(s["dp"], .9), pct(s["do"], .5), pct(s["do"], .9), s["moved3"], pct(s["upd_book"], .5))
print("problemas:", dict(problems), "cuerpos leidos:", len(cache), "partidos:", len(asks))
PY
IMG=$(docker inspect -f '{{.Config.Image}}' predigol-worker)
docker run --rm --network none -v $L:/lab:ro -v $RAW:/raw:ro --entrypoint python "$IMG" /lab/analisis.py

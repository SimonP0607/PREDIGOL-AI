#!/usr/bin/env bash
# IA-037 · 06 · Pases de 15 min: edad del libro frente a la de la captura, sellos del proveedor, 30 días de capturas y el umbral propuesto.
# Solo lectura. Necesita la función psq: psql en el contenedor de PostgreSQL con
#   PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=95000" (una sentencia a la vez, salida separada por |).
# Las fechas son las de la medición del 11-nov-2026 (ventana de 30 días UTC); cámbialas para otra ventana.
# Los ficheros intermedios van a $LAB en el servidor; el análisis corre en la imagen del backend sin red (docker run --network none)
# y lee el crudo (RAW) montado en solo lectura. Borra $LAB al terminar.
LAB=${LAB:-/tmp/lab_ia037}
RAW=${RAW:-/srv/predigol/raw}
mkdir -p $LAB; L=$LAB
psq -c "\copy (with fx as (select distinct provider_fixture_id pid from market.book_asks), f as (select f.id, f.provider_fixture_id pid, f.kickoff_at, exists(select 1 from intel.decisions d where d.fixture_id=f.id and d.decision_version='decision-v1') decided, fp.provider_update_at final_upd, fp.outcome final_outcome from core.fixtures f join fx on fx.pid=f.provider_fixture_id left join market.final_prematch_checks fp on fp.fixture_id=f.id), a as (select 'capture' kind, provider_fixture_id pid, asked_at, results, payload_hash from market.odds_asks where provider_fixture_id in (select pid from fx) union all select 'refresh', provider_fixture_id, asked_at, results, payload_hash from market.book_asks) select f.id fixture_id, f.pid, f.kickoff_at, f.decided, f.final_upd, f.final_outcome, a.kind, a.asked_at, a.results, a.payload_hash, p.file_path from a join f on f.pid=a.pid left join raw.ingestion_payloads p on p.hash=a.payload_hash where a.asked_at < f.kickoff_at and a.asked_at >= f.kickoff_at - interval '4 days' order by f.id, a.asked_at) to stdout with csv header" > $L/asks2.csv
wc -l $L/asks2.csv
cat > $L/pases.py <<'PY'
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
START = datetime(2026, 11, 9, 23, 8, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 11, 13, 30, tzinfo=timezone.utc)
Q = Decimal("0.01")
def ts(s):
    return datetime.fromisoformat(s.replace(" ", "T")) if s else None
asks, kick, pid_of, decided, final = defaultdict(list), {}, {}, {}, {}
for r in csv.DictReader(open("/lab/asks2.csv")):
    fid = int(r["fixture_id"]); kick[fid] = ts(r["kickoff_at"]); pid_of[fid] = int(r["pid"]); decided[fid] = r["decided"] == "t"
    final[fid] = (ts(r["final_upd"]), r["final_outcome"])
    asks[fid].append((ts(r["asked_at"]), r["kind"], int(r["results"]), r["payload_hash"], r["file_path"]))
for v in asks.values():
    v.sort()
cache = {}
def body(h, path, pid, ko):
    if h in cache:
        return cache[h]
    out, upd = None, None
    try:
        env = json.loads(gzip.open("/raw/" + path, "rb").read().decode("utf-8"))
        b = env.get("body") or {}
        for e in b.get("response") or []:
            if isinstance(e, dict) and e.get("update"):
                upd = datetime.fromisoformat(str(e["update"]).replace("Z", "+00:00"))
        qs = [q for q in iter_odds(b, kickoff_at=ko, captured_at=ko - timedelta(hours=1), payload_hash=h, source="prematch")
              if q.provider_fixture_id == pid and q.market_key in CORE]
        rows = consensus([BookQuote(q.provider_bookmaker_id, q.market_key, q.selection, Decimal(q.line), q.odds_decimal) for q in qs], methods=(DevigMethod.SHIN,))
        out = {(r.market_key, r.selection, Decimal(r.line).quantize(Q)): (float(r.best_odds), float(r.p_fair)) for r in rows}
    except Exception as exc:
        out = None
    cache[h] = (out, upd)
    return cache[h]
def pct(xs, q):
    xs = sorted(xs)
    return None if not xs else round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)
BANDS = ((60, "a 0-1h"), (180, "b 1-3h"), (360, "c 3-6h"), (720, "d 6-12h"), (1440, "e 12-24h"), (2160, "f 24-36h"))
def band(m):
    for lim, name in BANDS:
        if m < lim:
            return name
    return None
for label, keep in (("decididos por decision-v1", lambda f: decided[f]), ("todos los partidos con refresco", lambda f: True)):
    acc = defaultdict(lambda: {"n": 0, "cap": [], "book": [], "ref": 0, "same": 0, "dp": [], "do": [], "m3": 0, "upd": [], "fx": set()})
    for fid, xs in asks.items():
        if not keep(fid):
            continue
        ko = kick[fid]
        t = max(ko - timedelta(hours=36), START + timedelta(minutes=15))
        t = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0) + timedelta(minutes=15)
        while t <= min(ko - timedelta(minutes=10), NOW):
            b = band((ko - t).total_seconds() / 60)
            cap = [a for a in xs if a[0] <= t and a[1] == "capture" and a[2] > 0]
            anyk = [a for a in xs if a[0] <= t and a[2] > 0]
            if b and cap and anyk:
                s = acc[b]; s["n"] += 1; s["fx"].add(fid)
                s["cap"].append((t - cap[-1][0]).total_seconds() / 60); s["book"].append((t - anyk[-1][0]).total_seconds() / 60)
                pb, upd = body(anyk[-1][3], anyk[-1][4], pid_of[fid], ko)
                if upd is not None:
                    s["upd"].append((t - upd).total_seconds() / 60)
                if anyk[-1][1] == "refresh":
                    s["ref"] += 1
                    s["same"] += anyk[-1][3] == cap[-1][3]
                    pc, _ = body(cap[-1][3], cap[-1][4], pid_of[fid], ko)
                    if pc and pb:
                        common = set(pc) & set(pb)
                        s["dp"] += [abs(pc[k][1] - pb[k][1]) * 100 for k in common]
                        s["do"] += [abs(pb[k][0] / pc[k][0] - 1) * 100 for k in common]
                        s["m3"] += sum(1 for k in common if abs(pb[k][0] / pc[k][0] - 1) > 0.03)
            t += timedelta(minutes=15)
    print("PASES cada 15 min desde 9-nov 23:08 UTC -", label)
    print("  franja | partidos | pases | edad captura p50/p90 | edad libro p50/p90 | pases con refresco vigente | mismo cuerpo que la captura | selecciones | |dp| pp p50/p90 | |dcuota| % p50/p90 | sel. con |dcuota|>3 % | edad del sello del proveedor (libro) p50/p90")
    for b in sorted(acc):
        s = acc[b]
        print(" ", b, len(s["fx"]), s["n"], pct(s["cap"], .5), pct(s["cap"], .9), pct(s["book"], .5), pct(s["book"], .9), s["ref"], s["same"], len(s["dp"]),
              pct(s["dp"], .5), pct(s["dp"], .9), pct(s["do"], .5), pct(s["do"], .9), s["m3"], pct(s["upd"], .5), pct(s["upd"], .9))
# sellos: la ultima respuesta antes del saque frente a la lectura final del proveedor (partidos ya jugados)
rows = []
for fid, xs in asks.items():
    ko = kick[fid]
    if ko > NOW:
        continue
    nonempty = [a for a in xs if a[2] > 0]
    if not nonempty:
        continue
    last = nonempty[-1]
    lastcap = [a for a in nonempty if a[1] == "capture"]
    _, upd_last = body(last[3], last[4], pid_of[fid], ko)
    _, upd_cap = body(lastcap[-1][3], lastcap[-1][4], pid_of[fid], ko) if lastcap else (None, None)
    fu, fo = final[fid]
    rows.append((fid, last[1], (ko - last[0]).total_seconds() / 60, None if upd_last is None else (ko - upd_last).total_seconds() / 60,
                 None if upd_cap is None else (ko - upd_cap).total_seconds() / 60, None if fu is None else (ko - fu).total_seconds() / 60, fo))
print("CIERRE de los partidos con refresco ya jugados:", len(rows), "| ultima respuesta de refresco:", sum(1 for r in rows if r[1] == "refresh"))
print("  min al saque de la ultima consulta p50/p90:", pct([r[2] for r in rows], .5), pct([r[2] for r in rows], .9))
print("  sello del proveedor en la ultima respuesta, min antes del saque p10/p50/p90:", pct([r[3] for r in rows if r[3] is not None], .1), pct([r[3] for r in rows if r[3] is not None], .5), pct([r[3] for r in rows if r[3] is not None], .9))
print("  sello en la ultima captura p50:", pct([r[4] for r in rows if r[4] is not None], .5), "| sello de la lectura final p10/p50/p90:", pct([r[5] for r in rows if r[5] is not None], .1), pct([r[5] for r in rows if r[5] is not None], .5), pct([r[5] for r in rows if r[5] is not None], .9))
both = [r for r in rows if r[3] is not None and r[5] is not None]
print("  con ambos sellos:", len(both), "| la lectura final es posterior a la ultima respuesta (>1 min):", sum(1 for r in both if r[5] < r[3] - 1), "| igual (+-1 min):", sum(1 for r in both if abs(r[5] - r[3]) <= 1), "| anterior:", sum(1 for r in both if r[5] > r[3] + 1))
print("  salidas lectura final:", dict((o, sum(1 for r in rows if r[6] == o)) for o in sorted({str(r[6]) for r in rows})))
print("cuerpos leidos:", len(cache), "| ilegibles:", sum(1 for v in cache.values() if v[0] is None))
PY
IMG=$(docker inspect -f '{{.Config.Image}}' predigol-worker)
docker run --rm --network none -v $L:/lab:ro -v $RAW:/raw:ro --entrypoint python "$IMG" /lab/pases.py 2>&1 | grep -v '^\s*$' | tail -40
mkdir -p $LAB; L=$LAB
psq -c "\copy (with fx as (select distinct d.fixture_id id from intel.decisions d where d.decision_version='decision-v1' and d.known_at >= '2026-10-12T00:00Z' and d.known_at < '2026-11-11T14:00Z'), f as (select f.id, f.provider_fixture_id pid, f.kickoff_at ko from core.fixtures f join fx on fx.id=f.id where f.kickoff_at < '2026-11-11T13:00Z') select f.id, f.ko, a.asked_at, a.results from f join market.odds_asks a on a.provider_fixture_id=f.pid and a.asked_at < f.ko and a.asked_at >= f.ko - interval '4 days' order by f.id, a.asked_at) to stdout with csv header" > $L/caps30.csv
wc -l $L/caps30.csv
cat > $L/pases30.py <<'PY'
import csv
from collections import defaultdict
from datetime import datetime, timedelta
def ts(s):
    return datetime.fromisoformat(s.replace(" ", "T"))
asks, ko = defaultdict(list), {}
for r in csv.DictReader(open("/lab/caps30.csv")):
    f = int(r["id"]); ko[f] = ts(r["ko"]); asks[f].append((ts(r["asked_at"]), int(r["results"])))
BANDS = ((60, "a 0-1h"), (180, "b 1-3h"), (360, "c 3-6h"), (720, "d 6-12h"), (1440, "e 12-24h"), (2160, "f 24-36h"))
def band(m):
    for lim, name in BANDS:
        if m < lim:
            return name
def pct(xs, q):
    xs = sorted(xs)
    return None if not xs else round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)
acc = defaultdict(list); nop = defaultdict(int); under24 = []
for f, xs in asks.items():
    xs.sort(); k = ko[f]
    t = k - timedelta(hours=36)
    t = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0) + timedelta(minutes=15)
    while t <= k - timedelta(minutes=10):
        m = (k - t).total_seconds() / 60
        b = band(m)
        last = [a for a, res in xs if a <= t and res > 0]
        if b:
            if not last or t - last[-1] > timedelta(hours=36):
                nop[b] += 1
            else:
                age = (t - last[-1]).total_seconds() / 60
                acc[b].append(age)
                if m < 1440:
                    under24.append(age)
        t += timedelta(minutes=15)
print("partidos:", len(asks))
print("franja | pases con precio | sin precio | edad p50 | p75 | p90 | p95 | > 3 h (%) | > 60 min (%)")
for b in sorted(acc):
    xs = acc[b]
    print(b, len(xs), nop[b], pct(xs, .5), pct(xs, .75), pct(xs, .9), pct(xs, .95), round(100 * sum(1 for x in xs if x > 180) / len(xs), 1), round(100 * sum(1 for x in xs if x > 60) / len(xs), 1))
allx = [x for v in acc.values() for x in v]
print("todas las franjas:", len(allx), "p50", pct(allx, .5), "p90", pct(allx, .9), "| proximas 24 h:", len(under24), "p50", pct(under24, .5), "p75", pct(under24, .75), "p90", pct(under24, .9))
PY
IMG=$(docker inspect -f '{{.Config.Image}}' predigol-worker)
docker run --rm --network none -v $L:/lab:ro --entrypoint python "$IMG" /lab/pases30.py
cat > $L/umbral.py <<'PY'
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
def ts(s):
    return datetime.fromisoformat(s.replace(" ", "T")) if s else None
def thr(m):
    return 45 if m < 60 else 75 if m < 360 else 195
BANDS = ((60, "a 0-1h"), (180, "b 1-3h"), (360, "c 3-6h"), (720, "d 6-12h"), (1440, "e 12-24h"), (2160, "f 24-36h"))
def band(m):
    for lim, name in BANDS:
        if m < lim:
            return name
START = datetime(2026, 11, 9, 23, 8, tzinfo=timezone.utc); NOW = datetime(2026, 11, 11, 13, 30, tzinfo=timezone.utc)
# libro (era de refrescos, partidos decididos)
asks, ko, dec = defaultdict(list), {}, {}
for r in csv.DictReader(open("/lab/asks2.csv")):
    f = int(r["fixture_id"]); ko[f] = ts(r["kickoff_at"]); dec[f] = r["decided"] == "t"
    asks[f].append((ts(r["asked_at"]), r["kind"], int(r["results"])))
acc = defaultdict(lambda: [0, 0, 0, 0, 0])  # passes, book ok, capture ok, capture ok by decision-v1 rules, book ok by v1 rules
for f, xs in asks.items():
    if not dec[f]:
        continue
    xs.sort(); k = ko[f]
    t = max(k - timedelta(hours=36), START + timedelta(minutes=15)); t = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0) + timedelta(minutes=15)
    while t <= min(k - timedelta(minutes=10), NOW):
        m = (k - t).total_seconds() / 60
        cap = [a for a, kind, res in xs if a <= t and kind == "capture" and res > 0]
        anyk = [a for a, kind, res in xs if a <= t and res > 0]
        if cap and anyk and band(m):
            s = acc[band(m)]; s[0] += 1
            ab = (t - anyk[-1]).total_seconds() / 60; ac = (t - cap[-1]).total_seconds() / 60
            v1 = lambda age: age <= 180 and not (m <= 90 and age > 30)
            s[1] += ab <= thr(m); s[2] += ac <= thr(m); s[3] += v1(ac); s[4] += v1(ab)
        t += timedelta(minutes=15)
print("LIBRO frente a CAPTURA, pases de 15 min desde 9-nov 23:08 (partidos decididos):")
print("franja | pases | libro dentro del umbral propuesto % | captura dentro % | captura dentro de las reglas de v1 (3 h; 30 min desde T-90m) % | libro dentro de las reglas de v1 %")
tot = [0, 0, 0, 0, 0]
for b in sorted(acc):
    s = acc[b]; tot = [x + y for x, y in zip(tot, s)]
    print(b, s[0], round(100 * s[1] / s[0], 1), round(100 * s[2] / s[0], 1), round(100 * s[3] / s[0], 1), round(100 * s[4] / s[0], 1))
print("total", tot[0], round(100 * tot[1] / tot[0], 1), round(100 * tot[2] / tot[0], 1), round(100 * tot[3] / tot[0], 1), round(100 * tot[4] / tot[0], 1))
# captura, 30 dias
caps, ko2 = defaultdict(list), {}
for r in csv.DictReader(open("/lab/caps30.csv")):
    f = int(r["id"]); ko2[f] = ts(r["ko"]); caps[f].append((ts(r["asked_at"]), int(r["results"])))
acc2 = defaultdict(lambda: [0, 0])
for f, xs in caps.items():
    xs.sort(); k = ko2[f]
    t = k - timedelta(hours=36); t = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0) + timedelta(minutes=15)
    while t <= k - timedelta(minutes=10):
        m = (k - t).total_seconds() / 60
        last = [a for a, res in xs if a <= t and res > 0]
        if last and t - last[-1] <= timedelta(hours=36) and band(m):
            s = acc2[band(m)]; s[0] += 1; s[1] += (t - last[-1]).total_seconds() / 60 <= thr(m)
        t += timedelta(minutes=15)
print("CAPTURA (precio de decision-v1), 30 dias, 3.097 partidos: pases dentro del umbral propuesto")
for b in sorted(acc2):
    s = acc2[b]; print(b, s[0], round(100 * s[1] / s[0], 1))
n = sum(s[0] for s in acc2.values()); ok = sum(s[1] for s in acc2.values()); print("total", n, round(100 * ok / n, 1))
PY
IMG=$(docker inspect -f '{{.Config.Image}}' predigol-worker)
docker run --rm --network none -v $L:/lab:ro --entrypoint python "$IMG" /lab/umbral.py

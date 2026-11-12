#!/usr/bin/env bash
# IA-037 · 01 · Edad del precio en las filas de decision-v1 (intel.decisions), 30 días.
# Solo lectura. Necesita la función psq: psql en el contenedor de PostgreSQL con
#   PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=95000" (una sentencia a la vez, salida separada por |).
# Las fechas son las de la medición del 11-nov-2026 (ventana de 30 días UTC); cámbialas para otra ventana.
W="d.decision_version='decision-v1' and d.known_at >= '2026-10-12T00:00Z' and d.known_at < '2026-11-11T00:00Z'"
echo ---TOTAL: filas, copias selection, sin price_at, sin odds, fixtures, min/max known_at
psq -tc "select count(*), count(*) filter (where checkpoint='selection'), count(*) filter (where price_at is null and checkpoint<>'selection'), count(*) filter (where odds is null and checkpoint<>'selection'), count(distinct fixture_id), min(known_at), max(known_at) from intel.decisions d where $W"
echo ---SIN_PRICE_AT por estado y primer motivo
psq -tc "select state, reasons[1], count(*) from intel.decisions d where $W and checkpoint<>'selection' and price_at is null group by 1,2 order by 3 desc limit 12"
echo ---EDAD global minutos: n, p50, p75, p90, p95, max, sobre 3h, sobre 30min
psq -tc "select count(*), round(percentile_cont(0.5) within group (order by e)::numeric,1), round(percentile_cont(0.75) within group (order by e)::numeric,1), round(percentile_cont(0.9) within group (order by e)::numeric,1), round(percentile_cont(0.95) within group (order by e)::numeric,1), round(max(e)::numeric,1), count(*) filter (where e>180), count(*) filter (where e>30) from (select extract(epoch from known_at-price_at)/60 e from intel.decisions d where $W and checkpoint<>'selection' and price_at is not null) x"
echo ---EDAD por checkpoint
psq -tc "select checkpoint, count(*), round(percentile_cont(0.5) within group (order by e)::numeric,1), round(percentile_cont(0.75) within group (order by e)::numeric,1), round(percentile_cont(0.9) within group (order by e)::numeric,1), round(percentile_cont(0.95) within group (order by e)::numeric,1), count(*) filter (where e>180) from (select checkpoint, extract(epoch from known_at-price_at)/60 e from intel.decisions d where $W and checkpoint<>'selection' and price_at is not null) x group by 1 order by min(case checkpoint when 'T-36h' then 1 when 'T-24h' then 2 when 'T-12h' then 3 when 'T-6h' then 4 when 'T-3h' then 5 when 'T-90m' then 6 when 'T-60m' then 7 when 'lineups' then 8 when 'T-15m' then 9 else 10 end)"
echo ---EDAD por franja de horas al saque
psq -tc "select b, count(*), round(percentile_cont(0.5) within group (order by e)::numeric,1), round(percentile_cont(0.75) within group (order by e)::numeric,1), round(percentile_cont(0.9) within group (order by e)::numeric,1), round(percentile_cont(0.95) within group (order by e)::numeric,1), count(*) filter (where e>180), count(*) filter (where e>60) from (select case when h<1 then 'a 0-1h' when h<3 then 'b 1-3h' when h<6 then 'c 3-6h' when h<12 then 'd 6-12h' when h<24 then 'e 12-24h' else 'f 24-36h' end b, e from (select extract(epoch from kickoff_at-known_at)/3600 h, extract(epoch from known_at-price_at)/60 e from intel.decisions d where $W and checkpoint<>'selection' and price_at is not null) y) x group by 1 order by 1"
echo ---POR ESTADO: n, p50 edad
psq -tc "select state, count(*), round(percentile_cont(0.5) within group (order by extract(epoch from known_at-price_at)/60)::numeric,1) from intel.decisions d where $W and checkpoint<>'selection' and price_at is not null group by 1 order by 2 desc"
echo ---MOTIVOS de precio: filas con price_stale / price_not_fresh / no_price
psq -tc "select count(*) filter (where 'price_stale'=any(reasons)), count(*) filter (where 'price_not_fresh'=any(reasons)), count(*) filter (where 'no_price'=any(reasons)), count(*) from intel.decisions d where $W and checkpoint<>'selection'"

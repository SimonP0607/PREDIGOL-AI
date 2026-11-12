#!/usr/bin/env bash
# IA-037 · 04 · Historia del libro: consultas de captura y de refresco, cobertura, y EXPLAIN de las lecturas «as of».
# Solo lectura. Necesita la función psq: psql en el contenedor de PostgreSQL con
#   PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=95000" (una sentencia a la vez, salida separada por |).
# Las fechas son las de la medición del 11-nov-2026 (ventana de 30 días UTC); cámbialas para otra ventana.
echo ---BOOK_ASKS rango y volumen
psq -tc "select count(*), count(distinct provider_fixture_id), min(asked_at), max(asked_at), count(*) filter (where results=0) from market.book_asks"
echo ---BOOK_ASKS por dia
psq -tc "select date_trunc('day', asked_at)::date, count(*), count(distinct provider_fixture_id) from market.book_asks group by 1 order by 1"
echo ---BOOK_ASKS por window_minutes
psq -tc "select window_minutes, count(*) from market.book_asks group by 1 order by 1 desc"
echo ---ODDS_ASKS rango
psq -tc "select count(*), count(distinct provider_fixture_id), min(asked_at), max(asked_at), count(*) filter (where results=0), count(*) filter (where payload_hash is null) from market.odds_asks"
echo ---ODDS_ASKS 30d por window_minutes
psq -tc "select window_minutes, count(*), round(avg(minutes_to_ko)), min(minutes_to_ko), max(minutes_to_ko) from market.odds_asks where asked_at >= '2026-10-12T00:00Z' and asked_at < '2026-11-11T00:00Z' group by 1 order by 1 desc nulls last"
echo ---RUNS de refresco y build
psq -tc "select job_type, count(*), min(started_at), max(started_at), sum(api_calls) from raw.ingestion_runs where job_type in ('odds_book_refresh','odds_book_build') group by 1"
echo ---BOOK_CURRENT estado
psq -tc "select count(*), count(distinct fixture_id), min(kickoff_at), max(kickoff_at), max(built_at), min(checked_at), max(checked_at) from market.book_current"
echo "---A partidos con saque en [10-nov 00:00, 12-nov 00:00) UTC: con captura no vacia, con refresco no vacio, decididos por v1, decididos con refresco"
psq -tc "with f as (select f.id, f.provider_fixture_id pid, f.kickoff_at ko from core.fixtures f where f.kickoff_at >= '2026-11-10T00:00Z' and f.kickoff_at < '2026-11-12T00:00Z'), c as (select f.id, exists(select 1 from market.odds_asks a where a.provider_fixture_id=f.pid and a.results>0 and a.asked_at < f.ko and a.asked_at >= f.ko - interval '4 days') cap, exists(select 1 from market.book_asks b where b.provider_fixture_id=f.pid and b.results>0 and b.asked_at < f.ko) ref, exists(select 1 from intel.decisions d where d.fixture_id=f.id and d.decision_version='decision-v1') dec from f) select count(*) filter (where cap), count(*) filter (where ref), count(*) filter (where cap and ref), count(*) filter (where dec), count(*) filter (where dec and ref), count(*) filter (where dec and cap) from c"
echo "---B partidos con refresco y saque ya pasado: n, ultima captura p50/p90 min al saque, n con ultima captura > 6 h, ultimo refresco p50 min"
psq -tc "with f as (select f.id, f.provider_fixture_id pid, f.kickoff_at ko from core.fixtures f where f.provider_fixture_id in (select distinct provider_fixture_id from market.book_asks) and f.kickoff_at < now()), y as (select f.*, (select max(asked_at) from market.odds_asks a where a.provider_fixture_id=f.pid and a.results>0 and a.asked_at < f.ko) lc, (select max(asked_at) from market.book_asks b where b.provider_fixture_id=f.pid and b.results>0 and b.asked_at < f.ko) lb, (select count(*) from market.odds_asks a where a.provider_fixture_id=f.pid and a.asked_at < f.ko and a.asked_at >= f.ko - interval '4 days') nc, (select count(*) from market.book_asks b where b.provider_fixture_id=f.pid and b.asked_at < f.ko) nb from f) select count(*), round(percentile_cont(0.5) within group (order by extract(epoch from ko-lc)/60)::numeric,1), round(percentile_cont(0.9) within group (order by extract(epoch from ko-lc)/60)::numeric,1), count(*) filter (where ko-lc > interval '6 hours'), round(percentile_cont(0.5) within group (order by extract(epoch from ko-lb)/60)::numeric,1), round(avg(nc),1), round(avg(nb),1) from y"
echo "---C los de ultima captura > 6 h antes del saque: id, saque, ultima captura, ultimo refresco, capturas, refrescos, cambios de saque"
psq -tc "with f as (select f.id, f.provider_fixture_id pid, f.kickoff_at ko from core.fixtures f where f.provider_fixture_id in (select distinct provider_fixture_id from market.book_asks) and f.kickoff_at < now()), y as (select f.*, (select max(asked_at) from market.odds_asks a where a.provider_fixture_id=f.pid and a.results>0 and a.asked_at < f.ko) lc, (select max(asked_at) from market.book_asks b where b.provider_fixture_id=f.pid and b.results>0 and b.asked_at < f.ko) lb, (select string_agg(window_minutes::text||':'||results::text, ',' order by asked_at) from market.odds_asks a where a.provider_fixture_id=f.pid and a.asked_at < f.ko and a.asked_at >= f.ko - interval '4 days') caps from f) select id, ko, lc, lb, caps from y where ko-lc > interval '6 hours' order by ko limit 15"
echo "---D EXPLAIN: consultas as-of de una jugada (partido de ejemplo)"
PID=$(psq -tc "select provider_fixture_id from market.book_asks order by asked_at desc limit 1")
FID=$(psq -tc "select id from core.fixtures where provider_fixture_id=$PID")
psq -tc "explain select asked_at, results, payload_hash from market.odds_asks where provider_fixture_id = $PID and asked_at >= now() - interval '4 days' and asked_at <= now() order by asked_at desc limit 200"
psq -tc "explain select asked_at, results, payload_hash from market.book_asks where provider_fixture_id = $PID and asked_at >= now() - interval '4 days' and asked_at <= now() order by asked_at desc limit 200"
psq -tc "explain select hash, file_path, fetched_at, params, http_status, results_count from raw.ingestion_payloads where hash = any(array['x','y'])"
psq -tc "explain select q.bookmaker_id, q.definition_id, q.selection, q.line, q.odds_decimal from market.odds_quotes q where q.fixture_id = $FID and q.extraction_id = any(array[1,2]::bigint[]) and q.captured_at >= now() - interval '4 days' and q.captured_at <= now() and q.definition_id = any(array[1,4,5,8,12])"
echo "---E bookmakers: proveedor -> id interno (conteo)"
psq -tc "select count(*), count(provider_bookmaker_id) from market.bookmakers"

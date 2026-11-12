#!/usr/bin/env bash
# IA-037 · 03 · El último precio prepartido de cada partido y su distancia al saque (CLV); el sello final del proveedor.
# Solo lectura. Necesita la función psq: psql en el contenedor de PostgreSQL con
#   PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=95000" (una sentencia a la vez, salida separada por |).
# Las fechas son las de la medición del 11-nov-2026 (ventana de 30 días UTC); cámbialas para otra ventana.
Q="with fx as (select distinct d.fixture_id id from intel.decisions d where d.decision_version='decision-v1' and d.known_at >= '2026-10-12T00:00Z' and d.known_at < '2026-11-11T14:00Z'),
f as (select f.id, f.provider_fixture_id pid, f.kickoff_at ko from core.fixtures f join fx on fx.id=f.id where f.kickoff_at < '2026-11-11T13:00Z'),
z as (select f.*, mc.as_of last_cons, ca.asked_at last_cap, ba.asked_at last_book, fp.provider_update_at prov_upd, fp.outcome fp_outcome, ex.provider_update_at cap_upd
 from f
 left join lateral (select m.as_of from market.market_consensus m where m.fixture_id=f.id and m.as_of < f.ko and m.devig_method='shin' order by m.as_of desc limit 1) mc on true
 left join lateral (select asked_at, payload_hash from market.odds_asks a where a.provider_fixture_id=f.pid and a.asked_at < f.ko and a.results > 0 order by asked_at desc limit 1) ca on true
 left join lateral (select asked_at from market.book_asks b where b.provider_fixture_id=f.pid and b.asked_at < f.ko and b.results > 0 order by asked_at desc limit 1) ba on true
 left join market.final_prematch_checks fp on fp.fixture_id=f.id
 left join market.odds_extractions ex on ex.payload_hash = ca.payload_hash),
y as (select z.*, extract(epoch from ko-last_cons)/60 m_cons, extract(epoch from ko-last_cap)/60 m_cap, extract(epoch from ko-last_book)/60 m_book, extract(epoch from ko-prov_upd)/60 m_prov, extract(epoch from ko-cap_upd)/60 m_capupd from z)"
echo "---A partidos, con consenso previo, con captura previa, con refresco previo, con lectura final ok, salidas de la lectura final"
psq -tc "$Q select count(*), count(last_cons), count(last_cap), count(last_book), count(*) filter (where prov_upd is not null and prov_upd < ko) from y"
psq -tc "$Q select coalesce(fp_outcome,'(sin lectura)'), count(*) from y group by 1 order by 2 desc"
echo "---B distancia al saque en min: n, p10, p25, p50, p75, p90 - consenso, captura, refresco, sello del proveedor (lectura final), sello del proveedor (ultima captura)"
for c in m_cons m_cap m_book m_prov m_capupd; do psq -tc "$Q select '$c', count($c), round(percentile_cont(0.1) within group (order by $c)::numeric,1), round(percentile_cont(0.25) within group (order by $c)::numeric,1), round(percentile_cont(0.5) within group (order by $c)::numeric,1), round(percentile_cont(0.75) within group (order by $c)::numeric,1), round(percentile_cont(0.9) within group (order by $c)::numeric,1) from y where $c is not null and $c >= 0"; done
echo "---C sello final del proveedor posterior a nuestra ultima captura: n con ambos, posterior, igual o anterior"
psq -tc "$Q select count(*) filter (where m_prov is not null and m_cap is not null), count(*) filter (where m_prov < m_cap - 1), count(*) filter (where m_prov >= m_cap - 1) from y"
echo "---D por semana de saque: n, p50 consenso, p50 sello proveedor"
psq -tc "$Q select date_trunc('week', ko)::date, count(*), round(percentile_cont(0.5) within group (order by m_cons)::numeric,1), round(percentile_cont(0.5) within group (order by m_prov)::numeric,1), count(m_prov) from y group by 1 order by 1"
echo "---A todos los partidos con lectura final 'priced', saque en [12-oct, 11-nov 13:00): n, p10, p25, p50, p75, p90 (min antes del saque)"
psq -tc "select count(*), round(percentile_cont(0.1) within group (order by m)::numeric,1), round(percentile_cont(0.25) within group (order by m)::numeric,1), round(percentile_cont(0.5) within group (order by m)::numeric,1), round(percentile_cont(0.75) within group (order by m)::numeric,1), round(percentile_cont(0.9) within group (order by m)::numeric,1) from (select extract(epoch from f.kickoff_at - k.provider_update_at)/60 m from market.final_prematch_checks k join core.fixtures f on f.id=k.fixture_id where k.outcome='priced' and f.kickoff_at >= '2026-10-12T00:00Z' and f.kickoff_at < '2026-11-11T13:00Z' and k.provider_update_at < f.kickoff_at) x"
echo "---B igual, 14 dias [26-oct, 9-nov)"
psq -tc "select count(*), round(percentile_cont(0.5) within group (order by m)::numeric,1) from (select extract(epoch from f.kickoff_at - k.provider_update_at)/60 m from market.final_prematch_checks k join core.fixtures f on f.id=k.fixture_id where k.outcome='priced' and f.kickoff_at >= '2026-10-26T00:00Z' and f.kickoff_at < '2026-11-09T00:00Z' and k.provider_update_at < f.kickoff_at) x"
echo "---C salidas de la lectura final en la ventana"
psq -tc "select k.outcome, count(*) from market.final_prematch_checks k join core.fixtures f on f.id=k.fixture_id where f.kickoff_at >= '2026-10-12T00:00Z' and f.kickoff_at < '2026-11-11T13:00Z' group by 1 order by 2 desc"

# PM-08-01 · Cobertura del árbitro y con cuánta antelación llega

Plan Maestro PM, ola 1. Medición de solo lectura del **20-nov-2026, 01:35–01:36 UTC**, 0 peticiones. Código del PR que deja
esta guía: OPS-010.

## Método

`core.fixture_facts` guarda una fila por **cambio** de lo que dicen las respuestas de `/fixtures` de un partido (árbitro, país
del árbitro, ganador, inicio de cada mitad), con `observed_at` = la hora de la respuesta (`fbi/ingestion/fixture_facts.py`).
Una respuesta sin ninguno de esos datos no deja fila. Así, la primera fila con árbitro es **la primera vez que PrediGol lo vio**,
y la antelación es `saque − esa hora`.

* Muestra: partidos **terminados** de las competiciones seguidas con saque entre el 5-oct-2026 y hace 3 h (4.669 partidos,
  108 competiciones; total, no muestra).
* Resolución: el calendario de cada competición se pide cada 6 h (`fixtures_sync`, que hoy arranca a las 03:55, 09:55, 15:55
  y 21:55 UTC y dura una hora) y en las capturas en vivo. **La antelación medida es una cota inferior**: el proveedor pudo
  tenerlo hasta unas 6 h antes.
* Antelación negativa = el árbitro apareció después del saque (en la respuesta en vivo o en la de después del partido).

## Resultado por prioridad editorial

| Prioridad | Partidos | Con árbitro | Antes del saque | ≥ 3 h | ≥ 12 h | ≥ 24 h | ≥ 48 h | Mediana (de los que llegan antes) | P25–P75 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 Colombia | 133 | 56,4 % | 24,8 % | 22,6 % | 21,1 % | 11,3 % | 1,5 % | 20,9 h | 17,3–43,1 h |
| P1 internacionales | 572 | 69,4 % | 53,8 % | 46,7 % | 44,8 % | 37,4 % | 3,0 % | 35,5 h | 16,3–37,8 h |
| P2 países prioritarios | 2.347 | 78,1 % | 61,6 % | 57,9 % | 53,3 % | 45,8 % | 25,9 % | 43,6 h | 21,6–58,0 h |
| P3 resto | 1.617 | 75,6 % | 51,0 % | 47,4 % | 41,9 % | 35,2 % | 17,6 % | 36,5 h | 16,3–53,8 h |
| **Todas** | 4.669 | 75,6 % | 55,9 % | 51,9 % | 47,4 % | 40,1 % | 19,5 % | 37,9 h | 18,5–55,5 h |

**Primera A (239):** árbitro en el 100 % de sus 75 partidos, pero **solo el 44 % antes del saque** (mediana 20,9 h; el 20 %
con 24 h o más). En la fase final empeora: del 26-oct al 15-nov, entre el 5 % y el 14 % por semana lo traía antes del saque
(antes del 26-oct, entre el 32 % y el 47 %). **Primera B (240): 0 %** (el proveedor no da árbitro).

Otras de referencia (antes del saque · mediana): Champions 100 % · 37,8 h; Europa League 100 % · 35,5 h; Conference 98 % ·
34,2 h; Nations League 100 % · 36,2 h; Libertadores 4 de 4 · 48,9 h; Premier 100 % · 56,8 h; La Liga 100 % · 13,8 h; Liga MX
84 % · 18,9 h; MLS 100 % · 41,2 h; J1 68 % · 0,7 h; K League 1 17 %; amistosos 0 % (11,5 % con árbitro alguna vez); CAF
Champions y Confederación, FA Cup, EFL Trophy, Copa del Rey, Coupe de France, Taça de Portugal y Türkiye Kupası ≈ 0 %.

Próximos 7 días (lectura de las 01:36 UTC): ninguno de los 8 partidos P0 ni de los 88 P1 tiene árbitro todavía; P2 78 de 365,
P3 34 de 236.

## Lectura para el bloque «Árbitro designado» (PM-08-02)

En la Liga BetPlay el árbitro llega **tarde y no siempre antes del partido**: un bloque prepartido solo se vería en menos de la
mitad de los partidos, y en la fase final casi nunca. Es viable en las competiciones UEFA y en las ligas grandes de Europa y
América con 24 h o más. El bloque tiene que decir «árbitro aún sin designar» cuando no lo hay, nunca inventarlo.

## Consulta reproducible

Guion de la medición (lo deja el plan en `fbi_scratch\pm\b_q0801.sh`; solo lectura, por la entrada estándar de
`ssh predigol bash -s`). Su núcleo:

```
WITH fx AS (SELECT f.id, f.kickoff_at, c.provider_league_id league FROM core.fixtures f
              JOIN core.competition_seasons s ON s.id = f.competition_season_id
              JOIN core.competitions c ON c.id = s.competition_id AND c.is_tracked
             WHERE f.status_group = 'finished' AND f.kickoff_at >= '2026-10-05' AND f.kickoff_at < now() - interval '3 hours'),
     ff AS (SELECT fx.*, min(x.observed_at) FILTER (WHERE nullif(btrim(x.referee), '') IS NOT NULL) first_ref
              FROM fx LEFT JOIN core.fixture_facts x ON x.fixture_id = fx.id GROUP BY fx.id, fx.kickoff_at, fx.league)
SELECT league, count(*) n,
       round(100.0 * count(*) FILTER (WHERE first_ref IS NOT NULL) / count(*), 1) pct_ref,
       round(100.0 * count(*) FILTER (WHERE first_ref < kickoff_at) / count(*), 1) pct_before,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM kickoff_at - first_ref) / 3600)
              FILTER (WHERE first_ref < kickoff_at))::numeric, 1) median_h
  FROM ff GROUP BY 1 ORDER BY 1;
```

con `SET default_transaction_read_only=on; SET statement_timeout='90s'`. La prioridad editorial de cada competición es la del
anexo A del plan (`prioridad_editorial`).

## Vuelta atrás

No hay nada que revertir: la medición solo lee.

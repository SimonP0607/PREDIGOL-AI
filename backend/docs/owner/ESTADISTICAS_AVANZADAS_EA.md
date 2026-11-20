# Estadísticas avanzadas (plan EA, 2026)

Plan aprobado el 18-nov-2026: `claude/PLAN_MAESTRO_ESTADISTICAS_AVANZADAS_2026.md` (proyecto). Este documento dice qué hay en el
código, cómo se enciende y qué queda bloqueado.

## Qué hay

| Pieza | Dónde | Qué hace |
|---|---|---|
| EA-003 a EA-006 | `fbi.stats`, `fbi.statmath`, migración 0167 | El cálculo nocturno (07:20 UTC, `FBI_STATS_AGG`) escribe en `analytics.stat_documents` un documento por equipo, jugador y liga, por temporada en curso (≥ 10 partidos terminados), alcance u5/u10/u20/temporada y contexto todo/local/visitante. Cada pasada queda en `analytics.stat_runs`. Solo base de datos: no pregunta al proveedor ni usa IA |
| EA-008 | `scripts/stats_coverage.py` | Informe de cobertura por métrica y temporada (umbral 80 %): una métrica por debajo no se publica, se dice «cobertura insuficiente» |
| EA-001 / C-13 1.0.0 | `contracts/intelligence/stats_profile.py` | Perfil estadístico: equipo, jugador, comparación y previa del partido |
| EA-002 / C-14 1.0.0 | `contracts/intelligence/market_probs.py` | Probabilidades por mercado: tres marcas (modelo ▮, implícita │, histórico ●) y si Mi parlay la toma |
| EA-102 a EA-107, EA-203 | web `product/teams/stats`, `product/match/stats` | Pestaña Estadísticas de equipo y jugador, `/compare/teams`, `/compare/players`, previa del partido (V2·1 a V2·7, V2·11) |
| EA-201, EA-202 | `services/market_probs.py`, `ProbabilitiesPanel` | Panel de probabilidades en «Mercados» antes del partido (V2·8) |
| EA-501 a EA-503 | `market/eligibility.py`, `picks/rule_settlement.py`, web `match/catalogParlay.ts` | Mi parlay acepta mercados del catálogo con regla IA-070, precio vigente de ≥ 3 casas y línea no de cuarto; se liquidan por su regla; sin datos tras 72 h, nula. El módulo no se rediseñó |

## Decisiones del 19-nov-2026 (BE-049)

- Mi parlay toma un mercado del catálogo solo si la temporada del partido registra lo que liquida su regla en al menos el 80 % de sus partidos terminados (mínimo 10): `fbi.market.settle_coverage`, medido sobre `market.fixture_outcomes`. Si no, `sin_cobertura` (C-14 1.1.0) y el precio dice por qué.
- Las cifras del modelo se comparan en los mismos términos que la implícita y el histórico (`fbi.market.coherence`): en líneas con devolución, la probabilidad de ganar si no hay devolución; en líneas de cuarto, ninguna; la doble oportunidad de una familia se lee de su 1X2 (suma 2).

## Métodos

- Percentiles por rango medio contra la liga (mínimo 8 equipos y 3 partidos; jugadores por posición, mínimo 5 noventas y 10 jugadores).
- Pulso de goles `pulso-v1`: suavizado gaussiano σ = 7,5' en tramos de 5', 45+ y 90+ aparte, índice = 100 · equipo / liga, banda por bootstrap (B = 1000, percentiles 10–90, semilla fija).
- Supervivencia del 0-0 por Kaplan–Meier; estados de partido sobre el reloj de 90'.
- Tendencias con intervalo de Wilson (z = 1,96), contadas con las reglas de liquidación IA-070.
- Probabilidad implícita: consenso sin margen de las casas vigentes. Histórico: últimos 10 de local del local y 10 de visitante del visitante.
- La cifra del modelo solo aparece en mercados que el catálogo tiene `evaluable`; las cifras en calibración (incluido forecast-v2) solo las ve el dueño (D-EA-2). Ningún LLM toca una probabilidad.

## Interruptores (orden D-EA-3)

Ver `INTERRUPTORES_UX.md`: `FBI_STATS_AGG` → `FBI_STATS_V2` → `FBI_MARKET_PROBS` → `FBI_PARLAY_MARKETS_V2` → `FBI_PLAYER_MARKETS`.
Todos apagados por defecto; se encienden con el kit auditado. `FBI_PICKS_SOURCE` no cambia.

## Bloqueado por datos (sonda EA-303 en producción, 18-nov)

Sobre 400 respuestas de cuotas recientes (2 657 partidos): los mercados de jugador solo los ofrece una casa (Bet365) y en ≤ 88
partidos (3 %); faltan varias apuestas de jugador y las etiquetas son ambiguas; las faltas y entradas por equipo casi no existen.
Con la condición del plan (≥ 3 casas) quedan bloqueadas EA-301, 302, 304, 305, 306, 308 y EA-401, y `FBI_PLAYER_MARKETS` sigue
apagado. No se contrata otro proveedor (regla vigente).

Segunda sonda (19-nov, 30 días, 6 000 respuestas de cuotas, 788 partidos): los mercados de jugador aparecen en 262 partidos y 1 055 pares partido-apuesta, **todos de una sola casa (Bet365)**; ninguno llega a 2 casas, menos aún a 3. La alternativa dentro de los recursos ya existe y no se duplica: las cifras de los jugadores (por 90, percentiles por posición, últimos 5) están en su perfil (EA-005), y el laboratorio privado de mercados de jugador (IA-130) sigue midiendo en sombra. `FBI_PLAYER_MARKETS` queda apagado; el kit no permite encenderlo.

## Desviaciones del plan

- La matriz de tendencias viaja en C-13 (no en C-14); C-04 2.0 no hizo falta; comparación y previa son composiciones de C-13.
- EA-307 (cifra forecast-v2 por mercado) se entrega como `model_shadow` privado de C-14, sin guardar una familia nueva.

## Correcciones al texto del plan EA (20-nov-2026, PM-00-03)

El plan EA vive en el proyecto y no se reescribe; lo que sigue corrige tres afirmaciones suyas que el código o la medición
contradicen. Manda esto.

- **Mitades.** El plan dice que el proveedor «no da» córners por mitad. No es así: `fixtures/statistics` acepta `half=true` (blog
  oficial de API-Football y contrato 3.9.3; anotado en `fbi/providers/api_football/integration.py`), y una sonda del 19-nov-2026
  devolvió córners, tarjetas y tiros por mitad en Champions League, Premier League, Primera A de Colombia, Segunda División de
  España y Nations League, y nada en Primera B de Colombia, National League e Isthmian League. **Confirmado en 5 competiciones el
  19-nov; medición por competición en curso (PM-01-05).** Hoy PrediGol no lo pide, así que las reglas `corners_1h` y `corners_2h`
  siguen sin poder liquidar (`no_period_data`) y su nota dice «never by half»: esa nota es dato servido y se cambia con la regla
  nueva de PM-05-03 (una convención nueva es una versión nueva de la regla), no a mano.
- **Tablas.** El plan describía `stats.team_aggregates`, `stats.team_event_series`, `stats.player_aggregates` y
  `stats.team_trends`. Lo construido es una tabla de documentos, `analytics.stat_documents` (con `analytics.stat_runs`, migración
  0167), descrita arriba.
- **`tax-v3`.** El plan reservaba el nombre para la taxonomía de cuotas de jugador (EA-301, bloqueada). Ese nombre ya lo usa el
  libro vigente (`fbi/odds/book_taxonomy.py`), mientras la historia sigue en `tax-v2` (`fbi/odds/quote_taxonomy.py`): una
  ampliación de mercados de jugador necesitará otro nombre.

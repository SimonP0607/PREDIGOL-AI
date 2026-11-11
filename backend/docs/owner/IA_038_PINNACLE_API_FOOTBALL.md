# IA-038 — Pinnacle dentro de API-Football: cobertura, frescura y distancia al consenso

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-A07, ola 1. Medido el 11-nov-2026 en producción, solo lectura.*

## Qué se midió

- **Población.** Los 3.368 partidos terminados de competiciones seguidas con saque entre el 12-oct y el 10-nov-2026 (30 días, UTC). «Con cuotas» = al menos un precio 1X2 de cualquier casa, capturado antes del saque o leído después: **3.284 (97,5 %)**.
- **Pinnacle** es `market.bookmakers.id = 4` (`provider_bookmaker_id = 4`, «Pinnacle»), con `is_sharp = false` y `consensus_weight = 1,00`. El consenso (`fbi/market/consensus.py`) no lee esas dos columnas: hace la media simple de las casas que pasan el desvigado.
- **Dos fuentes de precio.**
  - **S1**: las capturas prepartido, de T-72 h a T-3 h (`market.odds_snapshots`). De ellas sale `market.market_consensus`.
  - **S2**: el último precio prepartido del proveedor, leído después del partido (`market.final_prematch_odds`, con el sello `provider_update_at` anterior al saque).
- **Mercados.** 1X2, más/menos 2,5, ambos marcan y hándicap asiático (cualquier línea).
- **Frescura.** Para cada partido y casa, se busca el último cambio observado del precio 1X2 (y del 2,5) sobre la rejilla común de observaciones (capturas más sello final), y se mide en minutos antes del saque.
- **Distancia al consenso.** Se compara la probabilidad sin margen de Pinnacle (Shin) con el consenso que usa PrediGol en el último precio prepartido. Ese consenso es la referencia del CLV, `last-shin-consensus-before-kickoff` (`fbi/market/closing_reference.py`).
  - El consenso se recalculó con la función de producción `fbi.market.consensus.consensus`, con Pinnacle y sin ella.
  - Se validó contra lo guardado: 133.718 filas, ninguna diferencia mayor de 1e-5 (la mayor fue 5e-7).

## Resultados

### 1. Cobertura de Pinnacle por liga (30 días; % sobre partidos con cuotas, S1 ∪ S2)

| Competición | Partidos | Con cuotas | 1X2 | Más/menos 2,5 | Ambos marcan | Hándicap asiático |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Champions | 54 | 54 | 54 (100 %) | 47 (87,0 %) | 0 | 54 (100 %) |
| Premier League | 41 | 41 | 41 (100 %) | 41 (100 %) | 0 | 41 (100 %) |
| LaLiga | 42 | 42 | 42 (100 %) | 38 (90,5 %) | 0 | 42 (100 %) |
| Serie A | 52 | 52 | 52 (100 %) | 52 (100 %) | 0 | 52 (100 %) |
| Bundesliga | 36 | 36 | 36 (100 %) | 29 (80,6 %) | 0 | 36 (100 %) |
| Ligue 1 | 36 | 36 | 36 (100 %) | 36 (100 %) | 0 | 36 (100 %) |
| Primeira Liga | 28 | 28 | 28 (100 %) | 28 (100 %) | 0 | 28 (100 %) |
| **Grupo 1** (`comp-priority-v1`) | 289 | 289 | 289 (100 %) | 271 (93,8 %) | 0 | 289 (100 %) |
| Libertadores | 4 | 4 | 4 (100 %) | 4 (100 %) | 0 | 4 (100 %) |
| Sudamericana | 4 | 4 | 4 (100 %) | 4 (100 %) | 0 | 4 (100 %) |
| **Grupo 2** (copas continentales) | 163 | 163 | 163 (100 %) | 162 (99,4 %) | 0 | 163 (100 %) |
| Eliminatorias y selecciones (grupo 3) | 0 | — | — | — | — | — |
| **Resto** (grupo 4) | 2.916 | 2.832 | 2.751 (97,1 %) | 2.702 (95,4 %) | 0 | 2.770 (97,8 %) |
| **Total** | 3.368 | 3.284 | **3.203 (97,5 %)** | **3.135 (95,5 %)** | **0 (0 %)** | **3.222 (98,1 %)** |

- **Por fuente (1X2).** Pinnacle está en S1 en 3.170 de 3.255 partidos (97,4 %) y en S2 en 3.139 de 3.221 (97,5 %).
- **Más/menos 2,5.** Hay 149 partidos con cuotas sin el 2,5 de Pinnacle (18 en el grupo 1 y 131 en el resto), y en todos ellos las otras casas sí lo cotizan.
  - Unos 85 son partidos en los que Pinnacle publica más/menos, pero sin la línea 2,5. Pinnacle publica de 5 a 14 líneas por partido, y en esos partidos sus 8 líneas más frecuentes van de 3,0 a 4,75.
  - El resto son partidos sin Pinnacle en ningún mercado: 62 en total.
- **Ambos marcan.** Pinnacle no aparece en ningún partido.

**Contexto por casa (1X2, partidos con cuotas, n = 3.284).**

| Casa | Partidos | % |
| --- | ---: | ---: |
| Marathonbet | 3.257 | 99,2 % |
| Bet365 | 3.234 | 98,5 % |
| Pinnacle | 3.203 | 97,5 % |
| William Hill | 3.195 | 97,3 % |
| 1xBet | 3.186 | 97,0 % |
| Betano | 3.125 | 95,2 % |
| Betfair | 3.096 | 94,3 % |
| BetVictor | 3.086 | 94,0 % |
| Dafabet | 3.079 | 93,8 % |
| SBO | 2.508 | 76,4 % |

Dafabet no cotizaba el 4-oct. En el grupo 1, ocho casas (Pinnacle incluida) tienen los 289 partidos.

### 2. Verificación del «Pinnacle ≈ 70 %» de la Parte I

| Periodo (saque) | Capturados antes del saque | con Pinnacle | Con cuotas (S1 ∪ S2) | con Pinnacle |
| --- | ---: | ---: | ---: | ---: |
| 25-sep a 4-oct 09:00 (ventana del informe del 4-oct) | 182 | **128 (70,3 %)** | 353 | 339 (96,0 %) |
| 4-oct 09:00 a 6-oct | 81 | 75 (92,6 %) | 89 | 82 (92,1 %) |
| 6 a 8-oct | 84 | 79 (94,0 %) | 84 | 80 (95,2 %) |
| 8 a 10-oct | 90 | 90 (100 %) | 91 | 91 (100 %) |
| 10 a 12-oct | 437 | 435 (99,5 %) | 438 | 436 (99,5 %) |
| 12-oct a 10-nov (esta medición) | 3.255 | 3.170 (97,4 %) | 3.284 | 3.203 (97,5 %) |

Por semana ISO dentro de la ventana (con cuotas): W42 760/802 (94,8 %), W43 778/791 (98,4 %), W44 798/818 (97,6 %), W45 818/822 (99,5 %) y W46 parcial 49/51.

Presencia de Pinnacle en cada captura según la distancia al saque (12-oct a 10-nov):

| Distancia | Menos de 4 h | 4–8 h | 8–15 h | 15–30 h | 30–60 h | 60–120 h |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Capturas | 3.204 | 3.125 | 3.120 | 3.044 | 2.817 | 2.573 |
| Con Pinnacle | 97,5 % | 98,3 % | 97,8 % | 94,5 % | 93,5 % | 86,0 % |

### 3. Frescura: ¿deja Pinnacle de actualizarse antes?

Base: 3.142 partidos con capturas y lectura final con Pinnacle (1X2) y 3.075 en más/menos 2,5.

| Medida | Pinnacle | Otras casas |
| --- | ---: | ---: |
| Último cambio observado, 1X2, minutos antes del saque (p25 / mediana / p75) | 53,8 / **91,8** / 175,0 (n = 3.142) | 59,7 / **168,8** / 358,7 (n = 26.835) |
| Último cambio observado, más/menos 2,5 (p25 / mediana / p75) | 56,8 / **104,2** / 176,0 (n = 3.075) | 63,8 / **175,7** / 715,5 (n = 18.569) |
| Pasos de observación en que cambia el precio, 1X2 | **75,0 %** (16.639 pasos) | 50,2 % (129.783) |
| Pasos en que cambia el precio, más/menos 2,5 | **73,6 %** (16.279) | 39,8 % (90.772) |
| Cambió entre la captura de T-3 h y la lectura final, 1X2 | **84,2 %** (n = 3.108) | 61,3 % (n = 25.728) |
| Presente en la lectura final si estaba en las capturas | **99,9 %** (n = 3.109) | 72–100 % según la casa |

- **Comparación pareada, mismo partido.** El último cambio de Pinnacle es igual al de la mediana de las otras casas en el 60,9 % de los partidos, más tardío en el 35,7 % y más temprano solo en el 3,4 %.
- **Rejilla de observación.** La lectura final lleva el sello del proveedor, una mediana de 88,8 min antes del saque (p25 50,8, p75 150,8; n = 3.221). La última captura está a una mediana de 175,9 min (p25 175,2, p75 178,4; n = 3.255).
- **Pinnacle sin cambios desde T-3 h.** Su precio final coincide con el de T-3 h en el 7,4 % de los partidos del grupo 1 (21/283) y en el 16,9 % del resto (478/2.822).

### 4. Pinnacle frente al consenso de PrediGol, en puntos porcentuales (pp)

**a) Mismo instante.** Última captura antes del saque, que es la referencia del CLV, con 9 casas de mediana (p25 9, p75 10). Pinnacle está en esa captura en 3.168 de 3.255 partidos.

| Selección | n | Pinnacle − consenso: media | desv. típica | error medio absoluto | p90 de \|d\| | Pinnacle − consenso sin Pinnacle (error medio abs.) | Efecto de quitar Pinnacle (error medio abs.) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1X2 local | 3.165 | +0,11 | 0,84 | 0,62 | 1,29 | 0,70 | 0,08 |
| 1X2 empate | 3.165 | −0,11 | 0,72 | 0,54 | 1,11 | 0,61 | 0,07 |
| 1X2 visitante | 3.165 | −0,01 | 0,80 | 0,59 | 1,22 | 0,67 | 0,08 |
| Más de 2,5 | 3.094 | −0,03 | 0,85 | 0,61 | 1,26 | 0,73 | 0,11 |
| Hándicap asiático, local (todas las líneas de Pinnacle) | 28.646 líneas | +0,01 | 1,14 | 0,75 | 1,59 | 0,99 | 0,24 |

En el grupo 1 (n = 289) la distancia es menor, en error medio absoluto (desv. típica entre paréntesis):

- local, 0,48 (0,60);
- empate, 0,38 (0,47);
- visitante, 0,46 (0,56);
- más de 2,5, 0,57 (0,72; n = 271);
- hándicap asiático, 0,58 (0,77; 2.723 líneas).

**b) Último precio del proveedor (S2) frente a la referencia de CLV.** 1X2, n = 3.105. La referencia está a una mediana de 175,9 min del saque y S2 a unos 89 min.

| Selección | Pinnacle final − referencia (media / desv. / error medio abs. / p90) | Consenso final de todas las casas − referencia | Pinnacle final − consenso final (mismo instante) | Pinnacle final − Pinnacle en T-3 h |
| --- | --- | --- | --- | --- |
| Local | +0,12 / 2,39 / **1,54** / 3,71 | 0,00 / 1,99 / 1,11 / 2,97 | +0,12 / 0,97 / 0,69 / 1,42 | 0,00 / 2,27 / 1,30 / 3,55 |
| Empate | −0,14 / 1,12 / 0,81 / 1,78 | −0,04 / 0,68 / 0,39 / 1,04 | −0,10 / 0,76 / 0,56 / 1,19 | −0,03 / 0,92 / 0,55 / 1,38 |
| Visitante | +0,02 / 2,23 / **1,40** / 3,28 | +0,03 / 1,86 / 1,00 / 2,61 | −0,02 / 0,92 / 0,65 / 1,32 | +0,03 / 2,11 / 1,16 / 3,16 |

**Margen 1X2 en la última captura (mediana, p25–p75).**

| Casa | Grupo 1 (n = 289) | Resto |
| --- | --- | --- |
| Pinnacle | **3,18 %** (2,78–3,55) | **4,69 %** (3,65–6,47; n = 2.879) |
| Marathonbet | 4,27 % | 8,59 % |
| Bet365 | 5,57 % | 7,88 % |

## Conclusiones

1. **El «Pinnacle ≈ 70 %» ya no vale.**
   - Se reproduce exacto con los datos de hoy: 128 de 182 partidos capturados antes del saque entre el 25-sep y el 4-oct.
   - Ese mismo periodo daba 96 % si se suma la lectura final.
   - Desde el 8-oct, Pinnacle está en el 97–100 % de lo capturado. En los últimos 30 días cotiza el 1X2 del 97,5 % de los partidos con cuotas y el hándicap asiático del 98,1 %. En los grupos 1 y 2 llega al 100 % en los dos mercados.
   - No da ambos marcan (0 %). En más/menos 2,5 se queda en el 95,5 %: en unos 85 partidos publica sus líneas de 3,0 hacia arriba, y en 62 no está en ningún mercado.
   - Hipótesis, no verificada: la cifra baja del arranque encaja con que Pinnacle aparece más tarde que otras casas (86 % de las capturas a 60–120 h del saque frente a 97,5 % a menos de 4 h).
2. **Pinnacle no deja de actualizarse antes; el límite es el proveedor.**
   - Es la casa que más se mueve dentro de API-Football: cambia en el 75 % de los pasos, frente al 50 % de las demás, y en el 84 % de los partidos se movió entre T-3 h y el precio final.
   - Su último cambio (mediana de 92 min antes del saque) coincide con el último sello del proveedor (mediana de 89 min).
   - Lo que falta para todas las casas es la última hora y media antes del saque.
3. **A la misma hora, Pinnacle y el consenso de PrediGol casi coinciden.**
   - Error medio absoluto de 0,54–0,62 pp en 1X2, sesgo de 0,11 pp o menos y p90 de 1,1–1,3 pp. En el grupo 1, de 0,38–0,48 pp.
   - Quitar Pinnacle mueve el consenso 0,07–0,08 pp: con peso 1 entre 9 casas, Pinnacle no puede cambiarlo.
4. **Lo que más separa la referencia de CLV del cierre es el tiempo, no la casa.**
   - La referencia es la captura de T-3 h (mediana de 176 min antes del saque). Hasta el último precio del proveedor (unos 89 min), el propio consenso se mueve 1,0–1,1 pp en local y visitante, y Pinnacle 1,2–1,3 pp.
   - Hecho: PrediGol ya guarda ese precio final sin coste. La lectura final trae a Pinnacle en 3.139 de los 3.221 partidos leídos (97,5 %).
5. **Para tu decisión sobre la API de Pinnacle: los datos no la justifican ni por cobertura ni por frescura frente a API-Football.**
   - Lo único que podría añadir, como hipótesis, es el tramo final hasta el saque (un cierre verdadero) y la certeza de que los precios son los de Pinnacle; eso no se puede comprobar aquí.
   - Antes de pedir nada, lo barato es medir el CLV también contra `final_prematch_odds`, del consenso o de Pinnacle sola. `python -m scripts.postmortems closes` ya compara las dos referencias.
   - Si después la sigues queriendo, las condiciones de uso de Pinnacle van antes al abogado (ficha INT-A07).
   - Nada de esto toca el consenso, los umbrales ni los picks antes del Gate B del 25-nov.

## Limitaciones

- **Resolución de la frescura.** Está limitada por la rejilla: capturas en ventanas fijas (T-72 h…T-3 h) más el sello final del proveedor. El sello `update` del proveedor es por partido, no por casa, así que el «último cambio» por casa se deduce de los cambios de precio. Lo que pase entre dos observaciones no se ve.
- **Autenticidad de Pinnacle.** No se puede comprobar que el «Pinnacle» de API-Football sea el precio de Pinnacle en su web: no hay fuente independiente y su API pública está cerrada desde el 23-jul-2025, según `docs/research/ODDS_PROVIDER_GAP_ANALYSIS_2026.md`. Su margen bajo (3,2 % en el grupo 1) y su actividad son coherentes con una casa *sharp*, pero no lo prueban.
- **Muestra.** Libertadores y Sudamericana tienen 4 partidos cada una. No hubo eliminatorias ni torneos de selecciones en la ventana.
- **Partidos excluidos.** Se dejaron fuera los aplazados (32) y cancelados (6). 84 terminados no tienen ningún precio.
- **Hándicap asiático.** Se comparan todas las líneas que publica Pinnacle, y las líneas extremas dan colas largas (máximo de 19,8 pp). La cifra útil es la del grupo 1.
- **Ventana de capturas.** Las series de frescura empiezan como pronto 5 días antes del saque.

## Cómo se midió (consultas resumidas)

Todo en solo lectura (`default_transaction_read_only=on`, `statement_timeout=95 s`), con una consulta pesada cada vez y en tramos semanales. Los cálculos se hicieron en la imagen del backend con `--network none`. Carpeta de trabajo: `/tmp/lab_A07` del servidor, borrada al terminar.

1. **Casas.** `select id, provider_bookmaker_id, name, is_sharp, consensus_weight from market.bookmakers`, donde Pinnacle es id 4.
2. **Población.** `core.fixtures` con `kickoff_at` en [2026-10-12, 2026-11-11) y `status_group = 'finished'`: 3.368 partidos.
3. **Series de precio.** Exportadas de `market.odds_snapshots`, unidas a `core.fixtures`, en tramos semanales:
   - condiciones `source = 'prematch'`, `captured_at < kickoff_at` y `captured_at >= kickoff_at - 5 días`;
   - mercados: 1X2 y más/menos 2,5 de todas las casas, y ambos marcan y hándicap asiático solo de Pinnacle;
   - resultado: 991.937 filas.
4. **Precio final.** De `market.final_prematch_odds`, para los mismos mercados (184.658 filas).
5. **Consenso guardado.** De `market.market_consensus`, con `devig_method = 'shin'` y `as_of` igual al último `as_of < kickoff_at` de cada partido, mediante LATERAL (143.547 filas). También el hándicap asiático de todas las casas en la última captura (418.333 filas).
6. **Cálculo** (`analisis_a07.py`, `analisis_a07b.py` y `analisis_a07c.py`, en Python):
   - cobertura S1 ∪ S2 por partido y mercado;
   - último cambio por casa sobre la rejilla común;
   - consenso Shin recalculado con `fbi.market.consensus.consensus`, con y sin la casa 4, y comparado con lo guardado;
   - desvigado de Pinnacle con la misma función;
   - diferencias en pp.
7. **Verificación del 70 %.** Por tramos de 1 a 7 días entre el 25-sep y el 12-oct, por partido: si hay alguna fila 1X2 «Home» antes del saque en `odds_snapshots`, si la hay de la casa 4, y lo mismo en `final_prematch_odds` (LATERAL por partido).
8. **Escalera de más/menos de Pinnacle.** Líneas distintas por partido de `odds_snapshots` con `bookmaker_id = 4` y `market_key = 'OU'`.

Resultados en bruto guardados junto a este informe: `lab/IA_038/a07_results_20261111.json` y `lab/IA_038/a07_blocks_diff_20261111.json`.

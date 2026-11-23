# IA-154 · PM-10-08 · Cuántos partidos necesita cada estadística de equipo para ser estable

Plan Maestro PM, ola 5–6, tarea **PM-10-08** (OP-17). Calculado **fuera del servidor**, sobre la exportación de solo lectura del
LAB, con el protocolo preregistrado `PM-10-08` (`proto-pm-10-08-v1`, huella `9a8fdf48f635…e50b`). Nada se publica ni cambia en
producción: la tabla resultante (`src/fbi/stats/stabilization_v1.json`) **no la lee ningún código** y solo puede **subir** un mínimo
de muestra; bajarlo exige decisión del dueño.

## 1. Orden de los hechos (todo en UTC, 21-nov-2026)

| Hora | Hecho |
| --- | --- |
| 03:24:45 | Protocolo `PM-10-08` (y los de PM-08-07, PM-09-07, PM-12-03) empujado al repositorio: commit `fd0e5aa`, PR #461 |
| 03:37:07 | Código del LAB (`scripts/lab_stabilization.py` y comunes) empujado, probado solo con datos sintéticos: commit `b7d68df` |
| 05:00:55 | #461 fusionado en `main` (squash `194bf2f`) |
| 05:01:32–05:03:04 | Exportación `lab-export-v2` en el worker (`run --since 2019-01-01`, el `lab_export.py` de `main` por la entrada estándar, SHA-256 `f476c888…b49b`): 19 tablas, 5.293.854 filas, 35,3 MB; foto `4765478:4765516:4765478`, código desplegado `b14701da1afb` |
| 05:04 | Descarga al portátil (`fbi_scratch\lab\20261121T050132Z.tar`, SHA-256 `67204cc5…fc17`), `verify` correcto en el portátil y en el contenedor |
| 05:05 | Cálculo en el contenedor de la nube (no en el servidor): `python -m scripts.lab_stabilization <carpeta> --out … --table …` |

## 2. Método (el del protocolo, sin cambios)

Para cada estadística, lado (a favor / en contra), liga nacional y temporada **cerrada** desde 2019: varianza dentro del equipo
`s2w` (agrupada) y varianza real entre equipos `tau2 = var(medias) − media(s2w/n_i)`; por liga, ambas promediadas sobre sus
temporadas ponderando por equipos. Partidos para fiabilidad R: `n_R = R/(1−R) · s2w/tau2` (n50 y n70). Intervalo: bootstrap de
equipos dentro de cada temporada (1.000 réplicas, semilla 20261121). **Validación por mitades de temporada**: correlación entre
equipos de la media de la primera mitad (por fecha) y la de la segunda, frente a la predicha `R(m) = m/(m + s2w/tau2)`; una liga
valida si la observada ≥ predicha − 0,10; la estadística **PASA** si valida el 70 % de sus ligas elegibles (≥ 2 temporadas con ≥ 10
equipos de ≥ 10 partidos y cobertura ≥ 80 %). La cifra global es la mediana de las ligas.

Lectura: los mismos datos que la web (`core.fixture_team_stats` de origen `api-football`, como `fbi.stats.data`); goles del
resultado reglamentario. Única precisión de implementación: «temporada cerrada» excluye las que tienen partidos `postponed` sin jugar
(el protocolo solo exime los cancelados o abandonados; el proveedor no usa `abandoned`).

## 3. Resultado

**22 de 25 estadísticas PASAN; 3 NO PASAN** (faltas a favor y en contra, fueras de juego en contra: su correlación entre mitades
queda por debajo de lo predicho en más del 30 % de las ligas, es decir, cambian dentro de la temporada más de lo que el azar
explica). Ninguna queda INSUFICIENTE.

| Estadística | Lado | Veredicto | Ligas | Validadas | n50 | n70 | Fiab. a 5 | a 10 | a 20 | n50 Premier · Serie A · LaLiga · Bundesliga · Ligue 1 · Primera A |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Goles | a favor | PASA | 80 | 90 % | 15,6 | 36,4 | 0,24 | 0,39 | 0,56 | 9 · 9 · 9 · 6 · 10 · 33 |
| Goles | en contra | PASA | 80 | 82 % | 19,0 | 44,3 | 0,21 | 0,34 | 0,51 | 17 · 15 · 22 · 27 · 18 · 34 |
| xG del proveedor | a favor | PASA | 16 | 88 % | 6,1 | 14,2 | 0,45 | 0,62 | 0,77 | 6 · 6 · 5 · 4 · 6 · — |
| xG del proveedor | en contra | PASA | 16 | 88 % | 11,9 | 27,7 | 0,30 | 0,46 | 0,63 | 9 · 11 · 22 · 13 · 13 · — |
| Tiros | a favor | PASA | 65 | 74 % | 7,6 | 17,7 | 0,40 | 0,57 | 0,72 | 5 · 6 · 7 · 7 · 8 · 30 |
| Tiros | en contra | PASA | 65 | 75 % | 7,7 | 17,9 | 0,39 | 0,57 | 0,72 | 5 · 6 · 9 · 7 · 8 · 15 |
| Tiros a puerta | a favor | PASA | 65 | 88 % | 10,5 | 24,6 | 0,32 | 0,49 | 0,65 | 7 · 7 · 7 · 6 · 7 · 31 |
| Tiros a puerta | en contra | PASA | 65 | 82 % | 13,2 | 30,7 | 0,28 | 0,43 | 0,60 | 9 · 10 · 16 · 13 · 13 · 53 |
| Tiros dentro del área | a favor | PASA | 57 | 81 % | 8,0 | 18,7 | 0,38 | 0,56 | 0,71 | 5 · 6 · 8 · 7 · 7 · 17 |
| Tiros dentro del área | en contra | PASA | 57 | 84 % | 9,3 | 21,6 | 0,35 | 0,52 | 0,68 | 7 · 6 · 12 · 9 · 10 · 21 |
| Córneres | a favor | PASA | 66 | 91 % | 17,0 | 39,6 | 0,23 | 0,37 | 0,54 | 11 · 19 · 15 · 14 · 26 · 138 |
| Córneres | en contra | PASA | 66 | 85 % | 15,9 | 37,2 | 0,24 | 0,39 | 0,56 | 9 · 11 · 26 · 14 · 20 · 44 |
| Posesión | a favor | PASA | 63 | 84 % | 3,0 | 7,0 | 0,62 | 0,77 | 0,87 | 2 · 2 · 2 · 2 · 2 · 9 |
| Pases | a favor | PASA | 57 | 77 % | 2,3 | 5,3 | 0,69 | 0,82 | 0,90 | 1 · 1 · 1 · 1 · 1 · 6 |
| Pases | en contra | PASA | 57 | 84 % | 5,8 | 13,6 | 0,46 | 0,63 | 0,77 | 4 · 6 · 7 · 6 · 5 · 20 |
| Precisión de pase | a favor | PASA | 57 | 74 % | 2,4 | 5,6 | 0,68 | 0,81 | 0,89 | 1 · 2 · 1 · 1 · 2 · 8 |
| Precisión de pase | en contra | PASA | 57 | 81 % | 8,3 | 19,4 | 0,38 | 0,55 | 0,71 | 8 · 8 · 9 · 11 · 8 · 15 |
| Paradas | a favor | PASA | 64 | 78 % | 20,2 | 47,2 | 0,20 | 0,33 | 0,50 | 13 · 16 · 29 · 20 · 20 · 76 |
| Paradas | en contra | PASA | 64 | 80 % | 19,9 | 46,5 | 0,20 | 0,33 | 0,50 | 14 · 16 · 13 · 13 · 16 · 53 |
| Fueras de juego | a favor | PASA | 59 | 81 % | 34,1 | 79,5 | 0,13 | 0,23 | 0,37 | 47 · 29 · 61 · 48 · 19 · 46 |
| Fueras de juego | en contra | NO PASA | 59 | 27 % | 7,7 | 18,0 | 0,39 | 0,57 | 0,72 | 6 · 5 · 4 · 9 · 9 · 6 |
| Faltas | a favor | NO PASA | 65 | 68 % | 13,2 | 30,9 | 0,27 | 0,43 | 0,60 | 15 · 11 · 5 · 7 · 13 · 14 |
| Faltas | en contra | NO PASA | 65 | 63 % | 13,1 | 30,5 | 0,28 | 0,43 | 0,61 | 8 · 9 · 18 · 14 · 13 · 12 |
| Amarillas | a favor | PASA | 63 | 86 % | 38,7 | 90,4 | 0,11 | 0,21 | 0,34 | 29 · 34 · 22 · 34 · 43 · 36 |
| Amarillas | en contra | PASA | 63 | 87 % | 37,6 | 87,8 | 0,12 | 0,21 | 0,35 | 23 · 24 · 39 · 41 · 32 · 44 |

«Validadas»: ligas donde la mitad de temporada confirma la predicción. «Fiab. a n»: fiabilidad mediana de la media de n partidos.

### Qué significa para la web (propuesta; no se aplica)

* Hoy `team-agg-v1` (`fbi.stats.team`) muestra percentiles con **3** partidos (`MIN_MATCHES`) y ámbitos de 5, 10 y 20. Con 3
  partidos la fiabilidad mediana va de 0,07 (amarillas) a 0,57 (pases) según la estadística: solo **pases, precisión de pase y posesión** (n50 ≤ 4) son
  más señal que azar con tan pocos partidos.
* Con **5 partidos** (ámbito u5) pasan de 0,5 solo esas tres; tiros, xG a favor y pases en contra se acercan (0,40–0,46). Goles,
  tiros a puerta, córneres, paradas, amarillas y fueras de juego necesitan **10–40 partidos** para ser más señal que ruido: un
  «últimos 5» de esas cifras es sobre todo azar y debería decirlo.
* La tabla propone `max(3, n50)` como mínimo por estadística (columna `proposed_min_matches`): de 3 (pases, precisión) a 39
  (amarillas a favor). En la Primera A de Colombia los n50 suelen ser varias veces mayores que en las cinco grandes (tiros a favor 30 frente a 5–8;
  córneres a favor 138 frente a 11–26): sus equipos se parecen más entre sí, y la cifra de la liga, no la global, es la que vale allí.
* Las tres que NO PASAN conservan la convención actual, sin mínimo medido.

## 4. Criterios de aceptación y cierre

| Criterio (ficha) | Estado |
| --- | --- |
| Tabla de estabilización por estadística y liga, de solo lectura | **Cumplido**: `src/fbi/stats/stabilization_v1.json` (versión `stabilization-v1`, con el sello del protocolo y de la exportación); nada la lee |
| Validación por mitades de temporada | **Cumplido** (sección 2) |
| Puede subir mínimos, nunca bajarlos sin decisión | **Cumplido**: propone `max(vigente, n50)`; no cambia ningún mínimo |
| Tabla publicada en la consola con su método | **Pendiente**: la consola es web (zona UX) y exige una ruta privada; queda propuesto como pieza aparte tras la decisión del dueño |
| Veredicto registrado y decisión del dueño anotada | Veredicto registrado aquí; **decisión del dueño pendiente** (¿se adoptan los mínimos propuestos y el aviso de «muestra pequeña» en las cifras con n50 > 5?) |

## 5. Reproducir

```
python scripts/lab_export.py verify <carpeta 20261121T050132Z>
python -m scripts.lab_stabilization <carpeta> --out pm1008.json --table stabilization_v1.json
```

Resultado completo (1,6 MB, todas las ligas y temporadas): `fbi_scratch\lab\results_20261121\pm1008_stabilization.json` en el
portátil del dueño, SHA-256 `f8b678f2…88b7`; la tabla del repositorio, `2a118299…89c9`.

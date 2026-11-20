# IA-072 · Reglamentos codificados por competición y versionados

Pieza **AD-B01** del plan de la arquitectura definitiva 2026 (ola 2, ruta crítica AD-B01 → AD-B02). Guarda el reglamento de cada
competición como **datos revisables**, con su fuente oficial enlazada y la fecha en que se comprobó, para que el motor de escenarios
(AD-B02) pueda decir «qué se juega cada equipo» calculándolo en vez de leerlo de un texto. Donde no hay reglamento leído, el estado
es explícito: **«reglamento no codificado»**, y nada se afirma sobre objetivos.

No usa ningún modelo de lenguaje, ni internet en producción, ni ninguna API de pago. No tiene interruptor: es dato de referencia que
solo leerán AD-B02 y las vistas privadas. **No cambia nada de lo que ve el lector, ni picks, ni probabilidades, ni `decision-v1`.**

## 1. Qué hay

| Pieza | Dónde | Qué hace |
| --- | --- | --- |
| Ficheros de reglas | `config/rules/<id>_<nombre>/v<N>.yaml` | Uno por competición y versión: formato, fases, grupos, zonas por puesto, criterios de desempate en orden, tablas anual/acumulada/promedio, play-offs, ascensos, descensos y plazas continentales. Cada uno con su enlace oficial y su fecha. |
| Cobertura | `config/rules/coverage.yaml` | Las 136 competiciones que sigue producción (81 ligas y 55 copas, leído el 16-nov-2026): codificada o «no codificada» **con su motivo**. |
| Lector | `fbi/competitions/rules.py` | `rules_for(liga, temporada, on=fecha)` devuelve el reglamento vigente o `reglamento_no_codificado` con el motivo. Valida el esquema (`validate()`). |
| Desempates | `fbi/competitions/ranking.py` | Ordena una tabla con los resultados y los criterios del reglamento. Lo que los resultados no resuelven (fair play, coeficiente, sorteo, partido de desempate) queda **abierto**, nunca se adivina. |
| Reconstrucción | `fbi/competitions/reconstruction.py` | Compara la tabla que dan las reglas con la del proveedor (`core.standings`), puesto a puesto. |
| Registro | tabla `core.competition_rules` (migración 0143) | Cada versión cargada en producción, de solo añadido. |
| Mando | `scripts/ia_rules.py` | `check`, `show`, `status`, `load`, `reconstruct`. |

Solo se guardan **parámetros y el enlace**, nunca el texto del reglamento.

## 2. Qué está codificado (16-nov-2026)

Leído **solo** de reglamentos oficiales publicados. Lo que no se pudo abrir o no estaba claro queda como «no codificado» o como un
hueco declarado (`gaps`) dentro del fichero.

| Competición | Temporadas | Fuente oficial | Huecos declarados |
| --- | --- | --- | --- |
| Premier League | 2025/26, 2026/27 | Handbook, sección C | plazas europeas |
| LaLiga | 2025/26, 2026/27 | RFEF, normas de competición (arts. 7, 8, 10) | plazas UEFA (condicionales); orden durante la temporada |
| Serie A | 2025/26 (v1), 2026/27 (v2) | FIGC C.U. 331/A y 244/A; NOIF art. 49 | plazas UEFA; orden durante la temporada |
| Bundesliga | 2025/26, 2026/27 | DFL Spielordnung (Stand 06.03.2026) | plazas UEFA |
| Ligue 1 | 2025/26 | LFP Règlement des Compétitions 2025/2026 | plazas UEFA; empate del barrage (art. 519 ter no leído) |
| Liga BetPlay (Colombia) | 2026 (I y II) | DIMAYOR, reglamento 2026 «V0 - 14/01/26» (subido en abril de 2026; ver la nota de abajo) | — |
| Champions League | 2026/27, fase liga | UEFA, Regulations 2026/27 arts. 17-18 | eliminatorias no codificadas |
| Brasileirão Série A | 2026 | CBF, REC 2026 | orden durante la temporada |
| Liga Profesional Argentina | 2026 | LPF, reglamento de torneos 2026 | **descensos** (los fija el art. 93 del Estatuto AFA, no leído) |
| MLS | 2026 | mlssoccer.com (desempates y formato de play-offs) | empate del partido comodín; plazas CONCACAF |
| Liga MX | 2025/26 (v1), 2026/27 (v2) | FMF, reglamentos de competencia 2025-26 y 2026-27 | criterio «marcadores particulares» (no define cómo se cuenta) |

*Nota del 20-nov-2026 (PM-00-03).* La edición vigente de la Liga BetPlay es la **V0 fechada el 14-ene-2026** («V0 - 14/01/26»
en el propio PDF), la que enlaza el sitio de la DIMAYOR ([artículo del 13-abr-2026](https://dimayor.com.co/2026/04/13/reglamento-copa-betplay-dimayor-2026/));
el «16-04-2026» que figuraba aquí y que sigue en `config/rules/239_primera_a_colombia/v1.yaml` (`published`) es la fecha de
subida del archivo (carpeta `2026/04`), no la de la edición. En el mismo servidor hay una edición anterior, «V12 - 2026/01/09».
El fichero de reglas no se corrige a mano: sus versiones se añaden, no se reescriben, y su huella entra en
`core.competition_rules`; lo corrige la sesión de Intelligence con la próxima versión. La Copa BetPlay 2026 tiene una edición
del 25-ago-2026 (V1: octavos y cuartos a partido único) que sustituye a la del 17-mar-2026 (V5: a ida y vuelta); la Copa no está
codificada, así que hoy no cambia ninguna regla. Fuente: verificación del 19-nov-2026 del Plan Maestro PM.

**No codificado, con motivo**: Copa Libertadores (el CDN oficial de CONMEBOL rechazó la descarga, HTTP 403; el cambio de desempate
de 2026 solo se conoce por prensa y la prensa no es fuente de una regla), las otras 71 ligas y las 54 copas restantes (pendientes,
sin reglamento leído). Temporadas no cubiertas responden también «no codificado»: Ligue 1 2026/27 (reglamento no localizado),
Champions 2025/26 (el art. 18 de esa edición no se pudo abrir), Colombia 2025.

### Cambios de formato dentro de un año

- **Colombia 2026**: la Liga I termina en cuartos, semifinales y final; la Liga II en dos cuadrangulares y final. Las etiquetas del
  proveedor lo distinguen («Apertura - Quarter-finals» frente a «Clausura - Quadrangular - 3») y el lector devuelve la fase que toca.
  En los cuadrangulares, un empate entre una cabeza de grupo (1.º o 2.º de la Fase I) y otro club lo gana la cabeza de grupo.
- **Liga MX**: el Apertura 2025 tuvo *play-in* (7.º-10.º); el Clausura 2026 y la temporada 2026-27, no (los 8 primeros a cuartos).

## 3. Qué se midió (solo lectura en producción, 16-nov-2026)

Con los resultados guardados (`core.fixtures` + `core.fixture_results`) y la última tabla del proveedor de cada grupo
(`core.standings`), las reglas codificadas reconstruyen la tabla **puesto a puesto**:

| Competición y fase | Equipos | Coinciden | Comentario |
| --- | ---: | ---: | --- |
| Premier League 2025/26 | 20 | 20 | 6 puestos decididos por diferencia de goles |
| LaLiga 2025/26 | 20 | 20 | dos empates a tres resueltos por la mini-liga: Sevilla 13.º con la peor diferencia de los tres (43 pts); Mallorca 18.º y descendido entre Levante, Osasuna y Mallorca (42 pts) |
| Serie A 2025/26 | 20 | 20 | Torino 12.º sobre Parma por la *classifica avulsa*, con peor diferencia general |
| Bundesliga 2025/26 | 18 | 18 | |
| Ligue 1 2025/26 | 18 | 18 | un partido de la última jornada figura «AWD» sin marcador; el proveedor tampoco lo cuenta |
| Liga MX Clausura 2026 | 18 | 18 | 1.º y 2.º (Pumas y Chivas, 36 pts) por diferencia de goles |
| MLS 2026 (Este y Oeste) | 30 | 30 | 8 puestos decididos por número de victorias (primer criterio en MLS) |
| Argentina 2026, zonas del Apertura y del Clausura | 60 | 60 | |
| Colombia 2026, Fase I de la Liga I | 20 | 20 | |
| Colombia 2026, Fase I de la Liga II | 20 | 18 | los 2 puestos que no coinciden (13.º y 14.º) son de **datos**, no de reglas: la fila del proveedor de Internacional de Bogotá suma 3 puntos y un marcador distinto de los resultados guardados (23 pts 25-25 frente a 20 pts 22-27). Sin verificar la causa. |
| Brasileirão 2026 (en curso) | 20 | 20 | orden por victorias primero |
| Liga MX Apertura 2026 (en curso) | 18 | 18 | |
| Champions 2026/27, fase liga (4 jornadas) | 36 | 36 | criterios a-e durante la fase |

**Criterio de cierre de la ficha**: 81 de 81 ligas seguidas tienen reglamento codificado o «no codificado» con motivo (**cumplido**).
En las codificadas, la última temporada cerrada con datos se reconstruye idéntica en el 100 % de los puestos (PL, LaLiga, Serie A,
Bundesliga, Ligue 1, Liga MX Clausura 2026, MLS 2026, Argentina 2026 zonas, Colombia Liga I 2026). La única diferencia medida es
de datos del proveedor (Colombia Liga II), no de reglas. Brasil está en curso y Colombia 2025 no está codificada.

Las ocho temporadas cerradas quedaron congeladas como prueba (`tests/fixtures/competition_rules/`): si alguien cambia un fichero de
reglas o el motor y deja de reconstruirlas, la prueba falla.

## 4. Cómo se usa tras desplegar (un paso en el servidor)

```
python -m scripts.ia_rules check                      # los ficheros validan (no toca la base)
python -m scripts.ia_rules load                       # registra las 13 versiones en core.competition_rules (idempotente)
python -m scripts.ia_rules status                     # cobertura frente a lo que sigue producción; versiones por cargar
python -m scripts.ia_rules show --league 239 --season 2026
python -m scripts.ia_rules reconstruct --league 39 --season 2025 --phase season.league --group "Premier League"
```

`load` es el único que escribe, solo en la tabla nueva de solo añadido. `status` y `reconstruct` abren la base en solo lectura.
`status` devuelve error si producción sigue una competición que no está en `coverage.yaml` (por ejemplo, tras ampliar ligas).

## 5. Cómo añadir o corregir una regla

1. Leer el reglamento **oficial** de la temporada. Sin fuente oficial enlazada, no se codifica.
2. Nuevo fichero `config/rules/<id>_<nombre>/v<N+1>.yaml` con sus `seasons` (y `valid_from`/`valid_to` si cambia a mitad de
   temporada). El validador impide que dos versiones respondan por la misma temporada los mismos días.
3. Si una versión estaba mal: no se borra. Se pone `state: retired` con `retired_reason` y se añade la versión corregida.
4. Marcar la competición `coded` en `coverage.yaml`, pasar `scripts.ia_rules check`, la prueba de reconstrucción, y desplegar;
   después `load`.

## 6. Qué no cambia y cómo se revierte

- No cambia ninguna pantalla, prompt, motor, umbral, pick ni probabilidad. `stakes-v5` sigue como está hasta AD-B02.
- Sin interruptor: nada lo lee todavía salvo el mando y las pruebas.
- **Vuelta atrás**: revertir el PR. La migración 0143 tiene bajada (borra la tabla y su función; los ficheros siguen en el
  repositorio). Quitar la lectura devuelve todo a «reglamento no codificado», que es el comportamiento seguro.
- La migración se encadenó provisionalmente sobre 0139 (0140-0142 están en revisión): se reencadena al fusionar.

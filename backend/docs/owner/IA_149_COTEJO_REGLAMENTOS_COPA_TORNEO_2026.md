# IA-149 · Reglamentos del Torneo y de la Copa BetPlay DIMAYOR 2026, codificados en sombra, y su cotejo

Plan Maestro PM, tarea **PM-03-09** (OP-19). **Estado: hecha, pendiente del dueño** (cotejo humano, igual que DOC-008 / PM-09-02).

Qué hay: los reglamentos 2026 de las dos competiciones colombianas nuevas en el seguimiento — el **Torneo** (proveedor 240,
«Primera B», seguida desde el lote 3) y la **Copa** (proveedor 241, «Copa Colombia», seguida desde el lote 4, OPS-014) — leídos
del PDF oficial de la DIMAYOR y codificados con las mismas convenciones de `config/rules/` (IA-072), **en sombra**:

| Fichero | Reglamento | Huella SHA-256 del PDF | Estado |
| --- | --- | --- | --- |
| `config/rules/240_primera_b_colombia/v1.yaml` | Torneo 2026, «V0 - 21/01/26», 55 páginas | `abe959c6811bcc989b8ba97f09a3281864a50b8c19a864162c557b993c32d319` | `shadow` |
| `config/rules/241_copa_colombia/v1.yaml` | Copa 2026, «V1 - 25/08/26», 46 páginas | `ebfcac5d1de5f61a317304ac76a2fa78523b5ddce5a744ddcd740db2bf25b413` | `shadow` |

**Nada de esto llega a un lector.** `rules_for` sigue respondiendo «reglamento no codificado» a todo el que lo lee (escenarios,
perfiles, paquete de Intelligence), ahora con el motivo `pending_review` y lo que espera. Solo las herramientas de sombra, de solo
lectura, piden la versión en sombra: `python -m scripts.ia_rules show --league 241 --season 2026 --shadow` y
`python -m scripts.competition_tables show|check --league 240 --season 2026`. Las tablas siguen tras `FBI_COMPETITION_TABLES`
(**apagado**, BE-075). Ningún modelo de lenguaje toca nada de esto.

## 1. Qué cambia en el código (mínimo, aditivo)

- Esquema de reglas (`fbi.competitions.rules`): `state` admite `shadow`, que exige `pending` (qué espera); `sources[]` gana
  `edition` y `sha256` opcionales (la huella del archivo leído). Ningún otro fichero cambia ni su respuesta; un `Coded` de otra
  competición devuelve el mismo JSON que antes.
- `rules_for(..., include_shadow=False)`: con una versión en sombra y ninguna `coded`, responde `NotCoded` con motivo
  `pending_review`. Solo `include_shadow=True` (herramientas de sombra) la devuelve, marcada `"state": "shadow"`.
- `coverage.yaml`: 240 y 241 como `not_coded` / `pending_review`; se añaden 241 y 268 (Uruguay, lote 4; sin reglamento leído):
  140 competiciones seguidas el 20-nov-2026 21:09 UTC (84 ligas y 56 copas). El validador exige que un fichero en sombra figure
  como `pending_review` y al revés.
- `ia_rules load` **no registra** una versión en sombra en `core.competition_rules` (su `state` solo admite `coded` y `retired`; sin
  migración): se registra cuando el cotejo la convierte en `coded`. Así nada de la tabla de solo añadido se reescribe nunca.

**Paso a `coded` (solo con el acta firmada, §5):** un PR que cambie `state: shadow` → `coded` y quite `pending` en el fichero
cotejado, ponga la competición `coded` en `coverage.yaml` y, tras el despliegue, `python -m scripts.ia_rules load`. Si el cotejo
encuentra diferencias, se corrigen en el mismo fichero antes de ese paso (aún no está registrado en ninguna parte).

## 2. Los documentos que se cotejan

| | Torneo | Copa |
| --- | --- | --- |
| Enlace oficial | <https://dimayor.com.co/wp-content/uploads/2026/04/REGLAMENTO-TORNEO-2026-V0.pdf> | <https://dimayor.com.co/wp-content/uploads/2026/09/REGLAMENTO-COPA-2026-V1-1.pdf> |
| Edición (en el PDF) | «V0 - 21/01/26» | «V1 - 25/08/26» |
| **SHA-256** | **`abe959c6…d319`** (completa arriba) | **`ebfcac5d…b413`** |
| Tamaño | 12.997.908 bytes | 11.441.824 bytes |
| Metadatos | «REGLAMENTO-TORNEO 2026-V0», creado 16-abr-2026 22:49 UTC | «REGLAMENTO - COPA 2026 - V1», creado 25-ago-2026 20:45 UTC |
| Servidor | `Last-Modified: Fri, 17 Apr 2026 13:47:34 GMT` | `Last-Modified: Tue, 01 Sep 2026 14:05:48 GMT` |
| Descargado | 20-nov-2026 21:06 UTC | 20-nov-2026 21:06 UTC |

Edición anterior de la Copa, solo como referencia: «V5» de 17-mar-2026,
<https://dimayor.com.co/wp-content/uploads/2026/04/REGLAMENTO-COPA-2026-V5.pdf>, SHA-256
`c6828e35834ff02bd96ff43d5ce7bf4813101ddffee2eae01ecb44f2b56d8c28`. Comparadas por OCR las páginas 8 a 12 de las dos, **solo
cambian los arts. 16 y 17**: en V1 los octavos (Fase II) y los cuartos (Fase III) son a **partido único** y el empate va
directamente a penales; en V5 todas las llaves eran de ida y vuelta.

Comprueba la huella antes de empezar (si no coincide, la DIMAYOR cambió el archivo: para y avisa):

```
Get-FileHash .\REGLAMENTO-TORNEO-2026-V0.pdf -Algorithm SHA256     # Windows (PowerShell)
sha256sum REGLAMENTO-COPA-2026-V1-1.pdf                           # Linux o macOS
```

Texto: OCR Tesseract 5 en español a 200 ppp de las páginas citadas (20-nov-2026); los cuadros de la Copa (grupos, llaves de la
Fase 1B y cuadro de octavos) se leyeron sobre la imagen. Manda el PDF en pantalla.

## 3. Tabla de cotejo · Torneo 2026 (V0)

Marca **Coincide** o **No coincide** (con una nota) en cada fila.

| # | Pág. PDF | Artículo | Lo codificado en `240_primera_b_colombia/v1.yaml` | Pregunta | Casilla |
| ---: | ---: | --- | --- | --- | --- |
| T1 | 8 | 4 | `points` 3/1/0; nota: una fase por penales no da puntos ni goles | ¿3, 1 y 0, y los penales no suman? | ☐ |
| T2 | 8 | 5-6 | 16 clubes; dos torneos de 3 fases: 15 fechas, cuadrangulares (6), final (2) | ¿16 clubes y 3 fases por torneo? | ☐ |
| T3 | 9 | 7 | `fase_1`: todos contra todos, 15 fechas, una vuelta; torneo II = calendario del I con localías invertidas | ¿Una sola vuelta y localías invertidas en el II? | ☐ |
| T4 | 9 | 8 | zona `next_phase` puestos 1-8 → cuadrangulares | ¿Pasan los 8 primeros? | ☐ |
| T5 | 9 | 9 | desempate Fase I: DG, GF, GF visitante, menos GC, menos GC visitante, sorteo; parágrafo: último cupo, partido(s) | ¿Ese orden, y el parágrafo del último cupo? | ☐ |
| T6 | 10 | 10 | `cuadrangulares`: 2 grupos de 4, ida y vuelta (6 partidos); 1.º y 2.º cabezas de grupo; 3.º-8.º por sorteo; pasa el 1.º de cada grupo | ¿Grupos de 4, ida y vuelta, pasa solo el 1.º? | ☐ |
| T7 | 10 | 11 | desempate: el 1.º/2.º de la Fase I gana el empate con los demás (`seed_priority`); luego DG, GF, GF visitante, menos GC, menos GC visitante y mejor puesto en la Fase I | ¿El 1.º y 2.º ganan el empate, y luego esos 6 criterios? | ☐ |
| T8 | 11 | 12-13 | `final`: ida y vuelta; puntos, luego diferencia de gol, luego penales; visitante en la ida el de más puntos en Fases I-II | ¿Puntos → DG → penales, sin prórroga? | ☐ |
| T9 | 11-12 | 14-15 | `tabla_torneo_i`/`_ii`: suma de las 3 fases; desempate como el T5 sobre la suma | ¿Suma de las tres fases y ese desempate? | ☐ |
| T10 | 12 | 16 | `reclasificacion`: suma de todos los partidos de las 3 fases de I y II; **no** cuentan Gran Final ni Repechaje | ¿Excluye Gran Final y Repechaje? | ☐ |
| T11 | 12 | 17 | desempate de la reclasificación: DG, GF, GF visitante, menos GC, menos GC visitante, sorteo (todas las fases de I y II) | ¿Ese orden? | ☐ |
| T12 | 15 | 19-20 | hueco `promotion`: el mismo campeón en I y II asciende; el 2.º cupo, Repechaje entre los dos mejores de la reclasificación | ¿Así lo dice el art. 20? | ☐ |
| T13 | 15 | 21 | hueco `promotion`: campeones distintos — A) los dos 1.º-2.º de la reclasificación suben; B) uno 1.º-2.º sube y el otro juega Repechaje con el mejor ubicado; C) ninguno, Gran Final | ¿Los tres escenarios, excluyentes? | ☐ |
| T14 | 15-16 | 22-23 | Gran Final: ida y vuelta, el ganador sube y el perdedor va al Repechaje; puntos → DG → penales | ¿Ese sistema? | ☐ |
| T15 | 16-17 | 24-25 | Repechaje: ida y vuelta contra el mejor de la reclasificación; puntos → DG → penales; visitante en la ida el mejor ubicado | ¿Ese sistema? | ☐ |

## 4. Tabla de cotejo · Copa 2026 (V1)

| # | Pág. PDF | Artículo | Lo codificado en `241_copa_colombia/v1.yaml` | Pregunta | Casilla |
| ---: | ---: | --- | --- | --- | --- |
| C1 | 8 | 4-5 | `points` 3/1/0; penales sin puntos ni goles; 36 clubes | ¿3/1/0 y 36 clubes? | ☐ |
| C2 | 8 | 6 | seis fases: 1A, 1B, II octavos, III cuartos, IV semifinales, V final | ¿Esas seis? | ☐ |
| C3 | 8-9 | 7-8 | `fase_1a`: 20 clubes (12 de la Liga fuera de cuartos de la Liga I y 8 del Torneo fuera de cuadrangulares del Torneo I), 4 grupos de 5 por los puestos de la Fase I, 5 fechas (cada club descansa una), 2 en casa y 2 fuera, sin ida y vuelta | ¿Grupos de 5 con una sola vuelta? | ☐ |
| C4 | 9 | 9 | desempate de grupo: DG, GF, GF visitante, menos GC, menos GC visitante, sorteo; parágrafo: último cupo, partido(s) | ¿Ese orden? | ☐ |
| C5 | 10 | 10 | zona `next_phase` puestos 1-2 de cada grupo → octavos | ¿Pasan los dos primeros? | ☐ |
| C6 | 10 | 11-12 | `fase_1b`: 8 de cuartos de la Liga I contra 8 de cuadrangulares del Torneo I, ida y vuelta, el del Torneo cierra en casa; llaves L8-T1, L6-T3, L4-T5, L2-T7, L1-T8, L3-T6, L5-T4, L7-T2 | ¿Esas 8 llaves y ese orden de localía? | ☐ |
| C7 | 10 | 13-14 | `fase_1b`: puntos → DG → penales; pasa el ganador de cada llave | ¿Sin prórroga? | ☐ |
| C8 | 11 | 15-16 | **`octavos` y `cuartos`: partido único**; misma división, local el mejor de su reclasificación al cierre del primer semestre; distinta, el del Torneo; cuadro de octavos (1B-A v D2, B v B2, C v D1, D v B1, E v A1, F v C1, G v A2, H v C2) | ¿Partido único en II y III, y ese cuadro? | ☐ |
| C9 | 11 | 16 | `semifinales` y `final`: ida y vuelta; misma división, cierra en casa el mejor de su reclasificación; distinta, el del Torneo | ¿Ida y vuelta en IV y V? | ☐ |
| C10 | 12 | 17 | II y III: empate → penales directamente (sin prórroga). IV y V: puntos → DG → penales | ¿Sin prórroga en ninguna fase? | ☐ |
| C11 | 12 | 18 | hueco `continental`: el campeón es Colombia 1 de la Sudamericana 2027 solo si juega la Liga 2027; si no, premio y el cupo va al mejor de la reclasificación de la Liga sin cupo | ¿Así lo dice? | ☐ |

## 5. Acta de cotejo (la rellena y la firma la persona que coteja)

```
Acta de cotejo · Reglamentos Torneo BetPlay DIMAYOR 2026 V0 (arts. 4-25) y Copa BetPlay DIMAYOR 2026 V1 (arts. 4-18)
(PM-03-09, IA-149)
Huellas comprobadas:  Torneo abe959c6…d319  ☐    Copa ebfcac5d…b413  ☐
Filas T1-T15:  coinciden ___ / no coinciden ___ (números: ________)
Filas C1-C11:  coinciden ___ / no coinciden ___ (números: ________)
Notas: _____________________________________________________________
Fecha: ____-__-__        Persona: ______________________     Firma: ____________
```

Con el acta firmada, el coordinador la anota en el anexo I y en el estado; el paso a `coded` es el PR del §1.

## 6. Revisión de la liquidación de la Copa (cambio de agosto)

Leído en producción, solo lectura, el 20-nov-2026 21:09 UTC (72 partidos de la Copa 2026; la final aún no está en el calendario
del proveedor):

- **Etiquetas del proveedor:** «Group Stage - 1…5» (40 partidos, Fase 1A), «Play-offs» (16, Fase 1B), «Round of 16» (8),
  «Quarter-finals» (4), «Semi-finals» (4). Cada una cae en una sola fase del fichero.
- **Octavos y cuartos** (2-sep a 2-nov-2026, todos después del 25-ago): **un partido por llave** en las 12, como dice V1. Tres
  octavos terminaron empatados y se definieron por penales (estado `PEN` con el marcador de los 90 minutos: Quindío-Llaneros 1-1,
  Barranquilla-Millonarios 1-1, Santa Fe-Fortaleza 2-2). No hubo prórroga, como dice el art. 17.
- **Liquidación de apuestas:** se liquida a los 90 minutos (`fbi.picks.settlement`, base `regulation_90`): un partido único
  empatado es empate para el 1X2 aunque un club pase por penales; sin prórroga en esta competición, el marcador guardado es el de
  los 90 minutos. **No hace falta ningún cambio**; queda escrito en las notas del fichero.
- **Quién pasó** (`fbi.competitions.ties` lo deduce de los propios partidos, no del reglamento): las 22 llaves jugadas, con las
  reglas codificadas (puntos → DG → penales en las de ida y vuelta; penales en las de partido único), dan el mismo ganador que la
  ronda siguiente en las 20 que ya tienen ronda siguiente (las 2 semifinales: América de Cali y Once Caldas, final sin calendario).
  En dos partidos, «puntos y luego DG» da siempre el mismo ganador que el global de goles; la diferencia solo aparece en penales.
- **Fase 1A:** los dos primeros de cada uno de los 4 grupos, calculados con el desempate del art. 9, son exactamente los 8 que
  jugaron octavos procedentes de la 1A.

## 7. Temporada 2026 reproducida con el fichero del Torneo

Con los mismos datos (solo lectura, 20-nov-2026 21:11 UTC) y `fbi.competitions.season_tables` sobre `240_primera_b_colombia/v1.yaml`:

- Fase I del Torneo I y del Torneo II = tablas «Apertura» y «Clausura» del proveedor: 16/16 clubes iguales en puntos, partidos y
  goles, y en el mismo orden.
- Reclasificación = «Tabla Anual» del proveedor: 16/16 iguales y mismo orden (aún incompleta: falta la final del Torneo II).
- Cuadrangulares de los dos torneos (4 grupos): mismos puntos y mismo orden que el proveedor, aplicando el art. 11 (el 1.º y 2.º de la
  Fase I ganan el empate; en el Torneo II, Real Cundinamarca queda 3.º por delante de Tigres con 5 puntos cada uno).
- Campeón del Torneo I: **Envigado** (2-3 y 1-1 ante Real Cartagena; 4 puntos a 1). Torneo II: final Quindío-Popayán aún sin
  calendario. Cómo se reparte el ascenso (arts. 19-25) no se calcula: es el hueco `promotion`.

Las salidas y los guiones de lectura quedan con el informe de ejecución (`ejecucion/PM-03-09.md`, carpeta `evidencia_ia149/`).

## 8. Qué no hace

No publica ninguna tabla ni regla, no cambia ningún pick, probabilidad, escenario ni pantalla, no registra nada en la base y no
toca el fichero de la Liga (`239_primera_a_colombia/v2.yaml`, cuyo hueco `continental` sigue deteniendo el reparto de la
Sudamericana). Uruguay (268) queda «no codificado» (fuera del alcance de esta tarea).

**Vuelta atrás:** revertir el PR. Al no estar registradas en `core.competition_rules`, no queda nada en la base.

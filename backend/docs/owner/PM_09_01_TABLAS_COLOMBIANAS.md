# PM-09-01 · Tablas colombianas calculadas desde el reglamento (BE-075) — en sombra, pendiente del dueño

Plan Maestro PM, bloque 9 (OP-20). Código BE-075. 20-nov-2026.

## 1. Qué hace

`fbi.competitions.season_tables` calcula, solo con los resultados y el fichero de reglas, las tablas que deciden el año en la
Liga BetPlay y que el proveedor no da completas:

| Tabla | Artículos | De dónde sale cada dato (todo en `config/rules/239_primera_a_colombia/`) |
| --- | --- | --- |
| Tabla de la Liga I y de la Liga II | 16-17, 25-26 | `tables.tabla_liga_i`, `tabla_liga_ii`: todas las fases de cada torneo |
| Reclasificación 2026 | 27-28 | `tables.reclasificacion`: todas las fases de los dos torneos y su desempate |
| Cupos de Libertadores y Sudamericana 2027 | 30-31 | `reclasificacion.places`: el orden de los cupos (campeón Liga I, campeón Liga II, mejores sin cupo...) |
| Tabla de descenso (promedio) | 32-34 | `tables.descenso`: Fase I de 2024-I a 2026-II (`past`), ventanas de Jaguares, Cúcuta y Llaneros (`windows`), desempate solo con 2026 (`ties_on`), los dos últimos descienden (art. 34) |

Nada está fijo en el código: otra temporada (2027) es otro fichero `v<N>.yaml` con su reglamento leído.

**Resultados cambiados fuera del campo.** El proveedor guarda el marcador jugado aunque la DIMAYOR lo cambie, y no guarda marcador
de un partido adjudicado. Esos cambios van en `decisions/<temporada>.yaml`, uno por partido, con la evidencia y `verified: false`
hasta que el dueño lea la resolución. Hoy son cuatro, todos vistos en la tabla del propio proveedor y en la tabla publicada:

| Temporada | Partido | Marcador guardado | Lo que cuentan las tablas |
| --- | --- | --- | --- |
| 2024 | Atl. Nacional – Junior (Clausura 10) | 2-0 | 0-3 |
| 2025 | Unión Magdalena – Once Caldas (Apertura 17) | ninguno (AWD) | 0-3 |
| 2025 | Atl. Nacional – Bucaramanga (Clausura 11) | ninguno (AWD) | 0-3 |
| 2026 | Inter de Bogotá – América (Clausura 1) | 0-2 | 3-0 |

## 2. Qué se comprobó (datos de producción leídos el 20-nov-2026 a las 14:22 UTC, solo lectura)

* **Fase I de la Liga I y de la Liga II 2026**: iguales a las tablas del proveedor en partidos, puntos, goles y orden (20 de 20).
  Sin la decisión de la Clausura 1 la Liga II difiere en dos clubes (Inter y América, 3 puntos cada uno).
* **Reclasificación 2026**: igual a la «Tabla Anual» del proveedor en cifras y orden (Atl. Nacional 95 puntos en 44 partidos).
  Aún no está completa: faltan los cuadrangulares y la final de la Liga II.
* **Tabla de descenso**: completa desde el 14-nov (última fecha de la Fase I de la Liga II). Puntos y partidos de los 20 clubes
  iguales a la tabla publicada ese día por Win Sports (<https://www.winsports.co/futbol-colombiano/liga-dimayor/descenso>).
  **Descienden Boyacá Chicó (106/116 = 0,914) y Jaguares (31/38 = 0,816)**, estado `definitivo`.
* Temporadas anteriores (Fase I 2024 y Clausura 2025): con las decisiones aplicadas, puntos y partidos iguales a las tablas del
  proveedor; quedan cuatro filas de 2024 que difieren en un gol (no en puntos): el proveedor no concuerda con sus propios marcadores.
* **Campeón de la Liga I 2026: Junior** (3-0 y 0-1: tres puntos cada uno; 3-1 en el global). El de la Liga II aún no se conoce.

Pruebas: `tests/unit/test_season_tables_be075.py` (23) sobre `tests/fixtures/competitions/239_primera_a_2024_2026.json`,
la copia de esos datos.

## 3. Dos hallazgos para el cotejo (DOC-008)

1. **Empate Deportivo Cali – Águilas Doradas** (145/116 = 1,250 los dos). El art. 33 lo rompe con los puntos de la Fase I de 2026:
   Cali 62, Águilas 51, así que Cali va por encima. La tabla publicada pone a Águilas por encima. No cambia ningún descenso.
2. **Decimales.** La tabla publicada muestra tres decimales **cortados**, no redondeados (204/116 = 1,7586 aparece 1,758). El
   cálculo ordena por el cociente exacto y mide si redondear o cortar a 2 o 3 decimales cambiaría alguna zona: hoy no cambia
   ninguna (`redondeo`: «igual» en los cuatro casos). La fila 12 del acta decide qué cifra se enseña.

## 4. Cómo se mira (en el servidor, solo lectura)

```
docker exec predigol-worker python -m scripts.competition_tables check --league 239 --season 2026
docker exec predigol-worker python -m scripts.competition_tables show --league 239 --season 2026 \
    --cup-winner "Copa BetPlay DIMAYOR 2026=<id del proveedor del campeón>"
```

`check` compara cada tabla calculada con la del proveedor de los mismos clubes y sale con 1 si alguna difiere. `show` imprime todas
las tablas, zonas y cupos con su estado: `definitivo`, `provisional`, `condicional`, `empate_abierto`; los cupos `calculado`,
`provisional`, `pendiente` (un campeón por decidir) o `no_calculado` (un caso de un parágrafo sin codificar). Ninguno escribe nada.

## 5. Lo que queda (pendiente del dueño)

1. Firmar el acta del cotejo (`DOC_008_COTEJO_REGLAMENTO_DIMAYOR_2026.md`, §5) con las dos preguntas del §3 de esta guía.
2. Confirmar las cuatro decisiones con la resolución de la DIMAYOR (o decir cuál no) y cambiar `verified` a `true` por PR.
3. DM-14: firmar la publicación. Solo entonces se crea la ruta que la lee (PM-09-04) y se enciende `FBI_COMPETITION_TABLES` con
   kit auditado (PM-15-03). Hasta entonces el interruptor está apagado y ninguna tabla llega a un lector.
4. Opcional: registrar la versión 2 en `core.competition_rules` con `python -m scripts.ia_rules load` (único paso que escribe, en
   la tabla de solo añadir); el cálculo no lo necesita.

Los parágrafos de los arts. 30-31 y el art. 18 de la Copa no están codificados: los cupos se enseñarían como condicionales.

## 6. Reversión

Nada que apagar (el interruptor ya lo está). Si hiciera falta, PR de `revert`: `v1.yaml` vuelve a `coded` y `v2.yaml` desaparece;
ninguna fila ni tabla de la base cambia.

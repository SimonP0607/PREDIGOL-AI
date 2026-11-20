# IA-150 · Cuánto tarda una baja en llegar a PrediGol por cada vía

Plan Maestro PM, tarea **PM-06-03**. **Estado: hecha con las vías ya en uso; lo que exige una firma del dueño queda pendiente
(§5).** Es la base de la decisión **DM-07** (X de pago en sombra).

Una **baja** es un jugador que no jugó un partido por una razón deportiva que dijo el proveedor o la prensa: el parte de bajas del
proveedor lo listó como `Missing Fixture`, o un hecho de prensa dijo que no estaba (lesión o sanción). Para cada una se mide el
**primer momento en que cada vía la trajo a PrediGol**, en horas antes del saque. Solo se usan vías que PrediGol **ya lee**: no se
pidió nada a ningún sitio nuevo ni sin firmar, ni a X. El tipo se reduce a `lesion`, `sancion` u `otro`; ningún nombre, motivo ni
texto sale del informe (los motivos del proveedor son datos de salud: Ley 1581, consulta DM-08).

## 1. Cómo se repite

```
docker exec predigol-worker python -m scripts.ia_absence_timing --days 30            # tabla
docker exec predigol-worker python -m scripts.ia_absence_timing --since 2026-10-25 --until 2026-11-21 --json --sample 20
```

Solo lectura (conexión de solo lectura, 90 s por consulta), 0 peticiones al proveedor. Módulo `fbi.ingestion.absence_timing`
(versión `absence-timing-v1`); no hay interruptor porque nada lo ejecuta solo ni lo lee ningún lector.

## 2. Las vías

| Vía | De dónde | Momento que cuenta |
| --- | --- | --- |
| proveedor · parte de bajas | `/injuries` → `core.player_availability_obs` (historia desde el 22-oct-2026) | primera fila `LISTED`, cuándo la pedimos |
| proveedor · periodos de baja | `/sidelined` → `core.person_sidelined` | primera fila cuyo periodo cubre el día del partido |
| prensa · liga, federación o club | hechos de `ai.evidence` (origen web) de fuentes de nivel oficial, competición o club | cuándo la investigación lo recuperó |
| prensa · medios | los mismos hechos de cualquier otro medio | ídem |
| alineación oficial | `core.fixture_lineup_arrivals` (desde el 17-nov-2026) | primera alineación de su equipo: confirma la baja por omisión |

La **resolución** es nuestra cadencia de lectura, no la publicación de la fuente (que ninguna fuente permitida fecha): el parte se
pide por competición cada 9 a 28 horas (mediana por competición) y la investigación corre a horas fijas (sobre todo a las 05:05 UTC).

## 3. Resultado · partidos jugados con saque del 25-oct al 20-nov-2026 (medido el 20-nov-2026 21:33 UTC)

2.881 bajas (lesión 2.257, otro 437, sanción 187); el parte del proveedor cubre **17 competiciones**: solo 24 se pidieron a
`/injuries` en el periodo y 7 de ellas una sola vez (entre ellas Primera B 240, Uruguay 268 y Venezuela 299). **La Liga
colombiana (239) no tiene parte del proveedor** en este periodo.

| Vía | Bajas | Antes del saque | Después | Mediana h antes | p10 | p90 | IC 95 % de la mediana |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| proveedor · parte de bajas | 2.784 | 2.262 | 522 | **56,9** | 21,4 | 65,7 | 56,7 – 57,9 |
| proveedor · periodos de baja | 608 | 339 | 269 | 630,1 | 416,6 | 778,9 | 601,4 – 634,1 |
| prensa · liga, federación o club | 11 | 11 | 0 | 11,4 | 5,8 | 14,7 | 5,8 – 12,7 (muestra pequeña) |
| prensa · medios | 115 | 115 | 0 | 11,9 | 5,8 | 17,4 | 10,2 – 12,7 |
| alineación oficial | 77 | 77 | 0 | 0,5 | 0,4 | 0,5 | 0,5 – 0,5 |

Frente al parte del proveedor (solo las bajas que trajeron las dos vías antes del saque):

| Vía | Pares | Adelanto mediano (h; + = antes que el parte) | IC 95 % | Antes que el parte | IC 95 % (Wilson) | Solo esta vía |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| proveedor · periodos de baja | 270 | +562,1 | 518,9 – 590,9 | 270 de 270 | 98,6 – 100 % | 69 |
| prensa · liga, federación o club | 2 | +6,0 | −8,5 – 20,4 | 1 de 2 | 9,5 – 90,5 % | 9 |
| prensa · medios | 5 | −43,7 | −44,0 – −32,5 | 0 de 5 | 0 – 43,4 % | 110 |
| alineación oficial | 41 | −16,1 | −17,9 – −16,1 | 0 de 41 | 0 – 8,6 % | 36 |

Lectura:

1. **El parte del proveedor es la vía principal**: trae la baja una mediana de 57 h antes del saque, en las 17 competiciones que
   lo tienen. Un 19 % de sus bajas aparece después del saque (listados tardíos o de partidos ya jugados).
2. **Los periodos de baja** (`/sidelined`) llegan semanas antes, pero solo para las bajas largas y no dicen el partido: confirman
   lesiones de duración, no adelantan un parte de jornada.
3. **La prensa no adelanta al parte donde hay parte**: en las 5 bajas que trajeron los dos, la prensa llegó unas 44 h después
   (muestra pequeña). Su valor está donde **no hay parte**: 110 bajas solo por prensa de medios y 9 solo por fuentes oficiales,
   unas 12 h antes del saque, al ritmo de la investigación diaria: en competiciones sin `/injuries` (Nations League 24, Segunda
   española 17, Escocia 5, amistosos 5…) y en bajas que el parte no listó en ligas que sí lo tienen (Brasil 9, Italia 9, España 8).
4. **La alineación** solo confirma, media hora antes del saque.
5. **Para DM-07 (X):** no hay ninguna medida de que una vía más rápida cambie algo donde ya hay parte del proveedor; donde no hay
   parte, la prensa ya trae la baja medio día antes. No hay base medida para pagar X ahora; se mantiene la recomendación A del
   anexo I («no, hasta medir»), ahora con este dato. La decisión es del dueño.

## 4. Pruebas

* `tests/unit/test_absence_timing_ia150.py`: cifras por vía, pares frente al parte, intervalos reproducibles (semilla fija),
  tipo reducido a tres palabras, la consulta no selecciona motivo, nombre ni texto, y la tabla.
* **30 bajas cotejadas una a una** contra las filas guardadas (lectura independiente de `player_availability_obs`,
  `person_sidelined`, `ai.evidence`, `fixture_lineup_arrivals` y equipos; 20-nov-2026 21:34-21:35 UTC): las 20 de la muestra de
  semilla 150 y 10 más elegidas entre las que trajo la prensa (6) o la alineación (4). **30 de 30 coinciden** en las cinco vías.
  Guiones y salidas con el informe de ejecución (`ejecucion/PM-06-03.md`, `evidencia_ia150/`).

## 5. Lo que queda pendiente de la firma del dueño (no medido)

* **Sitios oficiales nuevos** (DIMAYOR, FCF, clubes): los niveles propuestos en IA-147 esperan la firma en bloque **DM-05** y, para
  los tres firmables, la consulta **DM-08** («fuentes sin términos: ¿basta título y enlace?»). Con ellos firmados, la vía
  «prensa · liga, federación o club» tendría muestra (hoy 11 bajas) y podría medirse frente al parte en Colombia.
* **X**: decisión **DM-07**, que se toma con este informe; PM-06-04 solo si el dueño lo aprueba.
* **Noticias de `news.items`**: hoy 278 noticias de 2 dominios autorizados y ninguna enlazada a un jugador; no es una vía de bajas
  todavía.
* **Colombia sin parte del proveedor**: la Liga (239) no recibió `/injuries` en el periodo; si el proveedor lo cubre o no es una
  pregunta para la próxima sonda de cobertura (PM-01-04/PM-02-03), no de esta tarea.

## 6. Qué no hace

No pide nada a ningún sitio ni al proveedor, no escribe en la base, no cambia el parte, el Match Center, el paquete de
Intelligence ni ninguna probabilidad. Ningún modelo de lenguaje interviene (los hechos de prensa se leen solo por su hora y su nivel
de fuente). Vuelta atrás: revertir el PR.

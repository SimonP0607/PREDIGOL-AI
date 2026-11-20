# IA-150 · Cuánto tarda una baja en llegar a PrediGol por cada vía

Plan Maestro PM, tarea **PM-06-03**. **Estado: hecha con las vías ya en uso; lo que exige una firma del dueño queda pendiente
(§5).** Es la base de la decisión **DM-07** (X de pago en sombra).

Una **baja** es un jugador que el parte de bajas del proveedor listó como `Missing Fixture` para un partido (lesión, sanción u
otro motivo, como dato deportivo). Para cada una se mide el
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
| alineación oficial | `core.fixture_lineup_arrivals` (desde el 17-nov-2026) | primera alineación de su equipo: confirma la baja por omisión |

La **resolución** es nuestra cadencia de lectura, no la publicación de la fuente (que ninguna fuente permitida fecha): el parte se
pide por competición cada 9 a 28 horas (mediana por competición).

**La prensa no está en el informe repetible.** Los hechos de prensa que guarda la investigación (`ai.evidence`) solo se leen a
través del guardián de evidencias tipadas de Intelligence (`tests/unit/test_typed_evidence_guard.py` y su guía): un lector nuevo es
cosa de esa sesión. Se midieron **una vez**, en solo lectura, para esta guía (§3.2); el lector propio queda propuesto a Intelligence.

## 3. Resultado · partidos jugados con saque del 25-oct al 20-nov-2026 (medido el 20-nov-2026 21:33 UTC)

### 3.1 Lo que repite el informe

2.784 bajas del parte (lesión 2.166, otro 437, sanción 181) en **17 competiciones**: solo 24 se pidieron a `/injuries` en el
periodo y 7 de ellas una sola vez (entre ellas Primera B 240, Uruguay 268 y Venezuela 299). **La Liga colombiana (239) no tiene
parte del proveedor** en este periodo.

| Vía | Bajas | Antes del saque | Después | Mediana h antes | p10 | p90 | IC 95 % de la mediana |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| proveedor · parte de bajas | 2.784 | 2.262 | 522 | **56,9** | 21,4 | 65,7 | 56,7 – 57,9 |
| proveedor · periodos de baja | 590 | 322 | 268 | 621,7 | 413,2 | 751,2 | 585,8 – 632,3 |
| alineación oficial | 77 | 77 | 0 | 0,5 | 0,4 | 0,5 | 0,5 – 0,5 |

Frente al parte (solo las bajas que trajeron las dos vías antes del saque): periodos de baja **+562,1 h** (IC 518,9 – 590,9; 270 de
270 antes, Wilson 98,6 – 100 %); alineación **−16,1 h** (IC −17,9 – −16,1; 0 de 41).

### 3.2 Prensa ya leída por la investigación (medida una vez, solo lectura; no está en el informe repetible)

Misma ventana, hechos de `ai.evidence` (origen web, lesión o sanción, `CONFIRMED`/`PROBABLE`, afirmación «no juega», con partido y
jugador; solo su hora de recuperación y el nivel de la fuente). Universo con las bajas que trajo solo la prensa: 2.881.

| Vía | Bajas | Mediana h antes del saque | Frente al parte (pares) | Solo esta vía |
| --- | ---: | ---: | --- | ---: |
| prensa · liga, federación o club | 11 | 11,4 (IC 5,8 – 12,7; muestra pequeña) | +6,0 h (2 pares; IC −8,5 – 20,4) | 9 |
| prensa · medios | 115 | 11,9 (IC 10,2 – 12,7) | −43,7 h (5 pares; 0 de 5 antes) | 110 |

La investigación corre a horas fijas (sobre todo 05:05 UTC): esa es su resolución.

### 3.3 Lectura

1. **El parte del proveedor es la vía principal**: trae la baja una mediana de 57 h antes del saque, en las 17 competiciones que
   lo tienen. Un 19 % de sus bajas aparece después del saque (listados tardíos o de partidos ya jugados).
2. **Los periodos de baja** (`/sidelined`) llegan semanas antes, pero solo para las bajas largas y no dicen el partido: confirman
   lesiones de duración, no adelantan un parte de jornada.
3. **La prensa no adelanta al parte donde hay parte** (5 pares, unas 44 h después; muestra pequeña). Su valor está donde **no hay
   parte**: 110 bajas solo por medios y 9 solo por fuentes oficiales, unas 12 h antes del saque: en competiciones sin `/injuries`
   (Nations League 24, Segunda española 17, Escocia 5, amistosos 5…) y en bajas que el parte no listó en ligas que sí lo tienen
   (Brasil 9, Italia 9, España 8).
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
* **Lector propio de la prensa** (`ai.evidence`) en el informe repetible: propuesta para la sesión de Intelligence (§2).
* **Noticias de `news.items`**: hoy 278 noticias de 2 dominios autorizados y ninguna enlazada a un jugador; no es una vía de bajas
  todavía.
* **Colombia sin parte del proveedor**: la Liga (239) no recibió `/injuries` en el periodo; si el proveedor lo cubre o no es una
  pregunta para la próxima sonda de cobertura (PM-01-04/PM-02-03), no de esta tarea.

## 6. Qué no hace

No pide nada a ningún sitio ni al proveedor, no escribe en la base, no cambia el parte, el Match Center, el paquete de
Intelligence ni ninguna probabilidad. Ningún modelo de lenguaje interviene, y el informe no lee `ai.evidence`. Vuelta atrás: revertir el PR.

# IA-151 · Historial de bajas en «Bajas del partido» e Intelligence, sin detalle médico: diseño y consulta DM-08

Plan Maestro PM, tarea **PM-05-06** (OP-12). **Estado: pendiente del dueño — consulta al abogado DM-08** («Ley 1581: fichas de
árbitros y datos de bajas»), que no consta hecha. **Este documento no construye nada**: ningún código, contrato, tabla, pantalla ni
interruptor procesa ni muestra datos de salud por esta tarea. Es el diseño de lo que se construiría si el abogado lo permite y las
preguntas exactas que hay que hacerle. Nada aquí es asesoría legal.

## 1. Qué pide la tarea y por qué espera

La ficha: llevar el historial de bajas del proveedor (`/sidelined`, unas 13.945 respuestas guardadas que hoy solo se ven en la
página del jugador) al bloque «Bajas» del partido y al paquete de Intelligence, como hecho «reaparece tras N días» y recuento de
ausencias, con el tipo reducido a lesión o sanción. Criterio de aceptación: «el bloque de bajas muestra la duración de la ausencia
con fuente, sin diagnóstico». Dependencia: **DM-08**. Mientras no haya respuesta escrita del abogado, la tarea no pasa de este
documento.

## 2. Lo que ya existe hoy (leído en el código de `main`, 20-nov-2026) — para que el abogado lo vea entero

Esto **no lo cambia esta tarea** (son zonas de UX e Intelligence y no hay autorización); se cuenta porque las preguntas del §5 lo
cubren y la respuesta puede pedir corregirlo:

| Dónde | Qué dato | Quién lo ve |
| --- | --- | --- |
| Bloque «Bajas» del partido (contrato `Absence` de `center.py`; web `ContextBlocks.tsx`) | el **motivo literal del proveedor** (`reason`, p. ej. «Knee Injury») cruza la API; la web lo clasifica en Lesión / Sanción / Enfermedad / Otro motivo | lectores del Match Center |
| Página del jugador (`GET /players/{id}`: `absences[].reason`, `sidelined[].type`, fechas de inicio y fin) | motivo y tipo literales del proveedor, y los periodos de baja | lectores (ya anotado en `COORDINACION_SESIONES_2026.md`, nota de C-09) |
| Perfiles C-09 (`fbi.people.availability`, IA-091) | solo cuatro estados: `disponible`, `duda`, `baja`, `sancionado`, con fuente y fecha; el motivo se lee para distinguir sanción de lesión y se descarta | lectores con `FBI_PROFILES` |
| Paquete de Intelligence (`fbi/ai/packet.py`, bajas del partido) | nombre, tipo y **motivo literal** de cada baja | **los modelos de lenguaje** del ciclo de IA (proveedor en el extranjero) |
| Recolector de evidencias (`fbi/ai/collectors.py` → `ai.evidence`) | texto «Jugador (equipo): Missing Fixture - Knee Injury» y el motivo en `attributes` | se guarda; lo leen la IA y la consola privada |

Medida de PM-06-03 (IA-150, 20-nov-2026): en 30 días, 2.881 bajas; motivos del proveedor del tipo «Knee Injury», «Hamstring
Injury», «Illness», «Concussion», «Operation» (diagnóstico o parte del cuerpo) junto a «Red Card», «Yellow Cards» (sanción) y
«Inactive», «Coach's decision» (ni salud ni sanción).

## 3. Diseño propuesto (solo si DM-08 lo permite)

### 3.1 Qué se mostraría por cada baja del partido

| Campo | Valores | Fuente | Ejemplo |
| --- | --- | --- | --- |
| `estado` | `baja` · `sancionado` · `duda` | parte del proveedor o prensa con su nivel (precedencia de IA-091) | «Baja» |
| `tipo` | `no_disponible_por_lesion` · `no_disponible_por_sancion` · `no_disponible_otro` | reducido en el servidor; el motivo literal no sale | «No disponible por lesión» |
| `fuera_desde` | fecha (día) o vacío | inicio del periodo de `/sidelined` que cubre el partido, o primera ausencia en nuestros partidos | «desde el 3-nov» |
| `dias_fuera` | entero o vacío | días entre `fuera_desde` y el saque | «17 días» |
| `partidos_sin_jugar` | entero o vacío | partidos oficiales seguidos de su equipo sin él, en nuestra base | «4 partidos» |
| `ausencias_temporada` | entero | partidos de la temporada en que figuró como baja | «6 en la temporada» |
| `fuente` y `conocido_desde` | nombre de la vía y fecha y hora | como hoy | «Parte del proveedor, 18-nov 09:12» |

Y, después de que vuelva a jugar, un hecho histórico: **«reapareció tras N días»** (N = días entre el inicio del periodo y su
primer partido jugado), solo como dato deportivo de la temporada.

### 3.2 Qué NO se mostraría ni procesaría nunca

Diagnóstico, parte del cuerpo, enfermedad, operación, conmoción, texto médico, «fecha prevista de regreso» o pronóstico del
proveedor (`end_date` futura de `/sidelined`), y cualquier texto libre de la prensa sobre su estado. El contrato no tendría ningún
campo de texto libre para la baja (solo los valores cerrados de la tabla), y una prueba comprobaría que ningún motivo del
proveedor ni texto de prensa sale del contrato.

### 3.3 Variante mínima (si el abogado considera que «por lesión» ya es dato de salud)

Un solo `tipo`: **`no_disponible`** (sin distinguir lesión de otros motivos no disciplinarios), conservando `sancionado` porque una
sanción es un dato disciplinario público de la competición. Duración y recuentos igual.

### 3.4 Dónde iría (para cuando haya respuesta)

* Contrato: C-09 (perfiles) y el bloque de bajas del partido, **versión menor**, campos opcionales nuevos con valores cerrados
  (contrato primero, consumidor después: C-16 y `COORDINACION_SESIONES_2026.md`).
* Cálculo: `fbi/people/availability.py` (IA-091) — zona de Intelligence, con reserva escrita antes del PR.
* Paquete de Intelligence: los mismos campos reducidos, nunca el motivo literal; ningún modelo de lenguaje toca probabilidades.
* Todo nace en sombra y apagado tras un interruptor `FBI_*` propio (por crear, apagado) y se enciende solo con firma del dueño.

## 4. Fuentes y su autorización

Solo el proveedor ya contratado (`/injuries`, `/sidelined`, 0 peticiones nuevas: los datos ya están guardados) y la prensa ya leída
(hechos de `ai.evidence`, por su nivel). Ningún sitio nuevo: los sitios oficiales esperan DM-05 (IA-147).

## 5. Preguntas exactas para el abogado (DM-08, asunto «Ley 1581: datos de bajas»)

1. **Naturaleza del dato.** Que un futbolista profesional «no está disponible por lesión» para un partido, tal como lo publican la
   liga, el club o un proveedor de datos deportivos, ¿es un **dato sensible relativo a la salud** (Ley 1581 de 2012, art. 5) para
   PrediGol? ¿Y la sanción disciplinaria («no disponible por sanción»)?
2. **Autorización.** Si lo es, ¿qué base permite tratarlo sin la autorización expresa del titular (art. 6: dato hecho público por el
   titular, finalidad histórica o estadística, otra)? ¿Cambia algo que PrediGol cobre una membresía y no sea prensa?
3. **Grado de detalle.** ¿Es aceptable mostrar a los lectores el diseño del §3.1 (estado, «por lesión»/«por sanción», desde cuándo,
   días y partidos fuera, ausencias de la temporada, «reapareció tras N días»), o solo la variante mínima del §3.3, o nada?
4. **Duración como dato de salud.** Los días y los partidos que lleva fuera, y «reapareció tras N días», ¿revelan por sí mismos un
   dato de salud (gravedad de la lesión), aunque no se diga cuál?
5. **Lo que ya se muestra (§2).** El motivo literal del proveedor («Knee Injury») en el bloque «Bajas» del partido y en la página del
   jugador, y los periodos de baja con sus fechas, ¿pueden seguir mostrándose? Si no, ¿basta clasificarlos en el servidor?
6. **Modelos de lenguaje en el extranjero.** Hoy el paquete de IA envía a un proveedor de modelos (fuera de Colombia) el nombre y el
   motivo literal de cada baja, y `ai.evidence` lo guarda. ¿Es una transferencia internacional (Ley 1581, art. 26) o una transmisión a un
   encargado (Decreto 1377 de 2013, compilado en el Decreto 1074 de 2015) de datos sensibles que exija contrato, aviso o autorización? ¿Bastaría enviar solo
   el estado reducido?
7. **Conservación.** ¿Cuánto tiempo puede conservarse el historial (13.945 respuestas de `/sidelined` y la historia de `/injuries`)?
   ¿Debe borrarse o anonimizarse el motivo literal pasado un plazo?
8. **Términos del proveedor.** ¿Permiten los términos de API-Football mostrar estas fechas y recuentos derivados a lectores de pago?
9. **Aviso de privacidad.** Si se permite, ¿qué debe decir el aviso de privacidad de PrediGol sobre estos datos de jugadores (que no
   son usuarios) y cómo atiende una solicitud de supresión de un jugador?

## 6. Qué hace falta para avanzar

1. El dueño envía este asunto con los otros de DM-08 (anexo I: «enviar la lista completa de una vez»).
2. Con la respuesta escrita: el coordinador la anota en el anexo I; se elige §3.1, §3.3 o nada; se reserva la zona con
   Intelligence y UX; contrato primero (versión menor), cálculo en sombra tras su interruptor apagado, prueba de que ningún texto
   médico sale del contrato, y encendido solo con firma (PM-15-03).
3. Si la respuesta pide corregir lo del §2, se abre una tarea aparte con las sesiones dueñas de esas zonas.

**Vuelta atrás:** no hay nada que revertir; es un documento.

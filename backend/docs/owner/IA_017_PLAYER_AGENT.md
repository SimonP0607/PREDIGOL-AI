# IA-017 · Player Intelligence Agent (`player-v1`), en sombra y apagado

**Qué es.** Un agente nuevo del registro (`player`, versión `player-v1`, nace CHALLENGER) que da **una postura por candidato de goles y resultado** según **quién juega**. No crea probabilidades, cuotas, stakes, mercados, URL, SQL ni consultas: escribe códigos, una **dirección** (nunca una magnitud) y referencias a la evidencia de su propio paquete. Modelo: Haiku 5.5 por la tarea `evaluation` del router (esfuerzo medio), como el Statistics Agent. Prompt `player-assess-v1`.

**Su contrato: `pa-v1`.** `aa-v1` no puede llevarlo sin cambiarse (su `agent` solo admite `match` y `stats`, y cada señal lleva `strength`, una magnitud), y `aa-v1` no se edita nunca en el sitio. `pa-v1` es `aa-v1` **recortado**: los mismos campos y topes, sin `strength`, sin `research`, solo modo `EVALUATION`, cinco códigos de señal (`ABSENCES`, `LINEUP`, `FORM`, `NEWS`, `DATA_QUALITY`) y siete riesgos sobre información de jugadores. El Match y el Statistics Agent siguen en `aa-v1`, byte a byte.

## Qué lee

La porción `player` del paquete (`mcp-v1`), as-of la pasada:

- `header` del partido;
- `shared.absences` (quién falta y por qué, peso y si es clave o portero titular), `shared.lineups`, `shared.players` (historial: partidos, titularidades, minutos, goles, asistencias, importancia; **sin** tarjetas ni faltas, que son de otra familia) y `shared.quality`;
- la evidencia de lesiones, sanciones, dudas, alineaciones, entrenador, noticias y traspasos (texto no fiable, con sus banderas).

**Nada de mercado, modelos ni familias.** Los candidatos le llegan con nombre (`c1`…), familia, mercado, selección y línea, sin un solo número. Los nombres de goles/resultado y de conteos no cambian: no añade candidatos ni renombra ninguno.

**Versionado de porciones.** El paquete no cambia (`package-v1`, mismo hash). Lo que cambia es el **conjunto de porciones** que guarda `ai.match_runs.slices`: `slices-v1` = `match, stats` (todas las filas de antes y todas las de ahora con el agente apagado, idénticas) y `slices-v2` = `match, stats, player` (solo pasadas con el agente encendido, que lo dicen en `model_status.slices`). La auditoría `slice_known` vuelve a derivar exactamente el conjunto que la fila nombra; una fila que no nombra ninguno es `slices-v1`.

## Cómo se enciende

Apagado por defecto: no hay tarea, ni coste, ni cambio en ninguna fila. Para encenderlo, añade `player` a `FBI_AI_AGENTS`:

```
FBI_AI_AGENTS=match,council,player          # o match,council,stats,player
```

Encendido, se le pregunta solo si su porción tiene jugadores (alineación, ausencias, plantilla o evidencia de disponibilidad) y el partido tiene candidatos de goles/resultado; si no, deja la nota `no_player_to_assess` / `no_candidate_to_assess` y no gasta nada. Su respuesta solo llega a las reseñas de sombra y al Council de los brazos `ma-v1` y `ma-v1-h` (como `A:player_evaluation`); el `engine_version` de esos brazos añade `+player-v1`. **Nada llega a una decisión.** Para volver atrás, quita `player` de la lista.

## Qué medir (en sombra)

1. **Salidas inválidas** de `player-v1` (`ai.agent_runs`, `agent = 'player'`, `status = 'invalid'`): el umbral de Gate B es 3 %. Los códigos de `error` dicen por qué.
2. **Posturas bajadas** por el servidor (`rests_only_on_instruction_like_evidence`, `no_driver_or_reference_that_stands`).
3. **C08**: cuántas veces el Player Agent discrepa de otro agente sobre el mismo candidato, y quién acierta después (atribución por resultado, cuando se le añada).
4. **Coste por pasada** y cuántas pasadas encendidas quedan sin pregunta (`model_status.player.note`).
5. **Batería**: el objetivo `player` (40 casos, 8 familias × 5) pasa offline en cada cambio (`fbi.ai.battery.simulate`); en el LAB se mide aparte (`run.submit(targets=("player",))`). No entra en la evidencia del gate `battery` de `battery-v3` mientras el agente esté apagado.

## Gate F-Player

Lo que F-Player sigue reteniendo son los **props de un jugador** (goles, asistencias, tiros, tarjetas, paradas): hace falta un mercado con modelo validado, una regla de liquidación y un precio de referencia. Antes de que `player-v1` cuente para algo más que la sombra: una versión nueva de la batería que lo meta en sus objetivos medida en verde, inválidas por debajo del 3 % y una fila firmada por el dueño en `intel.promotions`.

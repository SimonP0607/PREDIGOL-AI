# IA-066 · Contrato C-01 «Partido», entrega 1 (AD-J02)

*Pieza AD-J02 del plan maestro de la arquitectura definitiva 2026, ola 1 (entrega 1). 16/17-nov-2026. Para el dueño y para la sesión de UX.*

Es el contrato que leerán la pestaña «Intelligence» del partido (maqueta 02) y el «Análisis completo» (maqueta 03). Esta entrega
fija **su forma completa** y la llena **solo con lo que PrediGol ya calcula hoy**. Lo que todavía no existe llega como ausente,
con su motivo y la pieza que lo calculará. Sigue las convenciones de IA-057 (AD-J01): dos proyecciones, cifra con sello, versión,
ausente con motivo, ejemplos y prueba de no fuga.

## 1. Dónde está

| Qué | Dónde |
| --- | --- |
| Pública (lector) | `GET /api/v1/matches/{fixture_id}/intelligence` — nivel de producto, con las mismas puertas de consentimiento y membresía que el resto del partido. **Solo existe con `FBI_MATCH_INTELLIGENCE` encendido** (si no, 404) |
| Privada (dueño) | `GET /api/v1/admin/intelligence/matches/{fixture_id}/intelligence` — `require_admin`, sin interruptor. Es ruta hermana del dossier: el dossier de siempre (`…/dossier`) **no cambia** |
| Modelos | `backend/src/fbi/api/contracts/intelligence/match.py` (C-01, versión `1.0.0`) |
| Cómo se llena | `backend/src/fbi/api/services/match_intelligence.py` (`read` lee, `assemble` arma, `to_public` proyecta) |
| Ejemplos | `backend/tests/fixtures/contracts/intelligence/C-01/` — `antes_del_partido`, `con_alineacion_oficial`, `terminado` (pública y privada de cada uno) |
| Pruebas | `backend/tests/unit/test_match_intelligence.py`, `backend/tests/integration/test_match_intelligence_api.py` y las genéricas de IA-057 |

La pública **no se oculta en la web**: el servidor la construye copiando solo los campos públicos de la privada. Nada privado viaja,
ni siquiera como ausente.

## 2. Qué trae y de dónde sale (todo ya existía)

| Bloque | Pública | Privada añade | Origen |
| --- | --- | --- | --- |
| `match` | Equipos, competición, hora, jornada, estadio (nombre del proveedor), estado y fase (`previo`, `en_juego`, `terminado`, `aplazado`, `cancelado`, `otro`) | — | `core.fixtures` |
| `probabilities` | Una cifra por salida (1X2, más/menos 2,5 y ambos marcan) con su sello: `calibrada` solo si se aplicó un calibrador campeón con precio fresco; si no, `sin_calibrar`. Intervalo en puntos si el modelo lo dio | La cifra propia del modelo (`raw_probability`, siempre `sin_calibrar`, con un decimal), el modelo, por qué está o no calibrada y la cuota justa | El pronóstico del partido que ya ve el lector (`forecast-v1`, la vista común `market_view`) |
| `context` | Qué se juega cada lado: puesto, zona, presión, distancia a la zona de arriba y de abajo, partidos restantes | — | Paquete del partido, regla `stakes-v5` |
| `form` | «Cómo llegan»: últimos resultados (V/E/D), puntos y goles por partido | — | Paquete del partido |
| `official_lineup` | Formación y técnico de cada lado, o cuándo se espera (20 min antes del saque, la mediana medida) | — | Alineación oficial del proveedor |
| `reader_chronicle` | La crónica que el lector ya ve hoy (`user-narrative-v3`, verificada frase a frase), solo con `FBI_USER_NARRATIVE=on` y mientras cuente la historia de los datos actuales | `chronicle_preview`: la misma crónica aunque el interruptor no la muestre | `ai.user_narratives` |
| `selections` | Solo lo publicado (el conjunto `qualified` del día), con `publicada` / `en_juego` / `liquidada` y **la misma cifra** de `probabilities` | Todas las selecciones de la capa de decisión en sombra (`decision-v1`), con su estado, su cifra calibrada y bruta, cuota, valor esperado, razones y si están en el conjunto de evaluación | `intel.decisions` (solo lectura) y `picks.daily_sets` |
| `citations` | Los hechos del partido tal como los muestran sus noticias, cada uno con su nivel (`oficial`, `dos_origenes`, `un_medio`, `rumor`), fuente y sus cuatro fechas | `evidence`: todas las piezas web del partido, con su estado y su texto de extracción | `ai.evidence` (las mismas filas que lee Noticias) |
| — | — | `brief`: el último informe de la IA (texto propio del modelo, sin verificar) y `packet` | `ai.match_briefs`, `ai.match_packets` |

**Caso Arsenal W – London City** (producción, 15-nov-2026 10:35 UTC): la pública dice 59 % `calibrada`; la privada añade 78,5 %
`sin_calibrar`. Es el ejemplo `antes_del_partido` y tiene su prueba.

**Paridad de la cifra (G-COH):** una selección publicada lleva exactamente el mismo objeto de cifra que su salida en `probabilities`;
el modelo lo comprueba y rechaza otra cosa.

## 3. Lo que aún no existe (ausente con su motivo)

| Campo | Motivo | Pieza que lo trae |
| --- | --- | --- |
| `scenarios` («Qué se juega» como escenarios tipados) | `no_entregado` | AD-B02 |
| `chronicle` (la crónica única) | `no_entregado` | AD-F02 |
| `evaluations` (E1–E4) y `evaluation` de cada cifra | `no_entregado` | AD-D06 |
| `new_since_yesterday` («Lo nuevo desde ayer») | `no_entregado` | AD-C07 |
| `pending_unknowns` («Qué falta por saber») | `no_entregado` | AD-D05 |
| `keys`, `risks` | `no_entregado` | AD-F01 |
| `players_to_watch` | `no_entregado` | AD-H07 |
| `price` de cada salida (mejor cuota con su edad) | `no_entregado` | AD-B06 |
| Cifra de una selección fuera de 1X2 / más-menos 2,5 / ambos marcan | `no_entregado` | AD-B05 |
| Nivel de una noticia contradictoria o desactualizada; relación del hecho con el análisis | `no_entregado` | AD-C07, AD-G08 |
| Estado del ciclo de una selección (privada) | `no_entregado` | AD-D02 |

Además: `pendiente_derechos` cuando el dueño mantiene apagado lo que el lector vería (pronóstico, lectura, noticias o crónica), exista o no el dato (el motivo no delata lo que hay en la sombra); `sin_datos`
cuando no hay paquete, pronóstico o alineación; `sin_cobertura` cuando la competición no se modela; `sin_publicados` en una lista
pública vacía porque nada está publicado. **Ningún campo llega como `null` mudo** (hay prueba).

## 4. Qué no cambia

- No cambia ninguna cifra, decisión, pick, umbral, agente, prompt ni motor. No llama a ningún modelo ni cuesta nada de API: solo lee.
  `decision-v1` no se importa (se leen sus filas). `FBI_PICKS_SOURCE` sigue apagado.
- El dossier (`…/dossier`), `GET /matches/{id}/analysis` y la pestaña «Análisis» siguen igual.
- No hay migración. No se crea ningún interruptor: la pública usa `FBI_MATCH_INTELLIGENCE`, creado por UX en #318.

## 5. El interruptor en producción (comprobado en solo lectura, 17-nov-2026 00:20 UTC)

Dentro del contenedor de la API, con el propio código: `FBI_MATCH_INTELLIGENCE` **apagado** (sin línea en el entorno), crónica del
lector `on`, lectura y pronóstico para lectores encendidos. Con el interruptor apagado la ruta pública responde 404. Si el dueño lo
enciende, la pública solo trae lo que el lector ya ve en otras pantallas y bajo los mismos interruptores.

## 6. Comprobación con datos reales (solo lectura, 17-nov-2026 00:5x UTC)

El código de esta pieza se ejecutó, sin red y sin base de datos, sobre las filas exportadas de **61 partidos** (los 60 más recientes
con paquete entre hace 3 días y las próximas 24 h, más el Arsenal W – London City): **61 armados sin error, 0 fugas** en la pública,
290 cifras (254 `calibrada`), 7 partidos sin pronóstico, 484 selecciones en la privada y **0 en la pública** (nada publicado), 145 citas
públicas de 238 piezas web, 36 lados con contexto de tabla, 121 con forma, 17 alineaciones oficiales. Sin la crónica del lector en
esta prueba (necesita el cálculo de la historia, que no se exportó). Antigüedad del paquete en los 43 partidos de las próximas 24 h:
mediana 0,30 h, p90 0,96 h, máximo 1,21 h; por eso el aviso de «datos antiguos» (`freshness.stale`) solo salta si el paquete de un
partido de las próximas 24 h tiene más de 6 h.

## 7. Vuelta atrás

- Para el lector: `FBI_MATCH_INTELLIGENCE` apagado (como está) → la ruta no existe y vuelve la pestaña «Análisis» de hoy.
- El código: revertir el PR. Es aditivo y no tiene consumidor todavía.

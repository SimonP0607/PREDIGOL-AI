# IA-131 · Contrato C-01 «Partido» completo (2.0.0) — AD-J02, entrega 2

## Qué es

La entrega 1 (IA-066) dejó el contrato del partido con su forma completa y, donde no había dato, el bloque «ausente con su motivo».
Esta entrega **compone en el contrato lo que ya calculan las otras piezas**, sin rehacer ninguna y sin calcular nada nuevo:

| Bloque | De dónde sale | Quién lo ve |
| --- | --- | --- |
| Escenarios («Qué se juega»): objetivo, qué necesita, de quién depende, si está **demostrado**, su probabilidad simulada y qué hace cada resultado de este partido | `scenarios-v2` (IA-082), su última lectura de la temporada de los últimos 3 días | Solo el dueño (sombra) |
| La crónica única, por las ocho secciones del plan, y su actualización tras la alineación oficial | `chronicle-v4` (IA-104) y `lineup-update-v1` (IA-116) | Solo el dueño (sombra) |
| Evaluaciones E1–E4 con su versión, y qué hizo cada una con cada selección (cifra de `decision-v2` con su sello) | `eval-cycle-v1` (IA-105/106) | Solo el dueño (sombra) |
| Alertas del partido «antes → ahora» (C-05) | IA-107 | Solo el dueño |
| Estado de cada selección en el ciclo y su decisión (C-02) | IA-068/IA-114 | Solo el dueño |
| Fuentes del análisis (C-07), dentro del contrato | IA-122 | Solo el dueño |
| Previsiones de jugadores | `player-engine-v2` (IA-129) | Solo el dueño (sombra) |
| Estado de cada mercado mostrado | catálogo `market-states-v1` (IA-070) | Lector: los mercados de las cifras y de lo publicado |
| Quién puede faltar: estado, base, fuente y fecha (nada médico) | `availability-v1` (IA-091) | Lector, solo con `FBI_PROFILES` (igual que en los perfiles) |
| «Lo nuevo desde ayer»: las citas leídas en las últimas 24 h | las citas del propio contrato | Lector |
| «Qué falta por saber y cuándo»: la alineación oficial (20 min antes, la mediana medida) y, para el dueño, las evaluaciones que faltan | código | Lector: solo la alineación |

«Las claves», «Riesgos», «Jugadores a seguir», «Lo nuevo» y «Qué falta» de la crónica son, en 2.0.0, **secciones de la crónica única**
(`que_puede_definir`, `riesgos`, `jugadores`, `novedades`, `que_falta`): es donde el plan de contenido las pone. Una sección sin nada que
contar dice su código (`SIN_RIESGOS`, `NADA_PENDIENTE`…); una a la que el verificador quitó todas las frases dice `SIN_FRASES_VERIFICADAS`.

## Qué no cambia

- **La versión 1.1.0 sigue igual**, con sus dos rutas (`/matches/{id}/intelligence` y la privada hermana). 2.0.0 tiene rutas propias:
  `GET /api/v1/matches/{id}/intelligence/v2` (lector) y `GET /api/v1/admin/intelligence/matches/{id}/intelligence/v2` (dueño,
  `require_admin`). La forma de 1.1.0 queda congelada en la instantánea de contratos como `C-01@1`.
- **Nada experimental llega al lector.** Escenarios, crónica y E1–E4 llegan a la vista pública solo cuando el dueño los publique
  (`PUBLISHED_BLOCKS`, hoy **ninguno**) y solo con `FBI_MATCH_INTELLIGENCE` encendido (hoy apagado). Mientras, dicen
  `pendiente_derechos`, que no revela si el bloque existe en la sombra. Para la vista pública ni siquiera se leen esas tablas.
- Ninguna probabilidad cambia: cada cifra es la que guardó su pieza, redondeada una sola vez por el servidor. La cifra del lector
  sigue siendo `forecast-v1` (caso Arsenal W – London City: 59 % `calibrada` al lector, 78,5 % `sin_calibrar` solo al dueño).
- No hay migración, ni interruptor nuevo, ni llamada a modelos o a proveedores. No toca `decision-v1`, picks ni `web/`.

## Si falta una tabla

Si la base aún no tiene la tabla de una pieza, el bloque dice `no_entregado` con la pieza que lo calcula (AD-B02 escenarios, AD-F02
crónica, AD-D06 evaluaciones, AD-D08 alertas, AD-B08 jugadores, AD-D02 ciclo). Si la tabla existe pero no hay fila del partido, dice
`sin_datos`. Una temporada sin reglamento codificado dice `reglamento_no_codificado`.

## Cómo se apaga o se revierte

- El lector no ve nada mientras `FBI_MATCH_INTELLIGENCE` siga apagado (la ruta pública responde 404).
- Publicar un bloque de la sombra es un cambio de código revisado en su propio PR, con la firma del dueño.
- Revertir el PR quita las rutas `…/v2`; la 1.1.0 no se toca.

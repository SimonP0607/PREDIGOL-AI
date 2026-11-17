# Ejemplos de los contratos de Intelligence

Un fichero por caso y proyección: `<contrato>/<caso>.private.json` y, si el contrato tiene proyección pública,
`<contrato>/<caso>.public.json`. Cada fichero es el `data` de la respuesta (el sobre `status`/`data`/`reason`/`meta` de
siempre no se repite aquí).

- El privado valida contra el modelo privado y vuelve idéntico al serializarlo.
- El público es **exactamente** lo que el servidor construye a partir del privado (`to_public`), y la prueba de no fuga lo
  recorre: ningún campo privado, ninguna clave desconocida, ningún estado distinto de `publicada`, `en_juego` o `liquidada`.
- Equipos y personas ficticios, enlaces y direcciones en `.invalid`. **Nunca** datos de producción, y la web no los usa como
  datos: solo en pruebas de componente y de regresión visual.

Esta carpeta es propia porque `tests/fixtures/contracts/` guarda respuestas grabadas de API-Football (`teams.json`,
`standings.json`…).

Las reglas: `backend/docs/owner/IA_057_CONTRATO_INTELLIGENCE.md`. Las pruebas: `tests/unit/test_intelligence_contract_*.py`.

| Contrato | Caso | Qué enseña |
| --- | --- | --- |
| C-00 (muestra, sin ruta) | `publicada` | Una selección autorizada sale en la pública como `publicada`; la que sigue `en_evaluacion` solo en la privada. 59 % `calibrada` en las dos; 78,5 % `sin_calibrar` solo en la privada |
| C-00 | `sin_publicar` | Nada autorizado: la pública trae `{"items": [], "missing_reason": "sin_publicados"}` |
| C-01 Partido (entrega 1) | `antes_del_partido` | Caso Arsenal W – London City: 59 % `calibrada` en la pública, 78,5 % `sin_calibrar` solo en la privada; nada publicado (`sin_publicados`); alineación `aun_no_disponible`; escenarios, crónica única, E1–E4 y el resto `no_entregado` con su pieza |
| C-01 | `con_alineacion_oficial` | Alineación oficial; una selección publicada (`publicada`) con la misma cifra que su salida |
| C-01 | `terminado` | Partido terminado; la selección `liquidada`; la crónica apagada para lectores (`pendiente_derechos`) y visible solo en la privada |
| C-11 Consola (solo privada) | `en_sombra` | «Nada sale de la sombra» se cumple con `FBI_AI_MODE=enforce` porque el veto no está en vigor (el informe de combined no dice pass); batería NO PASA, Gate B NO EVALUADO con el cierre del dueño, un sobre al 80 % y un tope al 95 %; motor de noticias y cola de alertas `no_entregado` |
| C-11 | `esquema_atrasado` | Una base detrás del código: el registro y los costes llegan como `{"read_failed": true, "error": "UndefinedTable"}`, la sombra `sin_comprobar` y `schema_check` dice qué tablas faltan |
| C-05 Alertas por alineación (solo privada) | `con_alertas` | Las cuatro clases de alerta «antes → ahora»: una selección `pendiente_alineaciones` retirada en E3 por `alineacion_en_contra` (un jugador del que depende no es titular; cifra y precio antes y ahora), una que no recibió alineación en E4 (`sin_alineacion`), un saque adelantado (`cambio_horario`) y un partido aplazado (`cambio_condiciones`). `notifies_reader` siempre falso |
| C-05 | `sin_alertas` | Ninguna alerta en la ventana: `{"items": [], "missing_reason": "sin_datos"}` |
| C-10 (búsqueda v2) | `encontrado` | «atletico» encuentra por prefijo dos equipos (uno por su alias), un jugador y un estadio por palabras, y el partido de sus equipos; Noticias dice `no_entregado` (`AD-G01`). La privada añade `score`, `popularity`, `rank` y `index` |
| C-10 | `sin_resultados` | Ningún grupo con resultados: cada uno `sin_resultados` y «¿Quisiste decir…?» (`did_you_mean`) con un nombre cercano |
| C-10 | `sin_indice` | El índice aún no se ha construido: cada grupo `no_entregado` (`AD-I01`) y `freshness.stale` con `indice_sin_construir` |
| C-09 (perfiles) | `club` | Club con plantilla: entrenador de la última alineación, forma, cifras de temporada con su muestra (xG en 3 de 6 partidos), un sancionado del parte del proveedor (solo estado, base, fuente y fecha), palmarés calculado (liga 2025) y, en la privada, una selección en sombra (`detectado`) |
| C-09 | `club_sin_plantilla` | Club sin plantilla ni estadísticas y fuera de la cobertura del parte: `squad` `sin_datos`, `availability` `sin_cobertura`, cifras `sin_datos` con `matches_with_data: 0` |
| C-09 | `seleccion` | Selección: lista del proveedor (`convocados_ultimo_partido`, nivel `proveedor`) con `official_state: ninguna_fuente_oficial_autorizada` y 0 fuentes oficiales permitidas; líderes de partidos y goles |
| C-09 | `jugador` | Jugador con 630 minutos: tasas por 90 con partidos, minutos e intervalo; los remates cuentan solo los 5 partidos que los registran; foto como monograma; en la privada, lo que añadirá el motor (`not_yet_private`) |
| C-09 | `jugador_poca_muestra` | Jugador con 180 minutos: `muestra_insuficiente` (450 mínimos) y `sin_datos` donde la planilla no registra la acción; `sancionado` por el parte del proveedor |
| C-09 | `competicion` | Liga: temporada, tabla, próximos partidos, goleadores y cobertura de estadísticas |

Al añadir un contrato: su carpeta con al menos un caso, una fila aquí y su línea en la coordinación entre sesiones.

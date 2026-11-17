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
| C-02 Selección | `publicada` | Una selección que el dueño autorizó: 57 % `calibrada`, precio vigente con su regla y umbrales, por qué, versiones y fuentes; la privada añade el ciclo, la cifra `sin_calibrar` (78,5 %), la validación `INSUFICIENTE` (0 de 300) y la dependencia de alineación `no_entregado` (`AD-D03`) |
| C-02 | `liquidada` | La misma, evaluada: en la privada, la evaluación posterior (`MERECIDO`, CLV +4,3 %, «Un acierto no valida el mercado») |
| C-02 (solo privada, `privada/`) | `en_evaluacion`, `retirada` | Selecciones sin estado público: no tienen proyección pública y el servidor no las sirve al lector |
| C-03 Seguimiento privado (solo privada) | `en_sombra` | Los diez estados con sus recuentos, dos familias `INSUFICIENTE` con su muestra frente a 300 y una selección confirmada en sombra sin estado público |
| C-03 | `sin_tablas` | Una base sin las tablas del ciclo ni de evaluaciones: cada bloque `sin_datos` |
| C-06 Noticia | `portada` | La portada de `front-v1`: la principal (oficial), «Última hora» (solo fechas estructuradas; un rumor entra con su nivel), «Tus equipos» de un lector que sigue al Club Ejemplo Norte y las destacadas; el autor siempre `pendiente_derechos`, imagen monograma. La privada añade la cola (una historia `en_moderacion`), las fuentes retenidas y el texto propio fuera de derechos |
| C-06 | `portada_vacia` | Solo un medio y un rumor: sin principal (`sin_datos`), «Tus equipos» `sin_favoritos` |
| C-06 | `noticia` | Una historia con tres fuentes (oficial con resumen, radio y medio reservado solo con enlace), «Cómo se fue sabiendo», una relacionada y `match_impact` `sin_datos` porque el análisis que la usó no está publicado; la privada lista esa evaluación (AD-G08) |
| C-06 | `noticia_retirada` | Retirada a petición: `retirado_por_derechos` y nada de su contenido en las dos proyecciones |
| C-06 | `busqueda` | «Ejémplo Sur» con la categoría `bajas_y_sanciones`: facetas contadas antes del filtro, un resultado |
| C-06 | `partido` | Las historias del partido y de sus equipos dentro de su ventana |
| C-07 Fuentes del análisis | `publicada` | E3 de un análisis publicado: una baja oficial `en_contra` del over (su efecto por selección, solo privado), un contexto y un rumor `no_usada`; la privada añade el hecho rechazado por homónimo y las dos evaluaciones |
| C-07 | `sin_evaluaciones` | Ninguna evaluación aún: todo `sin_datos` |
| C-04 Parlays con estado | `ninguno` | Nada cumple la regla: el parlay del producto (`parlay-v5`) y el de la sombra (`parlay-v6`, `sin_candidatos`) llegan con `status: "ninguno"` y `NINGUNO_CUMPLE`, sin tramos; la pública solo trae el del producto |
| C-04 | `dos_tramos` | `parlay-v6` armado en sombra con 2 tramos (conjunta por simulación `sin_calibrar`, margen acumulado 5,81 %), solo en la privada; la pública, el del producto `ninguno`. La privada añade el histórico de `parlay-v5` por estado |
| C-04 | `tres_tramos` | `parlay-v6` de 3 tramos liquidado `perdido` (un tramo perdido, pago 0) y su calibración (1 liquidado de los 100 necesarios); la pública, el parlay de varios días del producto armado con 6 tramos (regla `parlay-v5`, máximo 7) |
| C-08 Evaluación posterior (solo privada) | `ganada_sin_valor` | Ganada con precio malo frente al cierre (CLV −6,4 %): `SUERTE`; las seis preguntas: cifra `calibrada`, resultado puntuado, precio, dos hechos sostenidos y uno no evaluable, la alineación cambió la decisión (de CAUTELA), escenario `no_entregado` (`AD-B02`); validación `INSUFICIENTE` con su muestra y el aviso fijo |
| C-08 | `perdida_con_valor` | Perdida con buen precio (CLV +9,2 %): `VARIANZA`; cifra `sin_calibrar`; sin hechos citados (`sin_datos`) |
| C-08 | `anulada` | Anulada: `NULO`, no se puntúa (`scores` `sin_datos`) |
| C-08 | `sin_evaluaciones` | Una base sin la tabla de evaluaciones: `selections`, `calibration` y `board` `sin_datos` |
| C-12 Inicio | `sin_publicados` | 0 publicados (lo de hoy): `{"items": [], "missing_reason": "sin_publicados"}` con la regla `featured-v1` |
| C-12 | `destacados` | Tres candidatos, dos con una selección publicada (resumen de su C-01 público): primero el del equipo favorito, luego el de la competición seguida; el que no tiene nada publicado nunca entra |

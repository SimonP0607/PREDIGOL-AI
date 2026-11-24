# PM-14-11 · Trazabilidad entre las láminas I01 a I12 y sus pantallas reales

Plan Maestro PM, bloque 14 (UX-231). Revisión del 24-nov-2026, sobre `main` en `a33de20` más las correcciones menores de este mismo PR.

## Cómo se comparó

- **Láminas**: página «12 · Innovación 2026–27» del lienzo principal, en sus capturas a tamaño real del 19-nov-2026 (versión 62 del
  lienzo, anexo H del plan: 21 artboards de I01 a I12; F01 a F04 quedan fuera del alcance de la ficha).
- **Pantallas**: la web de este PR construida en un entorno **local** (PostgreSQL 16 con la base migrada a la cabeza, la API y la web
  en modo `live`), con los interruptores de producción de hoy más los de las piezas nuevas **encendidos solo en ese entorno**
  (`FBI_AVAILABILITY`, `FBI_AVAILABILITY_PHASES`, `FBI_MATCH_SHOT_FUNNEL`, `FBI_MATCH_BALANCE`, `FBI_LINEUP_LAYERS`,
  `FBI_MATCH_COVERAGE`, `FBI_PROB_ICONS`, `FBI_COMPETITION_PAGE`, `FBI_COMPETITION_TABLES`, `FBI_COMPETITION_DIRECTORY`,
  `FBI_PLAYER_PROFILE_EXTRAS`, `FBI_WHAT_IF`, `FBI_USAGE_CONSOLE`, `FBI_STATS_PROVIDER_EXTRAS`, `FBI_CHRONICLE_STAT_SHEET`).
  Producción no se tocó.
- **Datos**: un mundo sembrado (equipos ficticios como los de las láminas): Primera A (239) de 2024 a 2026 con «Apertura/Clausura -
  N», y NB I (271), K League 1 (292) y Primera B (240) con la fracción de datos del anexo B; la matriz la gradúa el lote nocturno
  real (`fbi.coverage.job`) y C-13 el cálculo real (`fbi.stats.job`). Un partido terminado de cada nivel, uno por jugar con
  pronóstico 1X2 calibrado, un club, un jugador de campo, un portero y la competición con su reglamento (v2).
- **Captura**: Playwright, Chromium y WebKit, página completa, a 390 px (y 820 y 1440 donde la lámina tiene tableta o escritorio).
  Lámina y pantalla se miraron lado a lado, tramo a tramo. La misma prueba queda en el repositorio (`web/e2e/pmscreens.spec.ts`,
  proyectos `pm-screens` y `pm-screens-webkit`, solo con `E2E_PM_SCREENS=1`).

Leyenda: **coincide** (la pieza de la lámina está y se lee igual), **coincide con diferencias** (está, con las diferencias
anotadas), **sin hacer** (la pieza no existe todavía; con su motivo).

## Lámina por lámina

| Lámina | Pantalla | Veredicto | Coincidencias | Diferencias anotadas |
| --- | --- | --- | --- | --- |
| I01 · Estadísticas · cobertura A (390, 820, 1440) | `/matches/$id` · Estadísticas | coincide con diferencias | Embudo de remate con sus tres pasos y porcentajes (16·6·2 frente a 9·3·1), las dos zonas con xG del partido y xG por remate, balanza con su aviso «no es field tilt», estado del marcador con minutos por delante, tarjeta de estadísticas y mejores valorados. Mismo orden que la lámina | (1) Falta el chip «Cobertura A · completa» (el chip de I04 está sin hacer). (2) Falta el conmutador «Partido · 1.ª mitad · 2.ª mitad» y la tabla «Por mitad» (PM-05-01 y PM-10-03 esperan el cierre de PM-01-05, 26-nov). (3) La balanza está en Estadísticas (decisión de FE-006; el anexo G la ponía en Resumen). (4) Cada gráfica va en la tarjeta de evidencia E1 (FE-004, posterior a la lámina): título, frase, «Ver como tabla» y fuente; la pantalla mide 4.383 px frente a 2.287. (5) El estado del marcador no rotula los tramos «Gana X / Empate» sobre la barra |
| I02 · Alineaciones con capas | `/matches/$id` · Alineaciones | coincide con diferencias | Las cuatro capas (Valoración, Minutos, Tarjetas, Goles y asistencias), la cifra en cada titular y la mejor valoración destacada | Un solo campo con los dos equipos, sin el conmutador por equipo con su formación de la lámina; los nombres largos se recortan en la ficha del jugador («Santiag…»), la lámina usa inicial y apellido |
| I03 · Contexto (árbitro, clima, altitud, viaje) | `/matches/$id` · Resumen | **sin hacer** | El nombre del árbitro sale en la cabecera del partido | Bloque del árbitro construido sin exponer (PM-08-02, espera la consulta DM-08); clima, altitud, viaje y descanso bloqueados (PM-07-02 a PM-07-05) |
| I04 · cobertura B / C / D | `/matches/$id` · Estadísticas | coincide con diferencias | Sin tarjeta vacía: hechos del acta desde los eventos, **una sola** nota de lo que la competición no ofrece, forma y tabla; pestañas según el nivel (D: Resumen, Estadísticas, Alineaciones y Noticias) | (1) Falta el chip «Cobertura X». (2) Falta el enlace «Tabla completa» a la página de competición. (3) **Los niveles de la lámina no son los de la matriz**: la lámina dibuja B como «eventos y alineaciones, sin estadísticas de equipo» y C como «goles con minuto»; la matriz gradúa cada bloque por su dato (`coverage-levels-v1`), así que una liga B real con estadísticas de equipo al 87 % (NB I) enseña el embudo y la balanza, y una C real (K League 1) con alineaciones A conserva Alineaciones. La pantalla obedece a la matriz (PM-15-01, CI-021); la definición de la nota verde de la página 12 sigue pendiente de confirmar por el dueño |
| I05 · Perfil de equipo (390, 1440) | `/teams/$id` | **sin hacer** (pantalla existente) | Cabecera, próximo partido, últimos resultados, temporada por competición | Formación habitual y rotación (PM-08-03, PM-10-05), calendario con dificultad (PM-08-05 en sombra, PM-14-03), bajas e historial del entrenador (PM-05-06, PM-08-04): bloqueadas o pendientes del dueño |
| I06 · Perfil de jugador (campo, portero) | `/players/$id` | coincide con diferencias | Plantilla por puesto (C-13) con percentiles, últimos cinco y minutos; el bloque de datos del proveedor (UX-180) dice cuándo no hay muestra; al portero no se le muestran goles evitados (retenidos) | La lámina tenía «Participación», «Valoración por partido» y «Por 90 minutos frente a la liga»; la pantalla usa la plantilla por posición de la página 14 (V2·2). **Defecto fuera de esta zona**: a 390 px el título «¿Cómo rinde frente a los jugadores de su puesto?» queda en una columna de una o dos palabras, apretado por la etiqueta E1 y «Comparar con…» (gráficas de jugador, UX-221) |
| I07 · Competición · Primera A (390, 820, 1440) | `/competitions/$id` | coincide con diferencias | «Las tablas que deciden el año»: reclasificación, descenso por promedio y cupos internacionales, con la zona de hoy; «¿Qué pasa si…?» debajo; nivel de cobertura de la competición | **Corregido en este PR**: (1) a 390 px la página se desplazaba 287 px en horizontal (la rejilla no limitaba su columna y las fichas de las tablas la ensanchaban); (2) la etiqueta «Cupo internacional» se salía de la tarjeta y partía los nombres a mitad de palabra; (3) la tabla del proveedor saltaba al llegar las tablas calculadas (CLS 0,77 → 0,24; el resto es el pie de página común). Quedan: las vistas se llaman por el nombre del reglamento («Tabla de reclasificación total 2026») y no con el corto de la lámina, y la zona dice «Cupo internacional» (condicional) donde la lámina nombra Libertadores o Sudamericana |
| I08 · Directorio mundial (390, 1440) | `/competitions` | coincide | Buscador, filtros Todas/A/B/C/D con su recuento, «Solo destacadas», «Cómo leer las dos señales», competiciones por región con nivel y prioridad editorial | Sin «Las que sigo» cuando el lector no sigue ninguna |
| I09 · Probabilidad en iconos | `/matches/$id` · Resumen · «Pronóstico PrediGol» | coincide con diferencias | Conmutador «Barras · Iconos», 100 iconos con sus tres formas, cifras y la frase al revés | Abre en Barras (la lámina enseña el estado Iconos). Solo aparece con el 1X2 calibrado y campeón (`iconsAllowed`): con una estimación preliminar no hay iconos, a propósito |
| I10 · Crónica enriquecida (390, 1440) | `/matches/$id` · Resumen (postpartido) | **sin hacer** (en sombra) | — | La crónica con hoja de hechos espera PM-11-01 a PM-11-03 (bloqueadas) y la firma; `FBI_CHRONICLE_STAT_SHEET` solo cambia el texto del backend (IA-158) |
| I11 · Admin · Matriz de disponibilidad | `/admin/competitions` · Disponibilidad | coincide con diferencias | Cuatro cifras de cabecera, matriz competición × familia con niveles, filtros por nivel y país, «Solo bloqueadas», detalle por competición; aviso «Evaluación privada» | Es una pestaña de Competiciones y no una entrada propia del menú; la matriz va por familia con su nivel (A–D) en vez de «7 de 7» por mercado |
| I12 · Estados «información no disponible» | componentes compartidos (UX-173) en I04 C y D | coincide | «La competición no ofrece el dato»: una línea agrupada, sin tarjeta | «Aún no disponible», «muestra insuficiente» y «en revisión» no salen con estos datos; los cubren las pruebas de `product/shared/Unavailable.test.tsx` |

Resumen: **12 láminas, 12 con su pantalla aceptada o su diferencia anotada**. Coinciden 2 (I08, I12); coinciden con diferencias 7
(I01, I02, I04, I06, I07, I09, I11); sin hacer 3 (I03, I05, I10), todas por piezas bloqueadas o pendientes del dueño y ya
registradas en el estado del plan.

## Comprobaciones en cada pantalla (Chromium y WebKit)

Las 21 capturas (12 láminas a sus tamaños) cargan sin error de consola ni llamada fallida a la API y sin desplazamiento horizontal
en los dos motores, una vez corregida I07. Dos pasadas seguidas de Chromium sobre los mismos datos dan 0 píxeles distintos: las
capturas sirven de referencia para comparar una ola con la siguiente.

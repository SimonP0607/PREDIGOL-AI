# Sistema «Noche de partido» (plan maestro UX/UI 2026)

*Qué es el sistema visual y de interacción de PrediGol tal como quedó en el código al cerrar el plan maestro UX/UI 2026 (17 olas,
códigos UX-101 a UX-133 y BE-038 a BE-041 del registro). Es el mapa: dónde vive cada cosa y qué regla la gobierna. El detalle de
cada cambio está en su fila de `REGISTRO_CODIGOS.md` y en su PR.*

El plan no cambió picks, modelos, probabilidades, cuotas, pagos, membresías ni reglas de acceso: cambió cómo se ve y cómo se
recorre lo que ya existía, y agregó nueve pantallas aprobadas.

## 1. Fundamentos

| Qué | Dónde | Regla |
| --- | --- | --- |
| Color y superficies | `web/src/styles.css` (`@theme` y variables) | Fondo nocturno, tres superficies (`card`, `elevated`, `popover`), verde de campo (`pitch`) como escena, dorado (`gold`) solo para lo que PrediGol recomienda. Estados: `positive`, `negative`, `warning`, `info`, cada uno con su versión `-soft` |
| Radios | `--radius-chip` 8 px, `-field` 12, `-control` 14, `-card` 16, `-feature` 20, `-sheet` 24 | Un radio por papel; no se mezclan |
| Tipografía | Archivo variable (títulos y cifras), IBM Plex Sans (texto), IBM Plex Mono (referencias) | Servidas por PrediGol, con respaldo ajustado (`size-adjust`). Ningún texto bajo 12 px (prueba e2e) |
| Cifras | `web/src/lib/i18n/format.ts` | Un solo formateador de cuotas (`formatOdds`: decimal, americano o fraccional según el ajuste del lector) y uno de hora (`web/src/lib/time.ts`: 24 h o 12 h). Cambian cómo se escribe, nunca el valor |
| Movimiento | `web/src/product/shared/motion.ts`, `data-motion` en `<html>` | Se respeta «reducir movimiento» del sistema y el ajuste del lector; las cifras no cuentan hacia arriba |

## 2. Componentes

| Familia | Dónde | Notas |
| --- | --- | --- |
| Primitivas | `web/src/components/ui/*` | Botón, campo, `Segmented`, hoja (`sheet`), diálogo, `banner`, `skeleton`, tarjeta (`card`) |
| Sistema | `web/src/components/system/*` | Aviso legal (`Disclaimer`), frescura (`Freshness`), fuentes de datos, glosario en línea, estados vacíos y de error |
| Fútbol y datos | `web/src/product/shared/*`, `web/src/components/icons/football.tsx` | Escudo con siglas de respaldo, marcador sobre el campo, cuota (chip), barra de probabilidad, tarjeta dorada de pick y de parlay |
| Navegación | `web/src/components/layout/*` | Barra inferior de cinco destinos y hoja «Más» en móvil; barra superior desde 1024 px; campana de Avisos; idioma en acceso, Perfil y «Más» |
| Consola | `web/src/admin/*` | Menú en cinco grupos, primitivas de lista y detalle, Auditoría por familias |

## 2 bis. Piezas de Intelligence (plan maestro unificado, UX-140)

Las ocho piezas que necesitan las 18 maquetas de PrediGol Intelligence viven en `web/src/product/shared/intelligence/`
(`Pieces.tsx`, `model.ts`) y extienden primitivas existentes. Ninguna calcula: pintan lo que trae el contrato del backend, con
sus palabras (namespace de textos `intelligence`).

| Pieza | Extiende | Regla |
| --- | --- | --- |
| `LifecycleChip` | `StatusBadge` | Diez estados del ciclo; palabra e icono, nunca solo color. El lector solo ve «En juego» y «Liquidada» (`PUBLIC_LIFECYCLE`) |
| `ConfirmationLevel` | `StatusBadge` | Oficial, Confirmada por dos orígenes, Declaración, Un solo medio, Contradictoria, No confirmada (decisión D-04: sin pestaña «Rumores») |
| `ProbabilityLine` | barra de probabilidad | La cifra del contrato con su sello «Calibrada / Sin calibrar», hora y confianza. No recalcula ni elige |
| `EvaluationSteps` | fichas de `ExplainSteps` | E1 primera lectura, E2 por novedad, E3 alineación oficial, E4 cierre |
| `VersionHistory` | línea de tiempo | Cada evaluación añade versión, la más nueva arriba; nada se reescribe |
| `SourceLevelList` | fuentes de datos | Hechos agrupados por nivel, con fuente, hora y enlace al original |
| `PrivateBand` | `Banner` | «Evaluación privada · no visible para usuarios» encima de toda vista privada. Marca, no protege: protege el servidor |
| `EntityHeader` | escudo del partido | Cabecera de club, selección y jugador; el jugador nunca lleva foto, solo iniciales |

## 2 ter. Estados «información no disponible» (plan PM, PM-14-01, lámina I12; UX-173)

Un dato, un bloque o un mercado que no se puede enseñar está en uno de cinco estados, y cada uno tiene su componente en
`web/src/product/shared/Unavailable.tsx` (modelo puro en `availabilityState.ts`, textos en el namespace `availability`, que
viaja en el fragmento de la pantalla que lo usa y no en el arranque: `addCatalog` y el `t` de `availabilityText.ts`). Ninguna
pantalla pinta un hueco propio: ni tarjetas vacías, ni «0» que no son ceros, ni «—» sin explicación, ni el mismo mensaje para todo.

| Estado | Componente | Qué dice | Siete estados de C-16 que lo dan |
| --- | --- | --- | --- |
| No existe | `NotOffered` (una línea, sin tarjeta); `NotSettled` para el 6 | La competición no ofrece el dato; la sección desaparece | 1 existe (`no_entregado`), 2 `sin_cobertura`, 6 liquidable, 7 reglas (`invalid_selection`, `quarter_line`, `started`) |
| Cobertura parcial | `PartialCoverage` | Nivel C: se pinta con la nota y su porcentaje | 2 cobertura suficiente (C, D con dato) |
| Muestra insuficiente | `ThinSample` (recuento, «faltan n», nunca una tasa) | Hay datos, pero pocos | 1 o 2 con `muestra_insuficiente` o nivel MI |
| Pendiente | `PendingData` (cuándo llega y la acción que ofrezca la pantalla) | Llegará | 1 `sin_medir`, 3 cuota vigente, 4 probabilidad calculada, 7 sin precio |
| En revisión | `UnderReview` (banda de aviso) | Existe pero ahora no es fiable; qué sigue valiendo | 5 calibrada y autorizada, 7 `MERCADO_NO_EVALUABLE`, precio atípico |

Reglas: los siete estados se evalúan en orden y tras el primer «no» los siguientes quedan «sin evaluar» (`marketSteps`); una
pantalla con varios huecos usa `UnavailableNotes`, una sola nota por estado (ligas D). Solo se montan con `FBI_AVAILABILITY`
encendido (`availability` en `/auth/me`, `useAvailabilityOn`). Contraste AA de cada par de tokens medido desde `styles.css` en
`Unavailable.test.tsx` (`web/src/lib/a11y/contrast.ts`).

Primer consumidor: la consola del dueño de la matriz (PM-02-08, lámina I11; UX-174), pestaña «Disponibilidad» de
`/admin/competitions` (`web/src/admin/AvailabilityConsole.tsx`): nivel por familia, muestra y fecha de cada competición, cambios de
la semana, discrepancias de la sombra y los siete estados de un partido con la nota única que vería un lector.

## 2 quater. Gráficas nuevas: evidencia, lectura y accesibilidad (plan PM, PM-10-06; FE-004)

Toda gráfica nueva se dibuja dentro de `EvidenceChart` (`web/src/components/analytics/EvidenceChart.tsx`, sobre la `ChartCard`
del plan EA), que exige tres cosas sin las que no compila:

| Qué | Dónde | Regla |
| --- | --- | --- |
| Etiqueta de evidencia E0–E4 | `EvidenceBadge` (`StatusBadge`) | Los niveles de `DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md` §5.3; bajo la muestra mínima se muestra E0 diga lo que diga la pieza |
| Frase de lectura | `readingSentence` (`evidence.ts`), namespace `evidence` | Dice la cifra con su n, su intervalo y el valor de liga tal como llegan del contrato; bajo la muestra mínima no da tasa. Es también la descripción de la gráfica para el lector de pantalla (`aria-describedby`) |
| Revisión de accesibilidad | `ChartReview` y `reviewProblems` | Las 14 comprobaciones críticas (tras [Chartability](https://chartability.fizz.studio/)): contraste, alternativa textual, texto mínimo, sin parpadeo, color no único, teclado, foco, instrucciones, título y resumen, incertidumbre, lenguaje llano, tabla equivalente, zoom y espaciado, lector de pantalla. Cada una «ok» o «no_aplica»; ocho siempre aplican |

`chartGuard.test.ts` falla si un archivo nuevo dibuja una gráfica (Recharts, las primitivas de `components/analytics` o
`components/ui/chart`) fuera de `EvidenceChart`. Las 14 gráficas que existían el 20-nov-2026 quedan en su lista, que solo puede
encoger. Ninguna pieza del bloque 10 del plan PM se cierra sin las tres.

## 3. Pantallas

| Área | Rutas | Qué cambió |
| --- | --- | --- |
| Acceso | `/login`, `/register`, `/verify-email`, `/activate`, `/forgot-password`, `/reset-password`, `/unlock` | Tarjeta y botones del sistema; crear cuenta en tres tarjetas numeradas |
| Bienvenida y guía | `/welcome`, guías de cada pantalla | Paso «n de m», «Saltar», tarjeta dorada de la guía |
| Inicio | `/home` | Selector «Para ti / Todo»; abre en el que el lector elija en Perfil |
| Partidos y Match Center | `/matches`, `/matches/$fixtureId` | Días como fichas; seis pestañas; el postpartido encabeza el Resumen; «Avanzado» es un botón del administrador |
| Picks | `/picks`, `/picks/$pickId` | Detalle del pick en su propia pantalla, con la explicación que ya daba la API |
| Cuotas y Parlays | `/odds`, `/odds/status`, `/parlays`, `/my-picks` | «Estado de los precios» (interruptor) |
| Perfil | `/profile`, `/profile/$section` | Índice y una pantalla por sección; las direcciones viejas (`/profile#…`) redirigen. Los cinco ajustes: hora, cuotas, animaciones, Inicio por defecto y campana por equipo |
| Ayuda | `/help`, `/help/glossary`, `/help/how-it-works`, `/help/messages/$ticketId` | Asistente automatizado (interruptor) que solo responde con el contenido de Ayuda; Telegram si hay enlace oficial |
| Transparencia y Novedades | `/transparency`, `/transparency/methodology`, `/updates` | Metodología en su pantalla; Novedades con tipo y filtros |
| Noticias | `/news` | Lista de noticias de los partidos por jugar (interruptor) |
| Avisos | `/inbox` y campana | Bandeja con lo que ya se envió al lector (interruptor) |
| Consola | `/admin/*` | Usuarios con un botón «Acciones» por fila, cola de pagos con selector, comunicados con los campos del sistema |

## 4. Interruptores que agregó el plan

Todos nacen apagados y se encienden en `app.env` sin desplegar; el mapa completo está en
`backend/docs/owner/INTERRUPTORES_UX.md`.

| Interruptor | Qué enciende |
| --- | --- |
| `FBI_ODDS_STATUS` | «Estado de los precios» y su enlace desde Cuotas |
| `FBI_HELP_ASSISTANT` | El asistente de Ayuda |
| `FBI_TELEGRAM_CHANNEL_URL` y `telegram` en `FBI_SUPPORT_CHANNELS` | El canal de Telegram en el contacto de Ayuda |
| `FBI_NEWS_FEED` | La sección Noticias y su entrada en «Más» |
| `FBI_INBOX` | La bandeja de Avisos y la campana |
| `FBI_ODDS_BY_MATCH`, `FBI_NAV_V2`, `FBI_SEARCH`, `FBI_PROFILES` | Plan maestro unificado (BE-045): Cuotas «Por partido», las barras nuevas, el buscador y los perfiles |
| `FBI_AVAILABILITY` | Plan PM (C-16): los estados «información no disponible» y la consola de la matriz (`availability` en `/auth/me`) |
| `FBI_USAGE_CONSOLE` | Plan PM (PM-04-05): la vista «Consumo del proveedor» de `/admin/operation` (`usage_console` en `/auth/me`) |
| `FBI_COMPETITION_PAGE`, `FBI_COMPETITION_DIRECTORY` | Plan PM (PM-09-04, PM-09-05): la página de competición y el directorio mundial (`competition_page`, `competition_directory` en `/auth/me`) |
| `FBI_PLAYER_PROFILE_EXTRAS`, `FBI_WHAT_IF` | Plan PM (PM-08-06, PM-09-03): el perfil de jugador con los datos nuevos y la calculadora «¿Qué pasa si…?» (firma DM-14) (`player_profile_extras`, `what_if`; `competition_tables` dice si `FBI_COMPETITION_TABLES` está encendido) |
| `FBI_NEWS_V2`, `FBI_MATCH_INTELLIGENCE` | Plan maestro unificado: Noticias de las maquetas 08 a 10 (abogado y datos) y la pestaña «Intelligence» (el dueño) |

## 4 bis. Composición por tamaño de pantalla (auditoría visual del 16-nov-2026)

La auditoría frente a las 89 láminas encontró que las composiciones de escritorio no seguían las láminas (una columna a
todo el ancho). Desde UX-134 a UX-137:

| Regla | Dónde |
| --- | --- |
| Una rejilla de tarjetas se reparte por el ancho de su **contenedor**, nunca por el de la pantalla | `PICK_GRID` y `PICK_GRID_HOST` en `web/src/product/shared/Bits.tsx`; los bloques de Inicio usan `@3xl:` y `@5xl:` |
| Escritorio en dos columnas: la principal y una lateral de 380 a 400 px | Inicio (`home-columns`), Resumen del partido antes del inicio (`summary-before`), Picks (`picks-side`) |
| En teléfono y tableta, una columna en el orden de lectura; las columnas de escritorio no son cajas ahí (`contents`) | Los mismos |
| La barra superior muestra Parlays, Cuotas y Noticias desde 1280 px; bajo ese ancho están en «Más» | `DESK_BAR` en `web/src/components/layout/nav.ts` |
| Con tres picks o más, el panel de picks de un partido ocupa el ancho de la página | `useWidePicks` en `web/src/product/match/picks.ts` |

## 4 ter. Piezas del plan maestro unificado (UX-139 a UX-158, 16-nov-2026)

Sin sistema de diseño nuevo: cada pieza extiende las que ya había.

| Pieza | Dónde | Regla |
| --- | --- | --- |
| Barras unificadas | `barNav`, `deskExtras` y `moreItems` con `NavFlags` en `web/src/components/layout/nav.ts`; `Bars.tsx`, `MoreSheet.tsx` | Teléfono: Inicio · Partidos · Noticias · Picks · Más (D-01); Cuotas en «Más» y en la barra de escritorio desde 1600 px, sin desborde (D-02). Solo con `FBI_NAV_V2` |
| `SearchButton` y `ReaderSearch` | `web/src/components/system/search/` | Botón de 44 px, «/» fuera de un campo y Ctrl/⌘ K; resultados por grupo (equipos, competiciones, partidos); recientes solo en el dispositivo (`predigol.search.recent`). Solo con `FBI_SEARCH` |
| Páginas de perfil | `web/src/product/teams/` (`TeamPage`, `PlayerPage`, `TeamsPage`, `model.ts`) | Club, selección y jugador con `EntityHeader`; el jugador nunca lleva foto ni dato médico; un perfil que no existe es «no encontrado», no un error. Solo con `FBI_PROFILES` |
| `OrderedColumns` y `OrderedBlock` | `web/src/product/match/SummaryTab.tsx` | Dos columnas en escritorio; en teléfono una sola en el orden de la lámina (`contents` + `order-N`), sin duplicar bloques |
| `MatchOddsSheet` | `web/src/product/odds/byMatch/MatchOdds.tsx` | Mercados principales, comparación por casa y movimiento ya guardado de un partido; no calcula probabilidades |
| `Insights` | `web/src/product/transparency/Insights.tsx` | Unidades acumuladas con su tabla, «¿Estima bien?» en barras y tabla de mercados; nada bajo la muestra mínima |
| `RadioCards` | `web/src/product/profile/RadioCards.tsx` | Radix RadioGroup como tarjetas con ejemplo; objetivo táctil completo |
| `BusinessSummary` | `web/src/admin/BusinessSummary.tsx` | La consola abre con lo que espera una decisión; solo lectura |

El JS de arranque tiene un presupuesto de 640 KB (UX-139), que vigila la prueba de tamaño.

## 5. Reglas que se mantienen

- Accesibilidad: axe sin violaciones en las páginas del inventario (`web/e2e/inventory.ts`), foco visible y no tapado, objetivos
  táctiles de al menos 24 px, teclado en pestañas, hojas y menús.
- Móvil, tableta, escritorio y PWA: desde 320 px sin desplazamiento lateral; salto a escritorio en 1024 px; zonas seguras.
- Español e inglés: cada clave de texto existe en los dos idiomas (prueba unitaria).
- Presupuesto: JS total y mayor fragmento medidos en cada PR (`bun run budget`).
- Una pantalla nueva entra en el inventario de e2e y, si depende de algo que el dueño debe decidir, nace detrás de un interruptor.

## 6. Lo que quedó fuera, con su motivo

| Qué | Motivo |
| --- | --- |
| «Por casa» y «Últimas 24 h» en Estado de los precios | El libro guarda una hora de lectura por partido, no un historial por casa |
| Cuota justa y valor esperado en el detalle del pick | Son cifras de modelo; el plan no toca lo que se muestra de probabilidades |
| «Avisarme de novedades» | Requiere una decisión del dueño sobre un aviso nuevo |
| Noticias en la barra de escritorio y filtro por jugador | La barra queda en cinco destinos; las noticias no llevan jugador identificado |
| `PicksTab.tsx` | Sigue teniendo consumidores (Resumen, Postpartido, Intelligence) |
| Escena de escritorio del acceso (imagen A-01) | Opcional; espera la imagen |

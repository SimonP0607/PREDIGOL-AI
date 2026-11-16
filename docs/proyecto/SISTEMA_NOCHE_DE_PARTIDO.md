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

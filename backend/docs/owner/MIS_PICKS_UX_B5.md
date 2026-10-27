# B5 · Mis picks completo: todo lo guardado, buscable, con su muestra y descargable

En Mis picks el cliente encuentra cualquier pick que guardó, ve cuánto lleva con la muestra que lo respalda y se lleva sus datos
en un CSV. Nada de rachas ni de cifras sin muestra: con pocos picks liquidados solo se ven los conteos.

## 1. Qué ve el cliente

- **Buscar y filtrar «Picks guardados».** Un buscador siempre a la vista (equipo o liga, sin tildes: «nandu» encuentra
  «Ñandú») y los filtros: resultado, mercado, liga, rango de cuota, quién lo eligió (PrediGol o él) y los días del partido.
  En el escritorio van en un panel sobre la lista; en el móvil y la tableta, en la hoja «Filtros» que sube desde abajo, con el
  número de filtros puestos en el botón y «Ver N picks» bajo el pulgar. Cada cambio se aplica al momento y «Borrar filtros» lo
  deja todo como estaba. Las ligas y los mercados que ofrece son solo los suyos.
- **La lista por días, completa.** Los picks van por el día del partido, del más reciente al más antiguo, cada día con su
  encabezado («Hoy», «Ayer», «sábado, 4 de octubre»), de 25 en 25 con «Ver más» y «25 de 668»; al final, «Los 668 picks, todos
  a la vista». Nada se recorta.
- **Lo que suman, con su muestra.** Encima de la lista, lo que suman los picks filtrados: cuántos y cómo terminaron siempre;
  las unidades, la rentabilidad (ROI) y el acierto solo desde **25 liquidados**, la rentabilidad con su margen (±20 puntos con
  25, ±14 con 50, ±10 con 100, ±5 con 400) y, por debajo de **100**, el aviso «la muestra todavía no permite concluir». Con
  menos de 25: «12 liquidados: los aciertos, las unidades y la rentabilidad se ven desde 25».
- **El desglose.** «Ver el desglose» abre lo mismo por mercado, por liga y por rango de cuota; cada fila con su propia muestra
  (con menos de 25 liquidados en esa fila, «solo conteos»).
- **El valor de línea.** Cada pick cuyo partido ya empezó y tiene referencia de cierre dice «Valor de línea +3,1 %»: su cuota
  (la suya si la indicó) frente a la probabilidad sin margen del consenso de las casas en la última captura antes del inicio.
  Arriba, la media de sus picks (desde 25), cuántos quedan por encima de cero, cuántos minutos antes del inicio se tomó la
  referencia y la definición rotulada con su versión (`clv-v1`) y su fecha.
- **Descargar CSV.** «Descargar CSV» baja exactamente los picks filtrados (en su idioma: cabeceras, resultados y fechas en su
  zona horaria) y «Descargar CSV» en Mis parlays, todos sus parlays con una línea por pierna. Con la membresía vencida o
  suspendida, Mis picks queda en solo lectura y **la descarga sigue disponible**: acceder a sus datos es un derecho.
- **Mis resultados y Tu recapitulación** siguen la misma regla: los conteos siempre, la rentabilidad con su muestra. La
  recapitulación **ya no muestra rachas** («mejor racha», «racha actual»), ni la cuota media ni los gráficos por mercado y por
  cuota (que ahora están en el desglose, con su muestra); sus gráficos de unidades aparecen desde 25 liquidados.

## 2. Línea base

Antes de B5 (lo que A1 dejó en producción): la lista completa y paginada y una sola rentabilidad, pero ni filtros, ni búsqueda,
ni desglose, ni CSV, ni valor frente al cierre; «Mis resultados» daba aciertos y rentabilidad con cualquier muestra (un 100 %
con un pick) y la recapitulación contaba rachas, que el plan prohíbe por invitar a apostar.

**Producción hoy** (27-oct, 06:22 UTC, solo lectura): **ningún pick guardado** (0 lectores con picks guardados, 0 liquidados,
0 selecciones propias) y 15 parlays de un solo lector. Por eso todo B5 se comprobó en QA, con una cuenta de 668 picks guardados
sobre 330 partidos terminados y su cierre (abajo); en producción el primer lector que guarde verá desde el primer día los
conteos y, cuando llegue a 25 liquidados, sus cifras con su margen.

## 3. Lo que nunca cambia

- **PrediGol Intelligence no se toca.** Ni modelos, ni probabilidades, ni umbrales, ni liquidación, ni estados de la IA, ni
  RAW. El valor de línea lee el consenso de mercado que ya existe (la referencia de cierre del plan de Intelligence,
  `fbi.market.closing_value`) sin escribir nada. Las pruebas de aislamiento (que leen el código) cubren los módulos nuevos:
  ninguno llama a un modelo de lenguaje ni a internet, y nada de Intelligence importa la capa de usuario.
- **Cada cliente ve solo lo suyo.** La lista, el resumen, el desglose y los dos CSV filtran por la cuenta de quien pregunta;
  otro cliente no puede leer, cambiar ni quitar un registro ajeno.
- **Nada se borra y no hay migración.** Las consultas usan los índices que ya existen.

## 4. Lo nuevo por dentro

- **Un solo filtro** (`services/pick_filter.py`) para la lista, el resumen, el desglose y el CSV: los cuatro cuentan siempre
  los mismos registros. Valores siempre como parámetros; la búsqueda escapa `%` y `_`.
- **API (aditiva):** `GET /me/picks` acepta `result`, `market`, `competition`, `origin`, `band`, `since`, `until` y `q`;
  `GET /me/picks/summary` (totales, desglose, valor de línea y las opciones del cliente); `GET /me/picks/export` y
  `GET /me/parlays/export` (CSV con BOM, sin caché, nombre `predigol-mis-picks-AAAA-MM-DD.csv`); `GET /me/history` dice la
  muestra (`min_sample`, `conclusive`, el margen de cada grupo) y deja sin cifra lo que no la alcanza.
- **El CSV no ejecuta nada en una hoja de cálculo:** un texto que empieza como una fórmula (`=`, `+`, `-`, `@`) lleva un
  apóstrofo delante.
- **Membresía:** el resumen y los dos CSV son lecturas permitidas con acceso limitado.

## 5. Decisiones que tomé

- **La muestra es la de «Cómo le va a PrediGol»** (25 para ver cifras, 100 para concluir, margen 1/√n): una sola regla en todo
  el producto, la misma función en el servidor.
- **El rango de cuota es el precio con que se liquida** (el del cliente si lo indicó; si no, el mostrado al guardar).
- **El valor de línea solo después del inicio** y con la última captura (Shin) anterior al inicio; una captura posterior o de
  otro método nunca cuenta. La media, desde 25 picks con referencia.
- **El CSV de parlays lleva todos sus parlays**: los filtros son de los picks.
- **Los días son los del cliente** (su zona horaria), como el resto de Mis picks.

## 6. Pruebas

- **Backend (integración, base real, `test_my_picks_complete.py`):** cada filtro y sus combinaciones frente a consultas escritas
  en la prueba; los rechazos (422 con el campo); totales y desglose con su muestra; solo conteos por debajo de 25; el valor de
  línea por pick y su media (las capturas que no son cierre, fuera); el CSV en español y en inglés, con las fórmulas escapadas
  y solo las filas propias; el CSV de parlays; las lecturas permitidas con membresía limitada; la regla de muestra de «Mis
  resultados».
- **Web (unitarias):** el filtro (qué cuenta, el orden de las fechas, la búsqueda recortada), los parámetros iguales para la
  lista, el resumen y el CSV, la muestra y su margen en los tres estados (español e inglés), las palabras del resumen, y que no
  queda ninguna racha en los textos.
- **e2e (`mypicks.spec.ts`, proyecto `mypicks`, con `seed_b5.py`):** una cuenta de QA con 668 picks: «Todo» completo por la API
  y página a página en la lista, por días; trece filtros, el desglose y la lista frente a SQL; la muestra en sus tres estados;
  el valor de línea; el CSV filtrado solo con datos propios y otra cuenta sin acceso a ellos; y a 320 px la hoja de filtros sin
  nada de lado.

## 7. Puertas

- **Árbol final del paquete `ux-b5`** (`ux/rel-b5x`: A3 a A16 y B1 a B5 sobre `ia-p03` de la IA, con la migración 0095 colgada
  de la 0116, más dos arreglos que halló la puerta: las noticias y la narrativa de los lectores solo leen las afirmaciones
  tipadas de la investigación v2 cuando está encendida —la guarda del plan de la IA—, y la guía de la fase 2 de la IA cuenta
  bien a sus lectores): backend con ruff y mypy limpios y **8.947 pruebas pasadas**, 4 omitidas (27-oct, 08:26–08:50 UTC);
  web con lint en 0 errores (26 avisos de siempre), tipos, **1.165 pruebas** y build.
- **La base de QA migrada como producción:** copia de A2 en la 0113 → la 0115 y la 0116 de la IA → copia de seguridad
  (`fbi_qa_ia3_preREL3`, sha256 `408e7030…`) → **prueba de restauración** en una base desechable (revisión 0116, los conteos
  idénticos en las 197 tablas) → ensayo de la migración arriba (0102), abajo (0116, cada tabla como antes) y arriba otra vez →
  `fbi_qa_rel2` en la 0102 con cada tabla anterior intacta y las nuevas vacías.
- **e2e sobre ese árbol** (27-oct, 06:33–08:30 UTC): Mis picks completo (`mypicks.spec.ts`) **12 de 12**, Postpartido 8 de 8,
  estados de B3 10 de 10, la suite completa como arranca producción 159 pasadas, 10 fallidas y 19 omitidas (2 sin correr),
  autoservicio 39 / 1 / 2, membresía 8 / 8, tickets apagados 7 / 7, axe 35 / 35 y app instalable 8 / 8. Los 11 fallos fueron
  esperas de carga con la máquina ocupada (páginas aún cargando al agotarse el tiempo, un bloque sin pintar a los 15 s, una
  navegación interrumpida por otra) y, repetidos sobre el mismo árbol, pasaron **29 de 29** y **7 de 7**.
- **Antes, sobre la rama de la fase:** la puerta del backend halló que la instantánea de forma del cliente no conocía la
  muestra de `GET /me/history` (corregida en `2fc2ec5b` con su razón).

## 8. Despliegue

Backend y web juntos (el contrato cruza los dos), sin migración propia, con copia previa. Va en el paquete `ux-b5` con todo
lo terminado después de A2 (A3 a A16 y B1 a B5), sobre `ia-p03`, con sus migraciones 0095 a 0102 (BACKUP → RESTORE TEST →
MIGRATION → VALIDATION → DEPLOY); el resultado queda en `ESTADO_EJECUCION_UX.md`. **Vuelta atrás:** la web anterior funciona
con este backend (la API es aditiva) o las dos publicaciones anteriores. No hay nada que encender ni apagar.

## 9. Acción manual

Ninguna.

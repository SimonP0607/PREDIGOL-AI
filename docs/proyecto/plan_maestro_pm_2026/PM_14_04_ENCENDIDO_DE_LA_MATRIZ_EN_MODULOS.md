# PM-14-04 · Cuándo se enciende la matriz de cobertura en Cuotas, Picks, Noticias y Mi parlay

Plan Maestro PM, bloque 14 (BE-110, UX-240). Regla escrita el 25-nov-2026 (confirmada por el coordinador); sustituye a «esperar al 7-dic» sin cambiar ningún criterio estadístico.

## Qué hay construido (todo apagado)

Cuatro interruptores, uno por módulo, `FBI_MATRIX_ODDS`, `FBI_MATRIX_PICKS`, `FBI_MATRIX_NEWS`, `FBI_MATRIX_PARLAY`, cada uno `off` (por defecto), `show` o `on`.
Exigen `FBI_AVAILABILITY` (sin él valen `off`). Los lee la web en `Me.matrix_modules` y un solo módulo (`product/shared/matrixModules.tsx`) pregunta a C-16.

- `show`: la pantalla dice **una** nota («información no disponible», con los cinco estados de PM-14-01) de lo que C-16 dice de su partido. **No cambia** ningún precio, pick, mercado ni selección.
- `on`: Cuotas oculta los mercados que C-16 lista sin cuota vigente (menos de 3 casas); Mi parlay marca como no permitida una selección cuyo mercado C-16 niega a `mi_parlay` (solo puede quitar, nunca añadir). Picks y Noticias solo lo dicen: **un pick publicado nunca se retira por una matriz**.
- `FBI_PICKS_SOURCE` no se toca nunca; la sombra (`FBI_AVAILABILITY_SHADOW`) sigue encendida y midiendo mientras un módulo está en `show` u `on`.

## Regla de encendido

**`show`** de un módulo, cuando se cumplan **todas**:

1. **Sombra real con el código corregido.** Al menos **tres días consecutivos** con `availability_shadow` en `completed` (todos los partidos de las 48 h siguientes, hasta 500; no `aborted`) **desde el despliegue de BE-110** (la sombra del 25-nov a las 08:30 UTC es la primera), y **uno de los tres es sábado o domingo**. En esos días `analytics.availability_discrepancies` solo trae dos clases, ambas explicadas: `cuotas:menos_de_3_casas` (política de 3 casas de la matriz frente a C-14) y `mercados_parlay:ok/outlier_price` (el chequeo de precio atípico que la matriz modela y C-14 no). **Cero** de `probabilidad` y de `estadisticas`, salvo el borde del 80 % de un dato recién cruzado (se anota con el dato y la liga). Una clase nueva, un `error` o un `aborted` reinician la cuenta.
2. **Repetición («replay») con el código desplegado.** `ejecucion/evidencia_pm1404/pm1404_replay_v1.py` sobre los partidos terminados de los últimos 20 días (solo lectura, mismo tope de memoria): cero discrepancias sin explicar.
3. **Pasada completa de la matriz hecha** (las 272 temporadas con celda) y comparada con el anexo B.
4. `FBI_AVAILABILITY=1` y la salud del servidor sin `problem`.

Fecha más temprana posible: **sábado 28-nov-2026 a las 09:00 UTC** (sombras del 26, 27 y 28-nov; la del 28 es de sábado; si alguna falla, la cuenta se retrasa), no el 7-dic. Se enciende con el kit de PM-15-03 (`pm1503_kit_v1.sh aplicar`, con los cuatro nombres añadidos a su lista blanca), de uno en uno, y se vuelve atrás con `revertir` o quitando la línea.

**`on`** de un módulo, cuando además:

5. Han transcurrido los **14 días de sombra** (el día 14 es el **7-dic-2026**; el día 1 fue el 24-nov) con la regla 1 cumplida en todos los días medidos desde BE-110.
6. Para `FBI_MATRIX_ODDS=on`, **el dueño lo decide**: oculta los mercados que 1 o 2 casas cotizan (hoy 866 de las 1.130 discrepancias del 24-nov). Para `FBI_MATRIX_PARLAY=on`, la prueba de igualdad de Mi parlay en 1.000 selecciones sigue en verde con el código desplegado.

**Por qué el `on` no se adelanta más.** Lo que miden los 14 días es la coincidencia con las cuotas y los precios de partidos que aún no han ocurrido, día tras día; una repetición con partidos pasados no ve las ventanas de cuotas en vivo ni la deriva del proveedor. El `show` no depende de esa medición (no cambia ningún precio, pick ni mercado); el `on` sí, porque quita mercados y selecciones.

**Cierre (ficha PM-14-04, campo 20):** siete días encendido sin incidentes, aceptación visual contra su lámina, teclado y contraste, y prueba en WebKit.

## Medido el 25-nov-2026 (primer día con el código de BE-110)

- Sombra del 25-nov (fila 227764): `completed` 08:30:05–08:46:41, **118 partidos** (todos los de las 48 h siguientes), pico de memoria **157 MiB**, **1.144 discrepancias**: `cuotas:menos_de_3_casas` 899 y `mercados_parlay:ok/outlier_price` 245; **0** de `probabilidad` y **0** de `estadisticas`. El 24-nov (antes de BE-110) eran 866, 197, 62 y 5: lo corregido desaparece y lo explicado sigue.
- Matriz: pasada **completa** 24-nov 21:08 (fila 225167, 298 temporadas, 125 s, pico 72 MiB, 0 errores, lanzada a mano: `scheduled=false`); la incremental del 25-nov 08:00 (fila 227629) tardó 11 s. La pasada completa que programa el propio planificador (`full_due`) se verá el domingo 29-nov.
- Frente al anexo B (19-nov): las 272 temporadas ya tienen celda; 2.677 datos iguales y 43 distintos (1,6 %), 60 mercados distintos con ventana en B; mismas causas ya explicadas (umbrales cruzados por partidos jugados, árbitro, alineaciones con las dos plantillas). La Sudamericana 2026 sigue en D en los nueve mercados: la baja a `MI` es de la segunda pasada (29-nov).

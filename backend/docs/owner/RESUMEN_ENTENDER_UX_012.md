# UX-012 · El Resumen del partido, primero para entender

Plan de cierre de la UX, tarea 2.2. **Solo web: sin migración, sin interruptor nuevo y sin tocar la API.** No se borra ningún dato: se
ordena, y lo que otra pestaña muestra completo se cambia por un enlace a ella.

## 1. Qué ve el cliente

En el Resumen de un partido **que aún no empieza**, en este orden:

1. **Lectura y pronóstico**, lado a lado en una pantalla ancha: el resumen de la lectura con sus puntos clave, «Por qué hay valor» (solo
   si PrediGol publicó un pick) y los dos riesgos principales (UX-011), junto al pronóstico de PrediGol rotulado.
2. **Picks** que PrediGol publicó para el partido con su estado real (o que no publicó ninguno).
3. **El análisis de mercado** (si una opción está bien pagada) y **los mejores precios** de 1X2, más/menos 2,5 y ambos marcan, con el
   enlace a la pestaña Mercados.
4. **«Profundizar»**, plegado y **cerrado al llegar**: forma, tabla y cara a cara; después descanso y calendario en todas las
   competiciones, bajas y las alineaciones (con su enlace a la pestaña Alineaciones). Un botón de 44 px dice qué hay dentro y lo abre.

Antes la forma, la tabla, el calendario, las bajas y las alineaciones estaban siempre abiertas, en una columna a la derecha en las
pantallas anchas y entre medias de los picks y los precios en el teléfono. **Cambia la costumbre**: quien las usaba las encuentra ahora un
toque más abajo, con el mismo contenido.

**No cambian** los partidos en juego, terminados ni no jugados: siguen con su orden y su «Antes del partido» plegado. Las otras pestañas
(Análisis, Estadísticas, Mercados, Alineaciones, Postpartido) tampoco.

## 2. Lo que no hace

- No quita ningún bloque ni ningún dato: el contenido de «Profundizar» es el que ya estaba, con los mismos estados (cargando, error con
  referencia, vacío con su motivo).
- No cambia la API, los picks, las probabilidades ni nada de PrediGol Intelligence.
- No recuerda si el lector abrió «Profundizar»: cada visita empieza cerrado.

## 3. Pruebas

- Web: `SummaryTab.test.tsx` («Profundizar» cerrado al llegar, con su título y subtítulo en español e inglés, un botón de 44 px y nada de su
  contenido dibujado); `bun run lint`, `typecheck` (también los tipos del e2e) y `test`.
- e2e: la prueba que lee la frescura de la tabla (`user.spec.ts`) comprueba que «Profundizar» llega cerrado, que la tabla no está hasta
  abrirlo y que, abierto, dice cuándo se actualizó. Corre en el CI (aquí solo con tipos). Falta revisar a mano 320 px y el contraste con
  axe en un partido real tras el despliegue.

## 4. Despliegue y vuelta atrás

Solo web. Vuelta atrás: revertir el PR (no hay datos nuevos). Hasta que se despliegue, producción sigue con el orden anterior.

## 5. Acción manual

Ninguna. Al desplegar, abre un partido de mañana en el teléfono: arriba lectura, pronóstico y picks; «Profundizar» cerrado; ábrelo y mira
que forma, tabla, cara a cara, calendario, bajas y alineaciones están.

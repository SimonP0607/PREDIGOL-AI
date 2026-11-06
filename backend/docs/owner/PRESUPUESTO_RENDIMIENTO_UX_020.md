# UX-020 · Presupuesto de rendimiento y accesibilidad

Plan de cierre de la UX, tarea 5.2. **Solo web y CI: sin migración, sin interruptor, sin IA.** Convierte tres medidas en puertas.

## Qué se vigila

- **Tamaño del bundle (en cada PR):** tras `bun run build`, el paso «bundle budget» de Web CI falla si el mayor fragmento de JS, todo el JS o todo el CSS (comprimidos con gzip) superan los topes de `web/bundle-budget.json`. Medido el 5 de noviembre de 2026: mayor fragmento 296 KB, todo el JS 1.220 KB, CSS 24 KB; los topes dejan un margen de unos 15 % (340 KB, 1.400 KB y 40 KB). Subir un tope es una decisión que se explica en el PR. En local: `bun run build && bun run budget`.
- **Accesibilidad:** la prueba axe (`E2E_A11Y=1`) deja de solo anotar: **un error crítico o grave falla** y dice la regla y los elementos; los moderados y menores se siguen anotando.
- **LCP y CLS en el móvil (`E2E_PERF=1`):** Inicio, un partido y Picks, en un Pixel 7: CLS por debajo de 0,1 y LCP por debajo de 2,5 s (la línea «buena» de las métricas web). Conviene correrla contra `vite preview` o la web de pruebas, no contra `vite dev`; `E2E_LCP_MS` sube la línea en una máquina lenta, y el número queda en el informe en cualquier caso.

## Qué no cambia

Nada que vea el lector ni ningún dato: es solo vigilancia.

## Para la puerta de cierre (A16)

Antes del cierre se corren los tres proyectos (`a11y`, `perf` y `motion`) contra la web de pruebas; lo que falle se arregla o se explica en el informe.

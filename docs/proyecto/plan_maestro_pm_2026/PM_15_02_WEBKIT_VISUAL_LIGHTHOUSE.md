# PM-15-02 · WebKit, regresión visual y Lighthouse móvil de las pantallas nuevas

Plan Maestro PM, bloque 15 (CI-022). Medido el 24-nov-2026 en un entorno **local** (PostgreSQL 16, API y web de `main` más UX-231),
con los interruptores de las piezas nuevas encendidos solo allí; el mismo mundo sembrado que PM-14-11
(`PM_14_11_TRAZABILIDAD_LAMINAS.md`). Producción no se tocó: sus interruptores siguen apagados hasta PM-15-03.

## Lo que queda en el repositorio

- `web/e2e/pmscreens.spec.ts`: las pantallas de las láminas I01 a I12 a 390 px, cada una sin error de consola, sin llamada fallida
  a la API, sin desplazamiento horizontal y con la pieza de su lámina dibujada (embudo en I01, nota única en I04 D, tablas en I07…);
  una captura de página completa por lámina en la carpeta de resultados.
- `web/playwright.config.ts`: proyectos `pm-screens` (Chromium, Pixel 7) y `pm-screens-webkit` (WebKit, iPhone 13), solo con
  `E2E_PM_SCREENS=1`, como los demás proyectos que piden una pila con datos (`screens`, `perf`, `motion`).

Uso, contra una pila de QA o local con los interruptores del plan encendidos:

```
E2E_PM_SCREENS=1 E2E_PM_IDS='{"match_a":…,"match_b":…,"match_c":…,"match_d":…,"match_next":…,"team":…,"player":…,"keeper":…,"competition":…}' \
  bunx playwright test --project=pm-screens --project=pm-screens-webkit
```

**Por qué no entra en el CI de cada PR**: el CI de la web (`web.yml`) no levanta la pila (API, base con datos y cuentas de QA) que
estas pantallas necesitan, y ninguna de las pruebas de navegador del repositorio corre hoy en el CI. Lo que el CI sí tiene ya lo
cubre la parte sin navegador: PM-15-01 (CI-021) dibuja la pantalla con las respuestas reales de C-16 en `bun test`. Llevar estas
pruebas al CI pide un trabajo con PostgreSQL, migraciones, siembra, cuentas y los dos navegadores (unos 10-15 min por PR de web):
queda propuesto, no hecho.

## Resultados

**WebKit** (Playwright WebKit 27.2, 390 px, perfil iPhone 13): 14 de 14 pantallas en verde; las mismas 14 en Chromium. Antes de
UX-231 la página de competición se desplazaba 287 px en horizontal en los dos motores y, en WebKit, la etiqueta «Cupo internacional»
partía los nombres de los equipos a mitad de palabra.

**Regresión visual**: dos pasadas seguidas de las 21 capturas (12 láminas a sus tamaños) sobre los mismos datos: 0 píxeles distintos
(umbral 24/255). Las capturas son la referencia para comparar una ola con la siguiente sobre el mismo mundo sembrado.

**Lighthouse 12.8 móvil** (simulación de móvil lento por defecto, build de producción servida en local con un proxy de un solo
origen, sesión de lector). Accesibilidad y buenas prácticas: **100 en las siete páginas**. El rendimiento es de un contenedor
compartido y no se compara con producción (PM-14-05 midió allí LCP 6-7 s sin sesión); lo que sí vale es el CLS:

| Página (lámina) | Rendimiento | CLS | Qué se mueve |
| --- | --- | --- | --- |
| `/competitions/$id` (I07) | 27 → 44 | 0,773 → 0,233 | la tabla del proveedor al llegar las calculadas: **corregido en UX-231**; queda el pie de página común |
| `/matches/$id` Estadísticas (I01) | 20 | 0,567 | el panel de Estadísticas entero (lo de encima cambia de alto al cargar); no es de una pieza nueva: seguimiento |
| `/players/$id` (I06) | 29 | 0,704 | la tabla «Temporada» baja cuando llega la plantilla por puesto (C-13), y el pie: seguimiento (gráficas de jugador) |
| `/teams/$id` (I05) | 46 | 0,161 | pie de página |
| `/competitions` (I08) | 46 | 0,207 | pie de página |
| `/matches/$id` Resumen (I09) | 43 | 0,057 | — |
| `/matches/$id` Estadísticas, nivel D (I04) | 43 | 0,026 | — |

Sin fallos graves por pantalla (criterio de la ficha): ninguna pantalla nueva da error, se sale de ancho o falla en WebKit; los
tres desplazamientos de diseño grandes quedan uno corregido y dos anotados como seguimiento.

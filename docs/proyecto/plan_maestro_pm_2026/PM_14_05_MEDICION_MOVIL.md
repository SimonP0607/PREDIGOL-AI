# PM-14-05 · Rapidez en móvil: lo medido y lo que se cambió (FE-007)

Plan Maestro PM, tarea PM-14-05 (OP-44). Regla de la tarea: medir primero y cambiar solo lo que la medición pida. Medido el 21-nov-2026 entre las 03:18 y las 03:50 UTC, en solo lectura.

## Cómo se midió

- **Producción** (`https://predigolai.com`): Lighthouse 12.6.1, perfil móvil (red 4G lenta simulada, CPU ×4), Chromium 1243 sin interfaz. Solo las páginas que se abren sin cuenta: `/login`, `/forgot-password`, `/legal/terms`. Las pantallas con sesión no se midieron: hacerlo exige una cuenta y no se usó ninguna.
- **Laboratorio** (la misma versión de `main`, `d77613f`, compilada como en el servidor, `NITRO_PRESET=node-server`): Playwright con CPU ×4 y pantalla de 412 × 823; la API sustituida por respuestas fijas (`/auth/me` → 401; el texto legal, el que sirve producción, con 600 ms de espera). Sirve para comparar antes y después en las mismas condiciones; sus tiempos absolutos no son los de producción (sin HTTP/2 ni compresión).
- **Campo**: el INP real lo envía `web/src/lib/perf/vitals.ts` (3 % de las visitas) a Sentry. La lectura del percentil 75 se hace en el panel de Sentry del dueño; desde aquí no hay acceso.

## Antes

| Página (producción, móvil) | Puntuación | FCP | LCP | TBT | CLS | Peso |
|---|---|---|---|---|---|---|
| `/login` (3 pasadas) | 0,49–0,51 | 1,2–1,3 s | 6,9 s | 1,3–1,7 s | 0,001 | 1.152 KB |
| `/forgot-password` (2) | 0,52–0,60 | 1,2–1,3 s | 6,3–6,8 s | 0,7–1,1 s | 0,05–0,08 | 1.150 KB |
| `/legal/terms` (2) | 0,52 | 1,1–1,3 s | 6,2–6,5 s | 0,9–1,0 s | **0,125** | 1.081 KB |

- **INP** (laboratorio, `/login`, 3 pasadas de 27–31 interacciones: tocar, escribir correo y contraseña, botones): máximo 112–120 ms, p98 88–104 ms. **Dentro de «bueno» (≤ 200 ms).**
- **LCP** malo (> 4 s) en las tres. En `/login` el 77 % es «retraso de carga» (5,3 s): el servidor solo pinta el logo de espera (`Splash`) y la pantalla aparece cuando el JS de arranque (640 KB comprimidos; 1,15 MB en total) ha llegado y corrido; el logo grande se pide entonces. `index-*.js` corre 1,0 s en el arranque.
- **CLS** de `/legal/terms` en 0,125 («necesita mejora»): el pie de página se veía bajo tres líneas de esqueleto y el texto, al llegar, lo empujaba.
- Las imágenes de `/brand/` salen sin `Cache-Control` (solo `ETag`): se revalidan en cada visita.

## Qué se probó y no se cambió

- **Precargar el logo del inicio de sesión** (`<link rel="preload" as="image">` en la ruta `/login`): laboratorio, 5 + 5 pasadas: LCP mediano 14,1 s con precarga frente a 14,0 s sin ella. No mejora (la pantalla espera al JS, no a la imagen), así que no se hace.
- **Precarga por intención** (`defaultPreload: "intent"`): la ficha la propone, pero la navegación con sesión no se pudo medir; sin medición no se cambia (y precargar de más carga la API).
- **Avisos declarativos de WebKit**: no hay WebKit en este contenedor; queda para la prueba en un iPhone real.

## Qué se cambió (FE-007)

- `web/src/product/legal/LegalPage.tsx`: el esqueleto de un texto legal guarda la altura de una pantalla mientras carga. Laboratorio, `/legal/terms`: **CLS 0,126 → 0** (5 de 5 pasadas; antes, 0,126 en 8 de 8). Solo cambia el estado de carga; el texto cargado se ve igual. Sin interruptor: son páginas sin sesión, que no leen `/auth/me`.

## Plan de corrección (lo que la medición pide y no cabe en un cambio pequeño)

1. **LCP de las páginas sin sesión (6–7 s):** pintar en el servidor la pantalla de inicio de sesión y las legales en lugar del logo de espera, o sacarlas del arranque común. Es un cambio de arquitectura del `__root` (todo se pinta tras montar); necesita su propia tarea y la sesión de UX.
2. **JS de arranque (640 / 642 KB):** está al límite del presupuesto; el siguiente paso es sacar del arranque lo que solo usan pantallas con sesión.
3. **`Cache-Control` en `/brand/`:** cabecera en Caddy (zona de la sesión de seguridad); propuesta, no tocado.
4. **INP de campo:** leer en Sentry el p75 de la etiqueta `inp` de los eventos `web-vitals` (pendiente del dueño). Si supera 200 ms, medir esa pantalla con sesión antes de cambiar nada.

# Línea base UX · fase A0 (25 de octubre de 2026)

Plan maestro UX, fase **A0 · Línea base y protección**: congelar lo que hoy funciona y dejar en marcha las guardas que vigilan
la separación con PrediGol Intelligence durante toda la ejecución. Este documento guarda la evidencia. El inventario de rutas,
pantallas y datos personales de cliente está en `INVENTARIO_CLIENTE_A0.md`.

## 1. Lo que no cambia

- **PrediGol Intelligence, intacta.** Ni una línea de `models`, `features`, `predictions`, `backtesting` ni `domain`; la huella
  del código de modelos sigue siendo `mc9a7bec97ca` y la guardia (`model_code_guard.py`) corre en modo `stop` al empaquetar y
  otra vez en el servidor antes de desplegar.
- **Sin migraciones:** la base sigue en la `0093`.
- **El backend de producción no se toca** (`6851c0081d75`, F14). Sus pruebas nuevas viajan con la próxima publicación del
  backend; solo se publica la web, porque R02 (sección 5) es un cambio de dependencias de la web.
- **Lo que ve un usuario no cambia:** la actualización del framework no toca pantallas ni textos.

## 2. Las guardas nuevas

Todas corren en cada commit (`make check` en el backend, `bun run test` en la web) salvo la última, que corre en cada
despliegue. Cada una se probó rompiéndola a propósito: la guarda tiene que fallar con el cambio y pasar sin él.

| Guarda | Dónde | Qué protege | Cómo se comprobó que detecta |
| --- | --- | --- | --- |
| Instantáneas de forma | `backend/tests/unit/test_client_api_shapes.py`, `tests/snapshots/client_api_shapes.json`, `scripts/api_shapes.py` | Que `/home`, `/picks`, `/daily`, `/odds/best`, `/me/history` y `/matches/{id}/center` respondan con la misma forma (parámetros y esquema de la respuesta 200, con los 99 esquemas que usan). Un cambio querido se escribe con `python -m scripts.api_shapes write --reason "..."`, que guarda la fecha y la razón | Un campo quitado de un esquema y un parámetro nuevo salen nombrados por ruta |
| Importaciones prohibidas | `backend/tests/unit/test_user_layer_isolation.py` | Solo `fbi.api` importa la capa de usuario (`auth`, `userdata`, `customer`, `messaging`); ningún módulo de modelos, decisiones, picks o liquidación la importa; el analista de la consola (139 módulos) ni la alcanza ni nombra tablas de cliente; ninguna ruta de usuario importa el cliente de la IA, de Exa ni HTTP | Cuatro mutaciones: `fbi.auth` importado desde picks, SQL de `auth.users` en las herramientas del analista, `httpx` en el router de producto, la búsqueda del analista en el servicio de registros |
| Rutas de usuario sin llamadas externas | `backend/tests/integration/test_user_layer_guards.py` | Las 35 rutas GET que abre un USER, leídas del OpenAPI de la app (una ruta nueva queda cubierta el día que se añade), se llaman con todas las puertas de red cerradas: «analizar una vez y leer muchas» | Un `httpx` metido en `/home` hace fallar la prueba con la ruta que llamó |
| Vista en sombra | El mismo archivo | Las 12 rutas con `preview` niegan la vista en sombra a un USER (403) y ningún otro valor pasa; lo que lee sin `preview` es lo calificado | La comprobación de `preview` quitada de una ruta hace fallar la prueba |
| Marca `integration` | `backend/tests/integration/conftest.py`, `tests/unit/test_integration_marker.py` | Toda prueba de `tests/integration` necesita PostgreSQL y lleva la marca: `pytest -m "not integration"` ya separa de verdad (antes 147 de 219 archivos no la llevaban) | Sin el gancho, la prueba de la marca falla |
| R02, versiones del framework | `web/src/lib/frameworkAdvisories.test.ts` | Cada copia de `@tanstack/react-start`, `@tanstack/start-server-core`, `seroval` y `zod` que resuelve `bun.lock` está en la versión corregida o después | Contra el `bun.lock` que producción construía hasta hoy, sus cuatro comprobaciones fallan |
| R02, ruta de funciones de servidor | `web/e2e/serverfn.spec.ts` (proyecto `anon`) y el paso de humo del servidor | Un enlace a `/_serverFn/` abierto como página nunca devuelve como HTML lo que trae la petición (sin exploit: la marca es una negrita) | Es un testigo: la garantía es el suelo de versiones |
| Verificación tras desplegar | `day_digest.sh`, `step_verify.sh`, `post_deploy_reads.sh` (plantillas de despliegue del proyecto) | Picks y decisiones del día escritos antes del despliegue, idénticos antes y después (mismo corte); huella `mc9a7bec97ca`; la libreta de promociones | Se valida en cada despliegue (sección 9) |

`test_db_roles.py` (el worker no lee `auth` ni `customer`; la API no escribe en modelos, decisiones ni picks del sistema) ya
existía y pasa en la línea base.

## 3. Puertas en verde

| Árbol | Backend: ruff, mypy estricto, mypy del árbol, pytest | Web: lint, typecheck, bun test, build |
| --- | --- | --- |
| Producción hoy (`b0f693e`, F14) | Todo en verde; pytest 5.096 en verde y 4 omitidas | 0 errores (26 avisos, los de siempre), typecheck, 670 pass, build |
| A0 | Ver la sección 9 (la puerta corre sobre el árbol que incluye este documento) | 0 errores (26 avisos), typecheck, 676 pass, build |

## 4. Pruebas de extremo a extremo

Sobre la pila local de QA: la API y la web de esta rama, una base `fbi_qa` migrada a la `0093` **sin datos de fútbol** y las
cuentas de QA (SUPER_ADMIN, dos USER en español e inglés, y las de preferencias y de seguridad).

- **Línea base del código de producción:** 85 en verde, 6 omitidas y 2 fallos de carga que pasan solos al repetirlos (el primer
  inicio de sesión tras arrancar el servidor de desarrollo y la prueba de doble factor, que pasó de 60 s con la máquina a carga
  15 sobre 2 CPU). Las 6 omitidas lo dicen ellas mismas: 4 de la PWA necesitan la compilación de producción y 2 necesitan
  partidos que la base de QA no tiene.
- **Una primera pasada se descartó:** el servidor web de QA arrancó sin `VITE_API_BASE_URL` y la app cayó a su adaptador de
  demostración (`src/lib/api/mode.ts`): la Consola mostró los andamios de sus módulos y 8 pruebas del admin fallaron. Era mi
  configuración, no el producto; la cabecera de `playwright.config.ts` ahora lo advierte.
- **Tras A0:** 94 en verde, 0 fallos y las mismas 6 omitidas (anon 9 con la sonda de R02, user-es 16, user-en 16, admin 11,
  security 1, prefs 1, mobile 29 y mobile-webkit 6, más los 5 inicios de sesión; 2 workers, 15,2 minutos). El proyecto nuevo
  **WebKit** (el motor de todos los navegadores del iPhone) pasa sus 6 pruebas de teléfono a 320, 390 y 430 px.
- **Procedimiento de QA que queda:** web en modo live, servidor calentado antes de la pasada, 2 workers en esta máquina de 2 CPU,
  y la API de QA reiniciada entre pasadas completas seguidas (el freno de inicios de sesión vive en memoria: 30 fallos de un
  mismo cliente en 15 minutos y el siguiente inicio de sesión recibe 429, como debe).

## 5. R02 cerrado en la web

| Paquete | Antes | Ahora | Aviso |
| --- | --- | --- | --- |
| `@tanstack/react-start` | 1.168.32 | 1.168.61 | GHSA-qx66-fv34-fjm8 (XSS reflejado sin autenticación en respuestas de funciones de servidor; crítico) |
| `@tanstack/start-server-core` | 1.169.17 | 1.169.40 | El mismo |
| `seroval` y `seroval-plugins` | 1.5.6 | 1.6.9 | GHSA-p6vx-979v-rg4c y GHSA-jp82-f5mq-hwhp |
| `zod` | 3.25.76 y tres copias de 4.4.3 | 4.6.6 en todas | GHSA-mrhx-c7xc-m3w5 |

Se eligieron versiones publicadas hace al menos dos semanas (10 y 11 de octubre). Tres paquetes de compilación de Babel quedan
fijados en versiones de mayo, julio y septiembre porque el rango nuevo traía uno publicado hace dos días; se sueltan en la
próxima actualización de dependencias (plan de seguridad, S11). La imagen se construye con bun 1.3.13: con esa versión, la
instalación congelada (`--frozen-lockfile`) y la compilación pasan sobre el `bun.lock` nuevo. Lo único que cambió en el código
es el tipo del componente de error raíz. Quedan para el plan de seguridad (S11) los avisos de las herramientas de desarrollo
(vite, launch-editor, shell-quote, source-map-js), que corren al compilar y no llegan a la imagen que sirve la web.

## 6. Accesibilidad, medición inicial

axe-core 4.13 contra WCAG 2.2 A y AA, en la página de entrada y los ocho destinos del producto, a 1440 y a 390 px
(`E2E_A11Y=1 bunx playwright test --project=a11y`). Mide y no falla: es la línea base que las fases siguientes comparan.

| Página | Reglas incumplidas (elementos) |
| --- | --- |
| `/login`, `/home`, `/matches`, `/live`, `/picks`, `/parlays`, `/odds`, `/my-picks` | 0 en los dos anchos |
| `/profile` | 3 en los dos anchos: `aria-required-parent` (crítica, 120), `listitem` (seria, 120) y `aria-required-children` (crítica, 2) |

Los tres hallazgos son la misma pieza: la lista de zonas horarias del perfil (`src/product/profile/ProfilePage.tsx`), un `ul`
con rol `listbox` cuyos `li` no llevan rol propio, de modo que las opciones (`button role="option"`) quedan fuera del `listbox`;
un `role="presentation"` en cada `li` lo resuelve. Se corrige en la fase que toque el perfil. axe no pudo decidir el contraste
de 113 elementos de esa página (fondos con degradado): queda como revisión manual. Ojo: sin datos de fútbol, las páginas se
midieron en su estado vacío.

## 7. Capturas de referencia

Las ocho pantallas del producto a 320, 360, 390, 412 y 430 px, página completa, en `screenshots/ux-a0/` (40 imágenes al ancho
CSS; `E2E_SCREENS=1 bunx playwright test --project=screens` las rehace a tamaño real). Son de la base de QA, así que muestran
los estados vacíos. En una captura de página completa la barra de pestañas fija aparece a media altura: es cómo Playwright
compone la imagen, no el diseño.

## 8. Copia y restauración medidas (nivel 4 de marcha atrás)

| | Valor |
| --- | --- |
| Copia etiquetada | `predigol-20261025T022147Z-ux-a0.dump`, 1.369.631.395 bytes, 506 s, sha256 `5aa11c50040a170e…`, revisión `0093` |
| Restauración en una base desechable | `restore-test PASSED in 868s` (14 min 28 s) |
| De principio a fin | 23 min 29 s (02:21:47 → 02:45:16 UTC) |
| Volúmenes huérfanos | 5 antes y 5 después: la prueba no dejó ninguno (los 5 son los de R06, limpieza L1 del plan de seguridad) |

Conteos de la copia restaurada frente a producción leídos a las 02:48 (solo lectura):

| Tabla | Restaurada | Producción | Diferencia |
| --- | --- | --- | --- |
| `core.fixtures` | 246.018 | 246.018 | 0 |
| `market.historical_odds` | 345.964 | 345.964 | 0 |
| `auth.users` | 8 | 8 | 0 |
| `picks.picks` | 197.679 | 197.772 | 93 = los picks creados después de la copia |
| `picks.pick_results` | 197.679 | 197.772 | 93, los mismos |
| `raw.ingestion_payloads` | 189.886 | 190.007 | 121 = los recibidos después de la copia |
| `core.fixture_results`, `core.fixture_events`, `core.fixture_live_states` | 230.853 · 3.224.500 · 204.119 | 230.859 · 3.224.551 · 204.435 | Lo que siguió entrando en esos 26 minutos |
| `market.odds_snapshots`, `market.final_prematch_odds`, `market.market_consensus` | 4.026.534 · 760.506 · 3.182.304 | 4.027.580 · 764.327 · 3.183.096 | Ídem |

**Referencia para el nivel 4:** restaurar la base completa lleva unos 15 minutos de `pg_restore`, más el arranque de los
servicios. La copia solo existe en el servidor mientras R01 siga abierto: el gate G13 exige además la copia cifrada fuera y una
restauración desde ella (P13, plan de seguridad).

## 9. Despliegue y verificación en producción

Se completa tras la publicación (paquete `ux-a0`, solo la web) con la puerta del backend sobre el árbol final, el humo, la
verificación y la sonda desde Internet.

## 10. Gate

- **G1 · Estabilidad:** la evidencia empieza aquí y se repite en cada despliegue: huella `mc9a7bec97ca`, instantáneas de forma,
  pruebas de aislamiento y picks y decisiones del día idénticos antes y después.
- **G13 · Backup:** preparado. La restauración está medida (868 s) y con conteos; falta la copia cifrada fuera del servidor y
  su restauración (R01, P13), que dependen del plan de seguridad.

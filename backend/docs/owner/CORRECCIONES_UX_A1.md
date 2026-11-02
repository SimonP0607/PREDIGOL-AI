# Correcciones críticas UX · fase A1 (25 de octubre de 2026)

Fase A1 del plan maestro UX (`claude/PLAN_MAESTRO_UX_PREDIGOL.md`): los 13 defectos de la sección 6 que la
auditoría demostró, cada uno con su prueba de regresión escrita antes del arreglo. Rama `ux/a1` del monorepo, sobre
lo que corre producción: el backend de F14 (`6851c0081d75`, cortado de `4e9cc3c`) y la web de A0 (`5b74f8948ebb`,
cortada de `fd15772`). Antes de empaquetar, `ux/a1` incorporó la rama `sec/s1` del plan de seguridad (*merge*
`801e8df`): la regla de Caddy de R02, que ese plan aplica la noche del 25-oct como un lanzamiento solo de Caddy
(`refs/release/backend-sec-s1` = `8ba309f4c7e4`); el backend de A1 se construye sobre él.

## 1. Lo que no cambia

- **PrediGol Intelligence:** ni una línea en `models`, `features`, `predictions`, `backtesting` ni `domain`; huella
  del código de modelos `mc9a7bec97ca`, guardia en modo `stop`: UNCHANGED. Las pruebas de aislamiento de A0
  (`test_user_layer_isolation.py`, `test_user_layer_guards.py`) siguen en verde: la capa de usuario consume la
  inteligencia y no la altera.
- **Picks, liquidación, histórico y RAW:** solo lectura. El despliegue compara los picks y las decisiones del día
  antes y después con el mismo corte (sección 9).
- **Servicios externos y coste:** ninguno; coste 0.

## 2. Los 13 defectos y sus pruebas de regresión

| ID | Defecto | Corrección | Pruebas de regresión |
| --- | --- | --- | --- |
| F05 | La sesión de usuario caducaba a las 168 h aunque se usara | Sesión deslizante: 7 días desde el último uso, 30 como máximo; el administrador conserva 24 h / 8 h hasta el plan de seguridad (R14). `/auth/me` dice cuánto puede quedar sin uso | `test_auth_sessions.py` (8): en uso sobrevive al tope viejo; 7 días sin uso termina; 6 días sin uso sigue y se renueva; termina a los 30 días; la cookie vive lo que la sesión; el administrador conserva sus plazos; una sesión muerta por inactividad no se lista ni se cuenta; la cuenta sabe cuánto dura sin uso. e2e `admin.spec.ts`: «su sesión corta» |
| F01 · R12 | El bloqueo siempre decía «60 s» y el fallo que bloquea respondía 401 | 429 con la espera real (`Retry-After`), en minutos en la pantalla, **igual con o sin cuenta** | `test_auth_lockout.py` (10), `test_auth_lock_order.py` (4), `test_auth_units.py` (regla y espera), `wait.test.ts` (2), e2e `auth.spec.ts`: «el fallo que bloquea dice la espera real… una dirección sin cuenta se bloquea igual» |
| F53 | Borrar un pick, un parlay o tu cuota no pedía confirmación | Diálogo de confirmación y «Deshacer» de 5 s en el slip | e2e `user.spec.ts` (Mis picks y Mi parlay, con confirmación), `responsive.spec.ts` («Mis picks con un pick abierto, su confirmación…»), `model.test.ts` (`undoOf`, `UNDO_MS`) |
| F53 | «Todo» se recortaba a 500 picks y 200 parlays | Total real y cursor en `/me/picks` y `/me/parlays`; el resumen lee todas las páginas | `test_records_paging.py` (6), `recapData.test.ts`, e2e «Una cifra» |
| F54 | «ROI» y «Rentabilidad» con fórmulas distintas | Una sola cifra, «Rentabilidad (ROI)», con la fórmula del backend sobre la ventana del servidor | e2e `user.spec.ts`: «Una cifra: a 30 días y en todo, la ganancia y el rendimiento del resumen son los de Mis resultados»; `recapData.test.ts` |
| F05 | Un fallo al cargar sesiones se veía como una lista vacía | `ErrorState` con referencia y reintento; cerrar las otras sesiones pregunta antes | `States.test.tsx` (3), e2e «Seguridad del perfil: un fallo al leer las sesiones o la actividad lo dice, con la referencia y un reintento» |
| F16 | Las ayudas no se abrían dentro de las tarjetas | `InfoTip` fuera del enlace; `tapHint` con `[data-hint]` (toque, ratón o teclado) | `tapHint.test.ts`, e2e `responsive.spec.ts`: «la ayuda de una cifra se abre con un toque dentro del enlace de una tarjeta, y ese toque no abre el partido» |
| F16 | Jerga interna en pantallas de cliente | Textos claros y una prueba que veta los términos | `vetoed.test.ts` (3, incluida la que demuestra que habría cazado los textos viejos) |
| F07 | El rol «USER» se veía en la cabecera y el perfil | Oculto; el administrador ve «Administrador». De paso, la lista de zonas horarias del perfil es un `listbox` dueño de sus opciones (los tres hallazgos de axe de la línea base de A0, que A0 dejó para «la fase que toque el perfil») | e2e `user.spec.ts` (perfil y menú sin «USER»; la lista sin elementos que no sean envoltorios), `admin.spec.ts` («Administrator, never an internal role name») |
| F65 | El backend perdía el detalle de los errores | `_contain` registra tipo, resumen sin valores y marcos, tras el filtro de datos personales | `test_contain_trace.py` (12) |
| F08 · F09 | Traducciones incompletas (`lang`, `<head>`, página de error, selector, «pp», zonas y países) | ES y EN completos; `lang`, título y descripción desde el servidor según el navegador; zonas y países en palabras | `negotiate.test.ts`, `error-page.test.ts`, `codes.test.ts`, `time.test.ts`, e2e `auth.spec.ts` («servido en el idioma del lector»), `test_match_lifecycle_e2e.py` (código de país) |
| F33 | Objetivos táctiles de 32 px y aviso de actualización que tapaba la barra | 44 px; el aviso flota por encima de la barra y del botón del parlay | e2e `responsive.spec.ts`: 44 px a los cinco anchos con un pick abierto y los mercados de un partido; «el aviso de actualización flota por encima…» |
| F48 | Todo pick publicado decía «Recomendado» | «Recomendado · revisión de contexto aún no aplicada» mientras la IA siga en sombra (los cuatro estados llegan en B3) | `verdict.test.tsx` (2), `intelligence.test.ts`, `ForecastBlock.test.tsx` |

El defecto 14 de la tabla (filtro de auditoría de la consola) es de B10.

## 3. Desviaciones del plan

- **Una migración, la `0094`** (el plan decía «ninguna»). La segunda revisión mostró que la racha de una dirección,
  leída del registro de auditoría sin un índice propio, costaba treinta días del registro entero en cada intento, un
  coste que un atacante podía hacer crecer. `0094` añade un índice parcial `auth.audit_events (email, at DESC)` para
  las cinco acciones de una racha: aditiva, sin columnas ni filas, reversible (`DROP INDEX`). Por eso A1 sigue el
  flujo completo **BACKUP → RESTORE TEST → MIGRATION → VALIDATION → DEPLOY**. Las migraciones de las fases
  siguientes se numeran desde la `0095` (el plan, sección 44, lo prevé).
- **R12 en la base de datos.** El bloqueo por dirección vive en el registro de auditoría que comparten los dos
  procesos de la API (y los reinicios), no en la memoria de cada proceso (primera revisión).
- **El administrador conserva sus plazos de sesión** (24 h / 8 h) hasta que el plan de seguridad los acorte (R14).

## 4. Tres revisiones independientes y lo que cambiaron

| Revisión | Hallazgos | Arreglo |
| --- | --- | --- |
| Primera | El bloqueo por dirección vivía en la memoria de cada proceso: con dos procesos, una dirección con cuenta se bloqueaba al 5.º fallo y una sin cuenta al 9.º (el oráculo que R12 prohíbe), y un reinicio lo olvidaba; el desbloqueo del dueño no lo terminaba; datos personales que aún llegaban al registro; una página vacía tras la última decía que no había picks | La racha en la base de datos (`b6cf568`); resumen y marcos sin mensajes (`142d72f`); el motivo de la página vacía depende del total real (`8e57847`) |
| Segunda | Treinta días del registro entero en cada intento; cada rechazo de una dirección bloqueada escribía una fila; dos fallos simultáneos leían una racha vieja; un bloqueo guardado en la fila sobrevivía a la racha; primeras líneas que citaban valores | Migración `0094`, ventana del cliente primero, ningún rechazo escribe, candado consultivo por dirección, el bloqueo de la cuenta es el de la racha (`09bb9ed`); resúmenes estructurados de validación y base de datos (`9fb5c61`) |
| Tercera | **Interbloqueo**: un código de segundo factor erróneo bloqueaba las filas antes de pedir el candado de la dirección; con un inicio de sesión en curso, PostgreSQL abortaba el código (500) y el fallo no contaba, de modo que con la contraseña se podían probar códigos sin que el bloqueo llegara nunca. El desbloqueo y el restablecimiento no tomaban el candado. La segunda mitad de la racha leía el mes entero de la cuenta. La ventana por cliente nunca olvidaba un cliente. Valores entre comillas en mensajes de errores comunes | El candado de la dirección, siempre primero (`e3fd10e`); desbloqueos y restablecimientos con su dirección; la ventana por cliente olvida (`bafe3d9`); valores citados fuera, mensaje cortado antes del filtro y un resumen que falla nunca escapa (`eb1a6cc`) |

Cada arreglo tiene su prueba, y cada prueba nueva **falla sin el arreglo**: comprobado volviendo el código fuente a su
estado anterior con las pruebas nuevas (10 fallos en la tercera revisión).

## 5. Riesgos residuales aceptados

- **Sesiones de 3 a 7 días sin uso al desplegar:** con la regla vieja (72 h sin uso) estaban muertas; con la nueva
  (7 días) vuelven a valer hasta su caducidad original, como mucho 7 días después del inicio de sesión. La cookie de
  ese navegador las conserva; ninguna dura más de lo que duraba con la regla vieja desde su inicio.
- **Mis picks se pagina por la hora del partido:** un aplazamiento en mitad de la paginación puede saltar o repetir
  un elemento en esa lectura.
- **La ventana por cliente (30 fallos / 15 min) es de cada proceso:** con dos procesos, hasta 60. Es una defensa
  gruesa; el bloqueo por dirección, el que importa, está en la base de datos.
- **El registro de auditoría crece con los fallos** (cinco por dirección inventada antes del bloqueo); la retención
  y la limitación por prefijo de red son del plan de seguridad.
- **La migración `0094` construye el índice dentro de su transacción** (bloquea las escrituras del registro durante
  la construcción): la tabla es pequeña y el despliegue va en la ventana tranquila; `lock_timeout` de 10 s.

## 6. Puertas en verde

Hoja de puertas del paquete (`write_gates_ux.py`, escrita de los registros, sobre los árboles que se empaquetan: `backend/`
`0b0e8ac2954c`, `web/` `e80869fcbd14`; commit `24f5553`):

| Puerta | Resultado |
| --- | --- |
| `ruff check .` | sin avisos |
| mypy estricto, sin caché | 452 archivos, sin problemas |
| mypy de todo el árbol, sin caché | 1.070 archivos, sin problemas |
| pytest | **5.181 pasan, 4 omitidas**, 0 fallan (553 s); las pruebas del `Caddyfile` de `sec/s1` corren con el binario de Caddy 2.11.7 de producción (comprobado su sha512 contra la lista de la publicación) |
| web | lint 0 errores (26 avisos, los de siempre), tipos sin errores, **706 pruebas pasan**, 0 fallan, build de producción correcto |

## 7. Extremo a extremo, capturas y accesibilidad

- **e2e (stack de QA con datos de fútbol sintéticos y la base migrada a la `0094`, dos trabajadores), sobre `web/`
  `e80869fcbd14`:** **110 pasan, 0 fallan, 4 omitidas** (las de PWA, que piden el build de producción) en 22,6 min:
  anónimo 11, usuario en español 18, usuario en inglés 18, administrador 13, seguridad 1, preferencias 2, móvil 35,
  WebKit 7 y los 5 inicios de sesión. Corridas anteriores, para el registro: sobre `2a5e5675` (antes del arreglo de la
  lista de zonas) 110 pasan; la primera de la mañana dio 109 y 1 fallo en la primera prueba de la corrida (el título de
  `/login` tardó más de 15 s porque el servidor de desarrollo acababa de arrancar y compilaba; la captura del fallo ya lo
  muestra); desde entonces se calienta el servidor antes de correr.
- **Capturas a 320 y 390 px:** las ocho pantallas del producto a los dos anchos, página completa, ahora **con datos**
  (la base de QA tiene partidos, precios, picks liquidados y parlays sintéticos), en `screenshots/ux-a1/` (16 imágenes
  al ancho CSS). Las de 360, 412 y 430 px quedan en el stack de QA (`qa/run/screens-a1`).
- **Accesibilidad (axe-core 4.13, WCAG 2.2 A y AA, medida, no puerta):** **0 reglas incumplidas en las 18 mediciones**
  (la entrada y los ocho destinos, a 1440 y a 390 px). En la línea base de A0 había 3 en `/profile` (los dos anchos),
  las de la lista de zonas horarias, que A1 corrige. axe no pudo decidir el contraste de algunos elementos sobre fondos
  con degradado (de 2 a 108 por página, la mayoría en `/profile` y `/my-picks`): queda como revisión manual.

## 8. Lanzamiento

- **Ventana:** prevista la del **26-oct, 19:55–23:00 UTC** (la del 25-oct era del plan de seguridad, S1.a: un despliegue
  por ventana entre los planes). **El dueño pidió el 26-oct ≈01:00 UTC desplegarla ya**, con la cola de seguridad
  terminada y sin otro plan en producción: el paquete se reempaquetó con su palabra para **01:45–06:00 UTC** (mismos
  commits y bundles; solo la ventana y la carpeta, `WINDOW_OVERRIDE`), y la del 26-oct por la tarde quedó libre.
- **Paquete** (se construye una sola vez, después de S1.a): backend sobre `refs/release/backend-sec-s1`
  (`8ba309f4c7e4`, fuente `a362c7b`), web sobre `refs/release/web-ux-a0` (`5b74f8948ebb`, fuente `fd15772`), migración
  nueva `0094`, revisión de antes `0093`, guarda del código de los modelos en modo `stop`, tres comprobaciones de la
  migración dentro de `RELEASE.json` que `step_verify.sh` ejecuta en solo lectura (el índice existe, válido y listo; su
  definición exacta; el conjunto de índices de `auth.audit_events`).
- **Flujo:** comprobación previa de solo lectura (con el tamaño de `auth.audit_events` y las sesiones vivas) → **copia
  verificada y prueba de restauración** → vigilancia de candados (incluye `auth.audit_events` y `auth.sessions`) →
  `deploy_with_retries.sh` (`QUIET_GAP=60`; `predigolctl deploy` hace su copia previa, construye, aplica la `0094`,
  los permisos y reinicia) → humo (incluye `<html lang>` en es y en en) → verificación de solo lectura → lecturas
  posteriores. Aviso al dueño antes de cada paso que toca producción.
- **Marcha atrás:** `git checkout --detach` a `8ba309f4c7e4` (backend) y `5b74f8948ebb` (web) y `predigolctl deploy`.
  El índice de la `0094` puede quedarse (el código anterior no lo lee); quitarlo es `alembic downgrade 0093` (solo
  `DROP INDEX`).

## 9. Despliegue y verificación en producción

**Desplegada el 26-oct-2026; producción quedó en backend `ea157be10d24` y web `3c4c9b1a4e0f`, migración `0094`, a las
02:11 UTC.** Carpeta del servidor `/root/releases/20261026T0145Z-ux-a1/` (paquete sha256 `04f942ea…21ed`; el de la
ventana original, `b6a34c4a…7e07b08`, no se subió). Para que ningún paso dependiera de que el portátil del dueño estuviera
libre, los pasos del paquete corrieron encadenados en el servidor (`uxa1_chain.sh`, desacoplado con `systemd-run`), en su
orden y deteniéndose en el primer fallo, sin marcha atrás automática; aviso al dueño antes de cada paso.

| Paso | Hora (UTC) | Resultado |
| --- | --- | --- |
| Coordinación (solo lectura) | 01:05 | Candados `deploy`, `restore-test`, `backup` y `pitr` libres; ningún despliegue, copia ni restauración en marcha; checkouts `8ba309f4c7e4` y `5b74f8948ebb` sin cambios; revisión `0093`; 76 GB libres; cinco contenedores sanos |
| Comprobación previa | 01:05 | Todo OK salvo la hora (ventana aún sin abrir) y el servidor no tranquilo (`fixtures_sync` de las 01:03): las dos esperadas. Código de modelos `mc9a7bec97ca`; Sentry apagado; 615 filas en `auth.audit_events` |
| Copia y prueba de restauración | 01:07–01:37 | `predigol-20261026T010705Z-ux-a1`, 1.443.731.351 bytes en 712 s, revisión 0093; restauración **superada** en 1.027 s en un contenedor desechable (13 recuentos de tablas dentro de rango) |
| Despliegue | 01:45–02:11 | Intentos 1–7 rechazados por la escritura larga del `fixtures_sync` (nada se movió); el 8.º, a las 01:57, entró: guarda **UNCHANGED** (`mc9a7bec97ca`), corte de picks y decisiones 01:58:41, imágenes construidas, copia previa de `predigolctl deploy`, `0094` aplicada y reinicio; salud del despliegue OK (captura en vivo a los 15 s, 6 partidos en juego, 0 errores de servidor en 5 min) |
| Humo | 02:11 | **SMOKE OK**: salud, login 200, HSTS, 401 sin sesión, `/docs` 404, la sonda de R02 no vuelve como HTML (403), `<html lang>` es y en |
| Verificación | 02:11 | **Todas las líneas OK**: checkouts y revisión `0094`; `pip freeze` igual a `constraints.txt` en API y worker; huella `mc9a7bec97ca` y 0 filas escritas con otro código; **picks y decisiones del día idénticos** antes y después (10.035 y 2.333 al corte 01:58:41); el índice de la `0094` existe, es exactamente el descrito y `auth.audit_events` tiene sus cuatro índices; las 2 sesiones vivas antes lo siguen, ninguna revocada; los pronósticos siguen; 0 líneas de error en API y web desde el arranque |
| Lecturas posteriores | 02:11 | Libro de promociones: «1 de 2» (como desde el 24-oct) |
| Humo externo (desde fuera, `E2E_PROD_SMOKE=1`, sin la prueba del túnel de A2) | 02:14 | **5 de 5** contra `https://predigolai.com` |
| Gitleaks de las publicaciones | 02:15 | `scan.sh range` `backend-sec-s1..backend-ux-a1` y `web-ux-a0..web-ux-a1`: **0 hallazgos** |

**Copia del código** en el portátil del dueño: `fbi_scratch\release_ux_a1\monorepo_ux-a1_code_backup_after_release.bundle`
(sha256 `4d45c398…9f0a57`, comprobado allí; 57 referencias: las ramas `ux/a1`…`ux/a9`, `sec/*` y todas las de publicación).

**Visto de paso, ajeno a A1:** el trabajo `reference_refresh` acaba «aborted» cada media hora desde el 25-oct a las 22:01
UTC, cuatro horas antes de este despliegue (las corridas de las 20:31, 21:01 y 21:31 terminaron bien); queda anotado
para el plan de Intelligence, sin tocarlo.

## 10. Gate

- **G5 · Sesión que se renueva:** aportado (F05).
- **G9 · Lenguaje claro:** aportado (F16, F48, F07, F08, F09; prueba de términos vetados).
- **G11 · 44 px:** aportado (F33, comprobado a 320, 360, 390, 412 y 430 px).

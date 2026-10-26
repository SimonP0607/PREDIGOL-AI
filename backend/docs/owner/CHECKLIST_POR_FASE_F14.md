# Lista de cierre por fase (F14)

*Escrito el 24 de octubre de 2026. Es la lista que pide el plan para F14: «checklist por fase firmado en el documento de despliegue».
Vive aquí (`backend/docs/owner/CHECKLIST_POR_FASE_F14.md`, con una prueba que la mantiene entera: `tests/unit/test_phase_checklist.py`) y
se copia en `claude/PLANTILLAS_DESPLIEGUE_GUARDADO.md` del Proyecto. Es solo documentación: no cambia ningún modelo, pronóstico, precio
ni pick, no necesita migración, no hace peticiones al proveedor y no usa IA.*

## 1. Qué firma esta lista

El plan dice que **ninguna fase llega a producción sin pruebas, copia de seguridad, auditoría de fuga y tu aprobación para publicar**, y
que F14 se da por terminada cuando cada fase tiene su lista firmada. Son nueve comprobaciones (abajo). De cada fase se anota lo que
**consta** (✔ con el dato), lo que **no aplica** y por qué (n/a) y lo que **no se anotó entonces** (—).

Un «—» no quiere decir que fallara: quiere decir que nadie lo apuntó en su momento. Esta lista nace el 24 de octubre, después de F13, así
que para F0 a F10 solo recoge lo que consta en las guías de cada fase, en los registros de sus puertas y en los registros del servidor; no
se ha rellenado nada de memoria. **Desde F14 una fase no se da por cerrada con un «—» a no ser que diga por qué.**

Un lanzamiento armado y todavía sin desplegar tiene su fila, pero lo que solo existe después (la puerta sobre el árbol exacto del paquete, el reinicio, la copia,
el despliegue) dice «pendiente: …» y lo que espera; se rellena con el dato real al desplegar, como se hizo con F14. **Solo la última fila puede estar pendiente**
(una prueba lo exige) y una celda pendiente nunca se da por buena: es la lista de lo que falta para firmar.

Las dos firmas: **Ejecutor** es quien hizo y comprobó la fase (Claude, con el árbol y los lanzamientos que se citan); **Dueño** es la
aprobación para que se vea o cambie una decisión. Mientras no firmes, todo sigue en SHADOW: ninguna de estas fases decide, ni se muestra
a los usuarios (salvo lo que se dice en la sección 5).

## 2. Las nueve comprobaciones: qué cuenta como hecho

| # | Comprobación | Qué cuenta como hecho | Cómo se prueba |
|---|---|---|---|
| 1 | Pruebas | `ruff`, `mypy` estricto, `mypy` de todo el árbol (siempre con la caché vacía), `pytest` completo (unitarias y de integración contra PostgreSQL real) y, si hay web, `lint`, `typecheck`, `bun test` y el build; un test de regresión por cada defecto; **0 fallos sobre el árbol exacto que se empaqueta** | `ruff check .` · `mypy --cache-dir=/dev/null` · `mypy --cache-dir=/dev/null .` · `pytest` · `bun run lint && bun run typecheck && bun test` |
| 2 | e2e | La batería de Playwright pasa contra el stack de QA con datos (la migración vigente), en español e inglés, con administrador y usuario, en móvil de 320 y 390 px y en tabletas; más una revisión en móvil | `bun run test:e2e` |
| 3 | Fuga | Cada lector previo al partido que se añade tiene su regla en la auditoría nocturna (`leak-audit`) o una prueba de aislamiento que falla si algo previo al partido lee la tabla nueva; probado con mutaciones (se rompe la puerta a propósito y la prueba lo ve) | `fbi/intel/leakage.py` · `tests/unit/test_*_isolation.py` |
| 4 | Idempotencia | Repetir la carga, el constructor o la pasada no cambia nada: mismo contenido, mismo hash, ninguna fila nueva | el propio constructor / auditoría de la fase |
| 5 | Reinicio del worker | El despliegue reinicia el worker; después está vivo, programa sus trabajos y captura en vivo; la corrida que se cortó se cierra y se rehace; sin errores del servidor en 5 minutos | la salud que lanza `predigolctl deploy` |
| 6 | Restauración | **Antes de cada migración:** copia verificada y prueba de restauración superada, con las mismas cuentas de filas que producción | `step_backup.sh` (plantillas de despliegue) |
| 7 | Despliegue | `predigolctl deploy` (con su copia previa), comprobación de calma, vigilancia de bloqueos, prueba de humo y verificación de solo lectura, **avisándote antes de cada paso que toca producción** | `step_deploy.sh` · `step_smoke.sh` · `step_verify.sh` |
| 8 | Shadow ≥ 2 semanas | Todo cambio que altere una decisión corre al menos dos semanas en SHADOW antes de promoverse; hasta entonces nada decide ni se muestra | los interruptores `FBI_*_USERS` y la fila de promoción |
| 9 | Dueño | Tu aprobación para lo que ven los usuarios o cambia una decisión (el plan se aprobó el 22-oct; cada cosa que se enciende para usuarios es una decisión aparte) | «Decisiones que son tuyas» del estado |

## 3. Registro por fase (A): pruebas, e2e, fuga, idempotencia

Cada fila es un lanzamiento (varias fases salieron juntas). Fechas en UTC.

| Fase | 1 Pruebas | 2 e2e | 3 Fuga | 4 Idempotencia |
|---|---|---|---|---|
| F0 + F1 | ✔ 2.800 pasan (4 omitidas); mypy 367 archivos; web: lint, tipos, 314 pruebas y build; una prueba de regresión por cada uno de los 12 defectos | — | — | ✔ la reliquidación (D5): una segunda pasada no encuentra nada |
| F0.1 | ✔ 2.836 pasan (4 omitidas); ruff y mypy limpios | — | — | — |
| F2 | ✔ 3.094 pasan (4 omitidas); mypy 377 archivos y 827 del árbol; web 339 pruebas y build | — | ✔ `leak-audit-v2`, regla `tie_legs_known` | ✔ 0 deriva: cada agregado vuelto a sumar en SQL coincide (246.017 de 246.017 partidos con etapa, 21.353 cruces) |
| F3 + F1.1 | ✔ 3.427 pasan (con F3.1: 3.468); mypy 393 y 872; web 355 pruebas y build | — | ✔ `leak-audit-v3`, tres reglas (`referee_known`, `national_known`, `absences_known`) probadas con mutaciones | ✔ el pase de jugadores es idempotente y lo reconstruye; todas las invariantes a 0 |
| F3.2 + F5 | ✔ 3.552 pasan; mypy 398 y 888; web 393 pruebas y build | — | ✔ `leak-audit-v4`, regla `forecast_known`, y `test_forecast_isolation.py` (nada que decida lee el pronóstico) | — |
| F4 | ✔ 3.660 pasan; mypy 406 y 909; web 421 pruebas y build | — | ✔ `leak-audit-v5`, regla `calendar_known` (19 pruebas, con paquetes escritos a mano que leen el futuro y deben ser violaciones) y `test_calendar_isolation.py` | — |
| F6 | ✔ 3.974 pasan; mypy 412 y 937; web 465 pruebas y build | — | ✔ `leak-audit-v6`, cuatro reglas (`h2h_known`, `scenarios_known`, `tactics_known`, `factors_known`) y `test_context_isolation.py` | — |
| F7 | ✔ 4.277 pasan; mypy 421 y 961; web 537 pruebas y build | — | ✔ `test_knowledge_isolation.py`: ningún lector previo al partido lee Match Knowledge | ✔ reconstrucción idempotente: mismo contenido, mismo hash (0 diferencias en 38.121) |
| F8 | ✔ 4.464 pasan; mypy 426 y 983 (también con caché vacía); web 556 pruebas y build | — | ✔ `test_postmortem_isolation.py` (6 de 6 puertas rotas a propósito, detectadas); `leak-audit-v6` sin cambios | ✔ el constructor de la memoria es idempotente y la carga lo fue en producción |
| F9 | ✔ 4.517 pasan; mypy 429 y 991; web 589 pruebas y build | — | — | ✔ la matriz se guarda tras una auditoría independiente: 0 diferencias en 9.909 comparaciones |
| F10 | ✔ 4.642 pasan; mypy 442 y 1.021; web idéntica a la de F9 (sin cambios) | n/a (sin web) | ✔ `test_forecast_isolation.py` (solo los archivos declarados escriben o leen la tabla de pronósticos) y la huella del código de los modelos sin cambio (`mc9a7bec97ca`) | ✔ tras la primera pasada: un pronóstico por modelo y partido, todo `family-v1`, cada mercado suma 1 |
| F11 + F12 + F13 | ✔ 4.738 pasan; mypy 447 y 1.034; web 632 pruebas y build; lint 0 errores | ✔ 84 pruebas: 78 pasan, 4 omitidas (PWA, piden el build) y 2 caídas de Chromium por memoria compartida que se partieron en una prueba por ancho (12 pruebas, todas pasan); revisión en móvil a 320 y 390 px | n/a: sin tablas ni lectores nuevos (F11 es un módulo puro que nadie lee; F12 usa una tabla que ya existía) | ✔ `promotion_trace sync` repetido tras escribir la línea base: «nothing to write: every entry of the ledger is already in intel.promotions» (24-oct 05:06) |
| F14 (con F11.5 a F13.12) | ✔ 5.096 pasan (4 omitidas); mypy 452 y 1.057; web 670 pruebas, lint 0, tipos 0 y build; las puertas se anotaron sobre los árboles exactos que se empaquetaron (`backend/` `e6373c1013e1`, `web/` `2714c7160ef1`); la puerta completa encontró un fallo que las pruebas parciales no habían visto (`647186a`) | ✔ administrador 12 de 12 y móvil y tableta 6 de 6, sobre el mismo árbol de `web/` | ✔ `leak-audit-v6`, 17 reglas: `h2h_known` y `tactics_known` reescritas para leer un día entero en segundos con el mismo veredicto (una prueba compara las dos versiones sobre mundos al azar) y la relectura del trabajo posterior al partido ya no cuenta como lectura del futuro; las 17 leídas sobre todo el 23-oct de producción en 4 min 40 s: 251 de 32.520 en `forecast_known`, todas del mismo patrón (decisión 29), 0 en las otras 16; lo añadido en F11.5 a F12.7 y F13.9 a F13.12 es posterior al partido, de consola o de herramienta de lanzamiento: sin lectores previos al partido nuevos | n/a: ninguna carga, constructor ni paso nuevo escribe en producción (`promotion_trace show` y `hypotheses show` solo leen, `register` sin `--confirm` no escribe: registraría las 2 y no escribió nada; `register --confirm` espera tu palabra) |
| F11.7 a F11.12 (con F10.17) | ✔ 5.581 pasan (4 omitidas); mypy 462 y 1.090; web 761 pruebas, lint 0, tipos 0 y build; las puertas se anotaron sobre los árboles exactos que se empaquetaron (`backend/` `879a38c6ef3e`, `web/` `fa9a73007ed0`); cada módulo nuevo se probó con roturas hechas a mano y todas se detectaron (memoria de las familias 50 de 50, post-mortem 25 de 25, página de las familias 52 de 52, su guía 27 de 27, vista previa del partido 21 en el backend, 11 en las guías y 18 en la web, petición de investigación 69 en el backend y 52 en la web, vista previa de la pasada 114 de 114); la migración 0094 se subió, se bajó y se volvió a subir en una base de pruebas, con sus restricciones probadas en las 144 combinaciones de resultado, calidad y veredicto | ✔ administrador 13 de 13, anónimo 9 de 9, usuario en español 16 de 16 y en inglés 16 de 16, preferencias 2 de 2, seguridad 1 de 1 y móvil y tableta 29 de 29 (más los 5 inicios de sesión con que empieza cada una de las dos pasadas: 62 y 34 pruebas en total), 0 fallos, sobre el mismo árbol de `web/` y con la base de QA en la migración 0094; incluye la pestaña «Familias» de Aprendizaje y el detalle «Familias» de la vista previa del partido, que la batería de F14 no vio | ✔ `leak-audit-v7`, 19 reglas: a las 17 de `leak-audit-v6` se suman `family_forecast_known` (el pronóstico que cita cada decisión de una familia existe para ese partido, modelo, mercado, línea y selección, estaba escrito y con los datos cortados antes de la decisión y era el más nuevo de su modelo) y `family_price_known` (la casa que nombra había cotizado ese precio antes del partido y antes de la decisión): 32 pruebas, 19 variantes rotas a propósito y todas detectadas, y una prueba de escala de 5.000 decisiones de un día en 0,16 s; `consensus_known` lee solo la capa del pipeline y las demás reglas de decisiones leen las dos capas (`decision-v1` y `decision-fam-v1`); `test_decision_version_guard.py` obliga a todo lector de `intel.decisions` a decir qué capa lee, `test_postmortem_isolation.py` nombra las tablas nuevas y la migración 0094 (el post-mortem y la memoria de las familias solo se leen después del partido) y `test_forecast_isolation.py` cuenta el módulo de decisión entre los archivos que nombran la tabla de pronósticos; la sección «Familias» de la vista previa del partido (solo administrador, con los pronósticos conocidos en ese momento y la misma consulta del pronóstico del producto), la pestaña, la petición de investigación (no alimenta ninguna decisión: sus lecturas «al momento de» las sostienen pruebas de integración) y la vista previa de la pasada (la misma pasada con una conexión que no puede escribir) no añaden lectores previos al partido y no llevan regla nueva; las dos reglas nuevas no leen nada en producción mientras el interruptor siga apagado (allí no hay decisiones de familias): la medida a escala real es la primera auditoría nocturna tras encenderlo | ✔ una segunda pasada de las decisiones no escribe nada hasta que algo se mueve, ni siquiera un precio que se movió menos de lo que tolera la capa (3 %); la liquidación y el post-mortem no reescriben una fila y la memoria no escribe una noche sin evidencia nueva (pruebas de integración contra PostgreSQL); una pasada en seco (`python -m scripts.families decide`, con una conexión que no puede escribir) cuenta las filas que escribiría y no escribe ninguna, y tras una pasada real cuenta cero; en producción n/a hasta que enciendas el interruptor: con `FBI_FAMILY_DECISIONS` apagado ningún paso nuevo corre |

## 4. Registro por fase (B): worker, restauración, despliegue, shadow, dueño

| Fase | 5 Reinicio del worker | 6 Restauración | 7 Despliegue | 8 Shadow ≥ 2 sem. | 9 Dueño |
|---|---|---|---|---|---|
| F0 + F1 | ✔ salud tras el reinicio | ✔ copia verificada y prueba de restauración antes de 0077 y 0079–0081 (las cifras no constan en el estado) | ✔ 22-oct (`predigolctl deploy`, humo, salud) | n/a: la sede neutra queda APAGADA hasta que promuevas | plan aprobado 22-oct · abiertas: 1, 2 |
| F0.1 | ✔ salud tras el reinicio | n/a (sin migración) | ✔ 22-oct 14:17 | n/a: una corrección (un final imposible ya no se guarda, ni se liquida, ni se muestra) | plan aprobado · sin decisiones |
| F2 | ✔ salud tras el reinicio | ✔ 1,07 GB; superada en 604 s, las 12 cuentas de filas coinciden | ✔ 22-oct 16:41 (`cc4efa9aba71` / `0852a8d09069`), migración 0082; la historia entera en 319 s, 0 fallos | n/a: SHADOW, nada cambia un pick | plan aprobado · sin decisiones |
| F3 + F1.1 | ✔ salud tras el reinicio; **el primer pase programado de jugadores (23:14) falló limpiamente** → F3.1 | ✔ copia verificada y prueba de restauración (sin cifras en la guía) | ✔ 22-oct 22:50 (`be8050de78fd` / `e8d37dda5eb8`), migraciones 0083–0085; F3.1 a las 23:58 | n/a: SHADOW | abiertas: 7, 8, 9 |
| F3.2 + F5 | ✔ salud tras el reinicio | ✔ 01:23–01:42, superada, más la copia propia del despliegue | ✔ 23-oct 02:43 (`bbfec85e70d4` / `2f134b12be2a`), migración 0086; **el primer intento (01:42) se detuvo solo, sin daño**, por la espera de bloqueo | n/a: SHADOW; los usuarios no ven el pronóstico (`FBI_FORECAST_USERS` sin definir) | abiertas: 6 |
| F4 | ✔ salud tras el reinicio | ✔ 1.140.691.588 bytes en 429 s; superada en 619 s | ✔ 23-oct 03:48:45 (`2b6008641292` / `9db9fd620008`), migración 0087 | n/a: SHADOW; `FBI_CALENDAR_USERS` apagado | abiertas: 3, 4, 11 |
| F6 | ✔ salud tras el reinicio; el vigilante cerró la corrida que perdió su proceso y la siguiente la rehízo | ✔ 1.151.252.363 bytes en 407 s; superada en 653 s | ✔ 23-oct 08:09:15 (`51430f6b326a` / `29ba732b2358`), migración 0088, 9 min 7 s | **excepción:** el cara a cara que ven los usuarios ya cuenta los 90 minutos (no tuvo dos semanas en SHADOW; decisión 13) | abiertas: 12, 13 |
| F7 | ✔ salud tras el reinicio | ✔ 1.160.610.202 bytes en 502 s; superada en 804 s | ✔ 23-oct 14:13:15 (`db476d5bd534` / `b5136bc5f0c3`), migraciones 0089–0090, 12 min 50 s; carga de 400 días 100,00 % | n/a: SHADOW; `FBI_KNOWLEDGE_USERS` apagado | abiertas: 5, 14, 15 |
| F8 | ✔ salud tras el reinicio | ✔ 1.206.801.634 bytes en 468 s; superada en 737 s | ✔ 23-oct 16:41:56 (`b0ec26fd7386` / `8b88f950a07e`), migración 0091, 9 min 43 s | n/a: SHADOW | abiertas: 16, 17, 18 |
| F9 | ✔ salud tras el reinicio | ✔ 1,23 GB; superada en 751 s | ✔ 23-oct 20:23–20:34 (`5a7722b560c8` / `b2dfcf13ab74`), migración 0092, 10 min 31 s | n/a: SHADOW | sin decisiones |
| F10 | ✔ salud tras el reinicio; primera pasada de `family_forecasts` a los 37 min (04:13:00–04:23:40, 62.496 filas, 0 fallos) con las capturas en vivo a su ritmo | ✔ 1.253.105.280 bytes en 472 s; superada en 811 s | ✔ 24-oct 03:22:55–03:36:20 (`1df1ff3c7e1c`), migración 0093, 13 min 25 s | n/a: SHADOW; todo `family-v1` es UNCALIBRATED / `no_champion` y la página no lo lee | abiertas: 22 (mostrar pronósticos de familias) |
| F11 + F12 + F13 | ✔ API, worker y web sanos a los 44–48 s; la primera pasada de familias tras el reinicio mide otra vez la dispersión (≈ 10 min) | n/a (sin migración); copia previa propia de `predigolctl deploy`: 1.263.011.003 bytes en 500 s, revisión 0093 | ✔ 24-oct 04:46:04–04:56:37 (`7a7d010653a5` / `edf92b242b2b`), código de salida 0, 10 min 33 s; humo correcto; vigilancia de bloqueos sin esperas | n/a: SHADOW; ninguna familia tiene pick; F12 escribió una fila de línea base (promoción #120) | abiertas: 19, 20, 21, 23 |
| F14 (con F11.5 a F13.12) | ✔ API, worker y web sanos a los 14 s; primera pasada de `family_forecasts` tras el reinicio: empezó a las 20:53:49 UTC y quedó registrada a las 21:03:20 UTC (9 min 31 s, estado `completed`): 480 objetivos, 51 sin ajustar, 37.782 filas y 0 fallos, en las cuatro familias (goles por mitad 20.160, córners 8.544, tarjetas 3.738 y amarillas 5.340), todas con el código `6851c0081d75` y, en `models.predictions`, solo la huella `mc9a7bec97ca`; 0 errores en el worker y la API desde el reinicio | n/a (sin migración); copia previa verificada: 1.344.759.947 bytes en 599 s; restauración superada en 905 s, con las cuentas de filas iguales | ✔ 24-oct 20:02–20:17 UTC (`6851c0081d75` / `55366f6bab66`), código de salida 0, 14 min 52 s, a la primera: la comprobación de calma pasó en el intento 1 de 8; humo y verificación de solo lectura correctos; vigilancia de candados cada 3 s de las 20:02 a las 20:52 UTC, con el despliegue en medio (`lockwatch.log`, 1.371 líneas de candados): 0 en espera y 0 bloqueos; el `pip freeze` del worker y de la API contra `constraints.txt`: 0 diferencias | n/a: SHADOW; nada de lo añadido decide ni se muestra a los usuarios (la tarjeta «Código de los modelos» es solo de administrador) | abiertas: 10, 19, 21, 24, 25, 26, 27, 28, 29 |
| F11.7 a F11.12 (con F10.17) | pendiente: se anota al desplegar; con `FBI_FAMILY_DECISIONS` sin definir el worker no añade ningún paso a sus trabajos (son los de hoy), de modo que el reinicio solo carga el código nuevo | pendiente: lleva la migración 0094 (dos tablas y una vista, nuevas y vacías), así que antes va la copia verificada y la prueba de restauración (`step_backup.sh`), con las mismas cuentas de filas | pendiente: espera tu visto bueno, y te aviso antes de cada paso que toca producción | n/a: SHADOW y apagado por omisión; las decisiones de una familia nacen sin pick, con tope en `INVESTIGACION` y sin apuesta, y solo las ve un administrador | abiertas: 12, 22, 26 y la nueva 30 (¿encender `FBI_FAMILY_DECISIONS=shadow` cuando se despliegue la 0094?; recomiendo que sí, tras mirar `python -m scripts.families decide`) |

## 5. Excepciones y lo que salió mal (para no repetirlo)

* **F3 (22-oct):** el primer pase programado de jugadores falló limpiamente y no escribió nada: el proveedor mete una fila de relleno con el
  jugador «0» y la restricción de la tabla tumbó la transacción. Lo corrigió F3.1. Regla desde entonces: **la primera pasada programada de
  cada trabajo nuevo se mira antes de dar la fase por cerrada**.
* **F5 (23-oct 01:42):** la migración se rindió sola tras cinco intentos de 10 s porque `fixtures_sync` mantenía una transacción de unos
  27 minutos sobre `core.fixtures` (la liga 667, «Friendlies Clubs»). No hubo daño. Desde entonces: comprobación de calma antes de
  desplegar, `lockwatch` durante el despliegue y ventanas de despliegue fuera de las de `fixtures_sync` (01, 07, 13 y 19 UTC más ≈ 24–51 min).
* **F5 (23-oct):** un paso intermedio puso el escritor del pronóstico dentro de los paquetes de los modelos; la huella del código pasó de
  `mc9a7bec97ca` a `mce0abbbb30d` y se reescribieron 92.937 pronósticos bajo versiones nuevas. F4 lo sacó (`fbi.forecasting`). Desde
  entonces: `test_model_code_version` y, con F12, el registro de promociones. **Sigue en uso** (24-oct): 174 partidos conservan su última
  predicción de esa pasada; es la decisión 20.
* **F6 (23-oct):** el cara a cara que ven los usuarios cuenta los 90 minutos y enseña prórroga y penales. Es un cambio de lo que ve un
  usuario que salió sin las dos semanas de SHADOW; está como decisión 13 por si prefieres el recuento anterior.
* **F10:** dos errores míos de selección de tarjetas (exigir la roja informada y exigir que los eventos coincidan con las estadísticas)
  sesgaban la historia: el proveedor deja la roja VACÍA cuando no la hubo. Se corrigieron (F10.11) y F11 liquida con la regla de estadísticas.
* **F13:** pruebas largas de pantalla en una sola pestaña hacían caer Chromium (≈ 300 MB de memoria compartida por navegación completa
  hasta cerrar la pestaña). Se partieron en una prueba por ancho (F13.7/F13.8). El e2e encontró además un defecto de accesibilidad que ya
  existía: los ocho enlaces de partido del embudo de picks medían 224 × 20 px en tableta.

* **F14 (24-oct):** el paso nocturno de las 12:50 UTC se quedó 3 h 16 min dentro de la auditoría de fuga (`tactics_known`: para cada partido candidato preguntaba si estaba en una
  lista materializada del paquete, y el coste crecía con el cuadrado de los ≈ 11.000 paquetes del día) y hubo que cancelar esa consulta, con tu visto bueno; la auditoría del 23-oct no
  se escribió (decisión 29). Se arregló con una consulta lineal (`5abc7e9`), y una relectura del trabajo posterior al partido dejó de tomarse por lectura del futuro (`14e8e63`). Regla
  desde entonces: **una regla nueva de la auditoría se mide a escala de producción (un día entero de paquetes, en solo lectura) antes de empaquetarla**.
* **F14 (24-oct):** la comprobación de «servidor tranquilo» del plan no veía nada: el rol `fbi` no ve las sesiones de los demás roles en `pg_stat_activity`, así que habría dado luz
  verde con una corrida a medias. Ahora lee `pg_locks` (`quiet.sh`); con 20 s entre las dos lecturas se negó por un trabajo ordinario, y el lanzamiento usa `QUIET_GAP=60`. Regla desde
  entonces: **una comprobación se prueba contra la situación en la que debe negarse y se mide cuántas veces se niega sin motivo**.
* **F11.8 a F11.9 (24-oct):** el módulo de decisión de las familias nació dentro de `fbi.intel` e importaba `fbi.families`, y eso alargó en uno el mayor ciclo de
  importaciones (9 contra el tope de 8). Moverlo a `fbi.families` lo habría arreglado y habría roto algo peor: la versión del modelo de una familia es la huella de las
  fuentes de ese paquete, y un archivo de decisión allí renovaba la versión de todas las familias y el registro prospectivo empezaba de nuevo. Se creó `fbi.familydecisions`
  (solo lo importan el worker y los comandos del dueño; `test_decision_version_guard.py` lo sostiene) y la huella de los modelos no se movió. La suite unitaria
  completa llevaba además fallando desde F11.8 por una prueba de aislamiento (`test_forecast_isolation.py`: el módulo nombraba la tabla de pronósticos y no estaba en su
  lista) que las pruebas parciales no veían. Regla desde entonces: **el que mueve o añade un archivo pasa la suite completa antes de seguir, no solo la prueba del archivo**.
* **F11.9 (25-oct):** al subir la auditoría a v7, la prueba que liga el registro con el código obligaba a que el registro nombrara la versión vigente y se reescribió la fila de
  F14, que describía así un lanzamiento que no era el desplegado (v6, 17 reglas). Se devolvió a lo que se desplegó y la v7 va en la fila de su lanzamiento. Regla desde
  entonces: **la fila de un lanzamiento ya desplegado no se toca para satisfacer una prueba; lo nuevo va en la fila nueva**.

## 6. Lo que esta lista todavía no cubre

* **e2e por fase:** hasta F13 la batería nunca se había pasado entera sobre una base con datos; desde ahora se pasa en cada fase que toque la web.
* **Dependencias:** la imagen del backend se construía con cotas inferiores (`>=`), así que cada reconstrucción traía lo más nuevo de ese día
  (el 24-oct, seis librerías de producción eran más nuevas que las de las puertas). Desde F14.2 las 60 librerías están fijadas en
  `backend/constraints.txt` (guía `DEPENDENCIAS_F14.md`, con una prueba que mantiene el archivo, el Dockerfile y el entorno de la puerta de
  acuerdo); **entró en producción con el lanzamiento de la tarde del 24-oct** (el `pip freeze` del worker y de la API contra el archivo: 0 diferencias en las 60 librerías de `predigol-worker` y de `predigol-api`). Siguen sin fijar las imágenes base `python:3.12-slim` y `node:22-alpine`
  (decisión 24).
* **Copia de seguridad fuera del servidor:** no existe. El diario del servidor lo dice cada día (24-oct): la copia diaria, la del RAW y la
  recuperación a un punto en el tiempo (PITR) avisan de que no están configuradas, y las copias y las pruebas de restauración son todas del
  propio servidor. El código para activarlas ya está en `deploy/vps/bin` (`r2-setup.sh`, `pitr.sh`); falta el cubo de Cloudflare R2 y sus
  llaves, que son tuyos.
* **La huella del código de los modelos (decisión 19):** desde F12.7 existe la guarda `scripts/model_code_guard.py` (guía `PROMOCIONES_F12.md`): compara
  el código que subo con el que corre en producción y con el registro de promociones, y responde `UNCHANGED`, `COVERED` o `UNCOVERED`. Mis paquetes de
  lanzamiento la llaman al armar el paquete y otra vez en el servidor, antes de mover nada. Hoy está en modo `inform`: avisa y no detiene; si decides que
  se detenga (recomiendo que sí), la armo con `--mode stop`. No sustituye la prueba del registro ni mira las librerías (`DEPENDENCIAS_F14.md`).
* **Disco del servidor:** medido el 26-oct, la última semana creció ≈ 4,4 GB al día (≈ 4,0 del 24 al 26-oct), casi todo por los despliegues
  diarios; del 13 al 22-oct fueron ≈ 0,75. Si la cola de despliegues sigue así, el 90 % llega en unas dos semanas: conviene podar ya las imágenes
  viejas y la caché de construcción (≈ 21 GB, regenerable, no espera a R2). Qué lo llena y qué se puede quitar está en `DISCO_F14.md` y en
  el documento «ALMACENAMIENTO_PREDIGOL» del Proyecto: 54,2 GB son cinco volúmenes huérfanos que dejó un fallo ya corregido de la prueba de restauración. Quitarlos es
  tuyo (decisión 10) y espera a la copia fuera del servidor; no se ha borrado nada.

## 7. Plantilla para firmar una fase nueva

Copiar, rellenar con el dato real (no con «ok») y guardar en la sección «Resultado en producción» de la guía de la fase:

```
Fase: F__   Lanzamiento: backend ______ / web ______   Fecha (UTC): ____-__-__ __:__
1 Pruebas              ruff ✔ · mypy estricto ✔ (__ archivos) · mypy árbol ✔ (__) · pytest ____ pasan / 0 fallan · web lint/tipos/test/build ✔
2 e2e                  ____ pruebas: __ pasan, __ omitidas, 0 fallan · móvil 320/390 ✔      (n/a si no toca la web)
3 Fuga                 regla / prueba de aislamiento: ______________________ · probada con mutaciones ✔
4 Idempotencia         repetir ______ no cambia nada: ___ diferencias
5 Reinicio del worker  sano a los __ s tras reiniciar · primera pasada programada: ______ (fecha/hora, filas, fallos)
6 Restauración         copia ______ bytes en __ s · restauración superada en __ s · cuentas de filas iguales ✔      (n/a sin migración)
7 Despliegue           inicio–fin ______ · código de salida 0 · humo ✔ · verificación de solo lectura ✔ · bloqueos: sin esperas
8 Shadow               n/a (no cambia una decisión) | desde __/__ hasta __/__ (≥ 14 días)
9 Dueño                decisiones abiertas: __ · aprobada para usuarios: sí / no / pendiente
Ejecutor: __________   Dueño: __________
```

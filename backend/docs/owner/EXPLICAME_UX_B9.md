# B9 · Explícame: las preguntas frecuentes, contestadas con lo que PrediGol ya sabe

Un botón «Explícame» en un partido, en un pick y en el parlay que se está armando. Al tocarlo, una hoja ofrece las preguntas
que de verdad se hacen en ese lugar; al elegir una, contesta con frases escritas desde lo que PrediGol ya guarda: la lectura
estructurada del partido (A9), el pronóstico (F5), el estado y la explicación del pick (B3) y la comprobación del parlay. **No
llama a ninguna IA, no estima nada nuevo y no puede cambiar un pick.** Si falta un dato, lo dice («No tengo ese dato») y dice
cuál falta; nunca lo inventa.

## 1. Qué ve el cliente

| Lugar | Preguntas |
| --- | --- |
| Un partido (pestaña Análisis) | «¿Por qué no hay pick?», «¿Qué significa este pronóstico?» y «¿Qué puede salir mal?» |
| Un pick (Picks, el set del día) | «¿Qué puede salir mal?» y «¿Por qué cautela?» |
| El parlay (Mi parlay) | «¿Por qué baja la probabilidad de mi parlay?» |

- **Una hoja, como la de «¿Por qué este pick?»:** desde abajo en el teléfono y en pantallas estrechas, desde el costado en el
  escritorio; objetivos de 44 px; el foco vuelve al botón al cerrar.
- **Cada respuesta termina igual:** las palabras que vale la pena tocar (el glosario de A3), los sitios donde leer más
  («¿Por qué este pick?», «Cómo le va a PrediGol» solo cuando está abierta, el glosario), «¿Te sirvió?» (B6) y «Otra pregunta»,
  que abre «Reportar un problema» como sugerencia (A14) para que el cliente diga qué faltó.
- **«¿Por qué no hay pick?»** cuenta cuántas selecciones comparó PrediGol y por qué ninguna cumple sus reglas (la cuota no paga lo
  suficiente por lo que vale, una cuota fuera de rango, un mercado que aún no cubre…), o que todavía no hay pronóstico o cuotas
  recientes; y repite la regla: **PrediGol nunca inventa un pick para llenar el espacio**.
- **«¿Qué significa este pronóstico?»** dice qué es un pronóstico, el resultado más probable de cada mercado con todas sus
  probabilidades, si están calibradas («sin calibrar» se dice) y que un pronóstico no es un pick.
- **«¿Por qué cautela?»** dice el estado del pick con su motivo (la tabla única de B3): en cautela porque la revisión del
  contexto encontró riesgos; no en cautela porque la aprobó, porque todavía no se aplica o porque aún no hay revisión; no
  recomendado por falta de valor o por rechazo; en evaluación.
- **«¿Por qué baja la probabilidad de mi parlay?»** muestra cada selección con su probabilidad y de quién es («según PrediGol»
  o «según el mercado, sin margen»), la multiplicación, la dependencia entre selecciones si la hay y el aviso de «muy poco
  probable». Una selección sin probabilidad se dice como tal y no se calcula nada.
- Todo en español y en inglés. Ninguna frase promete («seguro», «fijo», «garantizado») ni dice cuánto apostar.

## 2. Línea base

Antes de B9 las dudas del cliente solo tenían la Ayuda (A14) y «¿Por qué este pick?» (B3). No había forma de preguntar por qué un
partido no tenía pick, qué significaba una probabilidad sin calibrar o por qué una combinada valía tan poco.

## 3. Lo que nunca cambia

- **PrediGol Intelligence no se toca.** Cada número de una respuesta ya estaba guardado o lo calcula la comprobación del parlay
  que el cliente ya usa; ninguna ruta nueva escribe en la base de datos ni lee la capa en sombra de un lector (el pick en sombra
  es un 404 para un lector; solo la vista previa del dueño lo ve).
- **Sin IA y sin gasto:** ninguna ruta de este módulo llama a un modelo de lenguaje ni a internet; una prueba lee el código y falla
  si lo hiciera, y otra la repite en ejecución (como las demás rutas de la capa de usuario).
- **Nada personal:** la analítica guarda solo qué pregunta se abrió (`match.no_pick`, `pick.caution`…, con `.missing` si faltaba
  el dato), nunca texto; el parlay se contesta sin guardarse.

## 4. Lo nuevo por dentro

- **Sin migración.** Todo es lectura.
- **`GET /api/v1/explain?entity=match|pick&id=&intent=`** y **`POST /api/v1/explain/parlay`**. Una pregunta que no es del lugar
  es un 422 (`unknown_question`); un partido o pick que no existe, 404; un cliente puede hacer **30 preguntas por minuto** (429 si
  las pasa). Las líneas de la respuesta son códigos estables con sus parámetros (`explain.say.<código>` en la web) o hechos de la
  lectura, que se escriben con la plantilla de la propia lectura; un código que la web no conoce se omite, nunca se muestra crudo.
- **`fbi/api/services/explain.py` (`explain-v1`)**: una función por pregunta, con las consultas de solo lectura; los motivos del
  estado de un pick salen de la tabla de `fbi/picks/user_status.py` (una prueba exige una frase para cada motivo, ni uno más).
- **`FBI_EXPLAIN`**: encendido mientras falte. `=0` quita los botones (`/auth/me` dice `explain: false`) y la API contesta 404
  `explain_off`; no hace falta desplegar.
- **Web:** `src/product/explain/` (las preguntas, la escritura de cada frase y la hoja), el botón en el análisis del partido, en
  las tarjetas de pick y en Mi parlay; `explain.json` en los dos idiomas.
- **«¿Te sirvió?»** guarda una respuesta por cliente y pregunta: el identificador es el del partido o pick por 8 más el número de la
  pregunta (`FeedbackSubject` `explain`).

## 5. Decisiones que tomé

- **Un registro de preguntas sin respuesta lo da «Otra pregunta»,** que abre una sugerencia; no guardo lo que el cliente escribe
  en la hoja porque no hay caja de texto: solo preguntas cerradas. El plan C1 (chat libre) tendrá así su evidencia en la analítica
  (cuántas veces se abre cada pregunta y cuántas sin dato) y en las sugerencias.
- **«¿Por qué cautela?» no inventa una causa** cuando la revisión de Intelligence sigue en sombra: dice «no está en cautela: se
  recomienda por el valor de su cuota, y la revisión del contexto todavía no cambia ningún estado» (la pregunta 6 del ensayo de
  A16 ya tiene respuesta).
- **El parlay se contesta con su propia comprobación,** no con una cuenta aparte: así la respuesta nunca contradice lo que muestra
  el armador.

## 6. Pruebas

- Backend: unitarias (cada frase que el servicio puede mandar tiene su plantilla en los dos idiomas; cada motivo de estado tiene
  su frase; la puerta), integración con base real (las tres preguntas de un partido con y sin pronóstico, con la lectura
  apagada y con la vista previa; las dos de un pick, el pick en sombra, el parlay con selecciones sin probabilidad y con
  dependencia; el límite; el interruptor) y las guardas de la capa de usuario (sin IA, sin escrituras).
- Web: la escritura de cada frase con sus plurales, lo que se omite, y que ninguna plantilla prometa ni diga cuánto apostar; la
  hoja con sus estados (con respuesta, sin dato, con y sin «Cómo le va a PrediGol»).
- e2e (`explain.spec.ts`, con la pila de los cuatro estados de B3): el botón en cada pick, las dos preguntas en el escritorio por
  teclado y con foco de vuelta, el teléfono de 320 px, el registro de `explain_opened` y la API (el pick en sombra, la pregunta
  que no es del lugar, el parlay).

## 7. Puertas

Puertas sobre el árbol integrado del PR #21 (`feat/UX-001`, 4-nov-2026), el que se desplegará:

- Backend: `ruff check .` limpio; `mypy` estricto (597 ficheros) y `mypy .` (1.492 ficheros) sin errores; pruebas unitarias **7.904 pasan, 16 omitidas**;
  migraciones 0095 a 0106 con una sola cabeza (0106, colgada de la 0119).
- Web: lint 0 errores (26 avisos que ya existían), tipos de la web y del e2e, **1.456 pruebas pasan, 0 fallan**, build.
- Seguridad: autoprueba de Gitleaks 41 de 41; escaneo de todo el historial limpio.
- CI del PR #21: Convenciones del PR, web, `ruff + mypy`, `scan` y secretos en verde; `pytest` con PostgreSQL 16 y la corrida de integración
  completa se anotan en el PR al terminar. El e2e de esta fase se repite sobre el árbol integrado antes del despliegue.

## 8. Despliegue

Backend y web juntos (el contrato cruza los dos), sin migración. **Vuelta atrás:** `FBI_EXPLAIN=0` en `app.env` (con su copia
fechada y, al final, `predigolctl config-baseline`); la web anterior funciona con este backend (la API es aditiva).

## 9. Acción manual

Ninguna.

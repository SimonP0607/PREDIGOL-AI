# Promociones del código de los modelos (F12)

*Escrito el 24 de octubre de 2026 (la consola y la guarda de lanzamiento, ese mismo día, después de las primeras líneas).
Código: `fbi/research/promotions.py` (el registro), `fbi/research/trace.py` (la medición), `python -m scripts.promotion_trace`, para la consola
`GET /api/v1/admin/evolution/code-promotions` con el panel `web/src/live/CodePromotionsPanel.tsx` y, para las entregas, `scripts/model_code_guard.py`.
Pruebas: `tests/unit/test_model_code_ledger.py`, `tests/unit/test_promotion_trace_cli.py`, `tests/unit/test_model_code_guard.py`,
`tests/integration/test_promotion_trace.py`, `tests/integration/test_evolution.py` y `web/src/live/CodePromotionsPanel.test.tsx`. Es solo código y
solo lectura: no cambia ningún modelo, pronóstico, precio ni pick, no necesita migración, no hace peticiones al proveedor y no usa IA.*

## Qué pide el plan y qué faltaba

La regla de F12 es que **nada cambie lo que PrediGol usa en producción sin una fila de promoción**: hipótesis, experimento, puerta y promoción.
Tres clases de cambio ya tenían su tabla: el *spec* de goles (`analytics.promoted_forecast_spec`, desde F0), los calibradores y la ventaja de
mercado (`intel.promotions`) y la regla de sede neutra (`analytics.neutral_rule_promotion`). Faltaba una: **el código de los modelos**.

Una versión de modelo se identifica por la huella de los paquetes que deciden lo que predice (`mc9a7bec97ca`, por ejemplo). Si una entrega toca
esos paquetes, nacen versiones nuevas de los tres modelos de goles y el pronóstico trabaja con ellas desde su pasada siguiente, sin que nadie lo
haya decidido ni quede escrito.

## Lo que se midió en producción (24-oct, entre las 00:50 y la 01:01 UTC, solo lectura)

* Desde el 5-oct (07:19 UTC), cuando las versiones pasaron a identificarse por la huella del código, produjeron en producción **seis huellas
  distintas**: `mc034f19d4a9` (5-oct, 11 minutos), `mcec6b780838` (5 al 9-oct), `mc1f28a88360` (9-oct 04:02, el corte del portátil al servidor),
  `mc118f6f26d7` (9-oct 13:31, una sola pasada), `mc9a7bec97ca` (22-oct 13:04, el código de F0, **la que está hoy**) y `mce0abbbb30d`
  (23-oct 02:45). Antes del 5-oct las versiones se identificaban por el commit del repositorio y hubo más de sesenta tandas de tres modelos.
* **Ninguna de esas huellas tiene fila de promoción.** Ninguna versión de modelo tiene estado distinto de «experimental».
* `mce0abbbb30d` no fue una decisión: un paso intermedio de F5 había puesto el escritor del pronóstico dentro de los paquetes de los modelos, y
  durante cerca de una hora del 23-oct los tres modelos corrieron como tres versiones nuevas (46.338 predicciones de Poisson, otras tantas de
  Dixon-Coles y 5.535 de Elo, entre las 02:45 y las 03:33). Se corrigió esa noche sacando el escritor de esos paquetes (`fbi/forecasting`), y la
  producción volvió a `mc9a7bec97ca`. Las cifras no cambian, porque la diferencia entre ambos códigos era dónde vive el escritor; pero esas tres
  versiones siguen presentes: 6.622 pronósticos guardados (para 631 partidos con Poisson, 600 con Elo y 31 con Dixon-Coles) y 2.859 decisiones,
  todos con el corte de datos de aquella pasada, porque para esos partidos no hay una predicción más reciente (medido a la 01:00 UTC).
* Sí tienen promoción las demás clases: el *spec* de goles (1 fila, sembrada por el sistema el 22-oct), los calibradores (100 pasos a
  CHALLENGER, 5 a CHAMPION y 3 a RETIRED en 30 días) y la ventaja de mercado (11 NOT_VALIDATED). La regla de sede neutra nunca se ha promovido.

## Lo que añade esta parte

1. **Un registro en el repositorio**, `fbi/research/promotions.py`: una entrada por huella, con quién decidió (`owner` o `system`), la fase, el
   motivo (al menos 40 caracteres) y en qué se apoyó (`hypothesis_id`, `experiment_ids`). La primera es la **línea base**: `mc9a7bec97ca`, el
   código que ya estaba en vigor, registrado después de los hechos y diciéndolo.
2. **Una prueba que falla** mientras la huella del código de los modelos no sea la última entrada del registro. Cambiar ese código obliga a
   añadir su entrada en el mismo commit; si el cambio no era intencionado, la prueba lo delata antes de que llegue a producción.
3. **`python -m scripts.promotion_trace show`**: lee (con una conexión que no puede escribir) qué huellas usó producción en los últimos
   30 días (predicciones del trabajador, pronósticos guardados y decisiones; lo que corre un backtest no cuenta), cuándo nació cada una y la
   promoción que la cubre. **`sync`** copia las entradas que falten a `intel.promotions` (entidad `model`, tabla que ya la admitía y es de solo
   añadir); sin `--confirm` solo dice qué escribiría, y rechaza una entrada que cite una hipótesis o un experimento que no existe.

Estados de cada huella: `BASELINE` (ya estaba en vigor cuando empezó el registro), `PROMOTED` (decisión anterior al primer uso),
`AFTER_USE` (decisión registrada pero posterior al primer uso), `PENDING_SYNC` (en el registro, aún no en la base), `UNTRACED` (sin decisión en
ningún sitio: lo que el plan dice que no debe pasar) y `PRE_LEDGER` (nació antes del registro: se lista y no se cuenta, porque el pasado no se
puede decidir después). El criterio del plan, «el 100 % de los cambios de los últimos 30 días con su promoción trazada», es
**trazadas / contadas**.

## En la consola: Evolución, «Código de los modelos»

Es la parte web de F12 y está al final de la página de **Evolución** (administración). Solo la ve una cuenta de administrador: para cualquier otra
cuenta la dirección responde 403. Lee lo mismo que `show`, con las mismas reglas, y no tiene ningún botón que escriba: el único botón,
«Actualizar», vuelve a preguntar.

* **Dirección:** `GET /api/v1/admin/evolution/code-promotions?days=30` (`days` entre 1 y 365; por defecto 30, la ventana del plan). Lee con la
  conexión de solo lectura de la API.
* **Tiempo:** la traza recorre un mes de predicciones y en producción tardó **4,2 segundos** (24-oct 07:00 UTC, 30 días, 7 huellas). La lectura de la
  API se corta a los diez segundos; esta petición se da **60 segundos** para que en frío nunca devuelva un 500, y la respuesta se guarda
  **cinco minutos** en el servidor. La página no se refresca sola: se pide al abrirla y al pulsar «Actualizar».
* **Cuatro cifras arriba:** «Cambios con promoción» (**1 de 2 · 50 %** en producción al desplegar F12: la línea base y el cambio accidental del
  23-oct), «Código que corre ahora» (la huella que lleva el código de este servidor, con la advertencia en ámbar si **no** es la que el registro
  tiene en vigor), «Huellas en la ventana» (cuántas hay y cuántas son anteriores al registro) y «Registro iniciado».
* **Una tarjeta por huella**, la más nueva primero: su estado, si **corre ahora**, cuándo apareció y cuándo se usó por última vez, cuántas
  versiones y de qué modelos, lo que produjo en la ventana (predicciones, pronósticos, decisiones) y la promoción que la cubre: quién la decidió,
  cuándo, el motivo y la evidencia (se despliega). Una huella sin promoción lo dice en rojo: «Ninguna decisión registrada cubre este código».
  Las anteriores al registro van aparte, plegadas, y no cuentan.
* **«Decisiones del registro»:** las entradas del `LEDGER` que lleva el código del servidor, la más nueva primero, cada una con dos marcas:
  si ya está **copiada a la base** (`intel.promotions`) y si producción la **usó** en la ventana. Una entrada nueva aparece «sin copiar» y
  «aún sin usar» hasta el siguiente `sync` y el siguiente pronóstico.
* **«Otras promociones en la ventana»:** calibradores, especificación de goles, ventaja sobre el mercado y regla de sede neutra, para contexto.

Lo que dice la consola de cada estado:

| Estado | Lo que dice la consola | Qué significa |
| --- | --- | --- |
| `BASELINE` | Base del registro | El código que ya estaba en vigor cuando empezó el registro; se anotó después de los hechos y así se dice. |
| `PROMOTED` | Promovido | Una decisión registrada, anterior al primer uso del código, lo cubre. |
| `AFTER_USE` | Decidido después | Hay una decisión registrada, pero con fecha posterior al primer uso del código. |
| `PENDING_SYNC` | Sin copiar a la base | Está en el registro del código, pero todavía no se copió a la base de datos. |
| `UNTRACED` | Sin promoción | Ninguna decisión lo cubre: es el cambio que el plan dice que no debe ocurrir. |
| `PRE_LEDGER` | Anterior al registro | Es anterior al registro: se lista y no cuenta. |

Un detalle de lectura: «Usado en los últimos 2 días» no quiere decir «en vigor». La marca «Corre ahora» es la del código que ejecuta el servidor;
la otra solo dice que esa huella produjo algo en los dos últimos días (la del 23-oct sigue produciendo decisiones porque 174 partidos conservan
su último pronóstico de aquella pasada).

## Qué se verá al desplegarlo y sincronizar

`mc9a7bec97ca` como `BASELINE`, `mce0abbbb30d` como `UNTRACED` y las anteriores como `PRE_LEDGER`: **1 de 2, el 50 %**. Es deliberado: la
huella del 23-oct es justo el cambio sin promoción que la medición debe mostrar. Seguirá dentro de la ventana de 30 días hasta el 22-nov; si
prefieres darla por explicada, es una decisión tuya (abajo).

## Cómo se usa cuando haya un cambio de código de modelo

1. Se cambia el código y la prueba falla con el mensaje de qué huella tiene ahora.
2. Se añade la entrada (motivo, hipótesis y experimentos si los hay) en el mismo commit.
3. Al armar el paquete, la guarda de lanzamiento (abajo) dice `COVERED` y te lo cuento antes de desplegar.
4. En la entrega: `python -m scripts.promotion_trace sync` (en seco) y luego `sync --confirm`; después `show`.

## La guarda de lanzamiento (F12.7)

La prueba `test_model_code_ledger` ya impide que el código de los modelos cambie sin una entrada en el registro, pero corre en mi puerta, sobre el
árbol que tengo delante, y no en el servidor. La guarda hace la misma pregunta con los dos árboles entre los que se mueve una entrega, el que corre
hoy en producción y el que lleva el paquete, en los dos puntos por donde pasa:

1. **Al armar el paquete:** compara el commit que corre hoy con el árbol que se empaqueta y anota el veredicto en `RELEASE.json`.
2. **En el servidor, antes de mover nada** (antes de cambiar de commit, de construir la imagen o de reiniciar un servicio): lo repite leyendo los dos
   commits del propio paquete, sin ponerlos en el árbol de trabajo.

Es una herramienta aparte, `scripts/model_code_guard.py`, que solo usa la biblioteca estándar de Python (necesita la 3.11.4 o una más nueva; la de un
Ubuntu 24.04, el sistema del servidor, es la 3.12), no toca la base de datos ni la red y no escribe nada: de un commit extrae `src/fbi` a una carpeta
temporal que borra. Lee cada árbol con **su propio** `version.py` y **su propio** registro, cargados por ruta, de modo que la respuesta es la que daría
el código que va a correr. Entra en mis guiones de entrega; no toca `predigolctl` ni tu `deploy/release.sh`.

Cada comparación termina en uno de tres veredictos:

| Veredicto | Cuándo | Qué hace |
| --- | --- | --- |
| `UNCHANGED` | La huella del árbol que llega es la que ya corre en producción. | Pasa siempre: la entrega no abre versiones nuevas de ningún modelo. |
| `COVERED` | La huella cambia y la **última** entrada del registro del árbol nuevo es ese código. | Pasa, con un aviso grande: quién lo decidió, cuándo y el motivo. |
| `UNCOVERED` | La huella cambia y no hay tal entrada: el registro termina en otro código, está vacío o el árbol no tiene registro. | Por omisión avisa y la entrega sigue; en modo `stop`, se detiene. |

Dos modos: `inform` (por omisión: se imprime el veredicto y la entrega sigue, y yo te lo cuento antes de desplegar) y `stop` (un `UNCOVERED` termina
con el código de salida `4`). El modo lo fijo al armar el paquete y queda escrito en él, para que el servidor lea el mismo que yo escribí. Códigos de
salida: `0` si la entrega sigue, `4` si se detiene (solo `stop` con `UNCOVERED`) y `2` si no pudo comprobar nada: un árbol que no se lee, un registro roto
o un `git` que no responde no son nunca luz verde, tampoco en `inform`.

**Probada con la historia real.** De las trece entregas del backend guardadas desde el 22-oct, la herramienta saca `mc9a7bec97ca` en doce y
`mce0abbbb30d` solo en la de F5 (23-oct 02:43), el cambio accidental de la sección anterior. Preguntando «F3.1 contra F5» en modo `stop`, responde
`UNCOVERED` y sale con 4: la guarda habría detenido aquella entrega. Contra el árbol de hoy, frente a lo que corre en producción, responde `UNCHANGED`.

Lo que **no** hace: no mira la base de datos (lo que cada huella produjo de verdad lo mide `python -m scripts.promotion_trace show` después de
desplegar); no sabe si la decisión de una entrada `COVERED` fue tuya, solo dice quién la anotó (`owner` o `system`) y cuándo, y por eso te cuento ese
veredicto antes de cada despliegue; no cubre lo que mueve los números sin tocar los paquetes de los modelos, como una librería nueva (para eso están las
versiones fijadas de `DEPENDENCIAS_F14.md`); y no sustituye la prueba del registro, que sigue en la puerta.

## Decisiones tuyas

* **¿Que mis paquetes de lanzamiento se detengan si la huella cambia y no hay entrada?** Hecho como herramienta (arriba) y puesto en modo `inform`: avisa
  y la entrega sigue. Lo recomiendo en `stop`, porque un cambio del código de los modelos sin entrada en el registro no debería llegar a producción sin
  que lo hayas visto; basta con que me lo digas y armo los paquetes con `--mode stop`. Si prefieres la misma guarda en tu `deploy/release.sh`, es una
  llamada a la misma herramienta; no lo he tocado.
* **¿Dar por explicada la huella del 23-oct como excepción documentada**, o dejarla contando hasta que salga de la ventana el 22-nov?
* **¿Mostrar estas promociones en la consola (Evolución)?** Hecho como lectura para administradores (arriba). Si prefieres no verlo ahí, basta
  con quitar una línea de `web/src/live/EvolutionLive.tsx`; la dirección y la medición no cambian.

## Lo que no hace

No promueve nada por su cuenta, no cambia un modelo ni un pronóstico, no avisa a nadie y no escribe en la base salvo `sync --confirm`. Lo que
sí hace es dejar medible el criterio de cierre de F12 y que cualquier cambio futuro del código de los modelos tenga que pasar por una decisión
escrita.

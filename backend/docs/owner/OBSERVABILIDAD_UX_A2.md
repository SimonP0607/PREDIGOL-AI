# Observabilidad UX · fase A2 (25 de octubre de 2026)

Fase A2 del plan maestro UX (`claude/PLAN_MAESTRO_UX_PREDIGOL.md`): ver cada error de la web, de la API y del
worker con un usuario seudónimo, la versión y el `request_id`, sin datos personales en un tercero, y un recorrido
sintético que cada 15 minutos hace lo que hace un lector. Rama `ux/a2` del monorepo, encima de `ux/a1` (A2 depende
de A1). Se despliega **después de A1 y de su verificación**, con los interruptores apagados: sin DSN no sale nada
hacia Sentry y sin la cuenta sintética el recorrido no corre. Se encienden con tu acción P1 (sección 6).

**Actualización del 27 de octubre:** el 26-oct a las 20:41 UTC la IA desplegó su lanzamiento `ia-p01` (backend
`c40e101b9a15`, web `6a0790f190bd`, Alembic **0113**) encima de A1, así que A2 se empaqueta ahora sobre lo que corre:
la rama **`ux/a2-ia`** es `ux/a2` con la fuente de la IA (`ia/rel-p01`, `40e311f0`) fusionada, sin conflictos. Nada de
lo que hace A2 cambia; cambian la base, la vuelta atrás (sección 7) y las puertas, repetidas sobre el árbol fusionado
(sección 8).

## 1. Lo que no cambia

- **PrediGol Intelligence:** ni una línea en `models`, `features`, `predictions`, `backtesting` ni `domain`; huella
  del código de modelos `mc9a7bec97ca`, guardia en modo `stop`. Las pruebas de aislamiento de A0 siguen en verde:
  la capa de usuario consume la inteligencia y no la altera.
- **Picks, liquidación, histórico y RAW:** no se tocan. El recorrido sintético solo lee; deja lo que deja la visita
  de cualquier lector: una sesión, cerrada al final, y las filas de auditoría del inicio de sesión (unas 190 al día).
- **Base de datos:** ninguna migración.
- **Coste:** 0. Sentry Developer es gratis (comprobado en sentry.io/pricing el 25-oct-2026: 5.000 errores al mes,
  1 usuario, 1 monitor de disponibilidad y 1 de tareas).

## 2. Qué hace A2

| Pieza | Qué hace | Dónde |
| --- | --- | --- |
| Errores del backend | Cada error inesperado de la API (el 500 que ve el cliente) y cada error que el worker registra llegan al proyecto *backend* de Sentry: tipo, un resumen del mensaje **sin valores**, los marcos de la traza **sin variables**, la ruta, la versión (`predigol-backend@<código>`), el `request_id` y el seudónimo de la cuenta | `fbi/core/sentry.py`, `api/app.py` (`_contain`), `core/logging.py` |
| Errores de la web | El navegador envía sus errores **a la propia API** (`/api/v1/monitoring/envelope`), nunca a Sentry: la dirección del lector no llega a un tercero, la política de seguridad de la página no gana orígenes y cada evento pasa el filtro dos veces (en el navegador y en el servidor). Llevan la ruta sin parámetros, la versión (`predigol-web@<código>`), el navegador, el ancho de pantalla, si es la app instalada o una pestaña, y el seudónimo | `web/src/lib/observability.ts`, `api/routers/monitoring.py` |
| Seudónimo | HMAC del id de la cuenta con la clave del servidor (20 caracteres hexadecimales). Es el mismo en la web y en la API, así que en Sentry ves que dos errores son de la misma persona, pero ni Sentry ni nadie puede volver al id ni al correo | `fbi/auth/crypto.py` (`observability_id`) |
| Referencia del error | El cliente ya veía «Referencia …» en la pantalla de error (A1). Ahora el evento de Sentry lleva ese mismo `request_id`: si un cliente te manda la referencia, la buscas en Sentry y ves el error exacto | `ErrorState`, `_contain` |
| Consola → Sistema | Panel «Recorrido sintético» (última vuelta, última vuelta completa, vueltas y fallidas en 24 h, el último paso fallido con su nombre) y panel «Pruebas de observabilidad» con dos botones: «Error de prueba en la API» (solo un SUPER_ADMIN puede provocarlo; responde 500 con su referencia) y «Error de prueba en la web» | `web/src/live/ObservabilityPanels.tsx` |
| Recorrido sintético | Cada 15 minutos el worker hace, por la puerta pública (Caddy, la web, la API y la base de datos juntas), lo que un lector: abre `/login`, inicia sesión con una cuenta dedicada, pide el inicio, los partidos de hoy, el centro de un partido, los picks y sus picks, y cierra la sesión. Como mucho 90 segundos; un paso que falla queda escrito con su estado y su error llega a Sentry | `fbi/ops/synthetic.py`, `apps/worker/scheduler.py`, `scripts/synthetic_journey.py` |
| `prod-smoke` | Comprobaciones de solo lectura de un sitio desplegado, sin cuenta: idioma de la página, salud, producto cerrado sin sesión, adónde informa el navegador, cabeceras de seguridad | `web/e2e/prod-smoke.spec.ts` |

## 3. Lo que nunca sale hacia Sentry, y cómo está probado

Nunca: correos, contraseñas, tokens, cookies, cuerpos de las peticiones, parámetros de las URL, la IP, cabeceras
(salvo el nombre del navegador), variables locales, consultas SQL, líneas de consola, lo que una persona escribe o
pulsa, los picks privados ni valores citados en los mensajes de error. Tampoco salen sesiones ni recuentos de uso
(*release health*), las cabeceras `baggage` / `sentry-trace` hacia terceros (API-Football, Anthropic, Telegram…) ni
informes internos del SDK: a Sentry solo llegan errores.

| Prueba | Qué demuestra |
| --- | --- |
| `test_sentry_filter.py` (13) | Un evento cargado de datos falsos (correo, token, cookie, nombre, IP, consulta SQL, variables) sale sin ninguno; ids de traza y marcos legibles; el tope de eventos del backend |
| `test_monitoring_tunnel.py` (11) | El túnel solo reenvía errores (nunca adjuntos, *replays*, sesiones ni comentarios), solo al proyecto web, filtrados; rechaza lo ilegible, lo de más de 100 KB, lo cruzado entre sitios y lo que pasa de los topes; el DSN real del proyecto web nunca llega al navegador |
| `test_synthetic_walk.py` (9) y `test_synthetic_journey.py` (3) | Los pasos en orden, el fallo con nombre, la sesión siempre cerrada (también si faltaba un paso del inicio de sesión) y el tope de 90 s; la contraseña nunca en un registro |
| `test_observability.py` (4) y `test_contain_trace.py` | El error de prueba del dueño llega con su `request_id`, la versión y el seudónimo; un 500 inesperado, igual |
| `observability.test.ts` (9) | El filtro del navegador: correos, tokens, valores citados y parámetros fuera; caracteres nunca cortados por la mitad; sin sesiones, consola ni clics |
| e2e `observability.spec.ts` (2) | Contra un Sentry de pega local: los dos errores de prueba de la consola llegan (el de la API con la referencia que muestra la consola, el de la web por el túnel y con el mismo seudónimo), solo llegan errores (ni sesiones ni informes del SDK), y el correo, la contraseña y la cookie de la sesión no aparecen en nada de lo recibido; un error con un correo y un token en el mensaje llega como `<email>` y `<token>` |

## 4. El mes gratis no se puede gastar desde fuera

El plan gratis da **5.000 errores al mes para toda la organización** (los dos proyectos juntos), y los límites por
clave de Sentry son solo de los planes Business y Enterprise. Por eso los topes están en PrediGol:

| Origen | Tope | Máximo al día |
| --- | --- | --- |
| Backend (2 procesos de la API y el worker) | El mismo error una vez por hora y 25 eventos al día por proceso (el error de prueba del dueño llega cada vez que se pulsa, dentro de esos 25) | 75 |
| Web (por el túnel, en cada proceso de la API) | 20 por minuto y cliente; 10 por hora y 20 al día por proceso | 40 |
| **Total** | | **115 al día ≈ 3.450 al mes** |

Y el DSN del proyecto web **no sale del servidor**: el navegador arranca con un DSN sustituto y la API reenvía con el
real. Nadie puede usar tu proyecto web para gastar el mes rodeando el túnel. Los topes de la web se ajustan con
`FBI_MONITORING_RATE_LIMIT`, `FBI_MONITORING_HOURLY_CAP` y `FBI_MONITORING_DAILY_CAP` (no hace falta tocarlos).

## 5. Pruebas y revisión

- **Puertas:** backend (ruff, mypy estricto y del árbol entero, pytest completo) y web (lint, tipos, 715 pruebas y
  build de producción) en verde sobre el árbol final; e2e completo con Sentry encendido contra el Sentry de pega.
  Cifras exactas en la sección 8.
- **Revisión independiente:** 1 bloqueante, 3 importantes y 5 menores, todos arreglados con su prueba:
  - Bloqueante: los errores del backend no tenían tope propio (un fallo en bucle tras un despliegue podía gastar el
    mes en un día). Ahora: tope por error y por día en `before_send`.
  - Importantes: el tope del túnel se cobraba antes de leer el envío (la basura bloqueaba a los navegadores reales);
    las peticiones del backend a terceros llevaban la clave pública del proyecto en `baggage`; el recorrido dejaba
    abierta la sesión cuando faltaba un paso del inicio de sesión.
  - Menores: un JSON demasiado profundo daba 500; medio emoji rompía el reenvío; las URL de los marcos conservaban
    sus parámetros; informes internos del SDK; una etiqueta `code` que el filtro tomaba por secreta.
- **Después de la revisión:** comprobado en la documentación de Sentry que el plan gratis no limita por clave; de ahí
  que el DSN del proyecto web no salga del servidor (sección 4).
- **Lo que encontró el e2e con Sentry encendido:** el SDK del backend enviaba las sesiones de cada petición
  (*release health*): apagado; el error de prueba del dueño pulsado dos veces en una hora no llegaba la segunda:
  ahora llega cada vez; y la prueba de integración buscaba el id de la cuenta como texto (falso positivo con un id
  de una cifra): ahora por clave y valor exactos. En QA los topes del túnel se suben (el e2e provoca decenas de
  errores del navegador a propósito); en producción quedan los de la sección 4.

## 6. Lo que necesito de ti (P1)

**Importante: no pongas ningún DSN en el servidor hasta que te avise de que A2 está desplegada.** El backend que hoy
corre en producción (y el de A1) ya sabe enviar a Sentry si encuentra `FBI_SENTRY_DSN`, pero sin el filtro de A2:
enviaría los mensajes de error tal cual.

### 6.1 La cuenta y los proyectos (cuando quieras)

1. Crea una cuenta en [sentry.io](https://sentry.io), plan **Developer** (gratis). Si el plan de seguridad (S3) ya
   la creó, usa esa. Región de datos: si vas a tener clientes en la Unión Europea, elige la UE.
2. Crea **dos proyectos**: `predigol-backend` (plataforma *Python* → *FastAPI*) y `predigol-web` (plataforma
   *Browser JavaScript*). No instales nada de lo que proponga el asistente: el código ya está.
3. En el asistente de cada proyecto, deja la alerta **«Alert me on every new issue»** (te llega un correo por cada
   error nuevo: son los «avisos activos» de G12).
4. **Settings → Security & Privacy** (de la organización), sección *Data Scrubbing*: deja activados *Data Scrubber*
   y *Use Default Scrubbers*, y activa *Prevent Storing of IP Addresses*. Es una segunda red: lo que llega ya va
   filtrado.
5. **Settings → Spike Protection:** compruébalo activado en los dos proyectos.
6. En `predigol-web` → **Settings → Inbound Filters**: activa los filtros de *localhost*, navegadores antiguos,
   rastreadores web y extensiones del navegador (ruido que gastaría el mes).
7. Opcional (incluido gratis): **un monitor de disponibilidad** (*Uptime*) sobre `https://predigolai.com/health`. Si
   ya tienes UptimeRobot, puede seguir igual; el recorrido sintético vigila además el recorrido completo.

### 6.2 La cuenta sintética (cuando quieras)

Una cuenta USER solo para el recorrido, sin segundo factor y que no uses para nada más (por ejemplo, una dirección
tuya con `+sintetico`). En el servidor:

```
predigolctl create-user --email <correo-dedicado> --role USER --name "Recorrido sintético"
```

La contraseña queda en `/root/predigol-credentials/<correo-dedicado>.txt` (600).

### 6.3 Cuando te avise de que A2 está desplegada

Añade a `/etc/predigol/app.env` (root, 600; **nunca por el chat ni en Git**):

```
FBI_SENTRY_DSN=<DSN de predigol-backend: Settings → Projects → predigol-backend → Client Keys (DSN)>
FBI_SENTRY_WEB_DSN=<DSN de predigol-web>
FBI_SYNTHETIC_BASE_URL=https://predigolai.com
FBI_SYNTHETIC_EMAIL=<correo-dedicado>
FBI_SYNTHETIC_PASSWORD=<la contraseña del fichero de 6.2>
```

Borra después el fichero de `/root/predigol-credentials/`. Dime solo «listo»: yo vuelvo a crear la API y el worker
para que lean el entorno, en la siguiente ventana tranquila y avisándote antes.

Nota de coordinación: los ficheros de entorno del servidor son territorio del plan de seguridad; esta es la única
línea que A2 te pide añadir y no cambia ninguna otra.

### 6.4 La prueba intencional (contigo, 5 minutos)

1. Consola → **Sistema** → «Pruebas de observabilidad»: pulsa «Error de prueba en la API». La consola muestra
   «Provocado: referencia …».
2. Pulsa «Error de prueba en la web»: «Enviado desde el navegador».
3. En Sentry deben aparecer **dos errores**:
   - En `predigol-backend`: `MonitoringTestError`, con la etiqueta `request_id` igual a la referencia de la consola,
     la versión `predigol-backend@…` y un usuario de 20 caracteres hexadecimales.
   - En `predigol-web`: «PrediGol monitoring test (A2): raised on purpose in the browser», con las etiquetas
     `boundary` = `console-test`, `viewport` y `display`, la versión `predigol-web@…` y **el mismo** usuario de 20
     caracteres.
4. Abre cada uno y comprueba que **no** aparecen tu correo, tu IP, cookies ni parámetros de URL.
5. Al cabo de 24 horas, el panel «Recorrido sintético» debe decir 96 vueltas en 24 h y 0 fallidas.

Con eso, G12 queda en verde.

## 7. Vuelta atrás

- Apagar Sentry: vaciar `FBI_SENTRY_DSN` y `FBI_SENTRY_WEB_DSN` y volver a crear la API y el worker. La web deja de
  cargar el SDK en cuanto la API dice que está apagado.
- Parar el recorrido: vaciar `FBI_SYNTHETIC_EMAIL` y volver a crear el worker.
- El código: `predigolctl rollback` a la versión que corre hoy, la de la IA (`ia-p01`: backend `c40e101b9a15`, web
  `6a0790f190bd`). A2 no tiene migración: la base se queda en la **0113** y no hay nada que deshacer.

## 8. Puertas y despliegue

- **Base del paquete:** las publicaciones de la IA que corren desde el 26-oct a las 20:41 UTC
  (`refs/release/backend-ia-p01` = `c40e101b9a15`, `refs/release/web-ia-p01` = `6a0790f190bd`). La rama `ux/a2-ia`
  (`6f505c20`) es `ux/a2` con la fuente de la IA fusionada: base común `012209bf` (la fuente de A1), sin conflictos.
- **Puertas sobre el árbol fusionado** (backend `dfe83d9d`, web `38fa5ff7`; esta guía no cambia código): ruff sin
  avisos; mypy estricto (492 ficheros) y del árbol entero (1.185), sin errores; **pytest 7.188 pasadas**, 4 omitidas
  (33,9 minutos); web: lint 0 errores (26 avisos de siempre), tipos, **809 pruebas**, build de producción; `bun audit`
  0 vulnerabilidades en 458 paquetes (con la S1.b del plan de seguridad).
- **e2e completo sobre los árboles fusionados:** 116 pruebas, **105 pasadas**, 7 fallidas y 4 omitidas (la PWA
  necesita el build de producción), 18,9 minutos (27-oct 00:22–00:41 UTC), con Sentry encendido contra el sustituto
  local y la base de QA `fbi_qa_a2ia`: una copia de la de A2 (`fbi_qa_a23`, en la 0094 como A1) con su copia y su
  prueba de restauración, subida después a la **0113** con las migraciones de la IA, como producción. Los 7 fallos
  fueron el servidor de QA bajo carga, todos en el proyecto `mobile` con dos trabajadores: dos veces la página de
  Chromium se cayó al navegar y cinco veces el esqueleto seguía ocupado a los 20 s. **Repetidos con un solo
  trabajador sobre el mismo árbol: 7 de 7 pasan** (3,9 minutos).
- **Paquete `ux-a2`, reconstruido:** backend y web hijos de las publicaciones de la IA, sin migración, huella del
  código de modelos sin cambios (guardia en modo `stop`). Los commits de publicación están en su `RELEASE.json`; el
  paquete anterior, construido sobre A1, queda retirado.
- **Despliegue: HECHO y verificado el 27-oct-2026, 04:28–04:41 UTC**, sin ventana: el dueño quitó las ventanas a las
  ≈03:55 UTC («siempre ir desplegando todo lo que se termine»), así que el paquete se reempaquetó sin horario (mismas
  publicaciones, sha256 `4454e054…ee206b332`) y salió en cuanto la copia estuvo comprobada. Carpeta del servidor
  `/root/releases/20261027T0400Z-ux-a2`:
  - comprobación previa (solo lectura): todas las líneas OK;
  - copia `predigol-20261027T035500Z-ux-a2` (1.499.125.151 bytes, 508 s, revisión 0113) y **prueba de restauración
    superada** (888 s, 04:18:51 UTC);
  - `deploy_with_retries.sh` al primer intento: servidor en calma, paquetes comprobados, guardia de modelos `UNCHANGED`
    (`mc9a7bec97ca`), copia previa del propio despliegue (`predigol-20261027T043219Z-pre-deploy-93aed12d9df9`), imágenes
    construidas, API, worker y web recreados; `deploy: done` a las 04:41:25 UTC;
  - **humo OK** (salud, entrada, HSTS, rutas cerradas sin sesión, sonda de R02, `<html lang>` en es y en)
    y **verificación con todas las líneas OK**: *checkouts* `93aed12d9df9` / `9cfb88a22697`, revisión 0113, `pip freeze`
    de API y worker igual a `constraints.txt`, huella de modelos sin cambios, los picks (4.131) y decisiones (773) del día
    idénticos antes y después con el mismo corte (04:19:07 UTC) y 0 líneas de error en los registros de la API y la web;
    la lectura `promotion_trace` posterior sale con 0;
  - **desde Internet, `prod-smoke` 6 de 6** contra `https://predigolai.com`.
  Producción corre **backend `93aed12d9df9` y web `9cfb88a22697`** sobre la **0113**. Sentry y el recorrido siguen
  apagados hasta tu P1 (sección 6): te lo pido cuando no quede ninguna otra tarea tuya abierta.

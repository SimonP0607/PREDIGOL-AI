# Despliegue Web + PWA en VPS: preparado y ensayado (7 oct 2026)

**Nada contratado ni publicado.** PrediGol queda listo para un VPS con Ubuntu 24.04: 4 vCPU, 8 GB y 100 GB, por
ejemplo OVH VPS-3 a €10,40/mes. El procedimiento completo está en `deploy/vps/README.md`.

## 1. Qué está listo

| Pieza | Cómo queda |
|---|---|
| PostgreSQL 16 | contenedor sin puertos públicos, `shm_size` de 512 MB, ajustado para 8 GB |
| Worker 24/7 | un solo contenedor, que se reinicia solo. Healthcheck con su latido (`scripts/worker_alive.py`). Un segundo worker lo rechaza el bloqueo (salida 75) |
| API | detrás de Caddy, 2 procesos. Sin `/docs` ni `/openapi.json`; `/health` sin detalles; cookie `Secure`; origen = dominio; IP real del cliente |
| Web | build de Nitro para Node (no el de Cloudflare que traía por defecto), usuario sin privilegios, healthcheck |
| PWA | manifiesto, iconos 192/512 (normales y maskable), service worker y página sin conexión. Nunca guarda la API ni páginas. Instalable en Android e iPhone |
| HTTPS y dominio | Caddy con Let's Encrypt automático. Redirección 80→443, HSTS, CSP, X-Frame-Options y Permissions-Policy |
| Copias | volcado diario verificado con su manifiesto, rotación (3 diarias + 2 semanales) y copia externa cifrada con `age` (opcional). RAW fuera del servidor con `rclone copy --immutable` |
| Prueba de restauración | semanal, en un PostgreSQL desechable sin red; nunca en la base en marcha |
| Arranque automático | `predigol.service` al encender, `predigol-post-boot.service` comprueba y avisa, y temporizadores para monitor, copia, prueba y RAW |
| Monitoreo | cada 5 min: contenedores, HTTPS, worker (lo reinicia si deja de latir, como mucho una vez por hora), captura en vivo con partidos en juego, disco, edad de la copia, prueba de restauración y certificado. Avisos por Telegram y Healthchecks.io (opcionales) |
| Recuperación tras reinicio | Docker devuelve los contenedores, systemd fija la versión y el catch-up del worker rehace lo vencido |
| Corte desde el portátil | `predigolctl import`: una vez, en una base vacía, verificada tabla a tabla, con el RAW sin sobrescribir |
| Despliegues | `predigolctl deploy` (copia previa, migración con reintentos, salud) y `predigolctl rollback`, con bloqueos para que nada se solape |

## 2. Cambios de código de esta fase

**Backend:**

* `b44ecc8` `FBI_API_DOCS` y `FBI_API_HEALTH_DETAIL`. Abiertos en local como antes; cerrados en el servidor.
* `b44ecc8` `scripts/worker_alive.py`.
* `b532d85` La página System ya no da un 500 si la carpeta de copias no se puede leer. Lo encontró el ensayo.
* `f7f9585` CA opcional de un proxy para construir la imagen. Nunca queda en la imagen.
* `0cfad64` El kit `deploy/vps/` y su manual.

**Frontend:**

* `5311680` La PWA y la imagen de producción.
* `21d3980` CA opcional en la construcción de la imagen.
* `a06ebe9` E2E de la PWA.

Pruebas nuevas:

* tests de los dos interruptores de la API;
* `worker_alive`;
* el listado de copias;
* 10 tests unitarios de la PWA: reglas del service worker leídas del `sw.js` real, registro y manifiesto;
* el proyecto Playwright `pwa`, que requiere `E2E_PWA=1` y el build de producción.

## 3. Ensayo (7 oct 2026, entorno de pruebas con Docker)

El mismo `docker-compose.yml` y el mismo `Caddyfile`, con tres diferencias:

* el dominio era `predigol.localhost`, con la autoridad local de Caddy;
* un simulador vacío de API-Football, sin clave ni peticiones;
* datos de prueba.

| Prueba | Resultado |
|---|---|
| Despliegue desde cero: migraciones 0001→0069, todo sano | OK |
| Cabeceras: 308 a HTTPS, HSTS, CSP, `/docs` y `/openapi.json` en 404, `/health` sin detalles, compresión | OK |
| Playwright contra el build de producción por HTTPS | 59 OK, 2 omitidos |
| PWA | 4/4 |
| Copias y rotación; copia cifrada fuera y descifrada con el mismo sha256 | OK |
| Prueba de restauración: buena → OK; copia dañada → FALLO detectado | OK |
| RAW inmutable: fichero alterado → rechazado, la copia remota intacta | OK |
| Segundo worker → salida 75; worker sin latido → reiniciado | OK |
| Reinicio simulado → todo vuelve solo; post-boot "ok" | OK |
| Importación verificada; segunda importación → rechazada; despliegue encima | OK |
| `rollback` y vuelta a la versión nueva; bloqueos ante dos ejecuciones a la vez | OK |

En el portátil, con el servidor de desarrollo y datos reales: Playwright 57 OK y 4 omitidos (los de la PWA). Con el
código nuevo instalado, la API, el worker y la web siguen en marcha.

## 4. Lo que solo se puede probar en el servidor real

* Emisión del certificado de Let's Encrypt: necesita el dominio y la IP pública.
* Avisos reales de Telegram y Healthchecks: necesitan las cuentas.
* El arranque con systemd en una máquina real. Los ficheros de unidad pasan `systemd-analyze verify`.
* Descargar las imágenes de Docker Hub desde la IP del VPS.
* La restauración con los datos reales, que ocurre en el corte. `import` compara cada tabla con el manifiesto.

## 5. Decisiones del dueño, en orden

1. Contratar el VPS y el dominio. Apuntar el DNS.
2. Renovar API-Football antes del **29 oct 04:31 UTC** y rotar la clave: `SECURITY_ACTION: rotación recomendada
   posteriormente`.
3. Elegir dónde van las copias externas (por ejemplo R2) y generar la clave `age`. La privada la guarda el dueño.
4. Crear los avisos: Telegram, Healthchecks.io y UptimeRobot.
5. Fijar la ventana del corte, sin partidos en juego.
6. Antes de abrir a usuarios, la revisión legal y las cuentas propias de los usuarios. Siguen pendientes según
   `DEPLOYMENT_COSTS.md` §6: registro, recuperación y borrado de cuenta, páginas legales, 18+.

**No desplegar públicamente hasta completar esos pasos.**

# R02 — Funciones de servidor de TanStack Start (plan de seguridad, S1)

Hallazgo R02 de la auditoría de seguridad (GHSA-qx66-fv34-fjm8: XSS reflejado sin autenticación en las respuestas a una función de
servidor; relacionados: seroval GHSA-p6vx-979v-rg4c y GHSA-jp82-f5mq-hwhp, zod GHSA-mrhx-c7xc-m3w5). El framework de la web atiende
`/_serverFn/<id>` como la llamada a una función de servidor; las versiones auditadas devolvían como HTML parte de lo que venía en la URL.

## Las cuatro defensas, de dentro a fuera

1. **Versiones corregidas** (desde UX A0, 25-oct-2026): `@tanstack/react-start` 1.168.61, `@tanstack/start-server-core` 1.169.40, `seroval`
   1.6.9, `zod` 4.6.6, en cada copia que resuelve `bun.lock`. Una prueba de la web (`web/src`) mantiene ese suelo.
2. **La app no define ninguna función de servidor** (`createServerFn` no aparece en `web/src`): no hay nada legítimo que llamar en esa ruta.
3. **Middleware CSRF de la app** (`web/src/start.ts`, `createCsrfMiddleware` con filtro `serverFn`): una llamada solo pasa si el navegador dice
   `Sec-Fetch-Site: same-origin` o, sin esa cabecera, el `Origin`/`Referer` es el propio; sin ninguna de las dos, 403.
4. **Regla de Caddy** (esta nota; `deploy/vps/Caddyfile`, bloque `handle /_serverFn/*`): una segunda cerradura en la puerta.

## La regla de Caddy

Una llamada a una función de servidor la hace el propio script de la app con la cabecera literal `x-tsr-serverFn: true`; nunca es la navegación
de un documento y nunca pide HTML. En `/_serverFn/*` Caddy contesta **403 con el cuerpo vacío** cuando se cumple **cualquiera** de estas tres:

| Condición | Por qué |
| --- | --- |
| falta `x-tsr-serverFn` o su valor no es `true` | el cliente y el servidor del framework reconocen una llamada por esa cabecera exacta |
| `Sec-Fetch-Mode: navigate` | es la navegación de un documento (un enlace, una URL escrita) |
| `Accept` contiene `text/html` | pide una página, no datos |

Lo demás sigue al servidor web como antes. En los dos casos la respuesta lleva las cabeceras de seguridad de siempre y la política
`Content-Security-Policy: default-src 'none'` (la de las páginas permite scripts y estilos propios; en esta ruta no hace falta nada).

Qué **no** es: autenticación. La cabecera la pone el cliente, así que quien sabe que existe la envía. Lo que protege de verdad son las
defensas 1 a 3; la regla impide que un enlace o una navegación llegue siquiera al framework. Si algún día la app define funciones de servidor
propias, la regla las deja pasar (llevan la cabecera) y su protección es el CSRF de `start.ts` y la autorización de cada función.

### Cómo está escrita (y por qué así)

* Caddy ejecuta el bloque `header` del sitio **al final** y, si borra `Server` (`-Server`), lo aplaza: una cabecera puesta dentro de un
  `handle` no puede sustituir un campo suyo (probado el 25-oct-2026). Por eso el bloque del sitio lleva el matcher `@not_serverfn` (todo menos
  esta ruta) y la ruta tiene su propio bloque; las seis cabeceras de seguridad y `-Server` viven una sola vez en el fragmento
  `(security_headers)` que importan los dos.
* El matcher `path` de Caddy no distingue mayúsculas: `/_SERVERFN/…` también se filtra. Caddy normaliza la ruta antes de comparar (`//`, `./`,
  `../`, `%5f`, `%2e`): ninguna de esas escrituras llega al framework sin pasar por la regla, y la prueba del marcador las ejercita. La barra
  invertida (`/\_serverFn/…`) no la normaliza Caddy: el servidor web la contesta con un 308 a la ruta normal, que ya cae en la regla (un navegador
  nunca envía `\` en una URL: la convierte en `/`).
* Caddy ordena los `handle` por la especificidad de su ruta; el que no tiene matcher va el último.

## Cómo se prueba

* `bin/serverfn-matrix.sh <url> [args de curl]` — 22 casos con el resultado esperado de cada uno (BLOQUEA o PASA); termina con estado 0 si todos
  coinciden. Cubre llamadas legítimas (cabecera en minúsculas y mayúsculas, sin `Accept`), cada condición por separado, el POST, el id vacío,
  mayúsculas, puntos codificados y las rutas que la regla no debe tocar (`/`, `/login`, `/sw.js`, `/health`, `/api/…`, `/_serverFnX/`).
* `bin/serverfn-probe.sh <url> [args de curl]` — la prueba del marcador (W1 del plan): una navegación de documento a `/_serverFn/…` con un
  texto marcador inocuo (nunca un script), escrita de 18 maneras (URL escrita, enlace desde otro sitio, id inventado, `%5f`, `//`, `./`, `../`,
  `\`, barra codificada…). Pasa si ninguna respuesta es HTML **y** contiene el marcador.
* Desde el servidor: `… https://$PREDIGOL_DOMAIN --resolve $PREDIGOL_DOMAIN:443:127.0.0.1`. Desde Internet: la URL pública sin más.
* `tests/unit/test_vps_caddyfile.py` — el texto de la regla, la configuración que Caddy construye de él (si `caddy` está instalado; `CADDY_BIN`
  lo señala) y la lógica de los dos scripts contra un servidor de pruebas que se comporta como la regla y otro que no.

## Cómo se despliega

`predigolctl deploy` **no recrea Caddy**: el compose monta `./Caddyfile` como **un solo fichero** y `git checkout` lo sustituye por otro con otro
inodo, de modo que el contenedor sigue viendo el viejo hasta que se recrea (el mismo defecto que el 22-oct-2026 con `grants.sql`). Después
de un despliegue que cambie `deploy/vps/Caddyfile` o `deploy/vps/caddy/`:

1. validar el fichero nuevo con la imagen que corre (`caddy validate`), sin tocar el contenedor vivo;
2. `compose up -d --no-deps --force-recreate caddy` (como `bin/cloudflare-ips.sh trust`); el certificado vive en `/srv/predigol/caddy/data`;
3. comprobar que el sha256 de `/etc/caddy/Caddyfile` dentro del contenedor es el del fichero del checkout, y pasar los dos scripts de arriba.

## Volver atrás

`git checkout --detach <commit anterior>` en `/opt/predigol/backend`, `predigolctl deploy` y los pasos 1 a 3 de arriba. La regla se puede quitar
sin tocar nada más: sin ella, `/_serverFn/*` vuelve a llegar al servidor web, protegido por las defensas 1 a 3.

## Observación aparte

El bloque `respond @closed 404` del Caddyfile (rutas `/docs`, `/openapi.json`, `/redoc`) **no se ejecuta**: Caddy ordena `respond` después de
`handle`, y el `handle` sin matcher ya atiende esas rutas llevándolas a la web, que contesta su 404. El efecto buscado se cumple de todos
modos, porque la API no publica sus documentos en producción y esas rutas no le llegan. Queda anotado para corregirlo con una prueba en un
cambio posterior del Caddyfile (no se toca aquí: un hallazgo, un despliegue).

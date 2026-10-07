# PrediGol en un VPS: web + PWA, 24/7

Este kit se preparó y se ensayó el 7 oct 2026. **No se ha contratado ni publicado nada.** Todo lo que cuesta dinero o
expone la plataforma (servidor, dominio, almacenamiento externo, avisos) lo decide y lo contrata el dueño (§2).

## 1. Qué corre en el servidor

```
Internet ──HTTPS 443 (y 80 → 443)──▶ Caddy: certificados de Let's Encrypt automáticos, cabeceras de seguridad
                                       ├── /api/*, /health ──▶ api   (FastAPI, 2 procesos)
                                       └── todo lo demás ────▶ web   (Node, la app y la PWA)
                       worker (uno solo, 24/7) ──HTTPS──▶ API-Football
                       postgres 16 (sin puertos públicos; solo api y worker lo ven)

/srv/predigol/
  pgdata      la base
  raw         las respuestas del proveedor (evidencia; nunca se borran)
  backups/db  volcados diarios con su manifiesto
  caddy       certificados
  state       estado del monitor, de las copias y de los despliegues
/etc/predigol/predigol.env   secretos y ajustes (root, 600)
```

Un solo `docker compose` (`docker-compose.yml`) con PostgreSQL 16, la API, el worker, la web y Caddy. Cada servicio
se reinicia solo si se cae. systemd levanta el conjunto al arrancar la máquina, comprueba que volvió y avisa.

Tamaño recomendado: 4 vCPU, 8 GB de RAM y 100 GB NVMe (por ejemplo OVH VPS-3).

* Hoy: 9,3 GB de base y 0,75 GB de RAW.
* Crecimiento (PostgreSQL + RAW, 133 ligas): ≈ 0,11 GB/día. Son ≈ 30 GB a 6 meses, 51 GB a 12 y 91 GB a 24.
* Con sistema, WAL y copias locales, el disco de 100 GB llega al 90 % hacia abr 2028.
* Las cifras salen de `docs/owner/LIVE_ODDS_CLEANUP_2026-10-06.md`.

## 2. Lo que decide y contrata el dueño

| Qué | Para qué | Coste orientativo (6 oct 2026) |
|---|---|---|
| VPS con Ubuntu 24.04 LTS, 8 GB, 100 GB | todo PrediGol | OVH VPS-3 €10,40/mes |
| Dominio (p. ej. `predigol.com`) | la dirección pública y su certificado | ≈ $11/año |
| Un correo para Let's Encrypt | avisos si un certificado no se puede renovar | — |
| Bot de Telegram (opcional) | avisos del servidor y de la app | gratis |
| Healthchecks.io y UptimeRobot (opcional) | saber si el servidor deja de latir o de responder | gratis |
| Almacenamiento externo, p. ej. Cloudflare R2 (recomendado) | copias cifradas y RAW fuera del servidor | 10 GB gratis, luego $0,015/GB-mes |
| Una clave `age` (la genera el dueño con `age-keygen` y guarda la privada) | cifrar las copias antes de salir | gratis |
| API-Football Ultra | los datos | $29/mes; **vence el 29 oct 04:31 UTC** |

`SECURITY_ACTION: rotación recomendada posteriormente`. La clave de API-Football conviene rotarla al renovar el plan.
La clave nueva solo va en `/etc/predigol/predigol.env`; nunca en un chat, en Git ni en un log.

## 3. Instalación (≈ 1 hora)

1. **DNS.** Crea un registro `A` del dominio (o de `app.` + dominio) con la IP del VPS, más un `AAAA` si hay IPv6.
   Usa TTL 300. Sin proxy de Cloudflare al principio: Caddy necesita llegar a Let's Encrypt por el puerto 80.
2. **Acceso.** Entra por SSH con llave, no con contraseña. `install.sh` no cierra el acceso por contraseña, para no
   dejarte fuera. Cuando la llave funcione, pon `PasswordAuthentication no` en `/etc/ssh/sshd_config` y reinicia
   `ssh`.
3. **Código.** Sin GitHub: se llevan los dos repositorios como bundles git desde el portátil.
   ```
   # portátil
   git -C ~/projects/football-intelligence-v2 bundle create /tmp/backend.bundle feature/predigol-ux-rbac
   git -C ~/projects/football-intelligence-hub bundle create /tmp/web.bundle feature/predigol-ux-rbac
   scp /tmp/backend.bundle /tmp/web.bundle root@SERVIDOR:/root/
   # servidor
   git clone -b feature/predigol-ux-rbac /root/backend.bundle /opt/predigol/backend
   git clone -b feature/predigol-ux-rbac /root/web.bundle /opt/predigol/web
   ```
4. **Preparar la máquina.** `sudo /opt/predigol/backend/deploy/vps/bin/install.sh` instala:
   * Docker (desde el repositorio oficial de Docker);
   * el cortafuegos: solo SSH, 80 y 443;
   * actualizaciones de seguridad automáticas, sin reinicio automático;
   * 4 GB de swap;
   * jq, age, rclone y openssl;
   * las carpetas de `/srv/predigol`;
   * `/etc/predigol/predigol.env` a partir de `predigol.env.example`;
   * los servicios y temporizadores de systemd y el comando `predigolctl`.
5. **Ajustes.** Rellena `/etc/predigol/predigol.env` con `nano`. Ese fichero es lo único que contiene secretos (600).
   * La contraseña de la base: `openssl rand -base64 32`.
   * Para copias fuera del servidor: `BACKUP_RCLONE_REMOTE`, `BACKUP_AGE_RECIPIENT` y `RAW_RCLONE_REMOTE`, tras
     `rclone config`.
6. **Datos.** Si vienen del portátil, haz el corte (§4) **antes** del primer despliegue. Si se empieza vacío, salta
   este paso.
7. **Arrancar.** `predigolctl deploy` hace todo esto:
   * construye las dos imágenes con la versión exacta del código;
   * hace una copia previa si ya hay base;
   * migra la base;
   * arranca todo y espera a que esté sano;
   * pasa el monitor.
8. **Cuenta del dueño.**
   ```
   predigolctl create-user --email TU@CORREO --role SUPER_ADMIN --name "Tu nombre"
   ```
   La contraseña generada queda en `/root/predigol-credentials/<correo>.txt` (600). Guárdala en tu gestor y borra el
   fichero.
9. **Comprobar.**
   * `https://DOMINIO/health` responde `"status": "ok"`;
   * el inicio de sesión funciona;
   * en el móvil se puede instalar la app (§10).
10. **Avisos.**
   * En Healthchecks.io crea un check por tarea y pega sus URL en `HC_PING_*`.
   * UptimeRobot vigila `https://DOMINIO/health` y busca la palabra `"ok"`.
   * Telegram usa `FBI_TELEGRAM_BOT_TOKEN` y `FBI_TELEGRAM_CHAT_ID`.

## 4. Corte desde el portátil, sin dos workers a la vez

Hazlo en una ventana sin partidos en juego (mira En vivo), con el servidor ya instalado (§3, pasos 1–5).

1. **Portátil: parar el worker.** `scripts/dev-down worker`. Desde aquí el portátil no captura nada.
   * Dos workers en máquinas distintas no se ven: cada uno tiene su propia base.
   * Capturarían los dos, gastarían cuota y divergirían.
   * Por eso nunca puede haber dos encendidos.
2. **Portátil: copia final.**
   ```
   python -m scripts.backup create --label CUTOVER
   ```
   Crea la carpeta `data/backups/<fecha>-CUTOVER` con `db.dump`, `raw.tar` y `manifest.json`. Como nada escribe
   durante el volcado, el manifiesto describe exactamente lo copiado.
3. **Copiar al servidor.** `scp -r data/backups/<fecha>-CUTOVER root@SERVIDOR:/root/import/`.
4. **Servidor: importar.** `predigolctl import /root/import/<fecha>-CUTOVER`.
   * Antes de tocar nada comprueba los sha256 y que la base esté vacía. Se niega a escribir sobre una base con datos.
   * Restaura y compara la cuenta de filas de **cada** tabla con el manifiesto.
   * Extrae el RAW sin sobrescribir nada.
5. **Servidor: arrancar.** `predigolctl deploy`. Migra desde la revisión importada hasta la última y arranca el
   worker. Su catch-up, anclado al ledger, recupera lo que vencía mientras tanto.
6. **Verificar.**
   * `predigolctl status`;
   * la página System del Admin Console;
   * la captura en vivo cuando empiece el primer partido;
   * `predigolctl backup && predigolctl restore-test`.
7. **Portátil.** Queda apagado como respaldo frío durante 7 días, con el worker parado. El archivo del in-play
   (`~/archive/inplay/…`) sube al almacenamiento externo con `rclone copy`.

Vuelta atrás del corte: mientras no se borre nada en el portátil, basta con encender allí el worker otra vez
(`scripts/dev-up worker`). El servidor se vacía y se repite.

## 5. Operación diaria

| Comando | Qué hace |
|---|---|
| `predigolctl status` | contenedores, versiones en marcha, último veredicto del monitor |
| `predigolctl logs worker` | logs en vivo de un servicio: postgres, api, worker, web o caddy |
| `predigolctl health` | el monitor, ahora |
| `predigolctl backup` / `restore-test` | copia o prueba de restauración, ahora |
| `predigolctl psql` | consola de la base en solo lectura |
| `predigolctl stop` / `up` | parar o levantar el conjunto; no se pierde nada |

Temporizadores de systemd (`systemctl list-timers 'predigol*'`):

| Tarea | Cuándo |
|---|---|
| monitor (`healthcheck.sh`) | cada 5 min |
| copia de la base (`backup.sh`) | 04:15 UTC |
| prueba de restauración (`restore-test.sh`) | lunes 06:00 UTC |
| RAW fuera del servidor (`raw-sync.sh`) | cada hora, en el minuto :20 |

Lo que revisa el monitor:

* contenedores vivos y sanos;
* `/health` y la web, por HTTPS como cualquier visitante;
* el latido del worker: si se para, lo reinicia como mucho una vez por hora y avisa;
* la captura en vivo, mientras hay partidos en juego;
* el disco: aviso al 85 %, problema al 92 %;
* una copia de menos de 26 h;
* una prueba de restauración superada en los últimos 8 días;
* el certificado: aviso a 14 días del vencimiento.

Avisa solo cuando cambia el estado y hace ping a Healthchecks en cada pasada.

## 6. Actualizar y volver atrás

1. Lleva el código nuevo como bundle (§3) y avanza cada repositorio:
   ```
   git -C /opt/predigol/backend fetch /root/backend.bundle feature/predigol-ux-rbac:refs/remotes/bundle/x
   git -C /opt/predigol/backend merge --ff-only bundle/x
   ```
   Lo mismo con `/opt/predigol/web`.
2. `predigolctl deploy`.
   * Construye las imágenes con la etiqueta de la versión.
   * Hace una copia `pre-deploy`.
   * Migra (5 intentos). Si la migración falla, no toca lo que está en marcha.
   * Recrea los servicios y espera a que estén sanos.
   * Pasa el monitor.

   Dos despliegues no pueden solaparse: hay un bloqueo.
3. Si algo va mal, `predigolctl rollback` arranca las imágenes de la versión anterior (se conservan).
   * La base **no** se baja de versión sola.
   * Si la versión anterior necesita el esquema anterior (por ejemplo, una tabla que la migración nueva retiró),
     deshacer la migración se decide con el dueño. Se hace con `alembic downgrade` o restaurando la copia
     `pre-deploy`.
   * Mientras tanto, lo seguro es quedarse en la versión nueva.

## 7. Copias y desastres

* **Cada día:**
  * un `pg_dump` coherente, leído entero (`pg_restore --list`), con sha256 y la cuenta de filas de las tablas clave
    antes y después del volcado;
  * se guardan en el servidor las 3 últimas y la última de cada una de las 2 semanas anteriores;
  * con almacenamiento externo, cada copia sale cifrada con `age` a la clave pública del dueño. La privada nunca
    está en el servidor.
* **El RAW:** copia horaria con `rclone copy --immutable`, que solo añade. Un fichero ya copiado no se modifica ni
  se borra fuera, pase lo que pase aquí.
* **Cada semana:** prueba de restauración de la última copia en un PostgreSQL desechable, sin red.
  * Comprueba el sha256, la revisión y que cada tabla clave quede entre sus recuentos de antes y después.
  * Nunca toca la base en marcha: hacerlo una vez la retuvo cinco horas y paró la captura.
* **Si se pierde el servidor:**
  1. VPS nuevo y §3, pasos 1–5.
  2. Bajar del remoto la última copia y el RAW:
     ```
     rclone copy REMOTO/db/<copia>.dump.age .
     rclone copy REMOTO/raw /srv/predigol/raw
     ```
  3. Descifrar en una máquina con la clave: `age -d -i clave.txt -o copia.dump copia.dump.age`. Subir `copia.dump`
     a `/srv/predigol/backups/db/`.
  4. Restaurar:
     ```
     docker compose ... up -d postgres
     docker exec predigol-postgres pg_restore -U fbi -d fbi --exit-on-error -j 4 /backups/copia.dump
     chown -R 1000:1000 /srv/predigol/raw
     ```
  5. `predigolctl deploy`.

## 8. Seguridad

* Puertos abiertos: 22, 80 y 443. PostgreSQL, la API y la web no publican puertos; solo Caddy.
* La API pública:
  * sin `/docs` ni `/openapi.json`;
  * `/health` solo dice cómo está cada parte, no por qué;
  * la cookie de sesión es `Secure`;
  * el origen permitido es el dominio;
  * la IP del cliente llega desde Caddy, y el límite por cliente y la auditoría de accesos la usan.
* Cabeceras de seguridad:
  * HSTS de un año;
  * CSP: solo este origen, más las fuentes de Google y los logos de `media.api-sports.io`;
  * no se puede incrustar en otra web;
  * sin cámara, micrófono ni geolocalización.
* Secretos:
  * solo en `/etc/predigol/predigol.env` (600);
  * las contraseñas nuevas en `/root/predigol-credentials` (600), y se borran tras entregarlas;
  * nada en las imágenes ni en Git.
* El sistema:
  * fail2ban vigila el SSH;
  * las actualizaciones de seguridad se instalan solas;
  * los reinicios se planifican fuera de partidos en vivo.

## 9. Reinicios y caídas

* Al arrancar la máquina, Docker devuelve los contenedores y `predigol.service` deja el conjunto en la versión del
  último despliegue. Luego `predigol-post-boot.service` espera a que esté sano, pasa el monitor y avisa por Telegram
  de lo que volvió.
* El worker no pierde trabajo programado: el catch-up anclado al ledger rehace lo vencido. Lo que no se puede
  recuperar son los ticks en vivo de los minutos sin máquina, porque `/odds/live` no guarda historia.
* Reinicio planificado (núcleo nuevo): fuera de partidos en vivo, `reboot` y después `predigolctl status`.

## 10. La PWA

* **Instalar.**
  * Android (Chrome): menú → "Instalar app".
  * iPhone (Safari): Compartir → "Añadir a pantalla de inicio".
* **Qué guarda:** solo los archivos de la app (scripts, estilos, iconos).
  * Nunca la API (cuotas, picks, cuenta) ni una página.
  * Sin conexión muestra "Sin conexión", nunca una copia vieja.
* **Actualizaciones:** llegan en la siguiente visita, porque `sw.js` se sirve sin caché.
* **Notificaciones push:** no incluidas. Necesitan claves VAPID y un emisor en el backend; es otra fase.

## 11. Ensayo realizado (7 oct 2026)

En un entorno de pruebas con Docker, el mismo `docker-compose.yml` y el mismo `Caddyfile` (`rehearsal/`). Cambiaban
tres cosas:

* el dominio era `predigol.localhost`, firmado por la autoridad local de Caddy;
* el worker hablaba con un simulador vacío de API-Football, sin clave ni peticiones;
* los datos eran de prueba.

| Prueba | Resultado |
|---|---|
| Despliegue desde cero: imágenes, migraciones 0001→0069, todo sano | OK |
| HTTP→HTTPS (308), HSTS, CSP, X-Frame-Options, `/docs` y `/openapi.json` en 404, `/health` sin detalles, compresión | OK |
| Playwright contra el build de producción por HTTPS (anónimo, USER es/en, admin, preferencias, móvil, PWA) | 59 OK, 2 omitidos |
| PWA: manifiesto e iconos, worker con alcance `/`, la API nunca desde caché, página sin conexión | 4/4 |
| Copia diaria, rotación 3 + 2 semanas, copia cifrada fuera y descifrada con el mismo sha256 | OK |
| Prueba de restauración: copia buena sí; copia dañada → FALLO detectado | OK |
| RAW fuera del servidor; un fichero alterado → copia rechazada y la remota intacta | OK |
| Segundo worker → rechazado por el bloqueo de la base (salida 75) | OK |
| Worker sin latido → el monitor lo reinicia y vuelve a latir | OK |
| Reinicio simulado (el demonio Docker cae y vuelve) → todo vuelve solo; post-boot "ok" | OK |
| Importación desde una copia `scripts.backup`, verificada tabla a tabla; una segunda importación → rechazada | OK |
| Despliegue sobre lo importado; `rollback` a la versión anterior y vuelta a la nueva | OK |
| Dos copias o dos despliegues a la vez → el segundo se niega (bloqueo) | OK |

Lo que solo se puede probar en el servidor real:

* el certificado de Let's Encrypt, que necesita el dominio y una IP pública;
* los avisos reales de Telegram y Healthchecks, que necesitan cuentas;
* el arranque con systemd en una máquina real (los ficheros de unidad pasan `systemd-analyze verify`);
* las descargas de Docker Hub desde la IP del VPS.

## 12. Ficheros

| Fichero | Qué es |
|---|---|
| `docker-compose.yml` | el conjunto: postgres, api, worker, web, caddy |
| `Caddyfile` | HTTPS, cabeceras, rutas (`/api` → api, el resto → web) |
| `predigol.env.example` | todos los ajustes, sin secretos; se copia a `/etc/predigol/predigol.env` |
| `bin/install.sh` | prepara un Ubuntu 24.04 nuevo, una vez |
| `bin/predigolctl` | el mando: up, stop, status, logs, deploy, rollback, backup, restore-test, health, import, psql, create-user |
| `bin/backup.sh`, `bin/restore-test.sh`, `bin/raw-sync.sh` | copias y su prueba |
| `bin/healthcheck.sh`, `bin/post-boot.sh` | monitor y comprobación tras arrancar |
| `bin/import.sh` | el corte: datos del portátil a un servidor nuevo, una vez |
| `systemd/` | arranque al encender y temporizadores |
| `rehearsal/` | solo para ensayos: simulador del proveedor y CA de pruebas; nunca en el servidor |

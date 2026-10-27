# Guías de respuesta a incidentes de PrediGol

Fecha: 26 oct 2026 · Fase S3 del plan de seguridad · Para el dueño, que opera PrediGol solo.

Cada guía cabe en una página y está pensada para usarla con prisa: qué mirar primero, qué hacer en los primeros diez
minutos, cómo saber que terminó, qué **no** hacer y a quién avisar. Los comandos se escriben en el servidor
(`ssh predigol`) salvo que se diga otra cosa. Todas las horas son UTC (Bogotá = UTC−5): `date -u` te da la hora de
verdad.

Este documento describe el servidor **con el paquete de S3 instalado** (avisos con número `INC-…`). Lo que depende de una
fase que aún no está en producción lleva su marca, y al lado qué hacer mientras tanto:

| Marca | Fase | Mientras no esté |
| --- | --- | --- |
| **[S2]** | Copias fuera del servidor (R2) y PITR | Los volcados diarios están en el mismo disco que la base. Si el disco se pierde no hay copia: no improvises, para y pide ayuda (ver la Guía 2) |
| **[S4]** | Acceso por WireGuard y usuario personal con `sudo` | Entras con `ssh predigol` como root y las órdenes van sin `sudo` |
| **[S8]** | Registro de borrados y exportación de la auditoría | No hay registro de borrados: si alguien pidió borrar su cuenta, anótalo a mano en la bitácora |
| **[S10]** | Cloudflare delante del servidor | El dominio apunta directo al servidor: no existe «Under Attack» y el bloqueo de emergencia es por IP (Anexo C) |

## Cómo se lee un aviso

Los avisos llegan por Telegram con esta forma:

* `[SEV1] svc.api: el contenedor api no está sano (parado) (INC-2026-014)`: se abrió un incidente. `svc.api` es la
  clave del aviso y `INC-2026-014` su número; apúntalo, es el nombre de todo lo que hagas.
* `[SEV1 sigue abierto desde las 13:05 UTC] svc.api: …`: un SEV1 que no se arregla se repite cada hora.
* `[recuperado] svc.api tras 12 min (INC-2026-014)`: el problema terminó, lo arreglaras tú o no.

| Gravedad | Qué es | Cuándo actuar |
| --- | --- | --- |
| **SEV1** | La web, los datos o la seguridad están rotos ahora | Ya. Si dura más de 30 minutos, un aviso breve a los usuarios. Revisión en 5 días hábiles |
| **SEV2** | Degradación o señal de seguridad | El mismo día |
| **SEV3** | Aviso sin impacto | En la revisión semanal |

PrediGol lo opera una sola persona: nadie promete atención las 24 horas. Si duermes, el aviso espera y se repite cada
hora hasta que se arregle.

## El mensaje dice… → guía

| Clave del aviso | Qué significa | Guía |
| --- | --- | --- |
| `svc.<nombre>` (SEV1) | Un contenedor no está sano; el texto dice en qué estado está | 1 (si es `postgres`: **2**) |
| `svc.<nombre>.loop` (SEV1) | Se ha reiniciado 3 veces en 15 minutos | 1 (si es `postgres`: **2**) |
| `web.health`, `web.login` (SEV1) | La puerta de entrada no responde, o la pantalla de login no carga | 1 |
| `worker.heartbeat` (SEV1) | El worker no da señales de vida | 1; si llegan `svc.postgres` y `web.health` a la vez: **2**; si el log habla del proveedor: 8 |
| `web.degraded`, `web.errors5xx` (SEV2) | Respuestas degradadas o más de 20 errores 5xx en 5 minutos (no se cuentan en los 6 minutos siguientes a un despliegue o a una vuelta atrás: los 502 de esos segundos son normales) | 1 |
| `api.login` (SEV1) | `/api/v1/auth/me` responde 200 **sin sesión**: el inicio de sesión no se está exigiendo | **5** y **4**, de inmediato |
| `db.connections` (SEV2), `pitr.wal` (SEV1) | Conexiones al 80 % o más; el WAL no sale hacia R2 | 2 |
| `backup.local`, `restore.test`, `pitr.backup`, `pitr.test` (SEV2) | Una copia o su prueba no se hizo | 2 |
| `backup.offsite`, `backup.locks`, `raw.sync`, `raw.full` **[S2]** | Las copias fuera del servidor no llegan o sus candados no se pudieron probar | 2 |
| `disk.usage` (SEV2 desde 80 %, SEV1 desde 90 %), `disk.forecast` (SEV2) | Disco casi lleno, o se llena en menos de 14 días | 3 |
| `auth.privileged` (SEV2; **SEV1** si lo hizo otra cuenta) | Cambio de rol, de MFA o de contraseña de una cuenta | 4 |
| `auth.newdevice` (SEV2) | Un administrador entró desde un navegador nuevo | 4 si no fuiste tú |
| `admin.denied` (SEV2) | Más de 20 respuestas 401/403 en rutas de administrador en 10 min | 7; si llega con `auth.newdevice` o `auth.privileged`: 4 |
| `auth.bruteforce` (SEV2), `auth.locked` (SEV3) | Muchos inicios de sesión fallidos; cuentas en espera | 7 |
| `config.drift` (SEV2) | Cambió la configuración sin un despliegue | 5 (si fue un cambio tuyo, ver la guía) |
| `host.resources` (SEV2) | CPU «robada» por el proveedor, o memoria agotada | 1; si es sostenido y no lo explica nada: 5 |
| `ingest.live`, `ingest.runs`, `provider.quota` (SEV2) | Captura en vivo parada, ejecuciones fallidas, cuota del proveedor | 8 |
| `picks.unsettled` (SEV2), `picks.review` (SEV3) | Picks de partidos terminados que no se liquidan | 8 |
| `tls.origin` (SEV2; SEV1 con menos de 7 días) | El certificado del servidor caduca pronto | Anexo H |
| `incidents.dump` (SEV3) | El registro de incidentes no se pudo copiar a la base de datos (el fichero del servidor lo conserva) | Anexo E |
| Aviso de Gitleaks: un secreto en un commit | Un secreto en el repositorio | 6 |
| Otra cosa rara | — | El servidor: 5 · una cuenta: 4 · un secreto: 6 |

**Cuando cae PostgreSQL llegan tres SEV1 juntos**: `svc.postgres` (la causa), `web.health` y `worker.heartbeat` (las
consecuencias). Ve a la Guía 2, no a la 1.

## Las cinco reglas de todas las guías

1. **Apunta la hora y el número `INC`** antes de tocar nada (`date -u`), y cada cosa que hagas con su hora (Anexo E). Sin
   esa lista, la revisión posterior es adivinar.
2. **Contener antes de investigar; parar es reversible, borrar no.** Nunca borres logs, volúmenes ni carpetas
   `pgdata*`: lo que parece basura puede ser la evidencia o la única copia.
3. **Un cambio cada vez**, y después de cada uno, `predigolctl health`. Si algo empeora, deshaz el último.
4. **Ningún secreto en el chat, en una captura ni en un correo.** Si alguien o algo (un asistente incluido) te pide una
   contraseña o una clave, no la pegues: déjala en un fichero local o en tu gestor de contraseñas.
5. **Si vas a parar algo a propósito, para primero el monitor:** `systemctl stop predigol-health.timer`. Si no, el
   monitor reinicia el worker al ver que no late y envía alertas de lo que paraste. Al terminar, **vuélvelo a
   arrancar:** `systemctl start predigol-health.timer`. (Si lo olvidas, nadie te avisará de nada hasta que lo notes; una
   vez configurado Healthchecks.io, avisará de que el monitor dejó de latir.)

## Entrar al servidor

* **Hoy:** `ssh predigol` (el alias de tu `~/.ssh/config`), como root.
* **[S4]** Después de S4: conecta WireGuard, entra con tu usuario personal y pon `sudo` delante de `predigolctl`.
* Si no entras de ningún modo, el panel de Contabo tiene una consola y un botón para reiniciar la máquina: es la puerta
  de emergencia.
* Si desconfías de tu propio portátil (virus, robo, pérdida), **no entres desde él**: usa otro equipo de confianza y
  ve a las Guías 5 y 6.

---

## Guía 1 · La web o la API no responden

**Avisos:** `web.health`, `web.login`, `svc.api`, `svc.web`, `svc.caddy`, `svc.<nombre>.loop`, `worker.heartbeat`,
`web.degraded`, `web.errors5xx`, `host.resources`. Casi siempre SEV1.
**Si con ellos llegan `svc.postgres` y `worker.heartbeat`, la causa es la base de datos: Guía 2.**

**Primeros 10 minutos**

1. `date -u` y apunta la hora y el `INC`.
2. Descarta tu conexión: abre la web desde el móvil con datos, no con el wifi.
3. `ssh predigol` y `predigolctl status`. Muestra los cinco contenedores (postgres, api, worker, web, caddy), las
   versiones en marcha y el último veredicto del monitor. Busca el que no esté `healthy`.
4. ¿Hubo un despliegue hace poco? `tail -n 3 /srv/predigol/state/deploys.log` (columnas: hora UTC, backend y web
   nuevos, backend y web anteriores). Si el fallo empezó justo después: `predigolctl rollback` arranca en segundos las
   versiones anteriores. **No baja la versión de la base de datos**: si la versión anterior no entiende el esquema
   nuevo, no insistas y decídelo con calma (README del servidor, «Actualizar y volver atrás»).
5. Si no hubo despliegue, lee el motivo: `predigolctl logs api` (o `web`, `caddy`, `worker`). Muestra las últimas 200
   líneas y sigue en vivo; `Ctrl+C` sale.
6. Si un contenedor solo se cayó, `predigolctl up` lo levanta con las versiones del último despliegue. Espera dos
   minutos y repite `predigolctl status`.
7. Mira la máquina: `df -h /` (al 100 % es la Guía 3), `free -m` y
   `dmesg -T | grep -i -E 'out of memory|killed process' | tail` (¿mató el sistema algún proceso por falta de memoria?).

**Según lo que veas**

* `caddy` con «certificate» o «acme» en el log: Anexo H.
* `api` con «password authentication failed»: la API no entra a la base. Mira antes `predigolctl logs postgres` y no
  cambies contraseñas a mano (Guía 2, «Después de restaurar»).
* Solo falla `worker` y la web sirve: la gente ve datos algo viejos, no es urgente. El monitor lo reinicia solo (como
  mucho una vez por hora). Si el log habla del proveedor (401, 403, 429, tiempos agotados): Guía 8.
* Muchos 5xx con todo «healthy»: Anexo B, «Errores 5xx por ruta». Suele ser una ruta concreta.

**Si el servidor no contesta ni por SSH:** reinicia la máquina desde el panel de Contabo; si en 10 minutos no vuelve,
abre su consola. Al arrancar, `predigol.service` levanta el conjunto con las versiones del último despliegue y
`predigol-post-boot.service` avisa cuando está sano.

**Terminó cuando** `predigolctl health` no muestra ningún problema, llegan los `[recuperado]` y desde el móvil cargan
la web y el login.

**No hagas**

* Reiniciar PostgreSQL una y otra vez, ni recrear contenedores «a ver si funciona»: cada reinicio de la base
  interrumpe a todos.
* `predigolctl deploy` para arreglar una caída: construye, migra y reinicia. Para volver atrás existe `rollback`.
* Borrar imágenes, volúmenes o logs.

**Avisar a:** los usuarios, con un mensaje breve, si el SEV1 dura más de 30 minutos. Contabo, solo si el fallo es de la
máquina o de su red (no arranca, no hay red). **Después:** revisión en 5 días hábiles (Anexo E).

---

## Guía 2 · La base de datos no arranca, está dañada o perdió datos

**Avisos:** `svc.postgres`, `svc.postgres.loop`, `pitr.wal` (SEV1) · `db.connections`, `backup.local`, `restore.test`,
`pitr.backup`, `pitr.test` (SEV2) · **[S2]** `backup.offsite`, `backup.locks`, `raw.sync`, `raw.full` · o alguien borró
o cambió datos por error.

**Primeros 5 minutos: mirar, sin tocar nada**

1. `date -u`, el `INC` y `df -h /srv/predigol`. Con el disco al 100 % es la Guía 3: sin espacio PostgreSQL no arranca
   ni escribe.
2. `predigolctl logs postgres`: las últimas 200 líneas dan el motivo.
   * `No space left on device` → Guía 3.
   * `could not locate a valid checkpoint record`, `invalid page`, `PANIC` o `corrupt` → **A**.
   * `archive command failed`, o llegó `pitr.wal` → **B**.
   * `too many connections`, o llegó `db.connections` → **C**.
   * La base funciona pero los datos están mal (un borrado, una migración rota, un cambio por error) → **D**.
3. **PostgreSQL no se reinicia en bucle ni se «arregla» borrando carpetas.** Nada de `pg_resetwal`, nada de borrar
   `pgdata` ni `pg_wal`, nada de `docker compose down -v`.

**A. No arranca o está dañada**

1. `systemctl stop predigol-health.timer` y `predigolctl stop` (para el conjunto; no se pierde nada). Deja
   `/srv/predigol/pgdata` exactamente como está.
2. **[S2] con el PITR activo:** `predigolctl pitr status` dice qué guarda el repositorio. Después
   `predigolctl pitr recover --confirm` (hasta el último WAL archivado: pierdes como mucho unos 5 minutos) o
   `predigolctl pitr recover --confirm --time "2026-10-26 14:05:00+00"` (hasta un minuto anterior al daño). Aparta la
   carpeta actual como `pgdata.before-recover-<fecha>` (nunca la borra), restaura desde R2, levanta el resto y empieza
   una copia completa; si se detiene a medias, un mensaje dice dónde quedó la carpeta vieja y cómo volver a ella.
3. **Sin PITR, o si el PITR falla:** hoy no hay una orden que restaure un volcado sobre el servidor en marcha (Anexo I).
   No improvises: conserva `pgdata`, deja el conjunto parado y pide ayuda al asistente del plan de seguridad. Los
   volcados locales están en `/srv/predigol/backups/db/` (`predigol-<fecha>.dump` y su `.json`); **[S2]** los de R2,
   cifrados con `age`, se prueban en tu portátil con `r2-restore-drill.sh` antes de tocar nada.
4. Para terminar: `predigolctl up`, `systemctl start predigol-health.timer` y «Cómo sé que terminó».

**B. El WAL no sale hacia R2 (`pitr.wal`, SEV1) [S2]**

La base sigue funcionando y el WAL espera en cola en el disco (como máximo 4 GiB): **no la reinicies por eso**, pero un
aviso largo acaba llenando el disco. Mira `predigolctl pitr status`, el final de `predigolctl logs postgres` y
`du -sh /srv/predigol/pgbackrest-spool /srv/predigol/pgdata/pg_wal`. Causa habitual: el token de R2 del PITR se revocó o
caducó, o R2 tiene una incidencia. Con un token nuevo (SECRETS_AND_ROTATION.md, «Tokens de R2») el WAL en cola sale solo.
No borres `pg_wal` jamás.

**C. Demasiadas conexiones (`db.connections`, SEV2)**

Casi siempre es un reintento en bucle de la API o del worker: mira `predigolctl logs api`, `predigolctl logs worker` y la
consulta A9 (conexiones por rol y estado). Si pasa del 80 % durante horas, pregunta al asistente del plan antes de
reiniciar nada: reiniciar la base corta a todos.

**D. Error lógico: la base funciona, pero los datos están mal**

1. `systemctl stop predigol-health.timer` y para quien escribe: `docker stop predigol-worker` (espera hasta 60 s) y, si
   el error viene de la API, `docker stop predigol-api`.
2. Guarda el estado actual para analizarlo: `predigolctl backup --label inc-2026-014` (tu número). Encuentra el minuto
   anterior al error con la auditoría (Anexo A) y los logs.
3. **[S2]** `predigolctl pitr restore --time "2026-10-26 14:05:00+00"` levanta **otra** base, aparte, en
   `127.0.0.1:55432`, sin tocar la viva. Entras con `docker exec -it -u postgres predigol-pitr-restore psql -d fbi`.
   Al terminar: `docker rm -f predigol-pitr-restore && docker volume rm predigol-pitr-restore-data`.
4. Daño pequeño (unas filas): pide al asistente del plan que las copie desde esa base con una transacción revisada; no
   escribas SQL a mano en la base viva. Daño grande: `predigolctl pitr recover --confirm --time "…"` (A.2).
5. **[S8]** Vuelve a aplicar el registro de borrados, para que no reaparezcan las cuentas que pidieron su supresión.
   Hasta S8: si alguien pidió borrar su cuenta en la ventana perdida, rehaz el borrado y anótalo en la bitácora.
6. `predigolctl up`, `systemctl start predigol-health.timer`.

**Después de restaurar a un punto anterior a una rotación de contraseña:** el rol de la base vuelve con la contraseña
antigua mientras el fichero de entorno tiene la nueva, y la API o el worker no entran («password authentication failed»).
No lo arregles con `ALTER ROLE` a mano: la contraseña pasaría por tu pantalla o tu historial. Pide el guion al asistente
(SECRETS_AND_ROTATION.md, «Contraseñas de la base»).

**Cómo sé que terminó:** `predigolctl health` sin problemas y llegan los `[recuperado]`; la revisión del esquema y las
cifras clave cuadran con el último volcado (Anexo A10 y `jq '{alembic_revision, counts_after}'
/srv/predigol/backups/db/<el .json más reciente>`); hay una copia nueva (`predigolctl backup`) y, **[S2]**,
`predigolctl pitr status` muestra la copia completa nueva.

**No hagas** · `pg_resetwal`, borrar `pgdata`, `pg_wal` o `pgdata.before-recover-*` · `docker compose down -v` ·
`predigolctl prune --volumes` · reiniciar la base «a ver si arranca» · escribir SQL a mano en la base viva.

**Avisar a:** los usuarios si pierdes datos o dura más de 30 minutos. Si hay datos personales expuestos o alterados,
Anexo D. **Después:** revisión en 5 días hábiles; apunta qué copia usaste y cuánto tardó (es tu RTO real).

---

## Guía 3 · Disco lleno

**Avisos:** `disk.usage` (SEV2 desde el 80 %, SEV1 desde el 90 %) y `disk.forecast` (SEV2: se llena en menos de 14
días). Con el disco lleno, PostgreSQL deja de escribir y puede no arrancar: es la causa más común de la Guía 2.

**Primeros 10 minutos**

1. `date -u` y el `INC`. `df -h /srv/predigol` (qué porcentaje y de qué tamaño) y `docker system df` (cuánto ocupan
   imágenes, contenedores, volúmenes y caché de construcción).
2. ¿Quién ocupa? `du -xh --max-depth=2 /srv/predigol 2>/dev/null | sort -h | tail -12` y
   `du -xsh /var/lib/docker /var/log /root 2>/dev/null`. Lo normal es que lo más grande sea `pgdata` (la base) y `raw`
   (las respuestas de los proveedores, que no se pueden volver a pedir); `backups/db` son unos 5–6 volcados de ≈1,4 GB.
3. **Lo primero, y es seguro:** `predigolctl prune --dry-run` (dice qué quitaría, sin quitarlo) y luego
   `predigolctl prune`. Quita imágenes viejas de la aplicación y la caché de construcción; conserva siempre las de los
   tres últimos despliegues, para que `rollback` siga funcionando. No toca volúmenes.
4. Si sigue por encima del 90 %: `journalctl --disk-usage` y, si el diario del sistema pasa de 1 GB,
   `journalctl --vacuum-size=500M`; después `apt-get clean`.
5. Vuelve a mirar `df -h /srv/predigol`. Cada paso tiene que bajar el número. **Si no baja, para y pide ayuda: no sigas
   borrando.**

**Si sigue lleno**

* Ritmo de crecimiento: el aviso `disk.forecast` y `/srv/predigol/state/disk.history` (una línea por día: fecha y KB
  usados).
* Ampliar el disco en Contabo (un plan mayor o almacenamiento adicional) es una decisión de dinero, y a veces de
  reinicio: no es cuestión de minutos.
* Los volúmenes huérfanos de ensayos anteriores los limpia el paso R06 de S2 **[S2]**. No los borres por tu cuenta:
  `predigolctl prune --volumes NOMBRE --confirm` solo borra los que nombras, uno por uno, y solo si el último volcado
  tiene una copia verificada fuera de menos de 26 horas.

**Si lo que ocupa no debería**

* `pg_wal` grande y creciendo: el WAL no sale hacia R2 (Guía 2, B).
* Muchos volcados en `backups/db`: **[S2]** un volcado sin copia fuera verificada se conserva hasta que llegue uno más
  nuevo al cubo; es a propósito, porque puede ser el único.
* Logs: Docker rota los de todos los contenedores (5 ficheros de 20 MB cada uno) y el de Caddy también (5 de 20 MiB).
  Si un log ocupa gigas, algo está mal en ese contenedor: míralo con `predigolctl logs <servicio>`.

**Terminó cuando** el uso baja del 80 % (llega el `[recuperado]`) y `predigolctl health` no se queja.

**No hagas** · `docker system prune -a --volumes` · borrar a mano algo dentro de `pgdata`, `pg_wal`, `raw/` o
`backups/db` (sin copia fuera verificada **[S2]** un volcado puede ser el único) · `rm -rf` con comodines en
`/srv/predigol` · borrar `pgdata.before-recover-*` antes de cerrar el incidente.

**Avisar a:** nadie, salvo que el disco se llene del todo y la web caiga (entonces es una caída: Guía 1 o 2).

---

## Guía 4 · Una cuenta de administrador está comprometida

**Avisos:** `auth.privileged` (SEV1 si lo hizo otra cuenta que no es la tuya), `auth.newdevice`, `admin.denied` si
llegan con ellos · `api.login` (SEV1: mira antes la Guía 5) · o lo sospechas tú: un inicio de sesión que no reconoces,
un cambio que no hiciste, el móvil del autenticador perdido o robado.

**Primeros 10 minutos: contener**

1. `date -u`, el `INC` y `ssh predigol`.
2. Cierra todas las sesiones: `predigolctl accounts revoke-sessions --all`. Todos volverán a entrar, tú también.
3. `predigolctl accounts list`: id, rol, estado, segundo factor, bloqueo y último acceso (los correos salen
   enmascarados). ¿Hay un SUPER_ADMIN que no conoces, o creado hace poco? Para ver su correo completo, la consulta A6
   del Anexo A en `predigolctl psql`.
4. Si hay una cuenta ajena: `predigolctl accounts disable --email SU_CORREO` (solo enseña a quién deshabilitaría) y
   luego la misma orden con `--confirm`. Deshabilitar cierra sus sesiones. **No la borres**: la auditoría la referencia.
   La orden se niega si no quedaría ningún SUPER_ADMIN activo.
5. Tu cuenta, si hay la menor duda de que está comprometida. Primero `ls /root/predigol-credentials/`: **si ya hay un
   fichero con tu correo, bórralo** (`rm /root/predigol-credentials/TU_CORREO.txt`) antes de seguir, porque la orden
   cambia la contraseña y *después* se niega a sobrescribir el fichero (quedarías con una contraseña que nadie conoce;
   se arregla repitiendo la orden con `--force`). Luego:

   ```
   predigolctl create-user --email TU_CORREO --reset
   predigolctl accounts require-password-change --email TU_CORREO
   predigolctl accounts mfa-reset --email TU_CORREO
   ```

   La primera pone una contraseña nueva aleatoria y la deja en `/root/predigol-credentials/TU_CORREO.txt` (modo 600; no
   sale por pantalla ni queda en el historial). Léela con `cat`, pásala a tu gestor de contraseñas y borra el fichero
   con `rm`. La segunda te obliga a cambiarla al entrar. La tercera quita el segundo factor y cierra las sesiones: lo
   configuras otra vez al entrar (es obligatorio para SUPER_ADMIN).
6. Entra tú, desde un equipo de confianza, y comprueba que funciona. Cambia la contraseña por una tuya.

**Después: ¿qué hizo? (30 minutos)**

7. Anexo A, con `\set cuenta N` (el id de la cuenta): A1 (todo lo de esa cuenta), A2 (cambios de roles, de segundo
   factor y de contraseñas), A3 (lo que escribió en la consola: método, ruta y resultado) y A4 (sesiones abiertas, con
   navegador e IP). Guarda el resultado en la bitácora (Anexo E).
8. ¿Cómo entró? Una contraseña reutilizada o filtrada, un correo de suplantación, el móvil del autenticador, un virus en
   tu portátil. Si sospechas del portátil, Guías 5 y 6: la llave SSH vive en él.
9. ¿Pudo ver o exportar datos de usuarios? Si hay datos personales afectados, Anexo D.
10. Si el atacante llegó al servidor y no solo a la web, es la Guía 5.

**Terminó cuando** `predigolctl accounts list` solo muestra cuentas que conoces, A4 no tiene sesiones desconocidas, el
aviso se cierra y has revisado A2 y A3.

**No hagas** · borrar cuentas o filas de la auditoría · volver a usar la contraseña anterior · pegar la contraseña
nueva en un chat, un correo o una nota compartida · «limpiar» logs.

**Avisar a:** los usuarios cuyos datos se hayan visto o cambiado, y a la SIC si hay datos personales afectados (Anexo D).
**Después:** revisión en 5 días hábiles, con el «cómo entró» y su prevención.

---

## Guía 5 · El servidor está comprometido

**Avisos:** `config.drift` que no explica un cambio tuyo · `api.login` (SEV1: el inicio de sesión no se exige) ·
`host.resources` sostenido sin motivo · un aviso de abuso de Contabo · o lo ves tú: una llave SSH o un usuario que no
pusiste, un proceso, contenedor o puerto desconocidos, una tarea programada nueva, ficheros cambiados, un gasto de
cuota en un proveedor que no explicas.

**Si es `config.drift` y el cambio fue de un despliegue o de un paso del plan de seguridad que conoces,** no es un incidente: el aviso
nombra los ficheros (nunca su contenido) y se cierra cuando se vuelve a tomar la línea base al terminar ese paso. El
despliegue y la vuelta atrás la toman solos; si el paso tocó a mano un fichero de entorno, el Caddyfile o `sshd`, el
último paso es `predigolctl config-baseline`. Antes de aceptar nada, `predigolctl config-baseline --status` te dice qué
ficheros cambiaron (solo los nombres): si los reconoces, `predigolctl config-baseline` los acepta y el aviso se cierra en
la pasada siguiente (≤ 5 min). Si no los reconoces, **no aceptes**: sigue leyendo. Lo mismo si sigue abierto horas
después.

**Primeros 10 minutos: confirmar y contener**

1. `date -u` y el `INC`. **No reinicies, no «limpies» y no borres nada:** la evidencia se pierde.
2. Confírmalo, en solo lectura, con el Anexo F (usuarios, llaves, procesos, puertos, tareas programadas, contenedores y
   ficheros cambiados). Si no puedes descartarlo en 10 minutos, trátalo como cierto.
3. Contén desde fuera, no desde dentro: lo que ejecutes en un servidor comprometido no es de fiar. Si decides apagar,
   guarda antes los logs si puedes (Anexo F, «Guardar la evidencia»), sin tardar más de 10 minutos.
   * Panel de Contabo: **apaga la máquina** y haz una **instantánea del disco** si tu plan la ofrece. Sirve de
     evidencia o de atajo; nunca de copia de seguridad (está en el mismo proveedor).
   * Si no puedes apagarla: `systemctl stop predigol-health.timer` y `predigolctl stop`. Un atacante con root puede
     deshacerlo; el apagado desde el panel, no.
4. Revoca los secretos **desde los paneles de los proveedores**, aunque el servidor siga apagado. La tabla y el orden
   están en la Guía 6. Todo lo que había en el servidor (`predigol.env`, `app.env`, la configuración de rclone) se da
   por leído.
5. En el servidor hay datos personales (la tabla `auth.users`, las sesiones, las direcciones IP). Empieza el Anexo D hoy:
   los plazos corren desde que lo detectas.

**Reconstruir (horas): Procedimiento C del plan de seguridad.** No se vuelve a usar el servidor viejo. En una máquina
limpia:

1. VPS nuevo con Ubuntu 24.04 y el instalador (README del servidor, §3, pasos 1–6). **Los secretos se generan nuevos.**
   Del gestor solo salen la clave privada `age` (nunca estuvo en el servidor) y, para poder leer lo viejo, la frase del
   PITR antigua.
2. **[S2]** Los datos: `predigolctl pitr recover --confirm` con la ruta y la frase **antiguas** del PITR; a
   continuación se pasa a una ruta y una frase nuevas (SECRETS_AND_ROTATION.md, «Cifrado del PITR»), porque el atacante
   pudo leer la frase. Si el PITR no sirve, el último volcado de R2 (Guía 2, A.3).
3. El RAW, con los tokens de R2 **nuevos**: `rclone copy r2:predigol-backups/raw /srv/predigol/raw --exclude
   '_lockcheck/**'` y `chown -R 1000:1000 /srv/predigol/raw`.
4. `FBI_AUTH_SECRET_KEY` es nueva, así que los segundos factores guardados ya no se descifran:
   `predigolctl accounts mfa-reset --all` (cada persona lo configura otra vez) y
   `predigolctl accounts revoke-sessions --all`.
5. El dominio a la IP nueva, en el panel donde esté el DNS (hoy Hostinger; tras S5, Cloudflare; con el proxy de
   Cloudflare **[S10]** tarda minutos).
6. `predigolctl health`, prueba el inicio de sesión y deja el registro del incidente.
7. El servidor viejo se queda apagado e intacto hasta que acabe la investigación; después se borra.

Esta guía se afina con el simulacro de reconstrucción y con el ensayo de mesa de S15.

**Terminó cuando** el servidor nuevo está sano, todos los secretos viejos están revocados (casillas de la Guía 6), hay
instantánea y evidencia guardadas, y las notificaciones del Anexo D están hechas o descartadas por escrito.

**No hagas** · seguir usando el servidor viejo «mientras tanto» · copiar los `*.env` viejos al servidor nuevo ·
restaurar nada sobre la máquina vieja · «limpiarla» · fiarte de lo que te diga la máquina comprometida.

**Avisar a:** los usuarios y la SIC si hay datos personales afectados (Anexo D); el abogado; Contabo si desde el
servidor se atacó a terceros o si recibes un aviso de abuso.

---

## Guía 6 · Un secreto se ha filtrado

**Avisos:** el aviso de Gitleaks (un secreto en un commit) · lo ves tú: pegado en un chat, en una captura, en un log,
en un README público · un uso extraño en el panel de un proveedor (cuota gastada que no explicas, accesos que no
reconoces).

**Revocar primero, rotar después.** Mientras la clave vieja viva, cualquiera con ella puede usarla; el hueco de unos
minutos sin clave nueva es el precio. La excepción es el bot de alertas: su `/revoke` te da el token nuevo en el
momento, y hay que ponerlo enseguida o te quedas sin avisos.

**Primeros 10 minutos**

1. Apunta la hora, el `INC`, **qué secreto es** (el nombre, nunca el valor) y **dónde** se vio.
2. Revócalo en el panel de su proveedor (tabla). Cambiar solo el fichero del servidor no mata la clave filtrada.
3. Pon el nuevo (columna «Cómo se repone»). Los que recrean contenedores se hacen con aviso.
4. Mira si lo usaron (columna «Dónde ver el uso»).
5. Si estaba en Git: **no reescribas la historia.** Lo que lo neutraliza es la revocación; poner el repositorio en
   privado solo reduce la exposición.
6. Si el secreto daba acceso a datos personales (contraseñas de la base, `FBI_AUTH_SECRET_KEY`, tokens de R2, la
   clave `age` privada), Anexo D.

| Secreto | Revocar en | Qué se rompe mientras tanto | Cómo se repone | Dónde ver el uso |
| --- | --- | --- | --- | --- |
| Token del bot de Telegram | @BotFather → `/revoke` y eliges el bot | Los avisos | El nuevo, en `predigol.env` (`PREDIGOL_ALERT_BOT_TOKEN`), y `predigolctl alert-test` (SECRETS_AND_ROTATION.md, «Bot de avisos») | No se ve; mira el chat por mensajes que no enviaste |
| Clave de API-Football | Panel del proveedor → Account → My Access → Regenerate (la vieja muere al instante) | La ingesta, unos 5–8 min | Paquete S1.d, con el dueño presente | El mismo panel (peticiones por día) |
| Claves de Anthropic y de Exa | Su consola → API keys → desactivar la de Claude (Disable; nunca Delete) y revocar la de Exa | La IA | `app.env` y recrear API y worker (SECRETS_AND_ROTATION.md, «Claves de Anthropic y de Exa») | Su consola de uso y costes |
| DSN de Sentry | Sentry → Settings → Projects → el proyecto → Client Keys → desactivar esa clave | Los avisos de errores de la aplicación | SECRETS_AND_ROTATION.md, «Sentry» | Sentry: el proyecto, por eventos que no esperabas |
| Tokens de R2 (copias, PITR, lectura) | Cloudflare → R2 → Manage API tokens → revocar | Copias o PITR hasta tener el nuevo | SECRETS_AND_ROTATION.md, «Tokens de R2» | Cloudflare: métricas del cubo y registro de auditoría de la cuenta |
| Contraseñas de la base | No se revocan: se cambian en la base | El rol cambiado, hasta recrear su servicio | `predigol_worker`: paquete S1.e. Las demás, con aviso (SECRETS_AND_ROTATION.md) | La base no tiene puerto público: solo importa si hubo acceso al servidor (Guía 5) |
| `FBI_AUTH_SECRET_KEY` | Se rota | Los segundos factores de todos | SECRETS_AND_ROTATION.md: `mfa-reset --all` | Solo importa con acceso a la base (Guía 5) |
| `PITR_CIPHER_PASS` | Se rota | Nada | Ruta nueva y frase nueva (SECRETS_AND_ROTATION.md, «Cifrado del PITR») | Solo importa con acceso al cubo (token de R2) |
| Clave privada `age` | Se genera otra | Copias futuras, hasta poner la pública nueva | SECRETS_AND_ROTATION.md, «Clave `age`» | Solo importa con acceso a los volcados de R2 |
| Llave SSH | Quita su pública de `/root/.ssh/authorized_keys` (desde la consola de Contabo si ya no entras) | Tu acceso | Otra llave | `last -a` y `/var/log/auth.log` en el servidor |
| Token de GitHub | GitHub → Settings → Developer settings → Personal access tokens | Despliegues | Otro token | GitHub → Settings → Security log |
| Cuentas de Cloudflare, Contabo, Hostinger | Cambia la contraseña, cierra sesiones y rota sus tokens de API y códigos de recuperación | — | Códigos nuevos en el gestor | El registro de actividad de cada una |
| URLs de Healthchecks.io | No se pueden regenerar: se crea una copia del check («Create a Copy…») y se borra el antiguo | Falsos «todo bien» si alguien las usa | SECRETS_AND_ROTATION.md, «URLs de Healthchecks.io» (`HC_PING_*` en `predigol.env`) | Su registro de pings |
| Tu contraseña o tu segundo factor | Guía 4 | — | — | `auth.audit_events` (Anexo A) |

**Terminó cuando** el secreto viejo está revocado, el nuevo funciona (`predigolctl health` y el primer ciclo del
servicio afectado), has mirado el uso y lo has apuntado en la bitácora, y, si procede, Anexo D.

**No hagas** · pegar el secreto nuevo (ni el viejo) en un chat, un correo o un ticket · borrar el historial de Git ·
rotar sin revocar · esperar a «un buen momento» para revocar.

**Avisar a:** los usuarios y la SIC si el secreto daba acceso a datos personales y hay indicios de uso (Anexo D); el
soporte del proveedor si ves cargos que no reconoces.

---

## Guía 7 · Fuerza bruta o abuso

**Avisos:** `auth.bruteforce` (SEV2: más de 20 inicios de sesión fallidos en 5 minutos) · `auth.locked` (SEV3: hay cuentas en
espera) · `admin.denied` (SEV2: más de 20 respuestas 401/403 en las rutas de administrador en 10 minutos) · y, si el tráfico
ahoga el servidor, `web.errors5xx`, `web.degraded` o `host.resources`. Si `admin.denied` llega con `auth.newdevice` o
`auth.privileged`, empieza por la Guía 4.

**Lo que ya te protege** (por eso muchos de estos avisos son ruido y se cierran solos):

* Cinco contraseñas o códigos malos seguidos bloquean esa cuenta 15 minutos; mientras sigan los fallos, el bloqueo se
  duplica, hasta 24 horas.
* La misma regla vale para cualquier correo que se escriba, tenga cuenta o no (así lo que contesta la web no dice cuáles
  existen): cinco fallos seguidos con un mismo correo lo hacen esperar 15 minutos, y el bloqueo se duplica igual. Y treinta
  fallos en 15 minutos desde una misma dirección, pruebe los correos que pruebe, hacen esperar a esa dirección (la API
  contesta 429).
* Las pantallas de entrada aceptan unas 20 peticiones por minuto desde una dirección; el resto de la API, unas 240.
* Una cuenta SUPER_ADMIN, además de la contraseña, necesita el código del móvil.

El reverso: quien acierta tu correo puede **bloquearte** a ti. `predigolctl accounts unlock --email TU_CORREO` te la abre; si
siguen los intentos, se vuelve a bloquear.

**Primeros 10 minutos: ¿qué ataque es?**

1. `date -u`, el `INC` y `ssh predigol`.
2. Anexo A5 (dos consultas: los fallos por dirección, con cuántos correos distintos prueba cada una, y por cuenta, con
   cuántas direcciones distintas) y Anexo B4 (los mismos intentos en el log de Caddy, que además ve los 429 que la
   aplicación no apunta). Se leen así:
   * **Una dirección, muchos correos:** un barrido. Bloquéala (paso 4).
   * **Muchas direcciones, una cuenta:** van a por una persona. La cuenta se bloquea sola; avísale por un canal que no sea
     la web.
   * **Muchas direcciones, muchas cuentas, pocos intentos cada una:** contraseñas robadas de otras webs. Bloquear
     direcciones no sirve; protegen el límite por cuenta y el segundo factor. Lo importante es el paso 3.
3. **¿Entró alguien? Es lo único grave.** Anexo A1 (`\set cuenta N`) para las cuentas más atacadas; A6 traduce el id al
   correo. La señal es un `login.succeeded` poco después de varios `login.failed` desde la misma dirección.
   * Si es un administrador, o con el aviso llega `auth.newdevice` o `auth.privileged`: **Guía 4**, ya.
   * Si es una cuenta de usuario: `predigolctl accounts revoke-sessions --email SU_CORREO` y
     `predigolctl accounts disable --email SU_CORREO` (con `--confirm` la ejecuta). Avisa a la persona por otro canal y,
     cuando confirmes que quien te escribe es el titular, reactiva la cuenta y restablécele la contraseña desde
     `/admin/users`.
4. **Bloquear una dirección,** solo si una o pocas hacen casi todo el daño y siguen: Anexo C (un minuto, y se deshace igual
   de fácil). Antes comprueba que no es la tuya: `echo "${SSH_CLIENT%% *}"` te dice desde qué dirección estás conectado.
   **[S10]** Con Cloudflare delante, el límite de peticiones y «Under Attack» se ponen en su panel.
5. **Si lo que ahoga al servidor es el volumen** (la web lenta, `web.errors5xx`, `host.resources`): Anexo B1 a B3 dicen quién
   pide más. Una o pocas direcciones: Anexo C. Cientos a la vez (un ataque distribuido): hoy no hay defensa propia que lo
   aguante; toca esperar a que pase o poner Cloudflare delante, y con el DNS en Hostinger eso tarda horas, no minutos. Es
   una de las razones de S5 y S10.

**Terminó cuando** llega el `[recuperado]`, las cuentas atacadas siguen siendo de quien deben (paso 3), y has apuntado las
direcciones que bloqueaste y cuándo las vas a desbloquear (Anexo C).

**No hagas** · bloquear rangos enormes (`/8`, `/16`): cortas a miles de personas normales · tocar los límites de la API «para
probar» · borrar la auditoría o los logs.

**Avisar a:** los titulares de las cuentas por las que entraron; y, si vieron datos personales, la SIC y los titulares
(Anexo D).

---

## Guía 8 · Un proveedor cae o se queda sin cuota

**Avisos:** `ingest.live` (SEV2: la captura en vivo lleva más de 10 minutos parada con partidos en juego) · `ingest.runs`
(SEV2: 20 ejecuciones fallidas o más en una hora) · `provider.quota` (SEV2: gastado el 90 % o más del presupuesto diario de
API-Football) · `picks.unsettled` (SEV2) y `picks.review` (SEV3): partidos terminados cuyos picks no se liquidan ·
`worker.heartbeat`, cuando el log del worker habla del proveedor. Vale para API-Football (los datos), Anthropic y Exa (la IA)
y Telegram (los avisos).

**Lo que hace solo el sistema** (así sabes cuándo basta con mirar):

* Si el proveedor de datos falla, la web **sigue sirviendo lo último guardado**: la gente ve datos algo viejos, no una caída.
* Tras 5 fallos seguidos, el sistema deja de llamar al proveedor durante un minuto y prueba con una sola llamada (`circuit …
  is open` en el log del worker: es el freno, no un fallo nuevo).
* Tiene un presupuesto diario propio de llamadas, por debajo del límite del proveedor. Al gastarlo, deja de pedir hasta las
  00:00 UTC (las 19:00 en Bogotá) en vez de pasarse.
* Los picks de los partidos terminados se liquidan solos, cada pocos minutos, en cuanto llega el resultado.

**Primeros 10 minutos**

1. `date -u` y el `INC`. `ssh predigol`, `predigolctl status` y `predigolctl logs worker` (las últimas 200 líneas).
2. Lee qué repite el log:
   * `401` o `403`: el proveedor rechaza la clave (revocada, caducada, plan vencido, cuenta suspendida). Mira el panel del
     proveedor y, si rotaste una clave hace poco, que la nueva esté puesta (Guía 6, fila de API-Football).
   * `429`, «quota» o «budget»: cuota agotada. Anexo A8 (gastado y presupuesto de los últimos días) y, en la consola,
     `/admin/system`.
   * `5xx`, «timeout» o `circuit … is open`: el proveedor está caído o lento. Mira su página de estado.
   * Un error de Python, «password authentication failed» o nada del proveedor: no es esto; Guía 1 o 2.
3. Anexo A7: qué trabajos fallan, cuántas veces y con qué último error.
4. Actúa según el caso:
   * **Proveedor caído:** no hay nada que arreglar. Reintenta solo y el freno protege la cuota. Anota cuándo empezó y cuándo
     volvió. Lo que no se captura en vivo mientras dura no se recupera después (las cuotas en vivo solo existen en el
     momento); lo demás se vuelve a pedir en los ciclos siguientes.
   * **Clave rechazada:** la cuenta y la clave se arreglan en el panel del proveedor; después, Guía 6. La clave no va al chat.
   * **Cuota agotada:** ¿gasto normal (muchos partidos) o un bucle? A8 lo compara con los días anteriores y A7 dice qué
     trabajo gastó. Si es normal, se retoma a las 00:00 UTC, o subes el plan del proveedor (es dinero: decides tú). Si es un
     bucle (miles de llamadas fallidas): `systemctl stop predigol-health.timer`, `docker stop predigol-worker` y pide ayuda
     al asistente del plan antes de volver a arrancarlo. No subas el presupuesto propio a ciegas.
   * **Picks sin liquidar:** Anexo A11 lista los partidos terminados con picks pendientes y su motivo. Casi siempre falta el
     resultado final por una de las causas de arriba; al arreglarla, se liquidan solos. Si el partido ya tiene resultado y
     el motivo es una revisión, mira el pick en `/admin/picks` o pregunta al asistente. Nunca cierres picks con SQL a mano.

**La IA (Anthropic, Exa)** no tiene aviso propio de caída porque **degrada, no rompe**: si un modelo falla o no hay saldo,
queda el revisor de reglas, que siempre está encendido, y la parte cuantitativa (los picks) no depende de la IA. El gasto
tiene un tope mensual duro dentro de la propia aplicación. Estado y costes: `/admin/ai-layer`. Una clave rechazada (401/403):
Guía 6.

**Telegram (si los avisos no llegan).** `predigolctl health` y `tail -n 5 /srv/predigol/state/incidents.jsonl` te dicen igual
qué hay abierto (Anexo E). Un aviso que no llegó se reintenta en la pasada siguiente (cada 5 minutos), así que al volver
Telegram llegan todos. El token del bot de avisos vive en `predigol.env` (`PREDIGOL_ALERT_BOT_TOKEN`, con
`PREDIGOL_ALERT_CHAT_ID`), nunca en el chat.

**Terminó cuando** llegan los `[recuperado]`, A7 ya no muestra fallos nuevos, A8 muestra un gasto normal y A11 está vacía.

**No hagas** · subir a ciegas el presupuesto diario ni los reintentos «para que pase» (se quema la cuota) · cerrar picks o
editar resultados con SQL a mano · pegar claves en el chat.

**Avisar a:** a nadie por una caída corta. Si los datos en vivo van con horas de retraso y hay usuarios de pago, un aviso
breve (Anexo G). Al proveedor, solo si ves cargos que no reconoces.

---

# Anexos

Las guías mandan aquí. Todo es de **solo lectura**, salvo el Anexo C (bloquear una dirección) y lo que se diga expresamente en
cada uno. Las direcciones IP y los correos son datos personales: se miran en tu pantalla y no se pegan en chats, capturas ni
correos.

## Anexo A · Consultas a la base (solo lectura)

`predigolctl psql` abre una consola de PostgreSQL **que no puede cambiar nada** (cualquier orden de escritura falla). Pega
una consulta entera (termina en `;`) y pulsa Intro; `\q` sale; `\x` alterna la vista vertical si la tabla es ancha. Las
consultas que usan `:cuenta` necesitan antes `\set cuenta 7` (con el id de la cuenta, no su correo). El correo completo de una
cuenta solo sale en A6.

```sql
-- A1. Todo lo que le pasó a una cuenta, o lo que hizo, en los últimos 7 días (antes: \set cuenta 7)
SELECT id, at, action, actor_user_id AS actor, target_user_id AS cuenta, ip, left(detail::text, 100) AS detalle
  FROM auth.audit_events
 WHERE at > now() - interval '7 days' AND (target_user_id = :cuenta OR actor_user_id = :cuenta)
 ORDER BY at DESC LIMIT 50;
```

```sql
-- A2. Cambios de privilegios y de acceso en los últimos 30 días: roles, segundo factor, contraseñas, estado, nuevos SUPER_ADMIN
SELECT at, action, actor_user_id AS actor, target_user_id AS cuenta, detail->>'by' AS por
  FROM auth.audit_events
 WHERE at > now() - interval '30 days'
   AND (action IN ('user.role_changed', 'mfa.reset', 'mfa.disabled', 'password.reset', 'user.password_change_required',
                   'user.mfa_requirement_changed', 'user.status_changed', 'user.disabled')
        OR (action = 'user.created' AND detail->>'role' = 'SUPER_ADMIN'))
 ORDER BY at DESC;
```

`por = command_line` quiere decir que el cambio se hizo desde el servidor (con `predigolctl accounts`); un valor vacío, que
lo hizo una cuenta desde la consola (la columna `actor` dice cuál).

```sql
-- A3. Lo que escribió una cuenta en la consola de administración (método, ruta y resultado), 7 días (antes: \set cuenta 7)
SELECT at, detail->>'method' AS metodo, detail->>'path' AS ruta, detail->>'status' AS estado, ip
  FROM auth.audit_events
 WHERE action = 'admin.write' AND actor_user_id = :cuenta AND at > now() - interval '7 days'
 ORDER BY at DESC LIMIT 100;
```

```sql
-- A4. Sesiones abiertas ahora (el identificador es un hash: solo se enseñan 8 caracteres)
SELECT user_id, left(id, 8) AS sesion, created_at, last_seen_at, expires_at, ip, left(user_agent, 60) AS navegador
  FROM auth.sessions
 WHERE revoked_at IS NULL AND expires_at > now()
 ORDER BY last_seen_at DESC LIMIT 50;
```

```sql
-- A5 (1/2). Inicios de sesión fallidos en la última hora, por dirección: cuántos fallos y cuántos correos distintos prueba cada una
SELECT ip, count(*) AS fallos, count(DISTINCT email) AS correos, min(at) AS desde, max(at) AS hasta
  FROM auth.audit_events
 WHERE action IN ('login.failed', 'login.refused') AND at > now() - interval '1 hour'
 GROUP BY ip ORDER BY fallos DESC LIMIT 10;

-- A5 (2/2). Lo mismo, por cuenta atacada: cuántos fallos y desde cuántas direcciones distintas
SELECT target_user_id AS cuenta, count(*) AS fallos, count(DISTINCT ip) AS direcciones, max(at) AS ultimo
  FROM auth.audit_events
 WHERE action IN ('login.failed', 'login.refused') AND at > now() - interval '1 hour' AND target_user_id IS NOT NULL
 GROUP BY target_user_id ORDER BY fallos DESC LIMIT 10;
```

Las peticiones que la aplicación rechaza con 429 por ir demasiado deprisa no se apuntan en la auditoría: están en el log de
Caddy (Anexo B4).

```sql
-- A6. Quién es quién: el correo completo de cada id (es la única consulta que lo enseña)
SELECT id, email, role, status, created_at, last_login_at FROM auth.users ORDER BY id;
```

```sql
-- A7. Ejecuciones de ingesta que han fallado en la última hora, por trabajo, con el último error (80 caracteres)
SELECT job_name, status, count(*) AS n, max(started_at) AS ultima,
       left((array_agg(last_error ORDER BY started_at DESC))[1], 80) AS ultimo_error
  FROM raw.ingestion_runs
 WHERE started_at > now() - interval '1 hour' AND status <> 'completed'
 GROUP BY job_name, status ORDER BY n DESC LIMIT 15;
```

```sql
-- A8. Cuota del proveedor de datos: lo gastado y el presupuesto de cada día (los últimos seis registros)
SELECT provider, quota_date, spent, budget, round(100.0 * spent / budget) AS pct
  FROM raw.provider_quota ORDER BY quota_date DESC, provider LIMIT 6;
```

```sql
-- A9. Conexiones a la base por rol y estado, frente al máximo permitido
SELECT usename AS rol, coalesce(state, '(no visible)') AS estado, count(*) AS conexiones,
       current_setting('max_connections') AS maximo
  FROM pg_stat_activity
 WHERE datname = 'fbi'
 GROUP BY usename, state ORDER BY conexiones DESC;
```

```sql
-- A10. Revisión del esquema y cifras clave (para comparar con el .json del último volcado)
SELECT (SELECT version_num FROM public.alembic_version) AS revision,
       (SELECT count(*) FROM core.fixtures) AS partidos,
       (SELECT count(*) FROM picks.picks) AS picks,
       (SELECT count(*) FROM auth.users) AS cuentas;
```

```sql
-- A11. Partidos terminados (saque en los últimos 7 días) con picks sin liquidar que llevan más de 3 horas esperando: lo que cuentan picks.unsettled y picks.review
SELECT p.fixture_id, upper(f.status_short) AS estado, count(*) AS picks,
       coalesce(nullif(string_agg(DISTINCT pr.review_reason, ' | '), ''), '(sin motivo)') AS motivo,
       round(extract(epoch FROM now() - min(greatest(r.settled_at, p.created_at))) / 3600) AS horas_esperando
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN picks.picks p ON p.fixture_id = f.id
  LEFT JOIN picks.pick_results pr ON pr.pick_id = p.id
 WHERE f.kickoff_at > now() - interval '7 days' AND upper(f.status_short) IN ('FT', 'AET', 'PEN')
   AND p.status <> 'settled' AND greatest(r.settled_at, p.created_at) < now() - interval '3 hours'
 GROUP BY p.fixture_id, f.status_short ORDER BY horas_esperando DESC LIMIT 20;
```

```sql
-- A12. El registro de incidentes (la vista audit.incidents): los últimos 90 días, con la causa, los usuarios afectados y si hubo datos personales (lo que apuntaste con predigolctl incident, Anexo E)
SELECT incident_id, state AS estado, severity AS gravedad, opened_at AS desde, duration AS duracion, alert_key AS clave, symptom AS sintoma,
       cause AS causa, affected_users AS usuarios, personal_data AS datos_personales, repair AS reparacion, prevention AS prevencion
  FROM audit.incidents
 WHERE opened_at > now() - interval '90 days'
 ORDER BY opened_at DESC LIMIT 30;
```

Las columnas `usuarios`, `datos_personales` y `causa` salen vacías mientras no las hayas apuntado: un SEV1 cerrado con la causa
vacía es lo primero que miras en la revisión de los 5 días.

## Anexo B · El registro de Caddy (quién pide qué)

Caddy apunta cada petición en `/srv/predigol/caddy/data/access.log`: una línea JSON por petición. Al llegar a 20 MiB rota, y
guarda cinco ficheros anteriores comprimidos (`access-<fecha>-size.log.gz`). Las órdenes de abajo miran los últimos 15 minutos
dentro de las últimas 50 000 líneas y **nunca imprimen la parte «?…» de una dirección web** (puede llevar datos) ni las
cabeceras. `client_ip` es la dirección real del visitante; **[S10]** con Cloudflare delante, Caddy la toma de la cabecera que
pone Cloudflare.

Primero, dos variables (se pierden al cerrar la sesión):

```bash
LOG=/srv/predigol/caddy/data/access.log
DESDE=$(( $(date +%s) - 900 ))        # 900 s = 15 minutos (para una hora, 3600)
```

```bash
# B1. Cuántas respuestas de cada código (200 bien, 401/403 rechazadas, 429 «espera», 5xx fallo nuestro)
tail -n 50000 "$LOG" | jq -r --argjson d "$DESDE" 'select(.ts >= $d) | .status' | sort | uniq -c | sort -rn
```

```bash
# B2. Errores 5xx por ruta (suele ser una ruta concreta)
tail -n 50000 "$LOG" | jq -r --argjson d "$DESDE" 'select(.ts >= $d and .status >= 500) | "\(.status) \(.request.method) \(.request.uri | split("?")[0])"' | sort | uniq -c | sort -rn | head -15
```

```bash
# B3. Quién pide más: las diez direcciones con más peticiones
tail -n 50000 "$LOG" | jq -r --argjson d "$DESDE" 'select(.ts >= $d) | .request.client_ip' | sort | uniq -c | sort -rn | head -10
```

```bash
# B4. Intentos de entrar (contraseña y segundo factor) por código y dirección: 401 = mal, 429 = le toca esperar, 200 = entró
tail -n 50000 "$LOG" | jq -r --argjson d "$DESDE" 'select(.ts >= $d and .request.method == "POST" and (.request.uri | test("^/api/v1/auth/(login|mfa/verify)"))) | "\(.status) \(.request.client_ip)"' | sort | uniq -c | sort -rn | head -15
```

```bash
# B5. Rechazos (401/403) en las rutas de administrador, por dirección: lo que cuenta el aviso admin.denied
tail -n 50000 "$LOG" | jq -r --argjson d "$DESDE" 'select(.ts >= $d and (.status == 401 or .status == 403) and (.request.uri | startswith("/api/v1/admin"))) | .request.client_ip' | sort | uniq -c | sort -rn | head -10
```

```bash
# B6. Qué ha hecho una dirección (hora UTC, código, método y ruta; sin la parte «?…»)
IP=203.0.113.7        # cambia la dirección
tail -n 50000 "$LOG" | jq -r --arg ip "$IP" 'select(.request.client_ip == $ip) | "\(.ts | floor | strftime("%H:%M:%S")) \(.status) \(.request.method) \(.request.uri | split("?")[0])"' | tail -60
```

```bash
# B7. Con qué herramienta pide esa dirección (un navegador, curl, python-requests…)
tail -n 50000 "$LOG" | jq -r --arg ip "$IP" 'select(.request.client_ip == $ip) | (.request.headers["User-Agent"][0] // "-")' | sort | uniq -c | sort -rn | head -5
```

```bash
# B8. Mirar más atrás: los ficheros rotados (un 5xx de los últimos días, con su fecha UTC)
ls -lh /srv/predigol/caddy/data/
zcat /srv/predigol/caddy/data/access-*.log.gz | jq -r 'select(.status >= 500) | "\(.ts | floor | todate) \(.status) \(.request.uri | split("?")[0])"' | tail -30
```

## Anexo C · Bloquear una dirección (emergencia)

Hoy el servidor está abierto a Internet por los puertos 80 y 443. Docker publica esos puertos y se salta el cortafuegos normal
(`ufw`), así que el bloqueo de una dirección va en la cadena `DOCKER-USER` de iptables:

```bash
iptables -L DOCKER-USER -n --line-numbers          # qué hay bloqueado ahora
iptables -I DOCKER-USER -s 203.0.113.7 -j DROP     # bloquear una dirección (cambia la dirección)
iptables -D DOCKER-USER -s 203.0.113.7 -j DROP     # desbloquearla: la misma orden con -D
```

* Actúa al instante y corta también las conexiones que esa dirección ya tuviera abiertas. SSH no pasa por aquí: si te
  bloqueas a ti mismo por error, sigues pudiendo entrar al servidor para deshacerlo.
* Un rango, solo si hace falta de verdad y pequeño: `-s 203.0.113.0/24`. Nunca `/16` ni mayores.
* IPv6, solo si el dominio tiene registro AAAA: `ip6tables -L DOCKER-USER -n`. Si lista la cadena, las mismas órdenes con
  `ip6tables` y la dirección IPv6. Si dice que la cadena no existe, el filtro IPv6 de este servidor no está ensayado: anótalo
  y pide ayuda al asistente del plan.
* **No sobrevive a un reinicio de la máquina.** Apunta cada bloqueo en la bitácora (Anexo E) con la hora y el motivo, y
  quítalo cuando pase el ataque.
* **[S10]** Con Cloudflare delante, el servidor solo acepta a Cloudflare y solo la ve a ella: este bloqueo ya no sirve (y
  bloquear una dirección de Cloudflare dejaría sin web a parte de la gente). Las direcciones se bloquean en el panel de
  Cloudflare, con una regla de seguridad (WAF).

## Anexo D · Datos personales afectados: el protocolo

Se usa cuando un incidente pudo **exponer, alterar o perder** datos personales (lo piden las Guías 2, 4, 5, 6 y 7). Resume el
protocolo del plan de seguridad y **no es asesoría legal**: el abogado confirma el alcance y los plazos. Los plazos corren
**desde que lo detectas**: apunta la fecha y la hora UTC en la bitácora (Anexo E).

**Qué datos personales hay hoy:** las cuentas (correo, huella de la contraseña con Argon2id —nunca la contraseña en claro—,
rol y estado), las sesiones (dirección IP y navegador), la auditoría (el correo y la dirección de cada intento de entrar) y
los logs de Caddy (direcciones IP). Cuando el producto crezca se suman más datos y esta lista se revisa.

1. **Contener.** `predigolctl accounts revoke-sessions --all`; rotar los secretos implicados (Guía 6); aislar el componente
   (`predigolctl stop` para el conjunto: aún no existe una página de mantenimiento) y, si es el servidor, apagarlo desde el
   panel de Contabo (Guía 5).
2. **Preservar la evidencia antes de limpiar** (Anexo F): logs, un volcado y la instantánea del disco.
3. **Evaluar:** qué datos, cuántos titulares (A10 da el número de cuentas), desde cuándo y qué riesgo corren. Con la base
   copiada, el atacante tiene correos y huellas de contraseñas (difíciles de revertir, no imposibles si la contraseña era
   débil); con la base y `FBI_AUTH_SECRET_KEY` a la vez, también los segundos factores.
4. **Notificar** (el abogado confirma cada punto):
   * **Colombia (Ley 1581):** reportar el incidente a la SIC, en el Registro Nacional de Bases de Datos, dentro de los **15
     días hábiles** siguientes a detectarlo. El abogado dice si PrediGol, operado por una persona natural, entra en el
     alcance del Registro.
   * **Titulares afectados:** un aviso claro y sin demora cuando el incidente les suponga un riesgo: qué pasó, qué datos y qué
     deben hacer (por ejemplo, cambiar su contraseña).
   * **Usuarios en la UE (RGPD):** notificar a la autoridad en **72 horas**. Solo si hay usuarios en la UE; lo confirma el
     abogado según el mercado.
5. **Revisión sin culpables en 5 días hábiles:** causa, qué falló y qué lo evita (Anexo E).

Las plantillas del reporte a la SIC y del aviso a los titulares las prepara S5 y las revisa el abogado. Hasta entonces, no
improvises un texto: avisa al abogado el mismo día.

## Anexo E · La bitácora y el registro de incidentes

**Lo que apunta el sistema solo.** Cada aviso que se abre o se cierra queda en `/srv/predigol/state/incidents.jsonl` (una
línea por evento; solo se añade) y los que están abiertos ahora, en `/srv/predigol/state/alerts.json`. Funcionan aunque la
base de datos esté caída.

```bash
# E1. Los últimos eventos (hora UTC, evento, INC, gravedad, clave: texto)
tail -n 20 /srv/predigol/state/incidents.jsonl | jq -r '"\(.at) \(.event) \(.incident) \(.severity) \(.key): \(.text)"'
# E2. Qué está abierto ahora
jq -r 'to_entries[] | "\(.value.incident) \(.value.sev) \(.key) desde \(.value.since): \(.value.text)"' /srv/predigol/state/alerts.json
# E3. La historia de un incidente (cambia el número)
jq -r --arg i INC-2026-014 'select(.incident == $i) | "\(.at) \(.event) \(.text)"' /srv/predigol/state/incidents.jsonl
```

Si un apagón cortó la última línea del fichero, `jq` se queja y no enseña nada; `predigolctl incident list` y
`predigolctl incident show INC-2026-014` (más abajo) enseñan lo mismo y se saltan la línea rota.

**Lo que apuntas tú, en el portátil.** Un fichero de texto por incidente **en tu portátil** (no en el servidor: si está comprometido, no es de
fiar), con el INC en el nombre, por ejemplo `INC-2026-014.txt`. Plantilla:

```text
INC-AAAA-NNN     gravedad: SEV_     servicio: ________
Detectado (UTC): ____________   cómo: aviso / lo vi yo / un usuario / otro
Cerrado (UTC):   ____________   duración: ______
Qué pasó (el síntoma, en una frase):
Qué hice y a qué hora (UTC), una línea por acción; incluye las direcciones que bloqueaste y cuándo las quitas:
  hh:mm  ...
Causa raíz:
Impacto (qué dejó de funcionar y para quién) y usuarios afectados (el número, no los nombres):
¿Datos personales afectados?  sí / no.  Si sí: cuáles, cuántos titulares y desde cuándo corren los plazos (Anexo D)
Reparación: automática / manual (qué copia usé; cuánto tardó = el RTO real)
Prevención (acción, fecha, quién):                                  ¿hecha?
```

La revisión en 5 días hábiles es para todo SEV1 y para cualquier incidente con datos personales.

**Lo que apuntas tú, en el servidor: `predigolctl incident`.** Lo que solo sabes tú (la causa, a cuántas personas afectó, si
hubo datos personales, cómo se reparó, cómo se evita) se apunta con una orden. Va al mismo fichero que los avisos, así que
funciona con la base de datos caída, y cada 10 minutos (y justo después de cada orden) se copia a la base: la tabla
`audit.incident_events` y su vista `audit.incidents` (consulta A12). Por eso el registro viaja dentro de los volcados y de las
copias de punto en el tiempo, y no se pierde con el servidor.

```bash
predigolctl incident list                  # lo que está abierto ahora (con --all, además los diez últimos cerrados)
predigolctl incident show INC-2026-014     # la historia completa de un incidente y sus notas vigentes
predigolctl incident note INC-2026-014 cause "el disco se llenó con volcados antiguos"
predigolctl incident note INC-2026-014 affected_users 12          # un NÚMERO, nunca nombres
predigolctl incident note INC-2026-014 personal_data "no"         # empieza por si o no
predigolctl incident severity INC-2026-014 SEV1 "el disco crece rápido"
# un incidente que el servidor no vio (te avisó el monitor de fuera, o la máquina estaba apagada); --at es la hora UTC en que empezó:
predigolctl incident open web SEV1 "la web no respondía desde fuera" --at 2026-10-26T15:02Z
predigolctl incident close INC-2026-020 "reiniciado el contenedor de Caddy" --at 2026-10-26T15:30Z
```

Los campos de `note` son `cause` (causa raíz), `evidence`, `impact`, `affected_users`, `personal_data`, `detection`, `repair` y
`prevention`: las preguntas de la plantilla de arriba que tienen campo. Una nota nueva del mismo campo sustituye a la anterior en
`show` y en la vista, pero la anterior sigue en el registro: nada se edita ni se borra.

* El texto es un síntoma, un recuento o el nombre de un servicio: **nunca** una dirección de correo, una contraseña, un token ni el
  nombre de una persona. La orden rechaza lo que lo parece (usa recuentos e ids). Una sola línea, hasta 1500 caracteres.
* Un `personal_data` que empieza por «si» avisa al canal y te recuerda el Anexo D: los plazos corren desde que lo detectaste.
* `severity` cambia la gravedad de un incidente abierto; la comprobación que lo abrió ya no la vuelve a cambiar mientras siga
  abierto, y el incidente se cierra con la gravedad que tú pusiste.
* Un incidente que abrió una comprobación lo cierra ella misma cuando el problema desaparece: `close` solo vale para los que
  abriste tú con `open`. Las notas valen para todos, también después de cerrados (la revisión llega días más tarde).
* Si llega el aviso `incidents.dump` (SEV3), la copia a la base falló: o una línea nueva que la tabla no aceptó, o la base lleva más
  de 24 horas sin aceptar la copia (no contesta, o le falta la tabla del registro porque la migración aún no se ha aplicado:
  Guía 2). El fichero del servidor lo conserva todo, así que no hay prisa: el aviso se cierra solo en la pasada siguiente si ya no
  hay líneas nuevas rechazadas, y la copia se pone al día sola cuando la base la acepta.
  `journalctl -u predigol-incident-dump.service -n 20` dice cuántas líneas fueron (solo recuentos, nunca su contenido) o, si la base
  no llegó a aceptar la copia, el código del error que dio (por ejemplo `42P01`: falta la tabla).
* Si desconfías del servidor (Guía 5), **no apuntes nada en él**: trabaja solo en tu fichero del portátil. Tu fichero sigue siendo
  la bitácora completa (qué hiciste y a qué hora); el registro del servidor es el resumen que permite buscar y comparar incidentes.

## Anexo F · Servidor comprometido: mirar y guardar la evidencia

Aquí solo se **mira**: nada de esto cambia el servidor. Lo que veas en una máquina comprometida puede ser mentira (quien tiene
root puede ocultar procesos y editar logs): trátalo como indicio, y no ver nada no prueba que esté limpia.

**F.1 Mirar** (de una en una):

```bash
last -a -n 20                                          # últimos accesos y desde dónde
journalctl -u ssh --since "7 days ago" --no-pager | grep -E 'Accepted|Failed' | tail -n 40   # entradas por SSH
ssh-keygen -lf /root/.ssh/authorized_keys              # llaves que pueden entrar como root (huellas): ¿las reconoces todas?
getent passwd | awk -F: '$3 == 0 || $3 >= 1000 {print $1, $3, $7}'   # usuarios con poder de root, o normales
ss -tulpn                                              # puertos abiertos y quién los escucha
ps -eo pid,ppid,user,lstart,comm --sort=lstart | tail -n 30          # procesos, los más recientes al final (sin argumentos)
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'    # contenedores: ¿alguno que no es tuyo?
systemctl list-timers --all --no-pager | head -30      # tareas programadas
ls -la /etc/cron.d /var/spool/cron/crontabs 2>/dev/null
find /etc /usr/local /root -xdev -type f -newermt "3 days ago" 2>/dev/null | head -50   # ficheros cambiados en 3 días (solo nombres)
```

**F.2 Guardar la evidencia** (antes de apagar; no más de 10 minutos). Todo se guarda en una carpeta nueva y no borra nada:

```bash
INC=INC-2026-014                                       # cambia el número
mkdir -p /root/evidencia-$INC && cd /root/evidencia-$INC
{ date -u; last -a; who -a; ss -tulpn; ps -eo pid,ppid,user,lstart,comm --sort=lstart; docker ps -a; systemctl list-timers --all --no-pager; } > estado.txt 2>&1
journalctl --since "7 days ago" --no-pager | gzip > diario.txt.gz
for s in postgres api worker web caddy; do docker logs --since 72h predigol-$s 2>&1 | gzip > log-$s.txt.gz; done
cp /srv/predigol/caddy/data/access*.log* . 2>/dev/null
sha256sum * > SHA256SUMS
ls -la
```

Luego, **desde tu portátil**: `scp -r predigol:/root/evidencia-INC-2026-014 .` (cambia el número) y guárdala como un secreto:
tiene direcciones IP y correos. Si la base aún responde y no se duda de ella, un volcado para analizar después:
`predigolctl backup --label forense-INC-2026-014`. Y desde el panel de Contabo, la instantánea del disco antes de apagar.

## Anexo G · Aviso breve a los usuarios

Cuándo: un SEV1 que dura más de 30 minutos (Guías 1 y 2), datos en vivo con horas de retraso (Guía 8) o las sesiones cerradas
a todos (Guías 4 y 5). Hoy PrediGol no tiene una página de estado ni un correo masivo: el aviso va por el canal que ya uses con
tu gente (lo decides tú; el correo de la aplicación llega con Resend, tarea S0-4).

Reglas: la hora de Colombia (UTC−5), no la UTC; qué pasa y qué **no** se ve afectado; qué estás haciendo; cuándo volverás a
hablar; sin detalles de seguridad que ayuden a un atacante, sin culpar a nadie y sin prometer una hora de arreglo.

> **Caída.** PrediGol no está disponible desde las HH:MM (hora de Colombia) por un problema técnico. Estamos trabajando en
> ello y te avisaremos cuando vuelva a funcionar. Gracias por la paciencia.

> **Recuperado.** PrediGol funciona con normalidad desde las HH:MM. Si algo no te carga, cierra sesión y vuelve a entrar.
> Disculpa las molestias.

> **Datos con retraso.** Los datos de los partidos en vivo están llegando con retraso por un problema de nuestro proveedor de
> datos. El resto de la información no se ve afectada. Lo estamos vigilando y te avisaremos cuando se normalice.

> **Sesiones cerradas.** Por precaución hemos cerrado todas las sesiones abiertas: tendrás que volver a entrar con tu
> contraseña. No tienes que hacer nada más.

Si hay **datos personales afectados**, no uses estos textos: el aviso a los titulares y el reporte a la SIC llevan la plantilla
que revisa el abogado (S5, Anexo D).

## Anexo H · El certificado del servidor (`tls.origin`)

Es el certificado que Caddy presenta en el puerto 443: de Let's Encrypt, que Caddy renueva solo desde 30 días antes del
vencimiento, o **[S10]** el certificado de origen de Cloudflare, que dura años. El aviso salta si quedan menos de 20 días
(SEV2), o menos de 7 o ninguno (SEV1).

1. Cuántos días quedan y quién lo emitió:

   ```bash
   DOM=$(grep -m1 '^PREDIGOL_DOMAIN=' /etc/predigol/predigol.env | cut -d= -f2)
   echo | openssl s_client -connect 127.0.0.1:443 -servername "$DOM" 2>/dev/null | openssl x509 -noout -subject -issuer -dates
   ```

2. Por qué no se renueva: `predigolctl logs caddy 2>&1 | grep -i -E 'certificate|acme|tls|challenge|rate' | tail -n 30`. Las
   causas de siempre: el DNS ya no apunta a este servidor; el puerto 80 está cerrado (el desafío de Let's Encrypt llega por
   ahí); **[S10]** el proxy de Cloudflare estaba activo al emitir (por eso con Cloudflare se usa el certificado de origen); el
   disco está lleno (Guía 3); o Let's Encrypt limita por demasiados intentos fallidos.
3. Arregla la causa. Caddy reintenta solo, con esperas cada vez más largas. **No reinicies Caddy en bucle:** cada reinicio es
   un intento nuevo y Let's Encrypt limita los fallos por hora.
4. Si quedan menos de 7 días y no se arregla, pide ayuda al asistente del plan; no esperes al último día.

## Anexo I · Lo que todavía no existe

Las guías usan lo que hay hoy y marcan lo que depende de una fase futura. Esta es la lista de huecos conocidos y qué hacer
mientras tanto.

| Falta | Qué significa hoy | Mientras tanto |
| --- | --- | --- |
| Copias fuera del servidor y PITR **[S2]** | Los volcados están en el mismo disco que la base | Guía 2: no improvises; conserva `pgdata` y pide ayuda |
| Una orden que restaure un volcado sobre el servidor | `predigolctl` restaura el PITR **[S2]**, pero no un volcado | Guía 2, A.3: deja el conjunto parado y pide ayuda; la ruta «volcado → servidor» se fija y se ensaya en S2 |
| Página de mantenimiento | `predigolctl stop` lo para todo | Aviso a los usuarios (Anexo G) |
| Un monitor desde fuera del servidor (decisión D2) | Si cae el servidor entero, nada avisa | Abre la web a menudo; Healthchecks.io (tarea S0-3) lo cubrirá |
| Línea base de la configuración (`config.sha256`) **[S3]** | Hasta el primer despliegue con el código de S3 el aviso `config.drift` calla: no hay con qué comparar | Después la toman solos el despliegue y la vuelta atrás; a mano: `predigolctl config-baseline` (`--status` solo mira) |
| Acceso por WireGuard y usuario con `sudo` **[S4]** | Entras como root por SSH | Guías 4 y 5, tal como están |
| Cloudflare delante **[S10]** | Sin «Under Attack»; el bloqueo es por dirección | Anexo C |
| Registro de borrados **[S8]** | Tras restaurar, pueden reaparecer cuentas borradas | Guía 2, D.5 |
| Plantillas legales (SIC y titulares) **[S5]** | No hay texto revisado por el abogado | Avisa al abogado el mismo día (Anexo D) |
| `create-user --reset` cambia la contraseña antes de comprobar el fichero de credenciales | Puede dejarte con una contraseña que nadie conoce | Guía 4, paso 5 (borrar antes el fichero); la corrección va en el próximo despliegue |
| Ensayo de mesa **[S15]** | Estas guías aún no se han probado «en voz alta» | Léelas una vez con calma, antes de necesitarlas |

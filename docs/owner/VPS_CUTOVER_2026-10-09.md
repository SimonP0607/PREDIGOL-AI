# PrediGol en el servidor: corte del 9 oct 2026

Desde el **9 oct 2026, 04:02 UTC** PrediGol corre en el servidor. El portátil quedó como respaldo frío: su worker
está parado y marcado para no volver a arrancar.

## 1. El servidor

| | |
|---|---|
| Proveedor y plan | Contabo **Cloud VPS 6 (2026)**, pago mensual, sin cargo de alta |
| Ubicación | Carlstadt, Nueva Jersey (US-east) |
| Dirección | **https://86.48.25.4**. Sin dominio todavía: el certificado lo firma el propio servidor y el navegador avisa |
| Sistema | Ubuntu 24.04.5 LTS, Docker 29.9, Compose 5.6 |
| Acceso | SSH **solo con llave**: la llave dedicada `predigol_vps_ed25519` del portátil, alias `predigol`. La contraseña de root está desactivada para SSH; la consola VNC de Contabo sigue funcionando |
| Protección | ufw (22, 80, 443), fail2ban, actualizaciones de seguridad automáticas sin reinicio, 4 GB de swap |

### Medición del día 1 (`bench.sh`)

| Prueba | Resultado | Mínimo |
|---|---:|---:|
| CPU, un hilo | 560 eventos/s | 500 |
| CPU, 6 hilos | 2.995 eventos/s (5,3×) | — |
| *Steal* de CPU bajo carga | 0,0 % | ≤ 10 % |
| Disco 4k aleatorio, lectura / escritura | 16.664 / 12.664 IOPS | 5.000 / 2.500 |
| Disco secuencial | 919 MB/s | 150 |
| fsync (como PostgreSQL) | 408 op/s | 400 |
| Descarga | 208–277 Mbit/s | 100 |
| Conexión a API-Football | 4,9 ms | — |

Todo pasa. La CPU por hilo y el fsync quedan justo por encima del mínimo: el plan B solo haría falta si el monitor
mostrara lentitud. La primera medición de descarga falló porque la prueba de velocidad de Cloudflare responde 403 a
esta IP; `bench.sh` ya prueba también otras fuentes.

## 2. El corte

| Paso | Hora UTC | Resultado |
|---|---|---|
| Ensayo en el servidor, sin worker ni claves | 03:40–03:44 | imágenes, migraciones 0001 → 0073 en base vacía, permisos; api, web y caddy sanos; HTTPS por IP |
| Worker del portátil parado | 03:46 | marca `~/.fbi/worker-moved-to-server` |
| Copia final del portátil | 03:48–03:50 | dump de 654,6 MB en 63 s y RAW de 863 MB. 138 tablas, 51.752.042 filas; nada cambió durante la copia |
| Copia al servidor | 03:50–03:54 | 242 s, sha256 comprobados allí |
| Importación | 03:54–03:59 | las 138 tablas con el mismo número de filas que el manifiesto, 91.332 ficheros RAW, 83 sesiones del portátil cerradas |
| Despliegue **con** el worker | 03:59–04:03 | los cinco servicios sanos; el worker late como `predigol-worker:worker` |
| Copia y prueba de restauración | 04:03–04:14 | volcado post-corte de 654,7 MB. La restauración en un PostgreSQL desechable **pasó en 299 s** |
| Reinicio real del servidor | 04:18 | todo volvió solo en 36 s; el monitor dio "ok" |

**Pausas de captura:** 16 minutos durante el corte (03:46–04:02). Antes, de 03:24 a 03:41, WSL cerró la distro del
portátil al reiniciarse el conector de Windows. En los dos casos el catch-up del worker recupera lo programado. No
había partidos en vivo.

**Lo que el corte corrigió en el kit:** `predigolctl` no encontraba `lib.sh` al llamarlo desde `/usr/local/bin`;
`export.sh` tomaba el `docker` falso de WSL en lugar de `docker.exe`; y la prueba de descarga de `bench.sh`.

## 3. Qué corre

| Servicio | |
|---|---|
| postgres | PostgreSQL 16, solo accesible dentro del servidor |
| api | FastAPI, 2 procesos |
| web | la app y la PWA |
| caddy | HTTPS, cabeceras de seguridad. `/docs` da 404 |
| worker | **uno solo**: captura, picks e IA |

**IA:** modo evaluación (shadow). Haiku 5.5, Sonnet 5.5 y Opus 5.5, búsqueda web con Exa. Presupuesto US$150/mes;
en octubre se gastaron US$2,57. Las claves se copiaron del portátil sin mostrarse.

**Cuentas:** solo la del dueño está activa; las 7 de QA quedaron desactivadas porque el servidor es público. La
clave del segundo factor es la misma del portátil, así que el autenticador sigue sirviendo. Las sesiones abiertas se
cerraron: hay que volver a entrar.

## 4. Operación

```
ssh predigol                      # desde el portátil (WSL o PowerShell)
predigolctl status | health       # estado y monitor
predigolctl logs worker           # logs en vivo
predigolctl backup                # copia ahora (también cada día a las 04:15 UTC)
predigolctl restore-test          # prueba de restauración (también los lunes)
```

Copias en el servidor: `/srv/predigol/backups/db`, las 3 diarias más recientes y 2 semanales.

## 5. Pendiente (decisiones del dueño)

1. **Copias fuera del servidor (R2): lo más urgente.** Hoy las copias solo existen en el servidor y en el portátil
   (este, hasta las 03:48 UTC del 9 oct). Si se pierde el servidor, se pierde lo posterior. Mientras tanto se
   puede bajar al portátil, de vez en cuando, el volcado más reciente.
2. **Dominio y Cloudflare:** acceso público, certificado sin avisos y PWA instalable (`deploy/vps/README.md` §3 bis).
3. **Avisos:** bot de Telegram, Healthchecks.io y UptimeRobot (gratis).
4. **Portátil:** 7 días como respaldo frío (hasta el 16 oct). Su API y su web siguen encendidas, pero muestran los
   datos congelados a las 03:48 UTC. Vuelta atrás: README §4.
5. La renovación mensual de Contabo.

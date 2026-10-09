# PrediGol en el servidor: corte del 9 oct 2026

Desde el **9 oct 2026, 04:02 UTC** PrediGol corre en el servidor. El portátil quedó como respaldo frío: su worker
está parado y marcado para no volver a arrancar.

## 1. El servidor

| | |
|---|---|
| Proveedor y plan | Contabo **Cloud VPS 6 (2026)**, pago mensual, sin cargo de alta |
| Ubicación | Carlstadt, Nueva Jersey (US-east) |
| Dirección | **https://predigolai.com** desde las 12:35 UTC del 9 oct (DNS en Hostinger, registro A → 86.48.25.4). Certificado de Let's Encrypt, renovación automática; `www.predigolai.com` redirige al dominio y `http://` a `https://`. Hasta entonces se entraba por la IP con un certificado propio del servidor |
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

## 4 bis. Rendimiento del primer día: qué falló y cómo se arregló

**Síntoma.** A las 11:48 y a las 13:00 UTC el monitor reinició el worker porque su latido se había detenido. Cada
reinicio tiró a la basura la pasada de picks que estaba corriendo y dejó la captura en vivo parada alrededor de un
minuto.

**Causa, medida en el servidor** (registro de sentencias lentas, muestreo de PostgreSQL y `py-spy` sobre el worker):

| Hallazgo | Medida |
|---|---|
| Una pasada del pipeline de picks tardaba ~10 min (97 s en el portátil) | 88 % del tiempo esperando a la base, 99 % dentro de `evaluate_captures` |
| Cada pasada repetía ~300.000 consultas: precio y alta de **cada** candidato ya evaluado | 2.227 instantes, ~159.000 candidatos existentes |
| Un viaje de ida y vuelta a la base cuesta más en el servidor | `SELECT 1`: mediana 0,16 ms, media 0,41 ms, p90 1,0 ms; la consulta de precio 2,1 ms de media |
| La captura de cuotas esperaba a "su" pasada antes de latir | latido viejo → reinicio |
| Dos pasadas a la vez se bloqueaban entre sí | 20 esperas de ~4 min en `models.model_registry` |
| Cada carga de `/fixtures` reescribía todos sus equipos | 3 esperas de ~7 min de la captura en vivo detrás del sync |

No es la máquina: *steal* 0 %, CPU 75 % libre, sin estrangulamiento de contenedores, caché de la base al 99 %.

**Arreglos (desplegados el 9 oct):**

1. `2674974` — la captura pide la pasada y sigue (ya no la espera), una sola pasada a la vez (`OnePass`: lo que
   llega mientras corre se convierte en exactamente una pasada más) y los equipos solo se escriben si cambian. De
   paso, un nombre de equipo conocido ya no se reemplaza por "team <id>". (El registro de modelos quedó como estaba:
   ver el tropiezo, abajo; con una sola pasada a la vez ya no hay con quién bloquearse.)
2. `5a7f8d4` — el motor de picks pregunta una vez por instante (todos sus precios en una consulta y los candidatos
   ya evaluados en otra) y solo inserta los nuevos. En la copia de datos reales: **mismos** candidatos (76.129),
   picks (12.050) e informe que antes, con la regla actual y con una regla nunca corrida; la pasada en régimen
   bajó de 55,5 s a 6,3 s allí.

**Resultado en el servidor** (desde las 13:47 UTC): una pasada tarda **126–148 s** (antes 570 s de media y hasta
1.069 s); la captura de cuotas termina en 1–2 s y pide su pasada sin esperarla, así que su latido ya no depende de
cuánto tarde el pipeline.

**Un tropiezo en el camino, ya corregido (`c552cc4`).** El registro de modelos sin bloqueo vivía en
`fbi.backtesting`, que forma parte de la huella del código de los modelos: cambiarlo creó, a las 13:31 UTC, una
versión nueva de cada modelo (258–260, huella `mc118f6f26d7`) con 89.585 pronósticos, 3.275 candidatos y 493 picks
en sombra de 19 partidos (18 revisiones de la IA, US$0,008). Se devolvió `persist.py` byte a byte: desde las 13:47
los pronósticos vuelven a las versiones 252–254 (`mc1f28a88360`), que son las que acumulan el registro. Las filas de
258–260 siguen ahí, separadas por versión; borrarlas es decisión del dueño (hay copia de las 13:22, anterior a ellas).

**Nota sobre versiones de modelo.** Las del portátil (249–251, `mcec6b780838`) dejaron de usarse en el corte: el
código del servidor tiene otra huella y abrió las 252–254 a las 04:02. Ninguna versión reciente tiene backtest, así
que ningún pick estaba calificado antes ni después.

## 5. Pendiente (decisiones del dueño)

1. **Copias fuera del servidor (R2): lo más urgente.** Hoy las copias solo existen en el servidor y en el portátil
   (este, hasta las 03:48 UTC del 9 oct). Si se pierde el servidor, se pierde lo posterior. Mientras tanto se
   puede bajar al portátil, de vez en cuando, el volcado más reciente.
2. **Cloudflare (opcional):** el dominio ya está (predigolai.com, certificado válido, PWA instalable). Cloudflare
   delante añadiría protección y caché; no es necesario para operar.
3. **Avisos:** bot de Telegram, Healthchecks.io y UptimeRobot (gratis).
4. **Portátil:** 7 días como respaldo frío (hasta el 16 oct). Su API y su web siguen encendidas, pero muestran los
   datos congelados a las 03:48 UTC. Vuelta atrás: README §4.
5. La renovación mensual de Contabo.

# Vigilancia externa: qué hay, qué falta y qué te toca (PM-06-01)

*Plan Maestro PM, tarea PM-06-01, decisión DM-11 · entra con DOC-007 · comprobado en el servidor el 20-nov-2026 entre las
00:27 y las 00:40 UTC, solo con lecturas. Ninguna URL de ping aparece aquí: son secretos.*

Un solo servidor no puede avisar de su propia caída. Para eso hacen falta vigilantes **fuera** de él. Este documento dice
cuáles hay hoy, si funcionan, qué no cubren y los pasos que quedan, uno por paso. Cómo se ensaya cada aviso está en
[`SIMULACROS_AVISOS.md`](SIMULACROS_AVISOS.md); aquí no se repite.

## 1. Lo que ya existe

| Vigilante | Qué mira | Cómo avisa | Desde |
| --- | --- | --- | --- |
| **Healthchecks.io**, 7 checks (plan gratuito: 20) | Que cada tarea programada del servidor late, y el veredicto de `healthcheck.sh` cada 5 min | Telegram, con su propia integración (otro remitente que nuestro bot) | 10-nov-2026 |
| **Monitor de disponibilidad de Sentry** (`PrediGol web`) | `GET https://predigolai.com/health` desde fuera, cada minuto, tiempo máximo 10 s | Correo, tras 3 fallos seguidos | 10-nov-2026 |

Términos leídos el 20-nov-2026: los de Healthchecks.io (actualizados el 19-nov-2026) no limitan el plan gratuito a uso
personal. Los de UptimeRobot (registro de cambios del 26-may-2026) dicen que el servicio vale «para cualquier uso, incluido
el comercial y de empresa»: **corrige** la nota del 9-nov, que lo daba por solo personal.

## 2. Lo comprobado en el servidor (20-nov-2026, 00:27 UTC)

- Las 7 variables `HC_PING_*` de `/etc/predigol/predigol.env` tienen valor y apuntan a `hc-ping.com` (se comprobó el
  dominio, no se imprimió ninguna). El servidor llega a `hc-ping.com:443`.
- En los últimos 14 días **ningún ping falló** (0 líneas «did not answer» en el diario).
- Cada tarea corrió y terminó bien desde que existen los checks:

| Check | Tarea y horario (UTC) | Última ejecución | ¿Ha enviado ping desde el 10-nov? |
| --- | --- | --- | --- |
| `health` | cada 5 min | 20-nov 00:26 | Sí (hoy envía `/fail`: ver §3.1) |
| `backup` | diaria 04:15 | 19-nov 04:30, bien | Sí |
| `restore-test` | lunes 06:00 | 16-nov 06:22, bien | Sí |
| `raw-sync` | cada hora a las :20 | 20-nov 00:20, bien | Sí |
| `maint` | diaria 05:30 | 19-nov 05:34, bien | Sí |
| `pitr` | diaria 03:30 | 19-nov 03:31, «no configurado» | **No, nunca** (§3.2) |
| `pitr-test` | primer martes del mes 06:00 | 3-nov, «no configurado» | **No, nunca** (§3.2) |

Lo que esto no puede ver es el panel de Healthchecks: si cada check está en verde lo confirmas tú en el paso 1 de §4.

## 3. Lo que falta de verdad

### 3.1 El check `health` mezcla «vivo» con «sano»

`healthcheck.sh` envía `/fail` cuando hay cualquier problema, y Healthchecks marca el check como caído. Mientras siga caído
por un problema conocido, **un silencio del servidor ya no produce un aviso nuevo**. Pasa ahora mismo: desde el 20-nov a
las 00:01 UTC el veredicto es «problem» porque falló el ensayo de restauración de la cadena `20261119T2313Z-auto-5af94de`
(el aviso `restore.test` es real, no de esta tarea; el defecto está en la comparación de recuentos de `restore-test.sh`,
que supone que `core.fixture_events` solo crece, y es de la sesión de seguridad). Por la misma razón, el check
`restore-test` puede estar también en «down». Hasta que vuelva el «ok», la caída total del servidor la ve solo el
monitor de Sentry, por correo.

**Propuesta (seguimiento con su propio código OPS, no hecho aquí):** un octavo check, `alive`, que reciba un ping normal en
cada pasada de `healthcheck.sh` sea cual sea el veredicto, desde la unidad de systemd y sin tocar el guion:

```ini
# backend/deploy/vps/systemd/predigol-health.service, sección [Service]
# ExecStopPost corre tras cada pasada, acabe bien o mal; «$$» es un «$» literal para el shell (systemd expande «$»).
ExecStopPost=-/bin/bash -c '. /etc/predigol/predigol.env; test -n "$${HC_PING_ALIVE:-}" || exit 0; curl -fsS -m 10 --retry 3 -o /dev/null "$${HC_PING_ALIVE}" || true'
```

Nace apagado: sin `HC_PING_ALIVE` no envía nada. Necesita que crees el check (paso 4 de §4), su línea en
`predigol.env.example` y una fila en la Tabla B de `SIMULACROS_AVISOS.md` (la prueba de ese documento la exige).

### 3.2 `pitr` y `pitr-test` nunca latirán mientras no haya PITR

`pitr.sh` termina con «not configured (PITR_S3_BUCKET is empty)» antes de enviar el ping. Healthchecks no avisa de un check
que nunca recibió ningún ping («new»), así que estos dos no molestan, pero tampoco vigilan nada. Configurar el PITR es de
la sesión de seguridad (copias); hasta entonces, lo honesto es pausarlos (paso 3 de §4).

### 3.3 Tareas sin latido

| Tarea | Frecuencia | ¿Hace falta latido? |
| --- | --- | --- |
| `security-alerts` | cada 5 min | **Sí**: si se para, los avisos de seguridad se callan sin que nadie lo note. Es zona de la sesión de seguridad: se le propone, no se toca aquí |
| `pitr-verify` | miércoles 05:00 | No mientras no haya PITR (§3.2) |
| `storage`, `incident-dump`, `weekly-summary` | 4 al día, cada 10 min, lunes | No: son informes; su falta no deja nada sin vigilar |
| Trabajos del worker (`fixtures_sync`, cuotas, estadísticas…) | los del planificador | Los cubre `healthcheck.sh` por dentro (latido del worker y ejecuciones fallidas en la última hora). Que un trabajo concreto deje de programarse sin fallar no lo ve nadie: es un seguimiento del bloque 4 (planificador), no de esta tarea |

### 3.4 ¿Aporta algo UptimeRobot?

Poco, pero algo. Sentry ya vigila `/health` desde fuera y avisa en unos 3 minutos. UptimeRobot añadiría:

- **otro proveedor**: si Sentry o su correo fallan, sigue habiendo un vigilante externo;
- **otra ruta**: la portada `https://predigolai.com/`, que sirve el contenedor de la web (Sentry solo mira la API);
- **50 monitores gratis** cada 5 minutos, por si un día hace falta vigilar algo más (por ejemplo la consola).

Decisión DM-11, aprobada: crear la cuenta tras leer los términos. Los términos ya permiten el uso comercial, así que el
alta queda en tus manos (pasos 6 a 11 de §4). Si prefieres no tener otra cuenta, no se pierde nada crítico: dilo y se
anota que basta con Sentry.

## 4. Lo que te toca (una acción por paso)

Ningún paso exige copiar una URL de ping en el chat. Cuando un paso pide guardar una URL en el servidor, la sesión te da el
comando que la lee de un fichero sin mostrarla, como el 10-nov.

**Healthchecks**

1. Entra en healthchecks.io y abre el proyecto de PrediGol. Mira que `health`, `backup`, `restore-test`, `raw-sync` y
   `maint` tengan un último ping posterior al 10-nov. Dile a la sesión cuáles no.
2. Abre el check `health` y mira en su historial si hubo un «down» el 20-nov hacia las 00:01 UTC (19:01 en Colombia) y si
   te llegó a Telegram. Dile a la sesión «llegó» o «no llegó».
3. Pausa los checks `pitr` y `pitr-test` (botón «Pause» de cada uno). Se reactivan cuando haya PITR.
4. Crea un check nuevo llamado `alive`, periodo 5 minutos y margen 5 minutos, con la misma integración de Telegram.
   Guarda su URL de ping en un fichero de `C:\Users\simon_zkmbj72\fbi_scratch\secretos\` y avisa a la sesión.
5. (Opcional) En el check `health`, baja el margen de 10 a 5 minutos: el aviso por silencio llega entonces en 10 minutos
   como mucho, en vez de 15.

**UptimeRobot** (solo si decides darlo de alta)

6. Lee los términos de uptimerobot.com y crea una cuenta gratuita con tu correo.
7. Pulsa «New monitor» y elige el tipo «HTTP(s)».
8. Pon como dirección `https://predigolai.com/` y como nombre `PrediGol portada`.
9. Deja el intervalo en 5 minutos y marca tu correo como contacto de aviso.
10. Guarda el monitor y espera a que salga «Up».
11. Dile a la sesión «monitor creado».

**Simulacro** (cuando `health` vuelva a estar en verde; con él caído, el silencio no produce aviso)

12. Pide a la sesión el «silencio del latido» de `SIMULACROS_AVISOS.md`. La sesión para el temporizador con su red de
    seguridad de 17 minutos, fuera de las copias (03:30–06:40 UTC), a más de 20 minutos de `fixtures_sync` (03:41, 09:41, 15:41 y 21:41) y lejos de cualquier cadena de
    despliegue. Tú anotas la hora a la que llega el aviso de Healthchecks a Telegram.

## 5. Criterio de aceptación y cómo se cierra

- **Criterio:** el aviso del simulacro llega en menos de 15 minutos desde que se para el temporizador. Con margen de
  10 minutos llega entre 10 y 15; con 5 (paso 5), entre 5 y 10.
- **Cierre:** la hora UTC de la parada y la del aviso se apuntan en el estado del plan PM (fila PM-06-01) y en la fila 3
  del acta de `SIMULACROS_AVISOS.md`.

## 6. Vuelta atrás

- Check `alive` o monitor de UptimeRobot: se borran en su panel; la línea `HC_PING_ALIVE` se deja vacía en
  `predigol.env` (copia fechada antes, como siempre).
- Checks pausados: «Resume» en su panel.
- Margen de `health`: se vuelve a poner en 10 minutos.
- Este documento no cambia nada en el servidor.

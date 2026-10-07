# PrediGol — beta privada en un VPS: informe de despliegue

7 oct 2026. El sistema está preparado y ensayado con los datos reales (saneados) en un entorno de pruebas.
**Se detiene en la compra del servidor**, que decide el dueño. Producción **no** está lista: falta repetir el
ensayo en la máquina comprada (FASE 12) y hacer el corte (FASE 13).

## 1. Decisión de infraestructura

**Contabo Cloud VPS 6, 200 GB SSD, US Central: $11,00/mes en pago mensual** ($9,20 con 24 meses).
Detalle y fuentes: `INFRA_DECISION_2026-10-07.md`.

| | Cloud VPS 4 | **Cloud VPS 6** |
|---|---|---|
| vCPU / RAM | 4 / 8 GB | 6 / 12 GB |
| Disco | 100 GB SSD | 200 GB SSD |
| CPU y RAM para 200 usuarios (prueba de carga, §3) | suficiente | holgado |
| Disco a 12 meses (≈ 75–80 GB) | ≈ 80 % | ≈ 40 % |
| Disco a 24 meses (≈ 130 GB) | **no cabe** (lleno hacia el mes 15–16) | ≈ 66 % |
| $/mes (US Central, mensual · 24 meses) | $7,90 · $6,58 | $11,00 · $9,20 |

La prueba de carga del §3 muestra que el VPS 4 aguantaría la CPU y la RAM de la beta. Lo descarta el disco: con
+100 GB costaría $8,38/mes (24 meses), frente a $9,20 del VPS 6, que además trae 6 vCPU y 12 GB. El riesgo de
Contabo es la variabilidad (vecinos ruidosos). Por eso se contrata en pago mensual y se mide el día 1 con
`bench.sh`. Si falla, el plan B es Cloud VPS Plus 4 u OVH VPS-3.

## 2. Qué quedó hecho, por fase

| Fase | Estado |
|---|---|
| 0 Auditoría y línea base | backup verificado (dump 631 MB + RAW 821 MB, sha256), restauración probada en 76 s (14/14 huellas), crecimiento medido, escaneo de secretos (`BETA_FASE0_BASELINE_2026-10-07.md`) |
| 1 Hardening | `/docs`, `/redoc` y `/openapi.json` cerrados; `/health` sin detalles; HSTS, CSP y cabeceras; cookie `__Host-`, `Secure`, `HttpOnly`, `SameSite=Strict`; CORS del dominio; CSRF; límites por IP, cuenta e inicio de sesión; 1 MB/256 KiB por petición; consola auditada; un rol de base por servicio; cuentas de QA apagables (`accounts disable --domain`) |
| 1–2 Autenticación | TOTP con QR y 10 códigos de recuperación, obligatorio para SUPER_ADMIN; inicio de sesión por etapas; bloqueo progresivo; contraseña temporal que se cambia al entrar; sesiones con caducidad, inactividad y revocación; historial de accesos; herramientas del dueño (reset de contraseña y de 2FA, desbloqueo, cierre de sesiones); sin registro público |
| 3 Web + PWA | build de producción; manifiesto, iconos, service worker que nunca guarda la API; actualización controlada ("Actualizar"); recarga única si faltan archivos tras un despliegue |
| 4 Arquitectura en el VPS | compose con límites de CPU/RAM, healthchecks, reinicio, volúmenes, rotación de logs; `tini` como PID 1 |
| 5 Secretos | dos ficheros (servidor / aplicación), generados por `install.sh`, 600, fuera de imágenes y de Git; inventario y rotación en `SECRETS_AND_ROTATION.md` |
| 6 Copias y PITR | pgBackRest a R2 (WAL continuo, AES-256, completa semanal y diferencial diaria); volcado diario cifrado con `age`; RAW inmutable; verificación semanal, prueba mensual, recuperación en el sitio (`pitr recover`) |
| 7 Monitoreo | monitor cada 5 min (contenedores, HTTPS, worker, disco y previsión, memoria, *steal*, conexiones, WAL, PITR, cuota, ejecuciones, 5xx, certificado); Healthchecks.io, UptimeRobot y Telegram (gratis, sin cuentas creadas) |
| 8 Despliegue sin GitHub | `deploy/release.sh`: puertas → bundles con sha256 → SSH → commits exactos → `predigolctl deploy` → humo; `rollback` |
| 9 Arranque | systemd: el conjunto vuelve solo y avisa |
| 10 Retención | `predigolctl maint`: particiones por delante y retención de restos (sesiones caducadas > 90 días, uso por minuto > 35 días), solo con copia verificada de < 26 h y registro en `audit.storage_cleanups`. Nada histórico se borra |
| 11 Cloudflare | certificado de origen, IP real del cliente, cortafuegos solo para Cloudflare, caché solo de estáticos |
| 12 Ensayo | completo en el entorno de pruebas (§3). **Pendiente en el VPS real** |
| 13 Corte | preparado (`export.sh` → `import` → `deploy` → DNS). **Pendiente**: requiere el VPS |
| 14 Validación 24–72 h | pendiente |

## 3. El ensayo

Entorno: 2 vCPU Xeon 2,8 GHz y 7,8 GB. Mismo `docker-compose.yml` y `Caddyfile`. Copia saneada de la base del
portátil (8,4 GB, 117 tablas, 49.763.561 filas, sin cuentas ni datos personales) y su RAW real (81.739 ficheros;
ninguno contiene la clave de API-Football). Simulador vacío de API-Football y S3 local en lugar de R2.

| Prueba | Resultado |
|---|---|
| Copia final con `export.sh` | OK: 117 tablas; 2 min 31 s |
| `import` (sha256, restauración como `fbi`, 117 tablas comparadas, RAW, sesiones, PITR) | OK en 5 min |
| Migraciones 0069 → 0071 con datos reales; despliegue desde cero 0001 → 0071 | OK |
| PITR: copia completa (8,8 GB → 1,1 GB cifrados) | 62 s |
| PITR: verificación del repositorio; restauración a un punto en un servidor desechable | OK |
| Pérdida de la base → `pitr recover --name` | base abierta en 69 s (restauración 53 s); 118 tablas como en el punto; el marcador posterior no está; nueva línea temporal y copia completa |
| Linaje del RAW | 72.174 de 72.287 payloads con su fichero y su tamaño; 112 posteriores a la copia (esperado); 1 vacío (§5) |
| PostgreSQL muerto con SIGKILL | vuelve en 7 s, datos intactos |
| Reinicio (Docker cae y vuelve) | todo vuelve solo; el monitor avisó del WAL sin archivar mientras el S3 estaba caído y se recuperó solo |
| `rollback` | 3 s; sano en 9 s |
| Copia cifrada fuera, rotación, restauración del volcado, RAW inmutable | OK |
| Cabeceras | 308 a HTTPS, HSTS, CSP, `X-Frame-Options: DENY`, `nosniff`; `/docs`, `/redoc`, `/openapi.json` → 404; `/auth/me` anónimo → 401 |
| Playwright por HTTPS con datos reales | 61 de 62 (la que falla: §5, Analítica) |

**Prueba de carga.** `predigolctl loadtest`. Cada persona entra con su cuenta y navega como la web: Inicio, Picks,
Partidos y un partido, En vivo, Competiciones y una tabla, Cuotas, Mis picks y Búsqueda, con 3–10 s entre páginas. 45 s
de entrada y 3 min por fase. El generador corría en la **misma** máquina de 2 vCPU que el servidor.

| | Antes de corregir (100 / 200) | **Después (100 / 200)** |
|---|---|---|
| Peticiones/s | 18 / 24 | **31 / 62** |
| Errores | 4,9 % / 30 % (5xx, conexiones agotadas) | **0 % / 0 %** |
| p50 | 1.312 / 2.952 ms | **13 / 20 ms** |
| p95 | 8.591 / 12.038 ms | **93 / 139 ms** |
| p99 | 10.689 / 13.642 ms | **181 / 280 ms** |
| CPU de la máquina (pico) | 100 % / 100 % | 90 % / 99 % (media 57 % / 66 %) |
| CPU de PostgreSQL (pico, de 200 %) | 149 % / 140 % | 107 % / 75 % |
| RAM usada (pico) | 3,6 / 3,9 GB | 3,4 / 3,3 GB |
| Conexiones a la base (pico) | 57 / 99 (máx. 100) | 15 / 19 |
| IOPS (pico) | 41 / 121 | 265 / 25 |
| Transferido | — | 15 MB / 29 MB en 3 min |

Lo que cambió: un pool acotado de conexiones en la API (antes, una conexión nueva por petición); los paneles que
son iguales para todos se calculan una vez cada 15–300 s; y tres consultas reescritas (cuotas, frescura de
plantillas, búsqueda).

## 4. Fallos que encontró el ensayo (corregidos)

1. **Bucle de reinicios de la base.** pgBackRest deja procesos huérfanos. Con PostgreSQL como PID 1, uno que fallara
   (R2 caído, sin *stanza*) reiniciaba la base entera cada pocos segundos. Ahora la base corre bajo `tini`.
2. **`import` verificaba una tabla, no 117.** `compose exec` consumía la entrada del bucle. Pasaba también en el
   ensayo anterior. Ahora falla si no compara tantas tablas como lista el manifiesto.
3. `import` fallaba al cerrar sesiones en un esquema anterior al del código. Ahora usa SQL válido desde la 0045.
4. **Cada despliegue reiniciaba PostgreSQL** (la imagen salía con otro id). Ahora se etiqueta por su contenido.
5. **La API no aguantaba carga:** una conexión por petición, sin límite, y los mismos paneles recalculados por
   cada lector.
6. **Consultas lentas con los datos reales:** lista de cuotas (> 30 s → 40 ms), frescura de plantillas (8,4 s →
   0,2 s), búsqueda (0,24 s → 27 ms; 6–11 s bajo carga).
7. Perfil → Seguridad mostraba el historial de accesos sin traducir.
8. Menores: `export.sh` (pipefail), nombre del `archive_command` (pgBackRest lo exige), CA del repositorio en la
   restauración, límites de CPU mayores que los vCPU, primera pasada del monitor, dos pruebas E2E.

## 5. Riesgos abiertos

| Riesgo | Qué hacer |
|---|---|
| Contabo: variabilidad del host | `bench.sh` el día 1, pago mensual, plan B |
| Admin → Analítica: informes de 4–9 s; la primera carga pasa de 20 s en 2 vCPU | Solo afecta al dueño. Quedan 5 min en caché. Mejora futura: que el worker los precalcule |
| Rankings 8,8 s, cobertura 6 s y conjuntos de datos 2 s en la consola | prototipo de rankings en 1,4 s (no aplicado). Mismo enfoque |
| 1 payload RAW vacío en el portátil (fixtures, 4 oct 02:57 UTC) | Los datos normalizados existen; falta la evidencia de ese fichero. Registrar como hallazgo de calidad. RAW nunca se modifica |
| CSP con `'unsafe-inline'` para scripts (hidratación de la web) | migrar a *nonces* en una fase posterior |
| Clave de API-Football | `SECURITY_ACTION: rotación recomendada posteriormente`, sin autorización no se rota |
| Ensayo en 2 vCPU con el generador dentro | repetir la carga en el VPS desde el portátil (fuera de la máquina) |
| `pitr test` y prueba del volcado con datos completos | necesitan el doble de disco que el sandbox: el día 1 en el VPS |

## 6. Aspectos legales (revisión, no asesoría jurídica)

| Tema | Situación | Antes de abrir la beta |
|---|---|---|
| Términos de API-Football | Prohíben revender los datos ("cannot directly sell the data"). Los datos llegan "as is" | La beta es privada. Si se cobra, que lo que se venda sea el análisis de PrediGol, no los datos del proveedor. Confirmarlo con API-Football si hay dudas |
| Logos e imágenes de `media.api-sports.io` | El proveedor los da solo para identificar. Pueden requerir autorización de ligas y clubes, y la responsabilidad es de quien los usa | Mantenerlos como identificación, sin uso promocional. Valorar retirarlos en la versión pública |
| Ley 1581 de 2012 (habeas data) | Correo, nombre, zona horaria, IP de accesos y picks del usuario son datos personales | Política de tratamiento y aviso de privacidad; autorización al crear la cuenta; canal para consultas y supresión. El Registro Nacional de Bases de Datos obliga a quien tenga activos > 100.000 UVT, que no parece el caso |
| Términos de uso y descargo | El pie ya dice que PrediGol no garantiza resultados y pide jugar con responsabilidad (+18) | Términos de uso (+18, sin garantía de ganancias, no es una casa de apuestas) aceptados al primer inicio de sesión |
| Mensajes comerciales | — | Nunca prometer ganancias ni rentabilidad garantizada |
| Cookies | Solo la de sesión, imprescindible | Mencionarla en la política; no hace falta banner de consentimiento |

## 7. Coste

| Partida | $/mes |
|---|---:|
| Contabo Cloud VPS 6, US Central, mensual | 11,00 |
| Cloudflare Free, Healthchecks.io, UptimeRobot, Sentry Developer, Telegram | 0 |
| R2 (PITR ≈ 2,2 GB con dos completas, copias y RAW) | 0–0,30 |
| Dominio (≈ $11/año) | ≈ 0,92 |
| **Total** | **≈ 12,0–12,3** (≈ $145/año). Con 24 meses de prepago ≈ 10,2–10,5 (≈ $124/año) |

API-Football Ultra se renueva sola y no entra en esta cuenta.

## 8. Siguiente paso: decisiones del dueño

1. Contratar **Contabo Cloud VPS 6, US Central, mensual**, con Ubuntu 24.04.
2. Dominio y zona en Cloudflare Free.
3. R2: un bucket y dos tokens (PITR y copias). Una clave `age`, con la privada solo en su gestor.
4. Bot de Telegram; cuentas gratuitas de Healthchecks.io y UptimeRobot.

Luego, en este orden (`deploy/vps/README.md`):

1. `bench.sh` → `install.sh` → ajustes → ensayo en el VPS: `import` de la copia saneada, `deploy`, `pitr test`,
   `restore-test`, reinicio real y carga desde el portátil.
2. Vaciar el ensayo y hacer el corte (§4 del README): DNS solo con todo en verde.
3. Validar 24–72 h, sin ampliar ligas.

## 9. Código

Todo está en los repositorios bare locales del portátil (nunca en GitHub). Backend y web en
`feature/predigol-ux-rbac`. Los commits de esta fase están en `git log`, desde `6a49c75` (backend) y `701b68e` (web).

# Desplegar PrediGol 24/7: costes, arquitectura y plan (6 oct 2026)

Sustituye a la versión del 5 oct. Precios de lista **sin IVA**, leídos el 6 oct 2026 en páginas oficiales y en las
listas de precios públicas de cada proveedor (AWS Price List, Azure Retail Prices API, API de precios de Hetzner);
lo que solo dan terceros va marcado. Cambio 1 EUR = 1,1225 USD (BCE, 2 oct 2026). Mes = 730 h.
En Colombia los servicios digitales del exterior pueden causar IVA del 19 %: no está incluido.
**No se ha contratado ni desplegado nada.** Contratar es decisión del dueño.

> **Corrección del 6 oct 2026:** las cuotas en vivo crecen bastante más de lo que suponía la tabla de abajo: ≈ 125 GB
> al año con 133 ligas (ver `LIVE_ODDS_STORAGE_2026-10-06.md`). Con la captura en vivo como está, el VPS-2 de 75 GB
> del escenario MVP llegaría al 90 % el 9 ene 2027; sin cuotas en vivo, el 28 ago 2027. Antes de contratar, el dueño
> decide qué hacer con la captura en vivo.

## 1. Qué hay que alojar (medido el 6 oct)

| Pieza | Hoy | Crece |
|---|---|---|
| PostgreSQL 16 | 9,8 GB + 0,6 GB de WAL | ~0,23 GB/día (~7 GB/mes) sin retención; ~52 GB a 12 meses con la retención diseñada (`STORAGE_FORECAST.md`) |
| RAW (respuestas del proveedor, gzip) | 1,0 GB | ~0,06 GB/día (~23 GB a 12 meses); nunca se borra |
| Worker 24/7 (APScheduler, un solo proceso) | 0,7 GB de RAM, picos de CPU en el catch-up | ~6.000 peticiones/día recurrentes a API-Football; hasta ~37.000 en días de cargas |
| API (FastAPI) | 0,17 GB de RAM | ~100 usuarios: carga pequeña |
| Web (TanStack Start, SSR con Nitro) | hoy corre el servidor de desarrollo | en producción: build de Nitro (`node-server`) o SPA estática |
| Copias | volcado ~0,63 GB (6 % de la base) + RAW | 7 diarias + 4 semanales + 6 mensuales ≈ 60–100 GB a 12 meses |

Una máquina de **8 GB de RAM** lo lleva todo con holgura; 4 GB funciona con swap. Lo que dimensiona es el disco de la
base, no los usuarios.

## 2. Los tres escenarios (USD al mes, sin IVA)

| | Económico / MVP | **Recomendado producción** | Alta disponibilidad |
|---|---|---|---|
| Dónde | OVHcloud VPS-2 (UE) | AWS us-east-1 (Virginia) | AWS us-east-1, 2 zonas |
| Infraestructura | $9,53 (€8,49; €7,21 con 12 meses): 4 vCore, 8 GB, 75 GB NVMe, tráfico ilimitado, copia diaria del proveedor | $28,18: EC2 t4g.medium (2 vCPU, 4 GB) + IPv4 | $85,93: 2 × t4g.medium + 2 IPv4 + balanceador ALB |
| Base de datos | $0 (PostgreSQL en el mismo servidor) | $47,45: RDS PostgreSQL db.t4g.medium, una zona | $94,17: RDS db.t4g.medium Multi-AZ |
| Almacenamiento | $0 (75 GB incluidos) | $9,30: EBS 30 GB + 60 GB de base | $18,60: 2 × EBS 30 GB + 60 GB Multi-AZ |
| Backups | $0–1,35: Cloudflare R2 (10 GB gratis; ~100 GB a 12 meses) | $0–1,35: copias automáticas de RDS con PITR incluidas hasta 60 GB + R2 | $3,30: S3 (RAW compartido y copias) |
| Tráfico / CDN / SSL | $0: Cloudflare Free (DNS, proxy, TLS, WAF básico, DDoS) | $0: Cloudflare Free; 100 GB/mes de salida de AWS gratis | $0 |
| Dominio | $0,93 (.com, $11,17/año desde el 1 nov) | $0,93 | $0,93 |
| Monitoreo | $0 (UptimeRobot, Healthchecks.io, Sentry Developer, Telegram) | $0 | $0 |
| **Total infraestructura** | **$10,46–11,81** | **$85,86–87,21** (con compromiso de 1 año: **$65,50–66,85**) | **$202,93** (con compromisos: **$162,93**) |
| Datos (obligatorio en los tres) | API-Football Ultra **$29** | $29 | $29 |

Qué compra cada salto:

* **MVP → Recomendado** (+$75): base gestionada con recuperación a un instante (PITR, hasta 35 días), parches y
  copias sin intervención, servidor de la app separado de los datos, latencia desde Colombia ~80–100 ms en vez de
  ~180–220 ms desde la UE, y un camino de crecimiento (cambiar de tamaño o pasar a Multi-AZ es un ajuste, no una
  migración).
* **Recomendado → Alta disponibilidad** (+$117): sin punto único de fallo en app ni base (failover automático de RDS,
  dos instancias). Exige cambios de código (§6, puntos 13–14). Para ~100 usuarios no se justifica todavía.

Opcionales (fuera de los totales): Apple Developer $99/año ($8,25/mes) y Google Play $25 una vez, solo si hay app en
tiendas; Cloudflare Pro $20–25/mes; Sentry Team $26/mes; Better Stack con guardia $29–34/mes; almacenamiento extra de
la base si no se activa la retención (a 12 meses: +32 GB ≈ +$3,68/mes en RDS de una zona, +$7,36 Multi-AZ).

## 3. Otros proveedores consultados (6 oct 2026)

| Proveedor | Referencia | Por qué no es la elección |
|---|---|---|
| Hetzner | CX33 €8,99 (4/8/80) — **"not available"**; CPX32 €35,99 tras la subida del 15 jun 2026 (+144–175 %); CCX13 €42,99; EE. UU. sin series baratas | la opción barata no se puede contratar hoy y el resto ya no es barato; solo UE/EE. UU./Singapur |
| DigitalOcean | Droplet 4 GB $24; PostgreSQL gestionado 4 GB $60,90 (60 GiB, PITR 7 días) | buena alternativa simple (≈$91/mes); desde el 15 oct (cuentas nuevas) el plan Standard no admite nodo de reserva y la HA exige Advanced desde $130/nodo |
| AWS Lightsail | instancia 4 GB $24 / 8 GB $44 (transferencia incluida); base 4 GB $60 | alternativa sencilla (≈$85); escala peor que EC2/RDS |
| Vultr | 4 GB $20, 8 GB $40; centros en Ciudad de México, São Paulo y Santiago | buena latencia a Colombia; base gestionada desde $15, sin PITR verificado |
| Google Cloud | e2-medium $24,46; Cloud SQL 1 vCPU/3,75 GB $49,31; salida a Sudamérica $0,19/GiB | similar a AWS y más caro en tráfico a Sudamérica |
| Azure | B2s $30,37; PostgreSQL Flexible B1ms $12,41; sin HA en Burstable; B-series v1 se retira en 2028 | sin ventaja |
| Render | servicio 1 CPU/2 GB $25; Postgres 4 GB $55 + $0,30/GB; espacio Pro $25 | ≈$125–150/mes (web + worker + base de 60 GB) |
| Railway | Pro $20 + uso ($20/vCPU, $10/GB RAM, $0,15/GB disco); Hobby limita el disco a 5 GB | coste variable con un worker 24/7 |
| Fly.io | máquina 2 GB $13,39; Postgres gestionado con HA desde $38 (+$0,28/GB) | HA barata, pero su documentación aún lista los parches de seguridad y las actualizaciones de versión como no disponibles |
| Supabase | Pro $25 + cómputo; 8 GB incluidos, $0,125/GB; PITR +$100/mes; el plan gratis se pausa | caro con PITR; no aloja el worker |
| Neon | $0,106/CU-h; $0,35/GB-mes; siempre encendido ≥ ~$20/mes | caro en disco para una base que crece 7 GB/mes |
| Vercel | Hobby **prohíbe el uso comercial**; Pro $20/mes | innecesario: la web cabe en el mismo servidor |
| Contabo | 4 vCPU/8 GB/100 GB ~€5,50 (€4,40 a 24 meses) | el más barato, con tráfico bajo "uso razonable" y recursos compartidos; sin base gestionada: riesgo para el worker y la base |
| Backblaze B2 / Wasabi | $6,95/TB / $7,99/TB (mínimo 1 TB y 90 días) | alternativas a R2 para copias |

## 4. Web, PWA, iOS/Android

| | Web responsive | PWA instalable | App nativa / envoltorio (Capacitor, React Native) |
|---|---|---|---|
| Coste | $0 (ya existe) | $0 de infraestructura; 2–5 días de desarrollo (manifiesto, iconos, service worker, push con VAPID) | Apple $99/año + Google $25; Mac o compilación en la nube; semanas de trabajo y revisiones |
| Instalación | — | Android: aviso de instalación; iOS: "Añadir a inicio" manual (desde iOS 26 toda web añadida abre como app) | tiendas |
| Notificaciones | no | sí: Web Push en Android y en iOS 16.4+ para apps en la pantalla de inicio | sí (APNs/FCM) |
| Cobro | web, sin comisión de tienda | igual | iOS en Colombia: **compra dentro de la app obligatoria** (15–30 %) y prohibido enlazar al pago web; Google: hasta sep 2027 Play Billing, salvo app "solo consumo" (iniciar sesión, pagar fuera sin enlace) |
| Riesgo de revisión | ninguno | ninguno | Apple 4.2 (envoltorios de una web) y 5.3 (contenido de apuestas: hay rechazos documentados de apps sin apuestas); Google: prohibido "¡Apuesta!", anuncios de apuestas o enlaces de afiliado; borrar la cuenta desde la app (Apple 5.1.1) |

**Recomendación:** web + PWA ahora. Más adelante, si hay tracción, Android en Google Play como Trusted Web Activity
"solo consumo" (la misma PWA, $25, sin pagos dentro). iOS nativo solo con caso de negocio y revisión legal, porque
obliga a cobrar con compras dentro de la app y expone a la revisión de contenido de apuestas.

## 5. Infraestructura por componente (escenario recomendado)

| Componente | Cómo se aloja |
|---|---|
| Web | contenedor con el build de Nitro (`node-server`) detrás de Caddy, **mismo origen** que la API (la cookie de sesión y la protección `Origin` lo exigen); estáticos en caché de Cloudflare |
| API | contenedor `uvicorn` (2 procesos) detrás de Caddy; `FBI_API_PUBLIC=1`, cookie `Secure`, `/docs` cerrado |
| Worker | contenedor único (el bloqueo de la base impide un segundo), `restart: unless-stopped`; su catch-up anclado al ledger recupera lo vencido tras cualquier caída |
| PostgreSQL | RDS PostgreSQL 16, subred privada, copias automáticas + PITR 7–35 días, cifrado, rol de la app con privilegios mínimos |
| RAW | disco del servidor + sincronización cada hora a un bucket R2 inmutable (nunca se borra sin copia verificada) |
| Backups | RDS (automático) + volcado lógico diario cifrado a R2 (copia fuera del proveedor) + prueba de restauración semanal (`scripts.backup restore-test`) |
| Tareas programadas | las del worker (capturas, sincronizaciones, auditorías); temporizadores systemd para volcado, retención, sincronización a R2 y prueba de restauración |
| Monitoreo 24/7 | UptimeRobot (web y `/health`, cada 5 min, uso comercial permitido), Healthchecks.io (latido del worker y de cada copia), Sentry (errores de API, worker y web), Telegram (el notificador ya lo soporta), alarmas de CloudWatch (créditos de CPU, disco, almacenamiento de RDS) |
| Borde | Cloudflare Free: DNS, proxy, TLS, WAF básico, 1 regla de límite de peticiones, DDoS; Cloudflare Tunnel (sin puertos abiertos) y Access gratis (hasta 50 usuarios) delante de `/admin` y de SSH |

## 6. Qué falta antes de producción (auditoría del código, 6 oct)

Bloqueantes:

1. **Legal y licencias**: API-Football no da licencia de publicación ("Any license or permission to publish the data
   must be requested by the user from the competent authorities") y su uso para apuestas "may require additional
   licenses"; logos de `media.api-sports.io` sujetos a derechos de terceros. Colombia: no promocionar casas sin
   licencia (Coljuegos bloquea dominios), 18+, publicidad no engañosa sobre aciertos (Ley 1480), Ley 1581
   (autorización, política de tratamiento, canal de reclamos; el RNBD no aplica por debajo de 100.000 UVT).
2. **API-Football vence el 29 oct 04:31 UTC**: sin renovar, el sistema cae al plan gratis de 100 peticiones/día.
   Ultra $29/mes, prepago, hasta −30 % según duración. Rotar la clave al renovar (`SECURITY_ACTION`).
3. **Cuentas propias del usuario**: no existen registro, verificación de correo, recuperación de contraseña ni
   borrado de cuenta (hoy solo el admin crea cuentas). Requieren un proveedor de correo (Resend: 3.000/mes gratis).
4. **Endurecimiento de producción**: `/docs` y `/openapi.json` abiertos; `/health` da detalle a anónimos; falta CSP;
   cookie `Secure` solo por variable; QA y contraseña del dueño en ficheros locales; sin 2FA para SUPER_ADMIN (usar
   Cloudflare Access delante de `/admin` mientras tanto); la API escribe con el rol principal de la base.
5. **Build de producción de la web**: hoy corre `vite dev`. Falta el build de Nitro (o SPA estática) servido en el
   mismo origen que la API.
6. **El diseño de `deploy/` está desactualizado**: pone la API sobre una réplica de solo lectura, incompatible con
   las sesiones y la auditoría de accesos (la API escribe en `auth`), y el Caddyfile no deja pasar `/api/v1/auth`,
   `/home`, `/daily`, `/parlays`, `/live` ni `/admin`. Hay que rehacerlo para el escenario elegido.
7. **Copias y restauración en el destino**: hoy son volcados completos en el portátil (21 GB en `~/backups`, sin
   rotación) y un `maintenance.sh` sin usar; falta copia fuera de la máquina, cifrada, con PITR, y una prueba de
   restauración en el servidor nuevo antes de abrir.
8. **Secretos**: `.env` en texto plano en el disco; en el servidor, fichero 600 o cifrado (SOPS/age) y nunca en el
   repositorio; claves distintas por entorno.

Importantes (antes de cobrar):

9. **Observabilidad externa**: sin monitor de disponibilidad ni de latido, sin Sentry, sin canal configurado en el
   notificador (todo queda `skipped`).
10. **CI/CD sin GitHub** (el backend no se publica allí): puerta local `make check` + `bun run typecheck/lint/test/build`,
    despliegue por bundle git o imagen enviada por SSH, copia automática antes de cada migración, verificación de
    salud y vuelta atrás documentada. Opcional: Forgejo + Woodpecker autoalojados.
11. **Reinicios**: hoy, tras arrancar Windows, nada se levanta solo, y una actualización de la app de Claude mató la
    pila a las 02:36 UTC del 6 oct (§12 de `OFFLINE_RECOVERY_2026-10-06.md`). En servidor: Docker con
    `restart: unless-stopped`, servicios habilitados en systemd y recuperación automática de la instancia.
12. **Retención de datos** (HOT/WARM/COLD diseñada, no activa): necesaria antes de ~enero 2027 para no duplicar el
    disco.
13. **Límites de peticiones por cliente**: el limitador es por proceso y en memoria; en producción, regla de
    Cloudflare + límite por cliente detrás del proxy.

Solo para alta disponibilidad:

14. RAW en almacenamiento compartido (S3/R2) en lugar del disco local, y un worker de reserva que espere el bloqueo de
    la base en vez de salir (hoy sale con el código 75).

## 7. Arquitectura final recomendada

```
Usuario (web/PWA) ──HTTPS──> Cloudflare (DNS, TLS, CDN, WAF, límite de peticiones; Access en /admin)
                                  │ Tunnel (sin puertos públicos)
                                  ▼
                 EC2 t4g.medium, us-east-1 (Docker Compose)
                 ├── Caddy ── /api/v1/* ─> api (uvicorn ×2)
                 │         └── resto ─────> web (Nitro, SSR)
                 └── worker (único) ──HTTPS──> API-Football
                          │ escribe RAW ──(cada hora)──> R2: raw (inmutable)
                          ▼
                 RDS PostgreSQL 16 (privado, PITR, cifrado) ──(diario, cifrado)──> R2: backups
Monitoreo: UptimeRobot · Healthchecks.io · Sentry · Telegram · CloudWatch
```

## 8. Plan de despliegue

0. **Decisiones del dueño (sin coste)**: escenario y proveedor, dominio, renovación de API-Football antes del
   29 oct, revisión legal, presupuesto.
1. **Código (1–2 semanas, en local)**: configuración de producción (§6.4), registro/recuperación/borrado de cuenta y
   consentimiento, páginas legales y 18+, build de la web, `deploy/` nuevo para un servidor + base gestionada, copias
   cifradas a R2 y prueba de restauración, Sentry/monitores/Telegram, PWA (manifiesto, service worker, push).
2. **Infraestructura (1 día, cuando se apruebe)**: cuentas, EC2 y RDS en subred privada, grupos de seguridad sin
   puertos públicos salvo el túnel, SSH solo por Access, actualizaciones automáticas, Docker, swap; Cloudflare (DNS,
   Full strict, WAF, Access, R2).
3. **Ensayo (1 día)**: restaurar la última copia en RDS, `alembic upgrade head`, comparar conteos y auditoría de
   verdad, prueba de restauración, prueba de carga para 100 usuarios.
4. **Corte (fuera de partidos en vivo)**: copia final local, parar el worker local, volcado + RAW final, restaurar,
   arrancar el worker del servidor (su catch-up cubre el hueco), cambiar DNS, verificar salud, capturas y
   auditorías. El portátil queda como respaldo frío 7 días, con el worker parado (nunca dos a la vez).
5. **Después**: prueba de restauración semanal, revisión de costes mensual, retención antes de enero 2027, Android
   como TWA si hay tracción.

## 9. Riesgos

* Un solo servidor (MVP y recomendado): si cae la instancia, la web cae hasta que se recupera (minutos con la
  recuperación automática de EC2; horas si hay que restaurar). La base gestionada protege los datos.
* Proveedores que cambian precios y planes: Hetzner (+113–175 % en CPX/CCX el 15 jun 2026, CX/CAX sin stock),
  DigitalOcean (sin nodo de reserva en Standard desde el 15 oct). Docker + PostgreSQL estándar evitan el bloqueo.
* API-Football: vencimiento, cuota y términos (sin licencia de publicación).
* Legal y tiendas (Coljuegos, Ley 1581, Apple 5.3/4.2, políticas de apuestas de Google).
* Crecimiento de la base (~7 GB/mes) si no se activa la retención.
* Hasta migrar, el portátil: dos caídas el 6 oct (apagado; actualización de la app de Claude).

## 10. Ahorros legítimos

* Cloudflare Free (DNS, TLS, CDN, WAF básico, DDoS, Tunnel, Access hasta 50 usuarios) en vez de balanceador, WAF o
  VPN de pago.
* R2 para copias y RAW: 10 GB gratis, $0,015/GB después, **sin coste de salida** (restaurar es gratis).
* Monitoreo gratis (UptimeRobot permite uso comercial; Healthchecks.io 20 comprobaciones; Sentry 5.000 errores/mes);
  alertas por Telegram con el notificador existente.
* Correo transaccional gratis (Resend 3.000/mes; Brevo 300/día).
* Compromisos de 1 año en AWS (−28 a −37 %); OVH −15 % con 12 meses; API-Football hasta −30 % por duración.
* Créditos de entrada: AWS hasta $200 (6 meses, cuentas nuevas), Google Cloud $300 (90 días): útiles para el ensayo,
  no para depender de ellos.
* Web y API en el mismo servidor: sin Vercel Pro ($20) ni Workers de pago.
* Retención HOT/WARM/COLD: la base a 12 meses pasa de ~92 GB a ~52 GB.
* No pagar alta disponibilidad hasta que la pidan los usuarios o los ingresos.

## 11. Decisión recomendada

Producción en **AWS us-east-1: EC2 t4g.medium + RDS PostgreSQL db.t4g.medium + Cloudflare Free + R2**: **≈$87/mes**
(≈$66 con compromiso de 1 año) más API-Football $29. Si se quiere empezar ya con una beta cerrada, el MVP en un VPS de
8 GB (OVH VPS-2, ≈$12/mes) con copias cifradas y PITR a R2 es seguro para los datos, a costa de latencia y de un
solo punto de fallo. Web + PWA primero; tiendas después.

Fuentes: hetzner.com (cloud, object storage, storage box, dedicated) y docs.hetzner.com; digitalocean.com/pricing y
docs.digitalocean.com; ovhcloud.com/en-ie/vps; vultr.com/pricing; akamai.com/cloud/pricing; scaleway.com; contabo.com;
aws.amazon.com (lightsail, ec2, ebs, rds, s3, cloudfront, free) y el AWS Price List; cloud.google.com (compute, sql,
run, storage, vpc, free); azure.microsoft.com y prices.azure.com; developers.cloudflare.com (pages, workers, r2,
tunnel, registrar, waf) y cloudflare.com/plans; railway.com y docs.railway.com; render.com; fly.io y docs.fly.io;
supabase.com; neon.com; vercel.com/docs; koyeb.com; northflank.com; betterstack.com; uptimerobot.com/terms;
healthchecks.io; grafana.com; sentry.io; resend.com; postmarkapp.com; aws.amazon.com/ses; brevo.com;
backblaze.com; wasabi.com; porkbun.com; api-football.com (pricing, terms); developer.apple.com (Schedule 2, review
guidelines, small business, EU, entitlements, age ratings); support.google.com/googleplay; webkit.org; web.dev;
developer.chrome.com; capacitorjs.com; docs.expo.dev y expo.dev/pricing; coljuegos.gov.co; normativa de Ley 643/2001,
Ley 1581/2012, Decreto 1377/2013, Decreto 090/2018; sedeelectronica.sic.gov.co. Terceros: domainoffer.net (precio de
Cloudflare Registrar), prensa sobre el caso Apple/Epic y la suspensión parcial de la Resolución 19054/2023.

# Desplegar PrediGol 24/7 para ~100 usuarios: opciones y costes (precios leídos el 5 oct 2026)

Precios de lista **sin IVA**, leídos en las páginas oficiales el 5 oct 2026 (cuando una página solo pinta los precios
con JavaScript se leyó con un scraper; las cifras de terceros se marcan). Cambio BCE 1 EUR = 1,1225 USD (2 oct 2026).
Mes = 730 h. **No se ha contratado nada**: contratar es decisión del dueño.

Qué hay que alojar: API (FastAPI), worker (APScheduler, 24/7), PostgreSQL 16 (9 GB hoy, +0,23 GB/día; ver
`STORAGE_FORECAST.md`), el RAW (0,7 GB, +0,06 GB/día), el frontend (estático) y copias fuera del servidor.
Para ~100 usuarios la carga de la API es pequeña; lo que dimensiona es la base de datos y el disco.

## A. MVP — un servidor en la UE con todo en Docker

| Concepto | Mes |
|---|---:|
| Hetzner CX33 (4 vCPU, 8 GB, 80 GB, IPv4) | €8,99 |
| Copias del servidor (20 %) | €1,80 |
| Backblaze B2 ~100 GB (RAW + 30 volcados) | €0,62 ($0,70) |
| Dominio .com | €0,83 ($0,93) |
| TLS (Let's Encrypt), monitor (Better Stack free), errores (Sentry free) | €0 |
| **Total** | **€12,24 / $13,74** |
| Si la CX33 sigue sin stock: CPX32 + copias | **€44,64 / $50,11** |

Añadir para el crecimiento de la base (ver almacenamiento): un volumen de 100–200 GB (Hetzner Volumes ≈ €0,057/GB-mes,
dato de terceros) ≈ €6–11/mes, o mover RAW y copias a Hetzner Object Storage (€6,49/mes incluye 1 TB).
**Riesgos:** un solo servidor (si cae, cae todo); Hetzner subió precios el 15 jun 2026 (CPX ×2,4, CCX ×2,7) y la
serie CX/CAX figura "currently not available" desde ~7 sep.

## B. Recomendado — DigitalOcean Frankfurt con PostgreSQL gestionado

| Concepto | Mes |
|---|---:|
| Droplet 4 GB / 2 vCPU + copias semanales | $28,80 |
| PostgreSQL gestionado 4 GB, 60 GiB, PITR 7 días | $60,90 |
| Spaces (RAW + volcados 30 días) | $5,00 |
| Dominio (monitor gratis) | $0,93 |
| **Total** | **$95,63 / €85,19** |

Alternativas: **Hetzner con dos servidores** (CPX22 app + CPX32 PostgreSQL con PITR a Object Storage) **€74,50**
($83,63; €25,30 si vuelve la serie CX); **AWS Ohio** (t4g.small + RDS t4g.medium Single-AZ 30 GB + S3) **$71,64**.
Ventaja de B: la base de datos tiene copias con recuperación a un instante y no depende del servidor de la app.
Disco: 60 GiB cubren ~6 meses sin retención; con retención, ~12 meses (ampliable a $0,215/GiB).

## C. Alta disponibilidad — AWS Ohio, dos zonas

| Concepto | Mes |
|---|---:|
| 2 × t4g.small + 2 IPv4 + 2 × 20 GB | $35,03 |
| Balanceador (~1 LCU) + 2 IPv4 | $29,57 |
| RDS t4g.medium Multi-AZ + 30 GB | $101,07 |
| S3 ~100 GB | $2,30 |
| Dominio (tráfico < 100 GB gratis) | $0,93 |
| **Total** | **$168,90 / €150,47** |

Alternativas: DigitalOcean 2 Droplets + balanceador + PostgreSQL 4 GB con standby **$163,73**, solo antes del
corte (desde el 15 oct 2026 para cuentas nuevas y el 30 nov para todas, el standby exige la edición Advanced, desde
$130 por nodo → **$301,93**); Render ≈ $206; Fly.io ≈ $102 (base de solo 2 GB de RAM).

## Otros proveedores consultados

| Proveedor | Precio de referencia | Para PrediGol |
|---|---|---|
| Google Cloud | e2-medium $24,46; Cloud SQL 1 vCPU/3,75 GB $49,31 (HA ×2) | similar a AWS |
| Azure | B2s $30,37; PostgreSQL Flexible B2s $49,64 (sin HA en Burstable) | similar a AWS |
| Render | servicio 1 CPU/2 GB $25; Postgres 4 GB $55 (+$0,30/GB) | cómodo, caro en disco |
| Railway | Pro $20 + uso (~$20/vCPU, $10/GB RAM, $0,16/GB volumen) | impredecible con un worker 24/7 |
| Fly.io | máquinas desde $6,70; Postgres gestionado 2 GB $72 | base pequeña |
| Cloudflare | Pages gratis; R2 $0,015/GB-mes sin coste de salida | ideal para el frontend y el RAW |
| Supabase | Pro $25 + cómputo (4 GB $60), PITR +$100 | caro con PITR |
| Backblaze B2 / Wasabi | $6,95/TB-mes / $7,99/TB-mes (mín. 1 TB, 90 días) | copias externas |

## Recomendación

1. **Empezar con B** (o su alternativa Hetzner de dos servidores si se prefiere la UE y el precio) cuando el dueño
   decida desplegar: base gestionada con PITR, app separada, RAW y copias en almacenamiento de objetos.
2. **Frontend en Cloudflare Pages** (gratis) y RAW/copias en R2 o B2.
3. **Antes de desplegar**: renovar o no el plan de API-Football (vence el 29 oct 2026), rotar la clave de la API
   (expuesta en capturas: `SECURITY_ACTION: rotación recomendada posteriormente`), activar la retención, revisión legal
   (`COMMERCIAL_PLANS.md`), HTTPS, secretos fuera del repositorio y prueba de restauración en el entorno nuevo.

Fuentes: hetzner.com/cloud (cost-optimized, regular-performance, general-purpose), docs.hetzner.com (IPv4, ajuste de
precios), hetzner.com/storage/object-storage, digitalocean.com/pricing (droplets, managed-databases, spaces,
load-balancers) y docs.digitalocean.com (PostgreSQL), aws.amazon.com (ec2, vpc, ebs, rds/postgresql, s3,
elasticloadbalancing, lightsail), cloud.google.com (compute, sql, storage), prices.azure.com y azure.microsoft.com
(postgresql, blobs), render.com/pricing, railway.com/pricing, fly.io/pricing, developers.cloudflare.com/r2/pricing,
supabase.com/pricing, backblaze.com, wasabi.com, betterstack.com, sentry.io; terceros: costgoat.com (volúmenes
Hetzner), cfdomainpricing.com, vincentschmalbach.com (stock Hetzner).

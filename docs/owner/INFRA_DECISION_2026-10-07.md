# Infraestructura de la beta: Contabo frente a OVHcloud (7 oct 2026)

**Recomendación: Contabo Cloud VPS 6, 200 GB SSD, región US Central (St. Louis).** Cuesta **$11,00/mes sin
permanencia** o **$9,20/mes prepagando 24 meses**.

El Cloud VPS 4 cumple en CPU, RAM, disco, red y latencia para 200 usuarios. **No cumple el almacenamiento a
24 meses**, y por eso se pasa al Cloud VPS 6, como pide el criterio. Ponerle 200 GB al VPS 4 cuesta solo $0,82/mes
menos que el VPS 6, que además trae +2 vCPU y +4 GB.

Nada se ha contratado.

## 1. Precios actuales

Leídos el 7 oct 2026 en el configurador de Contabo, desde el Chrome del dueño en Colombia, en USD:

| | Cloud VPS 4 | Cloud VPS 6 | Cloud VPS Plus 4 (Performance) |
|---|---|---|---|
| CPU / RAM | 4 vCPU / 8 GB | 6 vCPU / 12 GB | 4 vCPU AMD EPYC / 8 GB |
| Disco | 100 GB SSD (200 GB +$1,80) | 200 GB SSD o 100 GB NVMe (400 GB +$3,60) | 150 GB NVMe |
| Snapshots / puerto | 1 / 200 Mbit/s | 2 / 300 Mbit/s | 5 / 500 Mbit/s |
| 1 mes | $6,60 | $9,00 | $16,25 |
| 12 meses | $5,61 | $7,65 | — |
| 24 meses (prepago) | $5,28 ($126,72 hoy) | $7,20 ($172,80 hoy) | $13,00 |
| Cargo inicial | ninguno, en todos los plazos | ninguno | ninguno |
| US East (NJ) | +$1,90 · 98 ms | +$3,00 · 96 ms | sin consultar |
| US Central (St. Louis) | +$1,30 · 104 ms | +$2,00 · 104 ms | sin consultar |
| US West (Seattle) | +$1,60 · 124 ms | +$2,50 · 125 ms | sin consultar |
| UE / Reino Unido | gratis · 174 ms / +$1,30 · 175 ms | gratis · 173 ms / +$2,00 · 175 ms | — |
| Auto Backup (diario, 10 versiones) | $2,00/mes | $4,00/mes | — |

* El precio con descuento rige «durante los primeros 24 meses». Después vuelve a la tarifa de 1 mes: $6,60 y $9,00.
* El tráfico es ilimitado, con política de uso justo en la salida.
* Contrato mínimo de 1 mes, sin aviso de cancelación si es prepago.

### Cómo ampliar más adelante

Según la FAQ de Contabo, dentro de la línea Core se escalan RAM, vCPU y disco desde el panel «sin reconstruir el
servidor». También se puede duplicar el disco con una «Storage Extension».

Pasar a la línea Performance es una migración única, no una ampliación en el sitio.

### Advertencia de Contabo sobre la línea Core

Contabo la define así: «infraestructura probada con varias generaciones de CPU … donde la CPU rara vez es el cuello
de botella». Para «bases de datos, servicios de API» recomienda Performance VPS.

### OVHcloud, gama VPS 2027

Datos de us.ovhcloud.com, con compromiso de 12 meses. Todos llevan copia diaria incluida.

| Plan | CPU / RAM | Disco | Red | Precio/mes |
|---|---|---|---|---:|
| VPS-2 | 4 vCore / 8 GB | 75 GB NVMe | 1 Gbps | $8,50 |
| VPS-3 | 6 vCore / 12 GB | 100 GB NVMe | 2 Gbps | $12,32 |
| VPS-4 | 8 vCore / 24 GB | 200 GB NVMe | 3 Gbps | $23,37 |

Los snapshots cuestan desde $0,40/mes.

## 2. Latencia medida desde Colombia

Ping desde el portátil del dueño (Movistar, vía Barranquilla), 6 paquetes, 7 oct ~04:00 UTC:

| Destino | Media (mín–máx) |
|---|---|
| OVH US East, Vint Hill VA (`proof.ovh.us`, red SD-VIN de OVH US) | **75 ms** (73–80) |
| Contabo US East (NY/NJ, servidor `vmi*.contaboserver.net` vía Lumen NewYork6) | **99 ms** (94–120) |
| Contabo US Central (IP de prueba 209.126.0.1, red CONTA-48 St. Louis) | **108 ms** (107–109) |
| Contabo US West (servidor `m*.contaboserver.net`) | **121 ms** (120–124) |
| OVH Canadá, BHS (`proof.ovh.ca`) | 102 ms |
| OVH Francia / Contabo UE | 176 ms / 173–174 ms (configurador) |
| Referencia: Vultr NJ / Chicago / Miami / Seattle | 91 / 99 / 109 / 156 ms |

El configurador de Contabo mide lo mismo desde el navegador: 96–98 ms al Este, 104 ms al Centro y 124–125 ms al Oeste.

**Las tres regiones de EE. UU. sirven.** Con Cloudflare delante, la diferencia de 6–8 ms entre el Este y el Centro
no se nota.

## 3. Rendimiento publicado (terceros)

| Plan | Fecha y lugar | CPU (Geekbench 6) | Disco fio 4k aleatorio | Red |
|---|---|---|---|---|
| Contabo Cloud VPS 4 | 31 ago 2026, Francia | 1.172 / 3.393 | 13,1k + 13,1k IOPS (52 MB/s cada uno); 64k 448/450 MB/s | 160–206 Mbit/s (puerto 200) |
| Contabo Cloud VPS 10 (4c/8 GB, nombre anterior) | 9 sep 2026, Francia | 841 / 2.275 | 15,0k + 15,0k IOPS; 64k 1,1 GB/s | ≈ 200 Mbit/s |
| Contabo Cloud VPS 10 (prueba de VPSBenchmarks) | 12 dic 2025 | notas: web F, CPU D, **estabilidad F**, disco E, red E | | |
| OVH VPS-1 2026 (4 vCPU EPYC Milan) | 7 jun 2026, Alemania | notas: web B, CPU C, **estabilidad A**, disco C, red E | | |
| OVH VPS-2 (gama anterior, 6 vCPU) | 24 mar 2026, Gravelines | 698 / 2.724 | 30,3k IOPS; latencia 171/149 µs | ≈ 975 Mbit/s |

**Lectura.** Cuando el host no está saturado, el hardware de Contabo da de sobra para lo que mide PrediGol. El riesgo
real es la variabilidad: los vecinos ruidosos y el *steal* de CPU. OVH es más estable, pero en el presupuesto solo
ofrece 75–100 GB de disco.

**Ninguna de estas cifras sustituye a medir en la máquina comprada.** Para eso está `deploy/vps/bin/bench.sh`
(§5).

## 4. Lo que necesita PrediGol

Medido en el portátil el 7 oct. Ver `BETA_FASE0_BASELINE_2026-10-07.md`.

| Recurso | Uso medido | Mínimo exigido |
|---|---|---|
| CPU | worker 0,07 núcleos y PostgreSQL 0,08 de media; picos en catch-up y reconstrucciones | ≥ 4 vCPU compartidas con *steal* medio < 10 % |
| RAM | worker 1,4 GB; API 0,2 GB por proceso; base de 9,3 GB que crece 0,12 GB/día | ≥ 8 GB. Con 12 GB la caché cubre la mayor parte de la base durante el primer año |
| Disco | ≈ 75–80 GB usados a 12 meses y ≈ 130 GB a 24 | ≥ 100 GB a 12 meses; **≥ 160 GB a 24** |
| IOPS | lecturas en ráfaga (barridos, features) | ≥ 5.000 IOPS 4k mixtas; fsync < 2 ms |
| Red | ~20.000 peticiones/día a API-Football; 200 usuarios | ≥ 100 Mbit/s |
| Latencia desde Colombia | — | ≤ 120 ms |

## 5. Veredicto

| Criterio | Cloud VPS 4 | Cloud VPS 6 | OVH VPS-2 | OVH VPS-3 |
|---|---|---|---|---|
| CPU | ✓ | ✓ (+50 %) | ✓ | ✓ |
| RAM | ✓ (justo a 12–24 meses) | ✓ | ✓ | ✓ |
| Disco a 12 meses | ✓ (≈ 80 %) | ✓ (≈ 40 %) | **✗** (75 GB) | ✓ (≈ 80 %) |
| Disco a 24 meses | **✗** (se llena hacia el mes 15–16) | ✓ (≈ 66 %) | ✗ | ✗ |
| IOPS (publicado) | ✓ | ✓ | ✓ | ✓ |
| Red / latencia | ✓ / 104 ms | ✓ / 104 ms | ✓ / 75 ms | ✓ / 75 ms |
| Estabilidad (publicada) | riesgo (F) | riesgo (misma línea) | buena (A) | buena |
| Snapshots / copias del proveedor | 1 / $2 | 2 / $4 | incluidas | incluidas |
| $/mes (Centro; 1 mes · 24 meses) | $7,90 · $6,58 | **$11,00 · $9,20** | $8,50 (12 m) | $12,32 (12 m) |

**Elección: Cloud VPS 6, 200 GB SSD, US Central.**

**Prueba de carga del ensayo (7 oct, `BETA_DEPLOY_REPORT_2026-10-07.md` §3).** En 2 vCPU, con el generador en la
misma máquina, 200 personas con sesión navegando a la vez: 0 errores, p95 139 ms, RAM 3,3 GB, 19 conexiones. La CPU
y la RAM del VPS 4 bastan para la beta. Lo que lo descarta es el disco a 24 meses.

* El VPS 4 con +100 GB costaría $8,38/mes (24 meses, Centro) frente a $9,20. Por $0,82 más, el VPS 6 da 6 vCPU y
  12 GB.
* La RAM extra cubre la caché de una base que pasará de 9 a 51 GB en un año.
* En OVH, el plan con 200 GB (VPS-4, $23,37) se sale del presupuesto de $5–15.
* US East cuesta $1/mes más por 8 ms menos. Se puede elegir sin cambiar nada más.

### Cómo contratar con el menor riesgo

1. **Pago mensual al principio: $11,00.** No hay permanencia.
2. Medir la máquina el día 1 con `deploy/vps/bin/bench.sh`, antes de instalar nada. Si sale **FALLO** (*steal*,
   IOPS o fsync por debajo del mínimo), se cancela y se pasa al **Cloud VPS Plus 4** (AMD EPYC, NVMe, $13–16,25)
   o a **OVH VPS-3**.
3. Validar 24–72 h con la beta (FASE 14).
4. Pasar a 12 o 24 meses si todo va bien. Ahorra $1,35–1,80/mes. Hay que confirmar con Contabo si un contrato
   mensual se puede cambiar de plazo.

Auto Backup de Contabo ($4/mes) **no hace falta**: las copias propias cifradas fuera del servidor y el PITR (FASE 6)
lo cubren. Los 2 snapshots incluidos se usan antes de cada despliegue grande.

### Coste mensual real

| Partida | $/mes |
|---|---:|
| VPS (Cloud VPS 6, US Central, mensual) | 11,00 |
| Cloudflare Free, UptimeRobot, Healthchecks.io, Sentry Developer, Telegram | 0 |
| R2 (copias + WAL) | 0–0,30, según el volumen por encima de 10 GB |
| Dominio | ≈ 0,92 ($11/año) |
| **Total** | **≈ $12,0–12,3** · con prepago a 24 meses ≈ $10,2–10,5 |

API-Football Ultra ya se renueva sola y no entra en esta cuenta.

## 6. Riesgos y qué hacer

| Riesgo | Mitigación |
|---|---|
| Vecinos ruidosos o *steal* en la línea Core | `bench.sh` el día 1. El monitor vigila el *steal* y avisa si pasa del 15 % durante 15 min. Plan B: Plus 4 u OVH |
| Caída del host (Contabo promete 99,9 %, unos 43 min/mes) | Copias cifradas y PITR fuera (R2). Restaurar en otra máquina con `predigolctl import` lleva ≈ 1 h. Avisos por UptimeRobot y Telegram |
| Disco | Aviso al 80 %. A 24 meses se llega al ≈ 66 %. La Storage Extension duplica el disco sin migrar |
| Precio tras la promoción | El VPS 6 vuelve a $9,00 + región = $11,00. Sigue dentro del presupuesto |

## Fuentes

* Configurador de Contabo, consultado en vivo: `contabo.com/es/vps/cloud-vps-core-4` y `…/cloud-vps-core-6`.
  También `contabo.com/es/vps/` (FAQ) y `contabo.com/es/vps-performance/`.
* [OVHcloud US VPS](https://us.ovhcloud.com/vps/) y [OVHcloud VPS](https://www.ovhcloud.com/en/vps/cheap-vps/).
* YABS:
  * [Contabo Cloud VPS 4, 31 ago 2026](https://www.vpsbenchmarks.com/yabs/contabo-4c-8gb-20260831-b5eff7);
  * [Contabo Cloud VPS 10, 9 sep 2026](https://www.vpsbenchmarks.com/yabs/contabo-4c-8gb-20260909-15add6).
* Pruebas de VPSBenchmarks:
  * [Contabo Cloud VPS 10, dic 2025](https://www.vpsbenchmarks.com/trials/contabo_performance_trial_12Dec2025);
  * [OVH VPS-1 2026](https://www.vpsbenchmarks.com/hosters/ovhcloud/plans/vps-1).
* [CLN.io: OVHcloud VPS benchmark 2026](https://cln.io/blog/ovhcloud-vps-benchmark-geekbench-fio-performance/).
* [Contabo KB: cambiar de plan](https://contabo.com/blog/kb/103000269722-can-i-change-my-virtual-private-server-vps-plan/).
* Registro de redes (RDAP de ARIN): 209.126.0.0/20 y 144.126.128.0/19 son de Contabo Inc.; 135.148.100.0/24 es de
  OVH US (SD-VIN).

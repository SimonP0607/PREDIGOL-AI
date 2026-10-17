# Beta privada · FASE 0: estado inicial, copia verificable y restauración probada (7 oct 2026)

Todo se hizo en el portátil, que sigue siendo el servidor. Nada se borró, nada se publicó y nada se contrató.

## 1. Estado inicial

| | Valor |
|---|---|
| Código | backend `12ae97f` · web `a06ebe9`, en los repositorios bare locales. Etiqueta `PRE_VPS_20261007` en los dos |
| Esquema | Alembic `0069 (head)` |
| PostgreSQL | 16.15 (`postgres:16-alpine`). **9.976.560.663 B** (9,3 GiB); 117 tablas; 49.742.504 filas |
| Tamaño por esquema | core 5,8 GB · features 2,7 GB · models 358 MB · market 252 MB · audit 166 MB · analytics 111 MB · raw 68 MB · picks 54 MB · auth 0,4 MB |
| Roles de la base | solo `fbi`, superusuario. Se corrige en la FASE 1 (§ hardening) |
| Extensiones | btree_gin, pgcrypto, plpgsql |
| RAW | 81.739 ficheros, **761.700.109 B** |
| Servicios | API `/health` ok; web 200; worker latiendo (`Mila:worker`, último latido hace < 2 min); solo `fbi-postgres` en Docker |
| Usuarios | 6 activos: el dueño (SUPER_ADMIN), 1 QA SUPER_ADMIN y 4 QA USER |
| Secretos | la clave de API-Football no está en el historial git, en los árboles de trabajo, en los logs, en los 400 RAW más nuevos **ni en ninguna tabla** (`db_secret_scan`: 0 tablas) |
| Disco del portátil | C: 387 GB libres; copias locales 24 GB |

### Lo que dejó la limpieza del histórico in-play

Solo quedan las dos tablas del libro actual: `market.live_odds_current` (UNLOGGED, 512 KB) y
`market.live_fixture_current` (UNLOGGED, 48 KB). No hay histórico in-play en la base.

En el RAW quedan 17 ficheros `/odds/live`:

* 8 sin fila de índice, anteriores al histórico. No se tocan.
* 4 catálogos de apuestas en vivo (`odds-live-bets`).
* 5 conservados como evidencia porque tienen referencias.

Desde la limpieza no se ha escrito ninguno nuevo.

## 2. Copia completa

| Pieza | Tamaño | sha256 |
|---|---:|---|
| `fbi-20261007T033447Z-PRE_VPS_20261007.dump` (pg_dump `-Fc`) | 631.453.154 B | `c279eaf6…82d82023` |
| `raw-20261007T033447Z-PRE_VPS_20261007.tar` | 821.442.560 B | en `SHA256SUMS-PRE_VPS_20261007` |

* El volcado se hizo dentro del contenedor, desacoplado de `docker.exe`.
* Se copió a `~/backups` y el sha256 coincide dentro y fuera.
* `sha256sum -c` da OK en los dos ficheros.
* Las filas se contaron justo antes (49.742.504) y justo después (49.763.168).

## 3. Prueba de restauración

* **Dónde:** un contenedor `postgres:16-alpine` desechable y sin red (`--network none`). Nunca en la base en marcha.
* **Qué se hizo:** `pg_restore -j 3` del volcado copiado. Después se contaron todas las tablas y se calculó una huella de
  contenido en 14 tablas de historia.

| Comprobación | Resultado |
|---|---|
| `pg_restore` | código 0, **0 errores**, **76 s** |
| Revisión | `0069` |
| Tamaño restaurado | 8.811.158.551 B (8,2 GiB): sin la hinchazón de la base viva (1,17 GB) |
| Tablas y filas | 117 tablas, **49.742.504 filas**, igual que justo antes del volcado |
| Por tabla | 106 iguales antes y después; 11 entre el antes y el después (escritas durante la prueba); **0 fuera de rango; 0 ausentes** |
| Huella de contenido | **14/14 idénticas** |

La huella es el número de filas más la suma de un hash de 64 bits de cada fila. Cubre fixtures, resultados, eventos,
estadísticas de jugador, clasificaciones, cuotas pre-partido, cuotas históricas, últimas pre-partido, near-close,
consenso, predicciones, picks, índice RAW y evidence ledger.

Solo se excluyeron, por clave y en los dos lados, 2 partidos tocados después de las 03:30 UTC.

El contenedor y su volumen se borraron al terminar. **Resultado: la copia restaura. Se puede continuar.**

## 4. Crecimiento y previsión

Medido con `storage_forecast` a las 03:52 UTC, sobre los días completos del 3 al 6 de octubre:

* PostgreSQL crece **117 MB/día**. Lo que más crece:
  * predicciones en tiempo real: 43,3 MB/día;
  * conjuntos de features: 34,9 MB/día;
  * cuotas pre-partido: 9,4 MB/día.
* El RAW crece **21 MB/día**.
* Las cuotas in-play ya no crecen: 0.

| Horizonte | PostgreSQL | RAW | Total |
|---|---:|---:|---:|
| Hoy | 9,3 GB | 0,7 GB | 10,0 GB |
| 3 meses | 19,7 GB | 2,5 GB | 22,2 GB |
| 6 meses | 30,2 GB | 4,4 GB | 34,6 GB |
| 12 meses | 51,1 GB | 8,1 GB | 59,2 GB |
| 24 meses (misma tasa) | ≈ 92,9 GB | ≈ 15,5 GB | **≈ 108 GB** |

Son 133 ligas. Con +50 ligas, la parte ligada a partidos crece ×1,39: ≈ 78 GB a 12 meses y ≈ 147 GB a 24.

En el servidor hay que sumar:

* sistema e imágenes: ≈ 10 GB;
* WAL: 1–2 GB;
* 2 volcados locales: el volcado ocupa el 6,3 % de la base.

**Con eso, a 12 meses se usan ≈ 75–80 GB y a 24 ≈ 130 GB.**

### WAL (para el PITR)

| Medición | Valor |
|---|---|
| 03:33–03:45 UTC, con 2 partidos en vivo | 21,8 kB/s (≈ 1,9 GB/día) |
| Media del 6 al 7 oct, con la limpieza | 5,6 GB/día |

Con compresión del archivo, ≈ 0,4–1,2 GB/día. Ver el informe de despliegue.

## 5. Uso de recursos del sistema actual

En el portátil, para dimensionar:

| Proceso | Medición |
|---|---|
| Worker | 0,069 núcleos de media en 4,4 h; RSS 1,37 GB |
| PostgreSQL | 0,082 núcleos de media en 26,7 h; 273 GB leídos y 22,7 GB escritos. Incluye tres volcados completos y la limpieza in-play |
| API | sin usuarios, 0,003 núcleos; 0,2 GB por proceso |

## 6. Ficheros (portátil)

* `~/backups/fbi-20261007T033447Z-PRE_VPS_20261007.dump`
* `~/backups/raw-20261007T033447Z-PRE_VPS_20261007.tar`
* `~/backups/SHA256SUMS-PRE_VPS_20261007`
* Recuentos: `~/.fbi/prevps_counts_before.json` y `~/.fbi/prevps_counts_after.json`
* Informe de la restauración: `~/.fbi/drill_report.json`
* Previsión: `data/storage/20261007T035237Z/STORAGE.md`

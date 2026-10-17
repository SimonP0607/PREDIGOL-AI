# Backup y recuperación: probado restaurando

**Fecha:** 25 sep 2026 (réplica 01:53 UTC; máquina 03:18 UTC) · **Código:** `src/fbi/ops/backup.py`, `scripts/backup.py` · **Tests:**
`tests/integration/test_backup_restore.py`.

Un backup no cuenta como backup hasta que se ha restaurado y comparado. Esto es lo que hace
`scripts.backup` y lo que se ha comprobado.

## 1. Qué se guarda

`data/backups/<UTC>/` (fuera de git):

| Fichero | Contenido |
|---|---|
| `db.dump` | `pg_dump --format=custom --no-owner --no-privileges` de la base de la aplicación: una instantánea consistente |
| `raw.tar` | el almacén raw completo (los payloads ya están en gzip: tar sin recomprimir; propietario y fechas neutralizados) |
| `manifest.json` | sha256 y tamaño de ambos ficheros; **por tabla**, filas y una huella de contenido independiente del orden (md5 de los md5 ordenados del texto de cada fila, con `TimeZone`, `DateStyle`, `IntervalStyle` y `extra_float_digits` fijos); sha256 de **cada** fichero raw; revisión Alembic; versiones del servidor y de `pg_dump`; tablas escritas durante el dump |

La contraseña llega a `pg_dump`/`pg_restore` solo por el entorno del proceso hijo: nunca en la
línea de comandos, en logs ni en el manifiesto. El manifiesto no contiene parámetros de payloads
(la clave del proveedor no se guarda nunca en el almacén raw: `payload_store.sanitize`).

## 2. Qué comprueba la restauración

`python -m scripts.backup restore-test <carpeta>` (o `create --restore-test`):

1. **FILES** — `db.dump` y `raw.tar` re-hashean a su sha256 del manifiesto.
2. **RESTORE** — `pg_restore --exit-on-error` en una base **nueva y vacía**
   (`fbi_restore_<aleatorio>`) creada para la prueba.
3. **TABLES** — para cada tabla de la base restaurada, filas y huella iguales a las del
   manifiesto.
4. **SCHEMA** — la revisión Alembic restaurada es la del manifiesto.
5. **RAW** — cada fichero extraído re-hashea a su sha256.
6. **LINEAGE** — cada fila de `raw.ingestion_payloads` de la base **restaurada** apunta a un
   fichero que existe en el archivo y cuyo cuerpo re-hashea al hash registrado.

La base temporal y el directorio de extracción se borran al terminar (`--keep` para
inspeccionarlos). Nunca se escribe en la base de la aplicación.

## 3. Resultado en la réplica en la nube (25 sep 2026, 01:53 UTC)

```
backup data/backups/20260925T015302Z-replica in 8.5s
  database fbi_dev at revision 0024: 56 tables, 1083366 rows; dump 10923297 bytes
  raw store: 15 files, 715534 bytes; archive 747520 bytes
  [PASS] FILES: dump and raw archive match the manifest: sha256 ok
  [PASS] RESTORE: pg_restore into a new, empty database: into fbi_restore_74b442b8
  [PASS] TABLES: every table's row count and content fingerprint: 56 tables, 1083366 rows; identical
  [PASS] SCHEMA: the Alembic revision came back: 0024
  [PASS] RAW: every archived file re-hashes to its manifest sha256: 15 files
  [FAIL] LINEAGE: every payload the restored index names exists and re-hashes:
         47 index rows: 15 files present and verified, 32 not in this raw store
restore test FAILED in 7.0s
```

**Lectura honesta.** La base de datos (56 tablas, 1.083.366 filas) y los 15 ficheros archivados
se restauran idénticos. El fallo de LINEAGE es correcto y esperado **en la réplica**: 32 de los
47 payloads indexados (las respuestas de API-Football) están en el almacén raw de la máquina, no
en este entorno. La comprobación existe precisamente para detectar esto. **La prueba que cuenta
es la de la máquina**, con su almacén completo: tenía que dar 6/6 PASS, y lo dio (§4).

El test de integración reproduce los dos casos: un backup con un payload propio que restaura y
verifica, la fila semilla cuyo fichero nunca existió (LINEAGE lo detecta), y un archivo
corrompido un byte (FILES lo detecta y la restauración se niega).

## 4. En la máquina (25 sep 2026): 6/6 PASS

La máquina no tiene `pg_dump`/`pg_restore` en WSL (PostgreSQL vive en el contenedor de Docker
Desktop): con `FBI_PG_CONTAINER=fbi-postgres` las herramientas corren **dentro** del contenedor
por `docker exec`, con el volcado por stdout y la restauración por stdin (`938d55e`). Tras la
sincronización (Alembic 0017 → 0024), la importación de Football-Data y la sesión de backtest:

```
backup data/backups/20260925T031755Z-post-sync in 7.4s
  database fbi at revision 0024: 56 tables, 1121683 rows; dump 10730529 bytes
  raw store: 65 files, 1915175 bytes; archive 2037760 bytes
  [PASS] FILES: dump and raw archive match the manifest: sha256 ok
  [PASS] RESTORE: pg_restore into a new, empty database: into fbi_restore_a17daec6
  [PASS] TABLES: every table's row count and content fingerprint: 56 tables, 1121683 rows; identical
  [PASS] SCHEMA: the Alembic revision came back: 0024
  [PASS] RAW: every archived file re-hashes to its manifest sha256: 65 files
  [PASS] LINEAGE: every payload the restored index names exists and re-hashes: 57 index rows: 57 files present and verified
restore test PASSED in 6.0s (scratch database fbi_restore_a17daec6)
```

Antes de migrar se tomó además el volcado previo (`~/backups/fbi-20260925T025324Z-pre-sync.dump`,
1,9 MB, 43 tablas con datos, a Alembic 0017): el punto de vuelta atrás de la migración.

**Hallazgo menor:** el almacén raw tiene 8 ficheros sin fila de índice (65 ficheros, 57 filas):
seis respuestas de `/status` del 12–13 sep (gratuitas; `capture_odds status` guarda el cuerpo
pero no lo indexa porque no es ingesta), un `/fixtures` del 12 sep anterior al ledger y un
`/leagues` del 24 sep. LINEAGE comprueba índice → fichero y pasa; ningún dato normalizado
apunta a esos ficheros. No se "reindexan" a mano: se dejan como están y constan aquí.

Operación:

- Antes de cada cambio de esquema y antes de cada tier de la migración: `python -m
  scripts.backup create --label <motivo> --restore-test` (el raw crece ~0,1–0,6 GB por tier).
- Retención propuesta: los 3 últimos y el de antes de cada cambio de esquema. Copia fuera del
  portátil (disco externo o almacenamiento cifrado del usuario): **decisión de Simon** (no se
  envía nada a terceros sin su permiso).
- Recuperación ante desastre: `pg_restore` del `db.dump` en una base vacía + extraer `raw.tar` en
  `FBI_RAW_STORE_DIR` + `scripts.backup restore-test` para verificar. Cualquier tabla derivada
  (features, backtests) se puede además recalcular desde raw + core (`scripts.replay_raw`,
  `scripts.build_features`).

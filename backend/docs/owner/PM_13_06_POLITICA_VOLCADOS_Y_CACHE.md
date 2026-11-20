# PM-13-06 · Política de volcados locales y de caché de compilación — PROPUESTA, pendiente del dueño (D1)

Plan Maestro PM, bloque 13. Código DOC-011. 20-nov-2026. **Propuesta, no aplicada**: este documento no borra nada, no cambia ningún
permiso ni ningún ajuste del servidor. Depende de la decisión **D1** de la auditoría de seguridad del 18-nov-2026 (activar la copia
fuera del servidor, R2), que sigue sin decidir: `BACKUP_RCLONE_REMOTE`, `PITR_S3_BUCKET` y `RAW_RCLONE_REMOTE` están vacíos (leído el
20-nov a las 14:55 UTC). Mientras D1 no esté decidida y la primera copia fuera no esté **verificada**, los volcados locales son la única
copia de la base y **no se reduce nada** (regla 2 de la auditoría: no borrar copias ni volcados hasta aprobar el inventario de limpieza).

Coordinación: la política es de la zona de la sesión de seguridad (copias, `/root`, permisos). No había sesión de seguridad activa el
20-nov; esta propuesta queda para que esa sesión y el dueño la aprueben, corrijan o rechacen.

## 1. Lo medido (servidor, 20-nov-2026 14:55 UTC, solo lectura; guion `doc011_q1.sh`)

| Qué | Medida |
| --- | --- |
| Disco `/` (= `/srv`) | 76,0 GB usados de 206,9 GB (37 %); 130,8 GB libres |
| Volcados locales (`/srv/predigol/backups/db`) | **17,2 GB**: 6 volcados de 2,5 a 2,9 GB (15, 18, 19-nov y tres del 20-nov) y un `.dump.partial` de 156 MB del 9-oct |
| Origen de los 6 volcados | todos de despliegues (`auto-*` y `pre-deploy-*`): cada despliegue hace un volcado de ≈ 2,9 GB en ≈ 15 min; el del temporizador de las 04:15 UTC de hoy ya salió rotado por los de los despliegues posteriores |
| Rotación en vigor (`rotate-dumps.sh`, `predigol.env`) | `BACKUP_KEEP_DAILY=3`, `BACKUP_KEEP_WEEKLY=2`: los 3 más nuevos, el más nuevo de cada uno de los 3 últimos días y de cada una de las 2 últimas semanas ISO, más el último que pasó la prueba de restauración (OPS-005). Techo práctico: 9 volcados ≈ 26 GB |
| Caché de compilación de Docker | **3,79 GB** (3,34 GB recuperables) tras la poda automática de las 14:02 UTC (`state/prune.json`: liberó 1,24 GB; tope `PRUNE_BUILD_CACHE` 4 GB por omisión) |
| Imágenes | 3,28 GB (10 imágenes, 4 en uso; 1,52 GB recuperables): `prune.sh` guarda las de los tres últimos despliegues y la marcha atrás |
| Otras copias locales | `/root/import` 1,52 GB (importación del 9-oct, punto de partida de los datos), `/root/releases` 162 MB, `backend.bundle` y `web.bundle` en `/root` (9 MB), RAW 3,17 GB |
| Historia del disco (`state/disk.history`) | máximo 123,7 GB (27-oct, con los 5 volúmenes huérfanos, borrados el 2-nov); desde el 3-nov entre 54,8 y 92,6 GB (el pico del 17-nov, día de varios despliegues) |
| INC-2026-096 (19-nov 09:27-09:31 UTC) | «el disco llega al 90 % en unos 13 días (+5.548 MB/día)», cerrado a los 4 min. El pronóstico (`healthcheck.sh`, punto 12) compara el uso **en ese instante** con la primera muestra de hace 7 días: en mitad de una cadena de despliegue (volcado nuevo + imagen nueva antes de rotar y podar) el uso sube unos 6 GB durante minutos y el ritmo aparente se dispara |

## 2. La política propuesta

### 2.1 Mientras D1 no esté decidida (hoy)

1. **Nada se borra ni se reduce.** La rotación actual se queda (3 diarias + 2 semanales + la última restaurada) y el techo (≈ 26 GB, 13 %
   del disco) cabe de sobra en los 130 GB libres.
2. Los volcados siguen siendo la única copia: la prueba de restauración semanal (lunes 06:00 UTC) y la de cada despliegue con
   migración siguen siendo obligatorias.
3. La caché de compilación sigue con el tope de **4 GB** que ya aplica `prune.sh` después de cada despliegue (medido hoy: 3,8 GB). La
   cifra de 4,7 GB de la ficha era la de antes de esta poda.
4. Se deja escrito el ajuste para que no dependa del valor por omisión: `PRUNE_BUILD_CACHE=4GB` en `predigol.env` (lo hace la sesión de
   seguridad con su kit, cuando toque `predigol.env`; no cambia el comportamiento).

### 2.2 Cuando D1 esté decidida y la primera copia fuera esté verificada (W1 de S2)

| Elemento | Hoy | Propuesta | Libera | Condición |
| --- | --- | --- | --- | --- |
| Volcados diarios locales | 3 + 1 por día (3 días) | 2 + 1 por día (2 días) | ≈ 2,9-5,8 GB | copia verificada en R2 de cada volcado que sale (lo garantiza `rotate-dumps.sh` con `OFFSITE=1`) |
| Volcados semanales locales | 2 | 1 | ≈ 2,9 GB | la semanal en `dumps/weekly/` de R2 |
| Sin copia verificada | — | como mucho 6 (`BACKUP_KEEP_UNVERIFIED`, ya en el código) | — | ya implementado (S2a) |
| `.dump.partial` del 9-oct | 156 MB | borrar (no se puede restaurar) | 0,16 GB | inventario de limpieza (D11) |
| `/root/import` (9-oct) | 1,52 GB | subir cifrado a `audit/` de R2, comprobar huellas, borrar del disco con la palabra del dueño | 1,52 GB | D1 + decisión de la tarea 22 de S2 (el candado de `audit/` es de 365 días: irreversible) |
| `/root/releases` | 162 MB | copia a `audit/` y 30 días en el disco | ≈ 0,1 GB | D1 |
| Caché de compilación | tope 4 GB | tope 3 GB o 7 días | ≈ 1 GB | ninguna (es regenerable): el siguiente despliegue tarda unos minutos más |

Ahorro total con D1: unos **6-11 GB** (de 76 GB). No es urgente: el disco está al 37 %.

### 2.3 Dos propuestas para la sesión de seguridad (no son de esta tarea)

1. **Pronóstico del disco sin falsas alarmas** (causa de INC-2026-096): calcular el ritmo con las muestras diarias guardadas
   (`disk.history`, última frente a la de hace 7 días) en lugar del uso del instante, o no pronosticar mientras haya una cadena de
   despliegue o una copia en marcha. Es un cambio pequeño de `healthcheck.sh`, con sus pruebas `test_vps_*`; el código **OPS-016** que el
   coordinador reservó para un cambio de guion queda **sin usar**: el guion es de la zona de alertas de seguridad y no se toca sin ella.
2. **Permisos de los volcados**: la auditoría encontró los volcados con modo 0644 y montados en el contenedor de la API (para la página
   Sistema). Propuesta: 0640 y montaje de solo lectura o solo de la lista de nombres. Es un cambio de permisos: decisión del dueño y de
   seguridad (regla 1).

## 3. Cómo se aplicaría (cuando se apruebe) y cómo se vuelve atrás

* Lo de 2.2 son tres líneas de `/etc/predigol/predigol.env` (`BACKUP_KEEP_DAILY`, `BACKUP_KEEP_WEEKLY`, `PRUNE_BUILD_CACHE`) con copia
  fechada del fichero antes del cambio, y los borrados del inventario con el kit de R06 (volumen a volumen, con la palabra del dueño).
  Fuera de las ventanas de copia (03:50-05:00 UTC), de las `fixtures_sync` (03:55, 09:55, 15:55, 21:55 UTC) y de los lunes 06:00 UTC.
* Después de cualquier cambio: una prueba de restauración (`restore-test.sh`) y la evidencia con hora UTC en el estado de ejecución.
* Vuelta atrás: restaurar las tres líneas desde la copia fechada. Lo borrado no vuelve: por eso solo se borra lo que tiene copia fuera
  verificada o no se puede restaurar.

## 4. Pendiente

* **Dueño: D1** (copia a R2) y, con ella, W1 de S2. Sin D1 esta política se queda en 2.1.
* **Seguridad y dueño**: aprobar o corregir 2.2 y 2.3.
* Repetir la medición del §1 cuando D1 esté aplicada (mismo guion, solo lectura).

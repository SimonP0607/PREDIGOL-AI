# El disco del servidor: qué lo llena y qué se puede quitar (F14.3) — PrediGol

*Escrito el 24 de octubre de 2026 con lecturas del servidor hechas esa madrugada (las del disco, a las 05:13 y a las 05:38 UTC). **Es solo lectura: no se ha borrado, movido
ni cambiado nada.** Lo que sí se puede quitar, con las órdenes exactas, está en la sección 5 y es decisión tuya (la 10 de la lista).*

## 1. En pocas palabras

* El disco está al **59 %**: 113 GB usados de 193 GB, 81 GB libres.
* **54,2 GB son cinco copias viejas de la base que ningún contenedor usa** (volúmenes anónimos de Docker, del 9 al 12 de octubre). Las dejó la
  prueba de restauración por un fallo que ya está corregido (sección 3). Quitarlas llevaría el disco a ≈ 31 %.
* El aviso del vigilante («disco al 90 % en ≈ 15 días, +3.960 MB/día») **es real pero pesimista**: mide el ritmo de la última semana, y esa
  semana incluye 13 despliegues, tres reconstrucciones de la capa de librerías y el relleno del reloj de precios. Entre el 14 y el 22 de
  octubre, sin nada de eso, el disco crecía **≈ 0,5 GB al día**.
* La copia de seguridad **no sale del servidor** (sección 6). Es lo más importante que queda abierto y no tiene que ver con el espacio.

## 2. Dónde están los 113 GB

| Qué | Tamaño | Nota |
|---|---:|---|
| Volúmenes Docker huérfanos (5) | **54,2 GB** | ningún contenedor los usa; recuperables al 100 % |
| Base de datos viva (`/srv/predigol/pgdata`) | 19 GB (el WAL, 97 MB) | `core` 7,0 GB · `market` 4,7 · `features` 3,9 · `models` 0,9 · `ai` 0,8 · `picks` 0,8 |
| Caché de construcción de Docker | 15,7 GB | 10,3 GB propios; ninguna entrada en uso |
| Imágenes de Docker | 14,7 GB | 62 etiquetas (36 de backend, 26 de web), 4 en uso; 3,5 GB recuperables |
| Copias de la base (`/srv/predigol/backups/db`) | 6,8 GB | 6 volcados de 0,92 a 1,26 GB y un `.partial` de 0,16 GB del 9-oct |
| RAW (respuestas del proveedor) | 2,4 GB | solo crece |
| Sistema, `/root/import` (1,5 GB), diario (0,24 GB), otros | ≈ 6 GB | |

`df` cuenta en GiB y Docker en GB, y las imágenes y la caché comparten capas (en el disco ocupan unos 26 GiB, no 30), así que las cifras no
suman al decimal. Los registros son pequeños: 0,33 GB en `/var/log` y 10 MB cada uno el de `predigol-caddy` y `predigol-postgres`.

## 3. Quién creó los cinco volúmenes

Son volúmenes **anónimos** (los que Docker crea solo cuando una imagen declara un `VOLUME`, como la de PostgreSQL con su carpeta de datos),
de 10,3 a 11,7 GB cada uno. Por dentro son carpetas de datos de PostgreSQL 16 completas: una copia entera de la base restaurada, con el
último archivo escrito el 9-oct (6:14, 15:59 y 17:57), el 11-oct (8:33) y el 12-oct (8:05), hora del servidor.

La causa está escrita en el propio script de la prueba de restauración (`deploy/vps/bin/restore-test.sh`): borraba el contenedor
provisional con `docker rm -f` **sin `-v`**, y eso deja el volumen. Se encontró y se corrigió el 13-oct (la prueba
`test_vps_restore_test.py` lo vigila); el script habla de siete volúmenes y 78 GB entre el 9 y el 13, y hoy quedan cinco (54,2 GB). **Desde el 12-oct no ha aparecido
ninguno nuevo** (la prueba del 19-oct pasó en 490 s y no dejó nada), así que no es una fuga que siga abierta, sino lo que quedó.

## 4. De dónde viene el crecimiento

Una foto diaria del disco (la toma el vigilante a las 00:02 UTC; `/srv/predigol/state/disk.history`). Cada fila dice cuánto cambió **en el día
anterior**:

| Foto | Usado | Cambio del día anterior |
|---|---:|---|
| 10-oct | 56,5 GB | +46,6: el traslado al servidor (importación y los tres primeros volúmenes de prueba) |
| 12-oct | 69,2 GB | +11,7: un volumen de prueba de restauración |
| 13-oct | 81,6 GB | +12,4: otro |
| 14-oct a 22-oct | 84,1 → 88,3 GB | **≈ +0,5 por día**, ocho días sin cargas especiales |
| 23-oct | 102,8 GB | **+14,5** (el 22-oct) |
| 24-oct | 109,6 GB | **+6,8** (el 23-oct) |
| hoy, 05:13 UTC | 113 GB | +3,4 desde la foto, con dos despliegues |

Lo que se ha medido de esos días, que es trabajo de este plan y no un goteo:

* **13 despliegues del 22 al 24 de octubre** (5, 6 y 2 hasta las 04:56 UTC de hoy). Cada uno hizo antes una copia de la base de 1,0 a 1,26 GB; hoy
  hay 6 volcados completos a la vez.
* **La capa de librerías de la imagen (958 MB) se reconstruyó al menos tres veces** (hay tres entradas de 1,24 GB en la caché, creadas el
  22-oct 12:04, el 23-oct 14:01 y el 24-oct 03:24 UTC, y dos imágenes con una capa de librerías propia de 1,26 GB). Se reconstruye cuando
  cambia `pyproject.toml` (cinco commits lo tocaron entre el 22 y el 23-oct) o la imagen base: la reconstrucción del 22-oct 12:04 coincide con
  la descarga de una `python:3.12-slim` distinta de la del 9-oct. Con F14.2 solo se reconstruye cuando cambia `pyproject.toml` o `constraints.txt`
  (o, mientras las imágenes base no estén fijadas, cuando Docker baja una nueva).
* **El reloj de precios (F1) escribió 1,56 millones de cuotas el 22-oct y 11,7 millones el 23-oct** (el relleno desde el 25 de septiembre):
  la tabla `market.odds_quotes` tiene 12,9 millones de filas y 3,0 GB solo en octubre. Hoy escribe a unas 294.000 cuotas en las primeras 5 horas y
  media, es decir, del orden de **0,3 GB al día** con la agenda de hoy.
* La base completa pasó de 11,7 GB el 12-oct (la copia de prueba de ese día) a 19 GB, y el volcado diario de 0,92 GB (18-oct) a 1,26 GB (24-oct).

Con las fotos diarias no se puede repartir cada gigabyte de los dos días grandes entre estas causas; lo que sí se puede decir es que ninguna
es un goteo que siga abierto. **El ritmo de régimen que cabe esperar** es el de antes (≈ 0,5 GB/día) más el reloj de precios (≈ 0,3), más lo que
cueste cada despliegue (unos 0,05 GB si solo cambia el código, ≈ 2,5 GB si cambia una librería, más su copia previa). A ≈ 0,8 GB/día los 81 GB
libres duran más de tres meses, y con los volúmenes quitados, más de cinco.

**Medido el 26-oct (10:31 UTC, `disk.history`, una foto al día):** del 24 al 26-oct el disco creció **≈ 4,0 GB al día** (de 109,6 a 117,6 GiB) y
en la última semana (19 al 26-oct) **≈ 4,4 GB al día** (de 86,7 a 117,6 GiB); del 13 al 22-oct habían sido ≈ 0,75 GB al día. El ritmo de régimen
no se ha podido medir: cada día de esta semana tuvo uno o más despliegues (imagen nueva, caché de construcción y volcado previo) y la base crece
además ≈ 0,8 GB al día con los rellenos en marcha (medido el 25 y 26-oct; documento «ALMACENAMIENTO_PREDIGOL» del Proyecto). **Lo que cambia la conclusión:**
si la cola de despliegues sigue a este ritmo, los ≈ 80 GB libres llegan al 90 % en unas dos semanas. La poda de imágenes viejas y de la caché
de construcción (≈ 21 GB, regenerable) no depende de tener la copia fuera del servidor y es lo primero que conviene hacer; los volúmenes
(54 GB) siguen esperando la copia en R2 y tu «sí». Desde que se despliegue, `bin/storage-report.sh` medirá el ritmo cuatro veces al día.

## 5. Lo que se puede quitar (tuyo; yo no lo hago sin que me lo pidas)

**a) Los cinco volúmenes huérfanos: 54,2 GB.** Es lo único grande y no tiene riesgo para la base viva (usa `/srv/predigol/pgdata`, una
carpeta aparte, no estos volúmenes). Antes de borrar, `docker volume ls -q -f dangling=true` (los que ningún contenedor usa) debe mostrar
exactamente estos cinco nombres (hoy, a las 05:38 UTC, `docker volume ls -q` entero lista solo estos cinco) y `docker system df -v` debe
decir `LINKS 0` en cada uno:

```
docker volume rm \
  2ab7de07de1a627b8aadbabea21b5a5369e1826f81354cf8c5076e7437270385 \
  76fd97bad726fe35e2479692595bf6f86d4992507d1f0e3d2cef085fa9532a3c \
  c7d63a8a6517bfada3c1f92295cba7c7bbb9d59fdc732291d72246b715fd57e3 \
  d22c476bff9f6d95ffa5838ed69900b54e3869278d41bb80824c0f554898363e \
  fa737442e9ae4a01809681ad2e8616b5aa25034b6a3cf7b9f3b858e73978e4da
```

`docker volume rm` se niega a quitar uno que algún contenedor use, así que es seguro por construcción. **No se puede deshacer.**

**b) La caché de construcción y las etiquetas viejas: hasta 14 GB, sin urgencia.** `docker builder prune --filter until=72h` quita la caché que
nadie usa desde hace tres días (la capa de las librerías la usa cada despliegue, así que se queda mientras haya despliegues); y las etiquetas
de imagen de más de una semana que ningún contenedor usa se quitan con `docker image prune -a --filter until=168h` (conserva todo lo
reciente, incluida la versión a la que volvería `predigolctl rollback`). Es comodidad, no necesidad: recupera espacio una vez, y con F14.2 la
caché deja de crecer ≈ 2,5 GB cada vez que se toca `pyproject.toml`.

**c) Lo que no recomiendo tocar:** las copias de `/srv/predigol/backups/db` (la rotación ya decide cuáles quedan; solo sobra el
`predigol-20261009T041657Z.dump.partial`, 0,16 GB de un volcado interrumpido el 9-oct que la rotación no mira), el RAW (es la evidencia),
`/root/import` (1,5 GB de la importación del 9-oct; su borrado es tuyo) ni `/root/f3/referee_obs.csv` (lo usa la cola de árbitros).

## 6. La copia de seguridad que no sale del servidor

El diario del servidor lo dice cada día (22, 23 y 24 de octubre): la copia diaria avisa «no off-server copy configured (… this dump exists
only here)», la copia del RAW dice «RAW_RCLONE_REMOTE is not set» cada hora, y la recuperación a un punto en el tiempo (PITR) dice «not
configured (PITR_S3_BUCKET is empty)». Esas variables están vacías en la configuración del servidor. Todo lo que se ha restaurado en las
pruebas está en el mismo disco que la base.

El código para activarlo **ya está hecho y ensayado** en `deploy/vps/` (`r2-setup.sh`, `pitr.sh`, `r2-restore-drill.sh`; la guía del kit,
`deploy/vps/README.md`). Falta lo que solo tú puedes crear: un cubo de Cloudflare R2 con dos llaves (una para las copias y el RAW, otra para el
PITR), tu clave pública `age` (la privada no sale de tu equipo) y la contraseña de cifrado del PITR guardada en tu gestor. El coste lo marca
el propio kit: R2 cobra a partir de 10 GB, 0,015 US$ por GB y mes. Con los tamaños de hoy (14 diarias + 8 domingos + 12 primeros de mes de
1,26 GB, el RAW de 2,4 GB y el PITR) saldrían del orden de 50 GB, es decir **unos 0,6 US$ al mes** (es una estimación mía, no una medida).

## 7. Qué protege ya al disco

* El reloj de precios (F1) **se niega a estructurar** si quedan menos de 8 GB libres o su tabla pasa de 25 GB: las respuestas guardadas no pierden nada
  por esperar.
* La prueba de restauración semanal **se omite y avisa** si no hay sitio (necesita la base más un 10 % y 5 GB).
* El vigilante (cada 5 minutos) avisa cuando el disco pasa del 85 % y lo da por problema al 92 %; además avisa cuando, al ritmo de la última
  semana, el 90 % queda a menos de 30 días: ese es el aviso de hoy.
* La rotación de volcados está acotada (los más nuevos, el último de cada uno de los últimos días y de las últimas semanas; por defecto 3 días
  y 2 semanas) y, con la copia externa activa, no borra uno cuya copia no se haya comprobado.

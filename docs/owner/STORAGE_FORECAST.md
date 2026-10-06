# Almacenamiento: cuánto ocupa PrediGol hoy, cuánto crecerá y cómo retenerlo

Medido el 5 oct 2026 a las 08:12 UTC con `python -m scripts.storage_forecast` (solo lectura, 0 peticiones al
proveedor; código `8f054a2`). El informe completo, tabla a tabla, queda en `data/storage/<fecha>/STORAGE.md` y se
puede regenerar cuando se quiera. Nada se ha borrado ni movido.

> **Corrección del 6 oct 2026:** la fila de precios en vivo se quedó corta. Se midió en días con el worker apagado a
> ratos. Con partidos completos son 65 % de partidos con cuotas en vivo, 15.851 filas por partido y 306 B por fila: de
> media **~270 MB/día en PostgreSQL y ~70 MB/día de RAW** (≈ 125 GB al año con 133 ligas), no 147 MB/día. El detalle,
> las fechas en que se llena un VPS y las opciones están en `LIVE_ODDS_STORAGE_2026-10-06.md`.
>
> **Aplicado el 6 oct 2026 (23:09–23:41 UTC):** las cuotas en vivo ya no se guardan. Solo queda el libro actual,
> acotado; el histórico in-play quedó archivado y retirado. La medición nueva da 95 MB/día de PostgreSQL y 19 MB/día
> de RAW, con 0 de cuotas en vivo: ≈ 51 GB a 12 meses y ≈ 91 GB a 24 con 133 ligas. Detalle en
> `LIVE_ODDS_CLEANUP_2026-10-06.md`.

## Hoy

| Qué | Tamaño |
|---|---:|
| PostgreSQL | **9,0 GB** (WAL 0,5 GB) |
| RAW (respuestas del proveedor, gzip) | **0,7 GB** de datos, 0,86 GB ocupados en disco (47.221 ficheros) |
| Copias en la máquina | 9,9 GB en `~/backups` (33 ficheros) + 1,4 GB en `data/backups` |
| Logs | 33 MB |
| Disco de la máquina (WSL) | 1.007 GB, 2 % usado |

## Crecimiento diario en régimen estable

| Qué crece | MB/día | Cómo se calcula |
|---|---:|---|
| Precios en vivo (solo cambios) | **147** | 87,6 partidos seguidos/día (28 d) × 43 % con cuotas en vivo × 13.727 filas por partido |
| Vectores de features en tiempo real | 31 | 66,8 vectores distintos por partido en su vida |
| Pronósticos en tiempo real | 27 | 947 filas por partido en su vida |
| Precios pre-partido, consenso, precio final, candidatos | 16 | filas por partido × partidos/día |
| Índice RAW, ledger de ejecuciones, incidencias | 8 | mediana de los días completos |
| Datos de partido (jugadores, eventos, alineaciones) | 2 | ~39 filas por partido × partidos con detalle |
| Feeds de referencia tras su primer llenado | 2 | asignación (solo cambios, personas cada semana) |
| **Base de datos** | **≈ 233** | |
| **RAW** | **≈ 62** | bytes recurrentes por partido × partidos/día + referencia a ~3.500 peticiones/día |

Dos arreglos de hoy ya están descontados: el pipeline guardaba el mismo vector de features en cada ciclo de 30 min
(de 173.135 conjuntos solo 46.890 eran distintos; ~2 millones de valores duplicados al día) y cada despliegue creaba
versiones nuevas de todos los modelos (y re-pronosticaba todo). Ambos están corregidos y con test.

## Proyección

Base de datos y total, en GB. "Retención" = la política HOT/WARM/COLD de abajo. La columna *Backup* es el máximo que
ocuparían 7 copias diarias + 4 semanales + 6 mensuales de la base (cada una ≈ 6 % de la base) más una copia externa
del RAW y del archivo.

| Escenario | Horizonte | PostgreSQL | RAW | Archivo | Backup | **Total** |
|---|---|---:|---:|---:|---:|---:|
| Actual, sin retención | 30 días | 15,9 | 2,6 | 0 | 14,1 | **32,5** |
| | 3 meses | 29,7 | 6,3 | 0 | 31,4 | **67,4** |
| | 6 meses | 50,4 | 11,8 | 0 | 63,7 | **125,9** |
| | 12 meses | 92,1 | 22,9 | 0 | 117,6 | **232,5** |
| Actual, con retención | 6 meses | 36,8 | 11,8 | 1,6 | 51,2 | **101,4** |
| | 12 meses | 52,1 | 22,9 | 4,8 | 81,2 | **160,9** |
| +50 ligas, sin retención | 12 meses | 127,5 | 32,3 | 0 | 163,4 | **323,2** |
| +50 ligas, con retención | 12 meses | 70,6 | 32,3 | 6,8 | 111,7 | **221,5** |

+50 ligas = las 50 primeras candidatas del informe de capacidad: +37,4 partidos/día (+43 % de lo que crece con los
partidos) y +40 % de lo que crece con el número de ligas.

**Lectura para el despliegue:** un servidor con 80 GB de disco (p. ej. Hetzner CX33) se queda corto antes de 6 meses
sin retención. Con retención, la base sigue por debajo de 55 GB a 12 meses, pero el RAW y las copias deben ir a un
volumen o a almacenamiento de objetos (B2/R2/Hetzner Object Storage: céntimos por GB al mes).

## Diseño de retención HOT / WARM / COLD

| Capa | Dónde | Qué guarda | Cuándo pasa a la siguiente |
|---|---|---|---|
| **HOT** | PostgreSQL | todo lo que leen las páginas y los modelos: partidos, resultados, estadísticas, tablas, cuotas pre-partido, consenso, pronósticos, picks, auditorías; precios en vivo de los últimos **90 días** | precios en vivo con más de 90 días: por particiones mensuales (ya existen) |
| **WARM** | Parquet (zstd) en el disco del servidor | precios en vivo de meses anteriores, una carpeta por mes con manifiesto SHA-256; vectores de features duplicados ya no se generan | tras verificar el Parquet contra la partición (filas y huella) |
| **COLD** | almacenamiento de objetos fuera del servidor | RAW completo (inmutable, la prueba de todo), Parquet mensuales, copias de la base (7 diarias / 4 semanales / 6 mensuales / 1 anual) | nunca se borra RAW sin una copia verificada |

Reglas que no se negocian:

1. **El RAW no se borra jamás sin una copia externa verificada** (mismo SHA-256 que el manifiesto). Es la evidencia de
   cada número.
2. Una partición se desconecta de PostgreSQL solo después de que su Parquet se ha releído y cuadra fila a fila; se
   conserva la partición desconectada una semana antes de eliminarla, y eliminarla es decisión del dueño.
3. Las copias se comprueban restaurándolas (`backup restore-test`), no por existir.
4. Hoy las copias en la máquina son volcados completos más un tar completo del RAW (~1,4 GB cada vez): crecerán sin
   límite. Recomendación: volcado diario de la base y copia **incremental** del RAW (cada fichero una sola vez).

Nada de esto está activado: la retención automática es una tarea pendiente (implementar, probar con una partición
antigua y decidir). Antes de 90 días de precios en vivo (principios de enero de 2027) no hace falta.

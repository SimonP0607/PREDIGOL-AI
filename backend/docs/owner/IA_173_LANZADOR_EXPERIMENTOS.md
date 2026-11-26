# IA-173 · Lanzador de experimentos fuera del trabajador (RP-1.6, hallazgo H30)

El trabajador vive a 2,77 de 3 GB y `period_backfill` aborta por falta de margen. La investigación semanal corría como hijo del trabajador, así que su
memoria y su carga caían sobre el mismo contenedor y la misma máquina que los partidos. Esta pieza da un lanzador para el **contenedor de operaciones**.

## Qué hace

`python -m scripts.experiment_run research_v2` (en el contenedor de operaciones; en el servidor, `predigolctl research` o el temporizador):

- **Uno a la vez**: candado consultivo de la base (`pg_try_advisory_lock`) en una conexión que vive toda la corrida; si otro lanzador lo tiene, se niega al instante. El candado muere con la conexión: un lanzador caído no lo deja tomado.
- **Tope de memoria** (2.048 MB por defecto): cada 2 s se lee la memoria residente de todo el grupo de procesos; por encima del tope se mata el grupo (`memory_cap`).
- **Tope de tiempo** (2 h por defecto): pasado el tiempo se mata el grupo (`timeout`).
- **Libro de ejecuciones**: una fila `experiment_run` en `raw.ingestion_runs` por lanzamiento (abierta antes, cerrada después, con tope, pico de memoria y motivo); una negativa (candado, horas de partido, no toca aún) también deja su fila con el motivo.
- **Poca carga**: se niega mientras haya un partido en curso o a punto de empezar (de 3 h tras el saque a 45 min antes), salvo `--allow-match-hours` (orden del dueño).
- **Solo lo listado**: `JOBS` (hoy `research_v2`); nada llega desde fuera como comando. Antes de gastar nada pregunta al bucle de investigación si toca (código de modelo nuevo, conjunto de datos nuevo o cuatro semanas) y no corre si la investigación está congelada.
- Escribe solo su fila del libro; lo que guarda el experimento (`analytics.experiments`, informes) lo guarda él mismo, como siempre.

Códigos de salida: 0 hecho o no toca, 1 falló (error, tope de memoria o de tiempo), 3 negado (otro experimento o horas de partido), 2 uso.

## Kit del servidor

`deploy/vps/bin/research-run.sh`, `predigol-research.service` y `.timer` (lunes 04:20 Bogotá = 09:20 UTC, la hora que ya usaba el trabajo semanal), `predigolctl research`, el temporizador en `install.sh` y el candado/servicio en la quietud de despliegue (`quiet.sh`: un despliegue espera a que acabe una corrida).

## Activación (clase D1, vuelta atrás R1)

El código no cambia nada en producción por sí solo: el temporizador solo se activa cuando se instala en el servidor (`install.sh`), y mientras el trabajador siga
ejecutando su trabajo semanal los dos no deben convivir. Orden: (1) fusionar y desplegar; (2) el trabajo semanal del trabajador pasa a delegar
(`FBI_RESEARCH_RUNNER=ops`, ver la pieza siguiente de RP-1.6); (3) activar el temporizador en el servidor; (4) medir memoria del trabajador antes, durante y después de una corrida real (indicador 20).
Vuelta atrás: desactivar el temporizador y quitar `FBI_RESEARCH_RUNNER`.

## Pruebas

`tests/unit/test_launcher.py`: ceilings (memoria y tiempo matan al grupo entero y lo dicen), salida y fallo del hijo, lectura de `/proc`, trabajo desconocido negado sin tocar la base. `tests/integration/test_launcher_db.py`: un solo lanzador a la vez y el candado muere con su conexión; candado ocupado, horas de partido, «no toca» y «dry run» dejan (o no) su fila con el motivo; un lanzamiento real queda abierto y cerrado.

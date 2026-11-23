# PM-11-07 · La misma cifra en la crónica, el perfil y las estadísticas (IA-158)

Plan Maestro PM, ola 5. Estado: código en `main` tras `FBI_CHRONICLE_STAT_SHEET` **apagado**. Nada pasa a `enforce`; ningún modelo toca una cifra ni una probabilidad.

## 1. El problema, medido

Hasta IA-158 la crónica única (`chronicle-v4`) contaba el xG y los goles por partido de cada equipo desde el paquete de Intelligence:

| Cifra | Crónica (antes) | Perfil y «Estadísticas» (C-13) |
|---|---|---|
| xG a favor y en contra por partido | `dossier.teams.<lado>.all`: los 10 últimos partidos en **cualquier** competición, dos decimales | `analytics.stat_documents`: partidos de **la temporada de la competición del partido**, `u10`/`all` por omisión en la web, tres decimales, regla de cobertura del 80 % (EA-008) |
| Goles y puntos por partido | bloque `form`: los 5–6 últimos resultados | mismo documento C-13 |

Lectura de solo lectura en producción, 21-nov-2026 03:20 UTC, sobre las 118 crónicas v4 de los últimos 14 días (comparables: el documento C-13 vigente no cambió desde el plan, es decir, el equipo no jugó en esa temporada entre el plan y el cálculo):

| | Hechos comparables | Iguales (1 decimal) | Distintos | El perfil no la publica | Distintos escritos en el texto |
|---|---:|---:|---:|---:|---:|
| xG (`xg`) | 23 | 3 | 2 | 18 | 0 |
| Goles por partido (`form`) | 24 | 2 | 22 | — | 6 |

Ejemplos:

- Partido 701889 (18-nov, CONCACAF Nations League), Estados Unidos local: la crónica tenía 1,69 xG a favor y 1,17 en contra en 10 partidos; el perfil (temporada, 2 partidos) muestra 2,72 y 0,84.
- Partido 701888, México local: crónica 1,48 / 0,83 (10 partidos); perfil 1,71 / 0,89 (2 partidos).
- Partido 24829, Nantes local: el texto de la crónica decía 2,33 goles a favor por partido (6 últimos); el perfil muestra 1,30.
- Partido 32914, FC Cajamarca visitante: crónica 0,83 a favor y 2,17 en contra; perfil 1,30 y 2,30.
- Partido 180275, San Vicente y las Granadinas visitante: crónica 2,4 / 0,6; perfil 2,00 / 0,67.

Las 18 filas «el perfil no la publica» son xG que la crónica contaba donde C-13 lo deja vacío por cobertura (`sin_cobertura` o `sin_datos`). Según C-01 2.0.0 la crónica llega a la ruta pública como `pendiente_derechos` mientras el dueño no la publique: las diferencias se ven hoy en la vista privada y quedarían a la vista del lector al publicarla.

## 2. Qué hace IA-158 (con el interruptor encendido)

- `fbi.chronicle.stat_sheet` lee el documento C-13 de cada equipo (temporada de la competición del partido, `u10`, o `season` si no hay `u10`; contexto `all`) y la hoja de hechos (`fbi.chronicle.plan`) cuenta el xG solo de ahí, con `n` = partidos con dato. La fuente del hecho cita la clave de métrica, el documento y su fecha (`C-13:team/<temporada>/<alcance>/all/xg_for,xg_against@team-agg-v1@<computed_at>`).
- El xG del paquete queda fuera (`fuente_c13`); la forma conserva sus resultados y pierde sus promedios (`ppg`, `goals_for`, `goals_against`): un promedio por partido se cuenta desde C-13 o no se cuenta.
- Un documento calculado después del momento del plan no entra (`posterior_al_plan`); uno sin la cifra publicada, tampoco (`sin_cifra_c13`). Se usa el documento vigente y su fecha: la crónica no espera a la pasada de las 07:20 UTC.
- Apagado, el plan es idéntico al de antes (mismo hash). El prompt `chronicle-v4` no cambia.

## 3. La prueba que lo vigila

- `tests/unit/test_chronicle_stat_sheet.py`: sobre una temporada C-13 real (`fbi.stats.team.season_documents`), cero diferencias entre la hoja y lo que la API valida y sirve en todos los partidos; el verificador deja pasar la cifra C-13 y tira la del paquete.
- `tests/integration/test_chronicle_stat_sheet_db.py`: la pasada nocturna escribe, la hoja lee y `stats_profile` sirve la misma cifra; `chronicle_stat_check check` da 0 diferencias.
- En producción: `docker exec predigol-worker python -m scripts.chronicle_stat_check check --sample 500` (criterio: 0 diferencias en 500 partidos) y `... today` (las crónicas guardadas frente al perfil). Solo lectura.

## 4. Lo que no cubre (seguimiento)

- **Máximo goleador** (`top_scorer`): la crónica cuenta los goles de los 10 últimos partidos del equipo; la ficha del jugador (C-13) cuenta la temporada de una competición. Hace falta casar el jugador del paquete (id del proveedor) con su documento C-13: pieza aparte, con Intelligence.
- **Récord en el campo** (`venue_record`) y **cara a cara**: son recuentos de resultados con su propia ventana, no métricas de C-13.
- **C-09** (`/teams/{id}/profile`, «temporada») calcula su propio xG desde `core.fixture_team_stats`: si el dueño quiere una sola cifra también ahí, que lea C-13 (zona UX/Intelligence, contrato C-09).

## 5. Coordinación

Zonas tocadas: `backend/src/fbi/chronicle/*` (Intelligence, bloque 11 del plan PM «con acuerdo») y lectura de `analytics.stat_documents` (EA, solo lectura). 21-nov-2026 03:00 UTC: sin reservas activas en `claude/COORDINACION_SESIONES_2026.md`, ningún PR abierto toca estos archivos (solo los de dependabot) y ninguna sesión de Intelligence o EA activa. Cambio aditivo tras interruptor apagado; la sesión de Intelligence decide su encendido (PM-15-03) tras medir la memoria del worker antes y después.

## 6. Encendido y vuelta atrás

Encender: copia fechada de `app.env`, `FBI_CHRONICLE_STAT_SHEET=on`, `predigolctl up` (worker), y antes `chronicle_stat_check check` con 0 diferencias. Las crónicas de los partidos afectados se reescriben una vez (cambia el hash del plan). Volver: `=off` y `predigolctl up`; sin despliegue.

# PM-00-02 · Foto de las competiciones seguidas y de los interruptores (19-nov-2026)

Plan Maestro PM (`docs/proyecto/PLAN_MAESTRO_INNOVACION_COBERTURA_2026.md`), ola 0. Paso operativo de **solo lectura**: no escribe en la base, no reinicia nada, no cambia configuración y no gasta peticiones del proveedor. Código del registro: OPS-007.

## Resultado (19-nov-2026, 22:07 UTC; servidor en `status: ok`, sin despliegue ni copia en curso)

| Dato | Valor | De dónde |
| --- | --- | --- |
| Competiciones seguidas | **138** (83 ligas y 55 copas) | `core.competitions WHERE is_tracked` |
| Cargadas en total | 165 (27 sin seguir) | `core.competitions` |
| Último cambio en una seguida | 17-nov-2026 13:52 UTC (lote 3) | `max(updated_at)` |
| Competiciones con cobertura del proveedor | 1.253 | `raw.league_coverage` |
| Seguidas que faltaban en `config/rules/coverage.yaml` | 240 (Primera B, Colombia) y 299 (Primera División, Venezuela) | `python -m scripts.ia_rules status` (código 1 antes de este cambio) |

Este cambio añade las dos a `backend/config/rules/coverage.yaml` como «no codificadas» (`not_yet_coded`) y fecha la foto. Con eso, `ia_rules status` deja de marcar huecos tras el despliegue.

Interruptores `FBI_*`: se leyeron los nombres y los valores no secretos de `/etc/predigol/app.env` y del entorno efectivo del contenedor `predigol-api` (coinciden). La tabla queda en el documento de estado del dueño, no en este repositorio público. Ausentes (valen su valor por defecto, apagado): `FBI_PICKS_SOURCE`, `FBI_PLAYER_MARKETS`, `FBI_NEWS_V2`.

Zona horaria del servidor: `Europe/Berlin` (CET, +01:00). `systemctl list-timers` muestra hora local: PITR 04:30 y copia 05:15 CET son las 03:30 y 04:15 UTC del repositorio; la prueba de restauración del lunes, 07:00 CET = 06:00 UTC.

## Cómo repetirlo

Fuera de las ventanas de copia (03:30–05:00 UTC) y a más de 20 minutos de una `fixtures_sync`. Desde el portátil, por SSH al servidor:

```bash
docker exec -i predigol-postgres psql -U postgres -d fbi -X -A <<'SQL'
SET default_transaction_read_only=on; SET statement_timeout='90s';
SELECT count(*) FILTER (WHERE is_tracked) AS seguidas,
       count(*) FILTER (WHERE is_tracked AND type = 'league') AS ligas,
       count(*) FILTER (WHERE is_tracked AND type <> 'league') AS copas,
       count(*) AS cargadas
  FROM core.competitions;
SQL
docker exec predigol-api python -m scripts.ia_rules status   # conexión de solo lectura
```

Para los interruptores, listar solo los **nombres** con `grep -oE '^FBI_[A-Z0-9_]+' /etc/predigol/app.env` y mirar los valores de los que no son llaves, contraseñas, URL ni identificadores (nunca copiar esos valores a un chat, a un PR ni a un documento).

## Vuelta atrás

Las lecturas no dejan nada que revertir. El cambio de `coverage.yaml` se deshace con un PR de `revert`.

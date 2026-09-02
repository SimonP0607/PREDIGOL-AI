# Football Intelligence Platform — V2

Plataforma privada de inteligencia para apuestas de fútbol. Local-first. Uso personal.
No es una casa de apuestas: no gestiona depósitos, retiradas ni dinero real.
El bankroll se modela en **unidades teóricas**.

Sucesora de `football-bot` (congelado en el tag `legacy-final`).
La auditoría completa está en `football-bot/docs/rebuild/`.

## Arranque en frío

```bash
cp .env.example .env      # rellenar FBI_APIFOOTBALL_KEY
make up                   # postgres + api + worker
make migrate              # alembic upgrade head
make test                 # invariantes de esquema + unitarios
make capture              # arranca la captura de cuotas
```

## Lo que este sistema hace diferente al legacy

| Legacy | V2 |
|---|---|
| Una cuota por selección, sobrescrita | Serie temporal: `captured_at` en la clave primaria |
| Calibradores sin validación (ECE=0,0 en 134/152) | `n_val NOT NULL` + `CHECK (val_from > train_to)` |
| `roi_pct` contenía *accuracy* | `accuracy_pct` y `roi_pct` son columnas distintas; ROI exige stake |
| Picks seleccionados sin conocer el precio | `CHECK`: un candidato seleccionado siempre tiene cuota |
| Ranking por probabilidad | Ranking por EV ajustado por incertidumbre |
| 3 estados de liquidación | 7, incluido `half_win`/`half_loss` |
| Scheduler dentro del bot | Scheduler en el worker; el bot es un cliente de la API |

Estas no son convenciones: son restricciones del esquema. `tests/integration/test_schema_invariants.py`
lo demuestra.

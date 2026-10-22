# PREDIGOL

Monorepo con dos partes independientes y su historial original conservado:

- `backend/` — Python 3.12, FastAPI, SQLAlchemy + Alembic, PostgreSQL. Paquete `src/fbi`.
- `web/` — TanStack Start, React 19, Tailwind 4, shadcn/Radix. Se gestiona con **bun**.

Trabaja siempre desde el directorio de la parte que tocas (`cd backend` / `cd web`).

## Backend (`backend/`)

```
make check      # ruff check . && mypy && pytest -q  (la puerta antes de dar algo por hecho)
make test       # pytest -q
make lint       # ruff check .
make format     # ruff format .
make typecheck  # mypy (estricto sobre los paquetes de [tool.mypy].files)
make migrate    # alembic upgrade head
make revision m="mensaje"   # nueva migración
make schema     # python -m scripts.schema_status
```

- Los tests marcados `integration` necesitan un PostgreSQL vivo; sin él, usa `pytest -m "not integration"`.
- `ruff`: línea de 100, Python 3.12. `mypy` es estricto en `src/fbi/*`; un error de tipos ahí rompe `make check`.
- Un solo modo de ejecución local a la vez: host (`make dev-up` / `dev-down` / `status`) **o** compose (`make up` / `down`). `make up` se niega si el modo host está activo.
- `make fresh` BORRA el volumen de la base de datos: no lo ejecutes sin que el usuario lo pida (`CONFIRM=wipe`).
- Migraciones: no edites las ya aplicadas en `migrations/versions/`; crea una nueva con `make revision`.
- Despliegue: `deploy/release.sh` y `deploy/RUNBOOK.md`. No lo lances sin que lo pidan. El árbol de trabajo debe estar limpio.
- Config y secretos en `.env` (ignorado por git; plantilla en `.env.example`). Nunca los edites ni los muestres.

## Web (`web/`)

```
bun run dev         # vite dev
bun run lint        # eslint .
bun run typecheck   # tsc --noEmit && tsc --noEmit -p e2e
bun test            # bun test src   (equivale a `bun run test`)
bun run test:e2e    # playwright test
bun run format      # prettier --write .
bun run build
```

- Usa `bun`, no `npm`/`yarn`. No edites `bun.lock` a mano.
- Antes de dar un cambio por terminado: `bun run lint && bun run typecheck && bun test`.
- El proyecto está conectado a **Lovable**: los commits a la rama conectada se sincronizan allí. Mantén la rama funcionando.

## Reglas del monorepo

- **No reescribas historia publicada**: nada de force push, rebase, amend ni squash de commits ya subidos (Lovable perdería el historial; además el historial importado de cada parte se conservó a propósito).
- Un cambio que cruza el contrato API (`backend/src/fbi/api/contracts`) debe actualizar backend y consumidores en `web/` en el mismo cambio, y pasar los checks de ambos lados.
- Commits pequeños y por parte; prefija el mensaje con el ámbito (`backend:`, `web:`, `docs:`, `chore:`).
- No ejecutes comandos que toquen producción, bases de datos reales o envíen notificaciones sin petición explícita.

> **Sustituido el 7 oct 2026 por `deploy/vps/` (un solo VPS, ensayado; ver `deploy/vps/README.md`).**
> **Desactualizado (6 oct 2026).** Este diseño pone la API sobre una réplica de solo lectura, incompatible con las
> sesiones y la auditoría de accesos (la API escribe en `auth`), y el Caddyfile no deja pasar las rutas actuales
> (`/api/v1/auth`, `/home`, `/daily`, `/parlays`, `/live`, `/admin`). Precios y series de Hetzner también
> cambiaron. Ver `docs/owner/DEPLOYMENT_COSTS.md` antes de usarlo.

# Deployment runbook (shadow mode stays on)

Two Hetzner boxes on one private network, Cloudflare in front. About EUR 16/month.

| Box | Type | Runs | Public ports |
|---|---|---|---|
| A | CX33 | worker + primary Postgres + daily maintenance | SSH only (key, restricted source) |
| B | CX23 | read replica + API + Caddy | 80/443 |

Clients reach box B only. Box B holds no provider key and connects to a read-only replica as `fbi_ro`.
Box A is never exposed.

## First install

1. Create both servers in one Hetzner private network (10.0.0.0/24; A = 10.0.0.2, B = 10.0.0.3).
   Firewall A: 22 from your IP only; 5432 from 10.0.0.3 only. Firewall B: 80/443 (Cloudflare ranges), 22 from your IP.
2. Box A: install Docker, clone the repo to `/opt/fbi`, `cd deploy/primary`, copy `env_example.txt` to `.env`,
   fill it in (`chmod 600`), edit `pg_hba.conf` to B's private address, then `docker compose up -d --build`.
3. Restore the current database into A (`pg_restore`), run `alembic upgrade head`, then create roles:
   `psql -U fbi -d fbi -v ro_pw="'..'" -v repl_pw="'..'" -f roles.sql`.
4. Copy `data/raw` to A before starting the worker. Do not run two workers at once (the advisory lock refuses it).
   Stop the local worker first, then start the one on A, so no live tick is lost in between.
5. Box B: `cd deploy/api`, fill `.env`, run `./init-replica.sh`, then `docker compose up -d --build`.
6. Cloudflare: proxied DNS record to B, SSL mode Full (strict), rate-limit rule on `/api/*`, bot fight mode on.
7. `rclone config` on A for an R2 remote named `r2`; install `fbi-maintenance.timer` and its service.

## Rules that must hold

- The API runs with `FBI_API_PUBLIC=1`: `/picks` returns only qualified picks, no candidates, no rejection detail.
  Today that is none, and the response says so.
- Caddy allowlists product routes. System, ops, explorer and the AI analyst answer 404.
- Nothing is dropped from the live series unless the Parquet archive verified against its checksums first.
- The live worker is never scaled down or paused for maintenance longer than a deploy restart.

## Not done yet (decide before charging anyone)

- Per-client API keys and quotas (today only Cloudflare rate limiting protects the API).
- A public live-odds endpoint (the API has none yet).
- Written permission from API-Football to redistribute their data to third parties.
- Whether selling or publishing betting tips needs a licence in the countries you target.
- Restore test on the production database in a maintenance window.

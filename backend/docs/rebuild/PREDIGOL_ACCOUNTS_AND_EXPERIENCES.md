# PrediGol — accounts, roles, languages and the two experiences

State on 3 Oct 2026, branch `feature/predigol-ux-rbac` (backend + frontend). Local only:
nothing here is deployed publicly.

## Two experiences, one app (http://localhost:5173)

| | USER | SUPER_ADMIN |
|---|---|---|
| Lands on | `/home` | `/admin/overview` |
| Sees | Inicio, Partidos, En vivo, Picks, Parlays, Cuotas, Perfil | everything a USER sees **plus** the Admin Console (`/admin/*`) |
| Picks / parlays | **qualified selections only**; an honest empty state when there are none | can switch on a labelled *shadow preview* (unqualified picks laid out as the product would show them) |
| Match center | Resumen, Estadísticas, Mercados, Alineaciones | plus Avanzado / Auditoría |

"Ver como USER / Preview as USER" (admin header) renders the product exactly as a USER sees
it, with a banner and an exit button. It changes presentation only: the session keeps its role.

## Roles and what protects them

* Roles live in `auth.roles`; **what a role may do is decided in code**
  (`src/fbi/auth/roles.py`): `SUPER_ADMIN` has every permission, `USER` only `app`.
  An unknown role gets nothing.
* Every route belongs to one of three tiers, set in one place (`src/fbi/api/app.py`):
  * public: `/health`, `/api/v1/auth/login|logout|me`;
  * app (signed in): `/api/v1/home`, `/picks`, `/parlays/*`, `/odds/*`, `/matches*`, `/live`, …;
  * admin (`SUPER_ADMIN`): everything under `/api/v1/admin/*`, including users and audit.
* A USER calling an admin route gets **403** whatever the URL; `?preview=shadow` on a product
  route is also refused to a USER. `tests/integration/test_auth_rbac.py` walks every route of
  the OpenAPI document and checks 401 / 403 / 200 by tier.
* State-changing requests must be same-site (`x-requested-with: predigol` and a matching
  `Origin`), so another site cannot drive a signed-in browser.

## Sessions and passwords

* Passwords: Argon2id (`argon2-cffi`). Never stored, logged or returned.
* Session: a random token in an **HttpOnly, SameSite=Lax** cookie (`predigol_session`); the
  database keeps only its SHA-256. Nothing sensitive is kept in `localStorage`.
* Lifetime: `FBI_SESSION_TTL_HOURS` (default 168 h, absolute) and `FBI_SESSION_IDLE_HOURS`
  (default 72 h without use). Logout, a password change (other sessions) and disabling an
  account end sessions; the role is read from the database on every request, so a role
  change applies at once. Behind HTTPS set `FBI_SESSION_COOKIE_SECURE=1`.
* Failed sign-ins are throttled per e-mail and per client and written to the audit log
  (`/admin/audit`), as are sign-ins, sign-outs, preference, role and status changes.
* Guards: an admin cannot disable their own account, and the last active SUPER_ADMIN cannot
  be disabled or demoted.

## Accounts on this machine

| Account | Role | Language / zone | Credentials file (mode 0600, never in Git) |
|---|---|---|---|
| simon.p1506@gmail.com (owner) | SUPER_ADMIN | es · America/Bogota | `~/.fbi/predigol-admin.txt` |
| qa.admin@predigol.local | SUPER_ADMIN | en · UTC | `~/.fbi/qa-admin.txt` |
| qa.user@predigol.local | USER | es · America/Bogota | `~/.fbi/qa-user.txt` |
| qa.user.en@predigol.local | USER | en · Europe/Madrid | `~/.fbi/qa-user-en.txt` |
| qa.switch@predigol.local | USER | es · America/Bogota | `~/.fbi/qa-switch.txt` |
| qa.target@predigol.local | USER | es · UTC | `~/.fbi/qa-target.txt` |

The QA accounts exist for the end-to-end suite (`e2e/accounts.ts`); `qa.target` is the one the
suite disables, re-enables and promotes. Disable them before any public deployment.

```bash
# a new account (password generated into a 0600 file, shown nowhere else)
.venv/bin/python -m scripts.create_user --email someone@example.com --role USER \
    --language es --timezone America/Bogota --generate --out ~/.fbi/someone.txt
# a new password for an existing account
.venv/bin/python -m scripts.create_user --email someone@example.com --reset --generate \
    --out ~/.fbi/someone.txt --force
```
Accounts are also created, enabled/disabled and promoted from **Admin → Usuarios**.

## Languages and time zones

* Spanish and English from catalogs (`src/locales/{es,en}/*.json` in the frontend); no text
  is translated at run time. The choice is stored per account (`auth.users.language`) and
  changed from the header (ES | EN) or the profile; a key missing in one language falls back
  to the other, then to the key itself (the unit test and the E2E leak check fail on that).
* The database stays in UTC. Each account has an IANA zone, set when the account is created
  (Admin → Usuarios proposes the device's zone, detected with `Intl`) and editable in the
  profile, which offers the device's zone in one click. Every date and kick-off on screen
  uses it, DST included.
* Numbers follow the language: `2,10` / `52,3 %` in Spanish, `2.10` / `52.3%` in English.

## Picks and parlays (what a USER can ever see)

* `/api/v1/picks` and the home "Top 5" list **qualified** picks only. Shadow picks are never
  promoted automatically; with none qualified the answer is the empty state
  ("No hay suficientes selecciones calificadas hoy.").
* Parlays (`src/fbi/parlays/engine.py`): daily (next 24 h, 5 legs) and multi-day (next 48 h,
  6–7 legs). Every leg must pass the value gate — qualified, current best price no older than
  3 h, at least 2 bookmakers in the consensus, strictly positive EV against the de-vigged
  consensus, kick-off at least 10 min away, best price not more than 25 % above the fair price
  (otherwise it is a likely stale or wrong quote, `price_outlier`). The correlation guard
  keeps one leg per fixture. If fewer legs pass than the parlay needs, the answer is
  "NO VALID PARLAY TODAY" — value is never invented to fill it.
* Combined odds are the product of the legs; the joint probability is the product of
  independent legs from different fixtures; EV = Π(1+evᵢ) − 1.

## Before going public (pending, deliberately not done locally)

1. **API-Sports media rights.** Team logos, competition logos and flags are loaded from
   `media.api-sports.io`. Verify the licence allows redistributing them in a public product
   (or host licensed assets) before the deployment. Until then the UI falls back to initials.
2. HTTPS everywhere; `FBI_SESSION_COOKIE_SECURE=1`; web and `/api/v1` on the same origin behind
   the reverse proxy; HSTS and security headers (CSP, frame-ancestors) at the proxy.
3. CORS: `FBI_API_CORS_ORIGINS` restricted to the production origin.
4. `/health` tells anonymous callers component details and the provider's request count:
   reduce it to up/down for anonymous callers. Disable or protect `/docs` and `/openapi.json`.
5. Accounts: change the owner's password after storing it in a password manager and delete
   `~/.fbi/predigol-admin.txt`; disable the `qa.*@predigol.local` accounts.
6. Least privilege: the API writes auth tables with the main database role — give it a
   separate role limited to the `auth` schema.
7. Rate limits: the local web proxy shares one bucket (3,000 requests/min) between tabs;
   set production limits per client.
8. Serve the production build of the frontend (not the Vite dev server) and set
   `VITE_APP_VERSION`.
9. Backups: automatic dump before every deployment, and one restore test on the target host.
10. Review the legal requirements for betting-related content in each target market; the
    footer already says that PrediGol informs and guarantees no result (18+).

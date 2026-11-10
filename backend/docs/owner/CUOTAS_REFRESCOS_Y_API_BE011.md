# Refrescos del libro de cuotas y API del explorador (BE-011, plan Cuotas, ola 2)

**Qué es.** Dos cosas, las dos apagadas por defecto:

1. **Refrescos del libro** (`odds_book_refresh`): el worker vuelve a pedir `/odds?fixture=` entre las 6 ventanas de los modelos,
   solo para el libro vigente del explorador: cada 3 h de T-72 h a T-6 h, cada hora de T-6 h a T-1 h, y a T-30 y T-10 min (24
   peticiones más por partido como mucho; los puntos que coinciden con una ventana de modelo los pide la captura de siempre).
   Motivo medido: en 14 días (1.578 partidos) la última actualización del proveedor llegó una mediana de 103 min antes del inicio
   y, en el 84 % de los partidos, después de nuestra captura de T-180.
2. **API del explorador** (migración **0129**, aditiva): `GET /odds/families`, `/odds/board`, `/matches/{id}/odds-book`,
   `/odds/fixtures/{id}/movement` y `/admin/odds/health` (solo SUPER_ADMIN), leídas del libro y de la historia, con caché
   compartida de 60 s (el movimiento, 5 min). Ningún lector provoca una petición al proveedor. `/odds/best` sigue igual.

**Lo que NO cambia.** Modelos, picks, SHADOW, familias, parlay y Match Center ven exactamente lo mismo: las peticiones del refresco
se apuntan en una tabla nueva, `market.book_asks` (nunca en `market.odds_asks`); sus cuerpos van al crudo y al índice de payloads
bajo su propio trabajo, y el extractor (`quote_extract`) se los salta, así que `odds_quotes`, `odds_snapshots`,
`market_consensus` y `quote_current` no se mueven (prueba de integración). Si la captura recibe después un cuerpo idéntico que
pidió primero un refresco, la fila del índice pasa a ser de la captura, con su hora, como si el refresco no hubiera existido. La
huella de modelos sigue en `mc9a7bec97ca`.

## Los interruptores (en `/etc/predigol/app.env`)

| Variable | Por defecto | Qué hace |
|---|---|---|
| `FBI_ODDS_BOOK` | apagado | Construye el libro (BE-010). Los refrescos lo necesitan encendido. |
| `FBI_ODDS_BOOK_REFRESH` | apagado | Refrescos del libro. Solo corren con `FBI_ODDS_BOOK` encendido también. Reiniciar el worker. |
| `FBI_ODDS_BOOK_DAILY_BUDGET` | 8000 | Peticiones al día (UTC) como mucho para los refrescos, dentro del cupo compartido. |
| `FBI_ODDS_BOOK_RESERVE` | 6000 | Los refrescos se cortan si quedan menos de esto más las ventanas de captura de las próximas 24 h, en nuestro cupo o en el que dice el proveedor. Son lo primero que se corta (el seguimiento en vivo para en 3.000). |
| `FBI_ODDS_EXPLORER` | apagado | La web enseña el explorador nuevo en vez de la página de Cuotas actual (`/auth/me` → `odds_explorer`). Recrear la API. Las rutas de la API responden con él apagado, para verificar antes. |

Encendido «como `1`, `on`, `true` o `yes`»; cualquier otro valor es apagado. Cadencia del trabajo: cada 5 min
(`FBI_ODDS_BOOK_REFRESH_MINUTES`), como mucho 400 peticiones (`FBI_ODDS_BOOK_REFRESH_PER_RUN`) y 240 s por vuelta.

**Frescura (una sola regla, `fbi/odds/freshness.py`).** Un precio es *vigente* si lo confirmó la última captura o refresco
previsto para su distancia al inicio, con la tolerancia de siempre (`FBI_ODDS_WINDOW_TOLERANCE`, 45 min); *antiguo* si se saltó
uno. Con los refrescos apagados solo cuentan las 6 ventanas. Lo antiguo se ve atenuado, no va al parlay y no entra en el orden
por diferencia con la justa.

**Cupo del proveedor.** El cliente lee ahora las cabeceras `x-ratelimit-requests-*` (día) y `X-RateLimit-*` (minuto) de cada
respuesta y guarda la última del día en `raw.provider_reported_quota` (tabla nueva). `raw.provider_quota` sigue siendo nuestro
contador.

**«Mercados» del partido y Cuotas dicen lo mismo (BE-020).** Con `FBI_ODDS_BOOK_REFRESH` encendido, el libro cuenta también
las respuestas de los refrescos, que el extractor nunca lee; para que el mismo partido no enseñe un precio en Cuotas y otro en
«Mercados», la ruta `/matches/{id}/markets/catalog` lee entonces el libro (los mismos mercados, claves y números; «desde cuándo»
es el de la respuesta vigente, como siempre). Con los refrescos apagados, o si el libro aún no tiene filas de ese partido, lee
como siempre. Sin cambio de datos ni de migración; se deshace apagando `FBI_ODDS_BOOK_REFRESH` y recreando la API.

## Comprobarlo sin tocar nada

Con `predigolctl psql` (solo lectura):

```sql
SELECT count(*) AS pedidos_hoy, count(DISTINCT provider_fixture_id) AS partidos FROM market.book_asks
 WHERE asked_at >= date_trunc('day', now());
SELECT started_at, status, api_calls, rows_written, left(notes, 300) FROM raw.ingestion_runs
 WHERE job_type = 'odds_book_refresh' ORDER BY started_at DESC LIMIT 5;
SELECT * FROM raw.provider_reported_quota ORDER BY quota_date DESC LIMIT 3;
-- el extractor no ha leído nada de los refrescos (debe dar 0)
SELECT count(*) FROM market.odds_extractions x JOIN raw.ingestion_payloads p ON p.hash = x.payload_hash
  JOIN raw.ingestion_runs r ON r.id = p.run_id WHERE r.job_type = 'odds_book_refresh';
```

Y en la consola, con la sesión del dueño: `GET /api/v1/admin/odds/health` (antigüedad por horizonte, partidos antiguos, retraso
del extractor, tamaño del libro, cupo nuestro y del proveedor, filas en particiones DEFAULT, `odds_quotes` frente a su freno).
La huella de modelos: `python3 scripts/model_code_guard.py fingerprint dir=.` → `mc9a7bec97ca`.

## Vuelta atrás

1. Apagar: quitar `FBI_ODDS_BOOK_REFRESH` (o `=0`) y reiniciar el worker; quitar `FBI_ODDS_EXPLORER` y recrear la API. El libro
   vuelve a refrescarse solo con las 6 ventanas; lo ya guardado no molesta a nadie.
2. Quitar las tablas: `alembic downgrade 0128`, con el respaldo habitual. Borra `market.book_asks`,
   `raw.provider_reported_quota` y la columna `book_current.books`; el crudo y todo lo demás quedan intactos.

## Retirada de `/odds/best` y de la página antigua (BE-033)

`/odds/best` y la página antigua de Cuotas (`OddsPage`, la que se ve con `FBI_ODDS_EXPLORER` apagado) siguen mientras el explorador
se asienta. Desde BE-033 cada llamada se cuenta por día UTC, tipo de cliente y rol en `audit.deprecated_api_use` (migración
**0133**; sin usuario, sesión ni dirección), y la respuesta lleva `Deprecation: true` y `Link: </api/v1/odds/board>;
rel="successor-version"`. El tipo de cliente sale del User-Agent: `browser` (la página de un lector), `e2e` (Playwright),
`testclient` (la instantánea de línea base de cada despliegue), `script` (curl, httpx, la prueba de carga) y `other`.

**Comprobarlo** (con `predigolctl psql`, solo lectura):

```sql
SELECT day, caller, role, calls, last_at FROM audit.deprecated_api_use
 WHERE endpoint = '/odds/best' AND day >= current_date - 7 ORDER BY day DESC, caller;
```

**Se retira cuando**: (1) hay **7 días seguidos sin filas `browser`**; (2) el dueño ha comprobado el explorador con su cuenta;
(3) en la misma PR (backend y web a la vez) se quitan el endpoint, `OddsPage`, `bestOdds` del cliente y su consulta, su entrada de
`PRODUCT_PREVIEW` (`fbi/ops/baseline.py`) y de `scripts/api_shapes.py` (instantánea regenerada con `--reason`), los usos en las
E2E (`journey`, `personal`, `rbac`, `responsive`, `user`) y en las pruebas de integración (`test_product_endpoints`,
`test_auth_rbac`, `test_pick_states`, `test_personalization`), y `FBI_ODDS_EXPLORER` deja de decidir (el explorador para todos).
La prueba de carga (`deploy/vps/bin/loadtest.py`) ya pide el explorador. **Vuelta atrás**: revertir esa PR. La tabla se queda
(es solo un recuento); `alembic downgrade 0132` la quita si se quiere.

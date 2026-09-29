# Plan Ultra — límites reales de esta cuenta

**Comprobado el 29 sep 2026 a las 04:32 UTC** contra `/status` (llamada gratuita) y la página de
precios oficial. No se copia información antigua.

## 1. Lo que dice el proveedor sobre esta cuenta

```
plan (provider)      : ultra
requests today       : 4 / 75000
subscription active  : True (ends 2026-10-29T04:31:07+00:00)
```

| Concepto | Valor | Fuente |
|---|---|---|
| Plan | **Ultra** | `/status` |
| Cuota diaria | **75.000 peticiones** | `/status` (`limit_day`) |
| Peticiones/minuto | **450** | página de precios oficial |
| Precio | **$29/mes** | página de precios, 29 sep 2026 |
| Suscripción | activa hasta **29 oct 2026** | `/status` |
| Acceso a endpoints | **todos** | *"All our plans include all competitions and endpoints"* |

## 2. Restricciones que **desaparecen** al salir de Free

| Restricción en Free | Estado en Ultra |
|---|---|
| `/fixtures?ids=` rechazado (*"Free plans do not have access to the Ids parameter"*) | **disponible** — verificado con la sonda: 4/4 bloques, 3,8 KB/partido |
| `/fixtures?date=` solo ±1 día (*"try from X to Y"*) | **sin límite observado** |
| Temporadas antiguas inaccesibles (*"Free plans are limited in terms of available seasons"*) | **sin límite observado**: el plan cubre 643 competición-temporadas verificadas |
| 100 peticiones/día | 75.000 |

## 3. Restricciones que **siguen vigentes** en Ultra

Ninguna de estas depende del plan — son de la API:

- **Cuotas pre-partido: 14 días de antelación, 7 de historia.** Comprar Ultra no compra histórico
  de precios.
- **Cuotas en vivo: sin historia.**
- **Lesiones desde abril 2021**, VAR desde 2020-21, mitades desde 2024.
- **`ids` máximo 20.**
- **Paginación:** `/players` 20/página, `/players/profiles` 250, `/odds` 10, `/odds/mapping` 100.
- **Solo GET, solo la cabecera `x-apisports-key`.**
- **Cobertura por liga-temporada**: `true` no garantiza completitud.

## 4. Cómo se comporta al agotar la cuota

De los términos del proveedor: al llegar al límite diario **la API deja de procesar y devuelve un
error**, no cobra excedente. La cuota se reinicia a las **00:00 UTC** y lo no usado se pierde.

Nuestra defensa, ya en el código:
- `FBI_APIFOOTBALL_DAILY_BUDGET=60000` — tope propio, 80 % del límite del plan. Deja 15.000
  peticiones de colchón antes de que el proveedor corte.
- `raw.provider_quota` es un contador **compartido entre procesos**: el worker, el backfill y
  cualquier script cuentan contra el mismo número.
- El backfill reserva aparte lo que la operación en vivo va a necesitar en 24 h y **se abstiene**
  si el resto del día queda dentro de esa reserva.

## 5. Configuración aplicada

```
FBI_APIFOOTBALL_PLAN=ultra          # antes: free
FBI_APIFOOTBALL_DAILY_BUDGET=60000  # antes: 60
FBI_APIFOOTBALL_MAX_CONCURRENCY=4
FBI_APIFOOTBALL_KEY=[REDACTED]      # sin cambios: el upgrade no cambia la clave
```

`effective_budget = min(daily_budget, per_day_limit)` = 60.000.

## 6. Nota sobre la compra

El modelo de capacidad recomendaba **Pro** ($19): con `ids=` disponible la migración completa cabe
en 2,5 días. Se compró Ultra ($29). No es un error costoso —Ultra da margen para las 72
competiciones en vivo y para rehacer el histórico sin planificar— pero conviene tenerlo escrito:
**la diferencia de $10/mes no era necesaria para el alcance actual**. Al renovar, Pro es suficiente
salvo que el alcance en vivo crezca por encima de ~2.000 peticiones/día de pico.

## 7. Seguridad

`SECURITY_ACTION: Rotación recomendada posteriormente.` — la clave apareció legible en capturas de
pantalla del dashboard compartidas en la conversación del 29 sep 2026. No se ha rotado (requiere
autorización). Al rotar: solo cambia `FBI_APIFOOTBALL_KEY` en `.env`; nada más depende de ella.

Si alguna vez se usan los widgets, la clave queda **pública en el HTML** (`data-key`). El dashboard
permite restringir por dominio/IP. Nuestra UI no los usa.

# PM-12-01 · El tablero privado de evaluación (IA-153)

Plan Maestro PM, bloque 12. Código IA-153. **Privado** (`/admin/performance`, solo administradores) y tras **`FBI_EVALUATION_BOARD`
apagado**: la ruta `GET /api/v1/admin/evaluation/board` responde 404, la página no enseña el panel y el lote semanal no calcula nada.
No es una prueba de ventaja y no cambia picks, modelos ni probabilidades; `FBI_PICKS_SOURCE` sigue apagado.

## Qué completa

El tablero de AD-K02 (IA-113) juzga selecciones «cuando haya muestra». Faltaban la **fiabilidad y la resolución por separado** y la
comparación **modelo, mercado y proveedor** sobre los mismos partidos. `fbi.coverage.weekly_board` (`weekly-board-v1`), para la
última semana entera (lunes a domingo, Bogotá) y para todo lo acumulado desde el 23-oct-2026, por mercado (1X2, más/menos 2,5, ambos
marcan):

| Fuente | Qué es |
| --- | --- |
| `modelo` | lo que ve un lector: el último `forecast-v1` antes del saque |
| `mercado` | la probabilidad justa (Shin) del último consenso antes del saque (`market.market_consensus`) |
| `proveedor` | el pronóstico de API-Football antes del saque (`core.provider_predictions`), solo 1X2, sus porcentajes sobre su suma; auxiliar y rotulado como del proveedor |

Cada fuente, **en los partidos que comparten todas** las del mercado: log loss y Brier con su intervalo del 95 % (días enteros
remuestreados) y el Brier partido como Murphy: **fiabilidad** (lo lejos que están las probabilidades dichas de las frecuencias vistas;
menor es mejor), **resolución** (lo lejos que están las frecuencias de cada tramo de la general; mayor es mejor) e **incertidumbre**, con
diez tramos iguales por categoría; Brier = fiabilidad − resolución + incertidumbre + residuo (el residuo es lo que diez tramos no ven:
cero cuando cada tramo tiene un solo valor, comprobado con datos sintéticos). Fiabilidad y resolución llevan también su intervalo.

**Pares**: modelo menos mercado y modelo menos proveedor, diferencia por partido de log loss y de Brier con su intervalo y una lectura:
`modelo_mejor` (todo el intervalo bajo cero), `modelo_peor`, `indistinguible`, o `insuficiente` con menos de 30 partidos o un solo día.

Debajo, el último informe **por competición** de PM-12-06 (`segments-v1`): partidos, log loss, habilidad frente a las frecuencias propias
y veredicto (`apta`, `sin_habilidad`, `insuficiente`), y si los segmentos reproducen la cifra global.

## Órdenes

```
docker exec predigol-worker python -m scripts.evaluation_board show                     # la última semana entera; solo lectura
docker exec predigol-worker python -m scripts.evaluation_board show --week 2026-11-09   # otra semana (su lunes)
docker exec predigol-worker python -m scripts.evaluation_board run                      # calcula y guarda la semana
```

## Cálculo semanal

Con `FBI_EVALUATION_BOARD=1`, una vez por semana ISO al final del proceso nocturno de la matriz (`scripts.availability_refresh`, fila
`evaluation_board` en el libro de ejecuciones), en `analytics.evaluation_reports` (`kind = 'weekly'`, una fila por semana; solo se
añade). La tabla es la de la migración `0172` (PM-12-06).

## Vuelta atrás

Apagar el interruptor (sin despliegue). Si hiciera falta, PR de `revert`.

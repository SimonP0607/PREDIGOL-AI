# Go-live checklist

**Fecha:** 29 sep 2026 (máquina sincronizada el 25 sep; ciclo en vivo medido hasta el 29). Cada casilla se marca con evidencia (comando, fila, captura), nunca por
haber escrito el código. ✅ hecho · ⏳ pendiente de la máquina · 👤 paso manual de Simon.

## A. Puerta de compra (antes de pagar)

| Condición | Estado | Evidencia |
|---|---|---|
| PRE-UPGRADE SYSTEM COMPLETE | ✅ réplica y máquina | máquina en backend `df585b6` / Alembic 0024 / frontend `ffde018` (25 sep); tests en la máquina: ruff, mypy, 561 passed; frontend en GitHub |
| RESEARCH COMPLETE | ✅ | `docs/research/FOOTBALL_ANALYTICS_STATE_OF_THE_ART_2026.md` (15 áreas, 248 fuentes), `ANALYTICS_CAPABILITY_MATRIX.md`, `notes/A1–A5` |
| MIGRATION PLANNER COMPLETE | ✅ | `API_FOOTBALL_MIGRATION_PLAN.md`; dry run 9/9 PASS en la réplica **y en la máquina**; cobertura verificada con `/leagues` (643 competición-temporadas) |
| REQUEST BUDGET COMPLETE | ✅ | `API_PLAN_CAPACITY_MODEL.md`: 11.611 peticiones (15.675 con margen) con `ids=`; 756.810 sin él; vivo T1–2 medio 384 / pico 819 |
| BACKUP/RESTORE VERIFIED | ✅ máquina 6/6 | `BACKUP_RECOVERY_TEST.md §4` (1.121.683 filas, 57 payloads re-hasheados) |
| LIVE SYSTEM READY | 🟡 **7 de 9 pasos** | dos ventanas reales con movimiento de línea, consenso, candidatos y picks shadow (§D). Faltan near-close y resultado→liquidación: el worker cayó el 25 sep 13:12 UTC y la ventana de resultados de Free (3 días) se cerró. No se recupera ni se inventa |

### Pasos previos a la compra (en este orden)

1. ✅ Máquina sincronizada (25 sep 02:53–03:25 UTC): bundles git, dependencias, backup previo,
   Alembic 0017 → 0024, servicios reiniciados lejos de cualquier ventana, research, backup +
   restore-test 6/6, reproducción 5/5.
2. ✅ Sonda (`python -m scripts.probe_plan --yes`, 2 peticiones): **Free rechaza `ids=`**
   ("Free plans do not have access to the Ids parameter."); `/leagues` → cobertura verificada;
   NAME CHECK con un renombre (63). La pregunta del plan de pago se cierra en §B.1.
3. 👤 Confirmar el precio en el dashboard de API-Football el día de la compra.
4. 👤 **Pagar Pro, 1 mes** (regla y alternativas: `API_PLAN_CAPACITY_MODEL.md §5`).
5. 👤 Decidir cómo se mantiene encendido el anfitrión (§D, causa 2). No bloquea la compra, pero
   sí bloquea operar en vivo de verdad: sin esto se vuelven a perder ventanas en silencio.

## B. Tras activar el plan

1. `python -m scripts.capture_odds status` → el plan que dice el proveedor (/status, gratis).
   Enseguida, **antes de sembrar nada**: `python -m scripts.probe_plan --yes` (2 peticiones).
   AVAILABLE → seguir. Rechazado o sin bloques → upgrade a Mega (7,6 días sin `ids=`) o Ultra
   (15,3) desde el dashboard, repetir la sonda y `scripts.migration capacity --no-ids`.
2. `.env`: `FBI_APIFOOTBALL_PLAN=<plan>` y `FBI_APIFOOTBALL_DAILY_BUDGET` (por debajo del límite
   del plan); reiniciar el worker (el lock impide dos).
3. `python -m scripts.migration plan` → "verified" y NAME CHECK limpio; `capacity` con cobertura
   real.
4. `python -m scripts.backup create --label pre-tier1 --restore-test` → `seed --tiers 1 --yes` →
   `run --yes --max …` (o el worker, cada hora) → `status`.
5. Validación de calidad del tier 1 (`API_FOOTBALL_MIGRATION_PLAN.md §8`) + backup.
6. Features (`scripts.build_features --apply`), walk-forward (`scripts.run_backtest --apply`),
   reproducción (`scripts.experiment reproduce <id>`), comparación con el mercado (Models Lab,
   Analytics → Models).
7. Tiers 2 y 3 tras el NAME CHECK; backup tras cada uno.
8. Activar el vivo de forma permanente (§D) con las competiciones de los tiers 1–2
   (`config/competitions.yaml`; la prueba de la Segunda División queda dentro del tier 2).
9. **Si el plan sigue siendo Free cuando vuelva la Premier:** apagar la Segunda División
   (`enabled: false` + `manage_competitions apply`): dos ligas no caben en 60 peticiones/día.

## C. Validación del near-close antes de llamarlo "cierre"

Hasta que las 8 pasen, la UI dice "near-close snapshot (unvalidated)" y el CLV es provisional;
el cierre oficial es el de Pinnacle en Football-Data.

1. Procedencia: casa registrada; si no es Pinnacle, comparar con el cierre de esa casa o la media.
2. Integridad pre-partido: partido no empezado, mercado no bloqueado; ignorar `finished`; ids de
   apuesta en vivo mapeados explícitamente.
3. Timing: hora de captura propia y del proveedor; offset al kick-off real; sondeos repetidos
   T-15…T-1, último válido antes del inicio.
4. Cobertura por liga; ausencias no relacionadas con el precio.
5. Acuerdo con el cierre FD: |Δp| mediana ≤ 0,5 pp, |ΔLL| < 0,002, sin patrón favorito/longshot.
6. Captura de movimiento: pendiente ≈ 1 al regresar (cierre − T-3h) sobre (captura − T-3h).
7. Estabilidad: ≥ 500 partidos en ≥ 2 meses en las 5 ligas; revalidar tras cambios del proveedor.
8. Archivo: payload crudo con hash y marcas de tiempo (ya se hace).

## D. Puerta de modo LIVE — un ciclo completo demostrado

**Estado: 7 de 9 pasos demostrados sobre un partido real** (Girona–Albacete, fixture 6079,
Segunda División, 25 sep 2026). Lo que falta no es código.

| Paso | Cómo se comprueba | Estado sobre el fixture 6079 |
|---|---|---|
| Sync de fixtures | `core.fixtures` con `source_payload_hash` | ✅ 25 sep 03:06, payload `189921c1754e` |
| Captura de cuotas | Match Center → Timeline: ventanas `done`, no `skipped` | ✅ **dos ventanas**: T-12h 06:32 (235 precios, 9 casas) y T-6h 12:42 (219, 7 casas); T-72h/T-48h marcadas inalcanzables en Free, no "perdidas" |
| Features | `features.feature_sets` con `data_cutoff` < kick-off | ✅ fv2.0.0, corte 03:17, 7.459 entradas |
| Predicción | `models.predictions` `kind=forecast`, corte antes del kick-off | ✅ 3 filas de Elo-ologit, corte 15 h antes del saque |
| Baseline de mercado | consenso de-vigged (`market.market_consensus`) | ✅ Shin en los dos instantes; **movimiento medido**: margen 7,94 % → 6,76 % |
| Candidato shadow | `picks.pick_candidates` con decisión | ✅ 3 por instante: local rechazado por EV, visitante por cuota fuera de rango, empate seleccionado |
| Liquidación de la decisión | pick shadow con su linaje | ✅ 1 pick por instante (4 filas en total, 3 de ellas del fallo ya corregido) |
| **Near-close** | `market.near_close_snapshots` + Timeline | ❌ la ventana (18:18) llegó con el worker ya caído |
| **Resultado → liquidación** | `core.fixture_results` con linaje → `picks.pick_results` | ❌ ver abajo |

**Por qué se cortó, sin adornos.** El worker murió el 25 sep a las 13:12 UTC (último latido, sin
parada limpia) y nadie se enteró; el 27 sep Windows reinició y Docker Desktop no volvió solo.
Cuando se restableció todo el 29 sep, el proveedor ya contestaba a la petición de resultados:

```
{'plan': 'Free plans do not have access to this date, try from 2026-09-28 to 2026-09-30.'}
```

Tres días de ventana. El resultado del 25 sep **no es recuperable y no se inventa**: los 4 picks
shadow se quedan en `pending` y 8 partidos (3 de Premier del 13–14 sep y los 5 de Segunda del
25–26 sep) se quedan en `NS` para siempre. La liquidación sí está probada de extremo a extremo en
la suite de integración (postpuesto → pendiente con motivo; prórroga → pierde a 90 minutos; no se
liquida dos veces), pero **sobre datos sintéticos, no sobre un precio capturado**.

**Las dos causas son exactamente lo que se compra y lo que Simon decide:**

1. *La ventana de resultados.* En Free son 3 días; en un plan de pago el horizonte deja de ser el
   límite. Seguir esperando en Free no compra nada.
2. *El anfitrión.* Un portátil que duerme, se reinicia y arranca sus procesos a mano pierde
   ventanas en silencio. Antes de operar en vivo de verdad hacen falta arranque automático y un
   aviso cuando el latido se detenga (`/health` ya lo expone). **Decisión de Simon.**

**Cómo se cierra:** próxima jornada de Segunda (2–5 oct) con la máquina encendida, o el primer
fin de semana tras activar el plan. Un solo partido con resultado basta.

`GET /api/v1/matches/{id}/audit` reconstruye toda la cadena desde enlaces guardados; el E2E
"Match Center → Audit" comprueba que la UI muestra exactamente lo que devuelve la API.

## E. Puerta del modelo (MODEL GATE)

Un modelo sale de RESEARCH solo con los seis checks (`src/fbi/research/gate.py`), cada uno con su
evidencia en `analytics.experiments.gate`:

1. **out_of_sample** — cada bloque comprobado antes de ajustar: resultados públicos antes del
   corte, corte antes de cada kick-off.
2. **temporal_validation** — walk-forward; hiperparámetros solo en la temporada de validación o
   fijados a priori.
3. **calibrated** — ECE en la muestra común ≤ max(0,02, ECE del mercado + 0,01).
4. **reproducible** — `scripts.experiment reproduce` con el código y los datos registrados dio
   predicciones idénticas.
5. **stable** — la diferencia con el mercado tiene el mismo signo en ambas mitades del test y en
   ≥ 2/3 de las competiciones con ≥ 50 partidos.
6. **beats_market** — el intervalo entero de ΔLL contra Pinnacle cierre (Shin) está por debajo
   de 0.

Gate superado → `CANDIDATE`; `PRODUCTION` solo con `scripts.experiment promote <id>` (la base de
datos también lo rechaza sin gate). **Estado hoy:** 5 experimentos de la sesión 2 de la réplica
y 5 de la sesión 1 de la máquina (que ya incluye la Segunda División), los diez reproducidos bit
a bit, **ninguno bate al mercado → todos en RESEARCH.** El mejor en la máquina, el logit
multinomial: ΔLL **+0,0245 [+0,0152, +0,0333]** frente a Pinnacle cierre (Shin), 1.684 partidos,
evidencia suficiente de que es peor. No se fuerza un ganador.

## F. Quality gates

| Gate | Réplica (25 sep) | Máquina (25 sep) |
|---|---|---|
| Backend `ruff check .` | ✅ | ✅ |
| Backend `mypy` (estricto, 154 ficheros) y `mypy .` (261) | ✅ | ✅ (a `df585b6`) |
| Backend `pytest -q` | ✅ 561 passed | ✅ 561 passed a `df585b6` |
| Migraciones desde cero (suite + dry run) | ✅ 0001 → 0024 | ✅ dry run 9/9; producción 0017 → 0024 |
| Frontend `bun run lint` | ✅ 0 errores (13 warnings de fast-refresh, preexistentes) | ✅ igual |
| Frontend `bun run typecheck` | ✅ | ✅ |
| Frontend `bun run build` | ✅ | ✅ |
| E2E (Playwright, contra el stack en marcha) | ✅ 84 flujos y vistas responsive (1440/1024/768/390 px) | — (UI comprobada en Chrome contra la máquina) |
| Secretos en el repositorio | ✅ 0 (ver `PRE_UPGRADE_READINESS.md`, capa 30) | — |

## G. IA y Telegram — bloqueados a propósito

No se activan hasta que la plataforma cuantitativa esté sólida: histórico migrado, ciclo en vivo
demostrado (§D) y al menos un modelo evaluado con el gate (§E) sobre el histórico ampliado.
Reglas que ya están en el código y no cambian: la IA **explica** números que existen (herramientas
de solo lectura con linaje), **nunca genera probabilidades**; el bot informa en modo investigación,
nunca como consejo de apuesta, y nunca envía su token.

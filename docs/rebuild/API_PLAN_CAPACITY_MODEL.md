# Modelo de capacidad: qué plan de API-Football comprar

**Fecha:** 25 sep 2026 (cifras con la cobertura verificada en la máquina, 03:25 UTC) · **Código:** `src/fbi/migration/capacity.py`, `config/api_plans.yaml`,
`config/migration.yaml` · **Comando:** `python -m scripts.migration capacity [--no-ids]
[--with-optional] [--tiers …] [--live-tiers …]`.

**Regla:** el plan más barato que cumpla la migración deseada **y** la operación en vivo con un
margen razonable. No se asume Ultra ni ningún otro: se calcula.

## 1. Hechos del proveedor (fuentes oficiales, 25 sep 2026)

| Plan | Precio/mes | Peticiones/día | Peticiones/min | Prepago 3/6/12 meses |
|---|---|---|---|---|
| Free | $0 | 100 | 10 | — |
| Pro | $19 | 7.500 | 300 | $51,30 / $91,20 / $159,60 |
| Ultra | $29 | 75.000 | 450 | $78,30 / $139,20 / $243,60 |
| Mega | $39 | 150.000 | 900 | $105,30 / $187,20 / $327,60 |

- "All our plans include all competitions and endpoints" (página de precios). Los mismos cuatro
  precios aparecen en copias archivadas de la página oficial de 2020-03-12 a 2026-03-14.
- La cuota diaria se reinicia a las **00:00 UTC**; lo no usado se pierde; al llegar al límite la
  cuenta queda **suspendida el resto del día** (no hay cobro por exceso en el dashboard).
- Prepago de 1, 3, 6 o 12 meses; **sin reembolso**; un **upgrade** cambia plan y cuota, no la
  fecha de fin, y se paga la diferencia; **no se puede hacer downgrade** (términos, "Mai 21,
  2025").
- `/status` y los logos no consumen cuota. `/fixtures?ids=` admite hasta 20 partidos y devuelve
  eventos, alineaciones, estadísticas y jugadores (changelog 3.9.2; tutoriales oficiales de 2024 y
  2026) — con una única salvedad oficial: "**when available for your plan**" (post del 27 jul
  2026), sin decir qué planes no lo tienen.
- **Medido en esta cuenta (25 sep 2026, plan Free):** `{'plan': 'Free plans do not have access
  to the Ids parameter.'}`. Free queda descartado para `ids=`; para los planes de pago la
  documentación dice que sí y el rechazo nombra solo a Free, pero **no está demostrado** hasta
  sondearlo con el plan activo (§5).
- **Los precios hay que confirmarlos en el dashboard el día de la compra**: no se copian de aquí.

Detalle y enlaces: `docs/research/notes/A5_api_football_inventory.md`.

## 2. El modelo

```
necesidad_backfill   = peticiones_plan × (1 + 0,35)
disponible_por_día   = cuota × (1 − 0,10) − vivo_medio × (1 + 0,35)
días_backfill        = necesidad_backfill / disponible_por_día
holgura_vivo         = (cuota − vivo_pico × 1,35) / cuota
encaja               = holgura_vivo > 0  y  días_backfill ≤ límite (14 días por defecto)
```

**Operación en vivo** (`config/migration.yaml → live`): la temporada se reparte en 280 días; el
día más cargado concentra el 35 % de los partidos de la semana; por partido: 6 ventanas de
cuotas pre-partido (T-72h…T-3h, alcanzables en un plan de pago), 1 near-close, 2 sondeos de
alineación y 1 de detalle post-partido (en lotes `ids=`); por liga y día: lesiones y
clasificación; 12 sincronizaciones de fixtures/resultados al día.

| Captura en vivo | Competiciones | Partidos/temporada | Día medio | Día pico |
|---|---|---|---|---|
| Tiers 1–2 (por defecto) | 36 | 11.023 | 384 peticiones (39,4 partidos) | 819 (96,5 partidos) |
| Tiers 1–3 (las 72) | 72 | 21.265 | 736 (75,9 partidos) | 1.572 (186,1 partidos) |

En el día pico de tiers 1–2, las cuotas pre-partido son 579 peticiones y el near-close 96.

## 3. Escenarios

Cobertura **verificada** (`/leagues` en la máquina): 643 competición-temporadas, 190.313
partidos. Salida de `python -m scripts.migration capacity` en la máquina, 25 sep 2026:

**A. Migración completa (72 competiciones × ≤ 9 temporadas), `ids=` disponible:
11.611 peticiones → 15.675 con margen.**

| Plan | Peticiones/día | Backfill | Días | Vivo pico (T1–2) | Holgura | ¿Encaja? |
|---|---|---|---|---|---|---|
| Free | 100 | 15.675 | nunca | 819 | −1.005,9 % | no |
| **Pro** | 7.500 | 15.675 | **2,5** | 819 | **85,3 %** | **sí** |
| Ultra | 75.000 | 15.675 | 0,2 | 819 | 98,5 % | sí |
| Mega | 150.000 | 15.675 | 0,1 | 819 | 99,3 % | sí |

Con los perfiles de jugador opcionales (34.147 → 46.099): Pro **7,4 días**. Con captura en vivo
de las 72 competiciones (medio 736, pico 1.572 peticiones/día): Pro 2,7 días de backfill y
**71,7 %** de holgura en el día pico.

**B. La misma migración si `ids=` NO estuviera disponible: 756.810 → 1.021.694.**

| Plan | Días | Holgura vivo | ¿Encaja en 14 días? |
|---|---|---|---|
| Pro | 163,9 | 85,3 % | no |
| Ultra | 15,3 | 98,5 % | no por 1,3 días (sí dentro del mes) |
| Mega | 7,6 | 99,3 % | sí |

Por tiers sin `ids=`: tier 1 solo (99.594 con margen) → Ultra 1,5 días / Pro 16,0 días;
tiers 1–2 (530.441) → Ultra 7,9 días / Mega 3,9 / Pro 85,1.

## 4. Sensibilidad

- **La variable que decide es `ids=`**: sin ella el detalle cuesta ~79 veces más (4 peticiones por
  partido frente a 1 por cada 20: 9.565 → 754.764) y la migración entera 65 veces más
  (11.611 → 756.810). Todo lo demás (profundidad, opcionales, captura en vivo de las 72) mueve
  los días de Pro entre 2,5 y 7,4, nunca fuera del mes.
- El límite de 14 días es una decisión nuestra (tener el histórico pronto para modelar), no del
  proveedor. Con un mes de margen, sin `ids=` Ultra también encaja.
- La holgura de Pro en vivo (71–85 %) deja sitio para más competiciones en directo, más ventanas
  de cuotas o reintentos: el cuello de botella del vivo **no** es la cuota.
- Las peticiones/minuto no limitan: a 300/min, el disponible diario de Pro (~6.230) se gasta en
  21 minutos de transferencia.

## 5. Recomendación y regla de decisión

**Comprar Pro, 1 mes** — es el más barato que cumple la migración completa (2,5 días) y la
operación en vivo con 85 % de holgura **si el plan de pago sirve `ids=`**, que es lo que dice la
documentación oficial. La sonda en Free (25 sep) no pudo cerrarlo: Free rechaza el parámetro.
Por qué Pro sigue siendo la compra correcta:

- Si Pro sirve `ids=` (lo documentado): $19 y la migración completa en 2,5 días.
- Si no lo sirviera: el upgrade a **Mega** cuesta la diferencia ($20) y conserva la fecha de fin
  → migración sin `ids=` en 7,6 días (o Ultra, +$10, 15,3 días). El peor caso total es $39, el
  mismo que comprar Mega hoy; el mejor caso es $19. Empezar por Pro no tiene coste esperado y
  no se puede hacer downgrade: por eso se empieza por el más barato que encaja.

Regla, **en la primera hora del plan de pago y antes de sembrar nada**:

1. `python -m scripts.capture_odds status` → confirma el plan activo (gratis).
2. `python -m scripts.probe_plan --yes` (2 peticiones).
3. **AVAILABLE** → seguir con Pro (`GO_LIVE_CHECKLIST.md §B`).
4. **Refused / NOT available** → upgrade a Mega (7,6 días) o Ultra (15,3) desde el dashboard y
   repetir la sonda; `scripts.migration capacity --no-ids` recalcula con la cuota nueva.

Prepago: **1 mes** primero. La migración y la validación del ciclo en vivo caben de sobra; el
prepago largo (hasta −30 % a 12 meses, $159,60 en Pro) se decide cuando el vivo esté demostrado,
porque no hay reembolso.

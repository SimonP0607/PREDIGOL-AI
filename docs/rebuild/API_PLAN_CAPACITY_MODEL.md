# Modelo de capacidad: qué plan de API-Football comprar

**Fecha:** 25 sep 2026 · **Código:** `src/fbi/migration/capacity.py`, `config/api_plans.yaml`,
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

**A. Migración completa (72 competiciones × ≤ 9 temporadas), `ids=` disponible (documentado):
12.139 peticiones → 16.388 con margen.**

| Plan | Peticiones/día | Backfill | Días | Vivo pico (T1–2) | Holgura | ¿Encaja? |
|---|---|---|---|---|---|---|
| Free | 100 | 16.388 | nunca | 819 | −1.006 % | no |
| **Pro** | 7.500 | 16.388 | **2,6** | 819 | **85,3 %** | **sí** |
| Ultra | 75.000 | 16.388 | 0,2 | 819 | 98,5 % | sí |
| Mega | 150.000 | 16.388 | 0,1 | 819 | 99,3 % | sí |

Con los perfiles de jugador opcionales (35.467 → 47.881): Pro **7,7 días**. Con captura en vivo
de las 72 competiciones: Pro 2,8 días de backfill y **71,7 %** de holgura en el día pico.

**B. La misma migración si `ids=` NO estuviera disponible: 768.261 → 1.037.153.**

| Plan | Días | Holgura vivo | ¿Encaja en 14 días? |
|---|---|---|---|
| Pro | 166,4 | 85,3 % | no |
| Ultra | 15,5 | 98,5 % | no por 1,5 días (sí en un mes) |
| Mega | 7,7 | 99,3 % | sí |

Por tiers sin `ids=`: tier 1 solo → Ultra 1,5 días / Pro 16 días; tiers 1–2 → Ultra 8,0 días /
Mega 4,0.

## 4. Sensibilidad

- **La variable que decide es `ids=`**: sin ella el detalle cuesta ~80 veces más (4 peticiones por
  partido frente a 1 por cada 20) y la migración entera 63 veces más (12.139 → 768.261). Todo lo demás (profundidad, opcionales, captura en vivo de
  las 72) mueve los días de Pro entre 2,6 y 7,7, nunca fuera del mes.
- El límite de 14 días es una decisión nuestra (tener el histórico pronto para modelar), no del
  proveedor. Con un mes de margen, sin `ids=` Ultra también encaja.
- La holgura de Pro en vivo (71–85 %) deja sitio para más competiciones en directo, más ventanas
  de cuotas o reintentos: el cuello de botella del vivo **no** es la cuota.
- Las peticiones/minuto no limitan: a 300/min, el disponible diario de Pro (~6.230) se gasta en
  21 minutos de transferencia.

## 5. Recomendación y regla de decisión

**Comprar Pro, 1 mes** — es el más barato que cumple la migración completa (2,6 días) y la
operación en vivo con 85 % de holgura, con la condición que la documentación oficial ya indica
(`ids=` para todos los planes). La salvedad del 27 jul 2026 se cierra **antes de pagar** con la
sonda gratuita de 2 peticiones:

1. `python -m scripts.probe_plan --yes` (plan Free, 2 de las 100 peticiones del día).
2. Si dice **AVAILABLE** → comprar **Pro**.
3. Si dice **NOT available** → comprar **Ultra** (15,5 días, dentro del mes) o **Mega** (7,7
   días) según la prisa. Y si se compró Pro y el plan de pago no devolviera los bloques, el
   upgrade a Ultra/Mega cuesta solo la diferencia y conserva la fecha de fin; al revés no se
   puede (sin downgrade): por eso se empieza por el más barato que encaja.

Prepago: **1 mes** primero. La migración y la validación del ciclo en vivo caben de sobra; el
prepago largo (hasta −30 % a 12 meses, $159,60 en Pro) se decide cuando el vivo esté demostrado,
porque no hay reembolso.

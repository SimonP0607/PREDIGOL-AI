# API-Football: consumo real, margen y +50 ligas (5 oct 2026)

Medido con `python -m scripts.capacity_report --probe 120` (5 oct, 06:32 UTC; el sondeo gastó 120 peticiones para
medir la liquidez de las ligas candidatas) y con el ledger de ejecuciones. Informe completo en
`data/capacity/20261005T063217Z/CAPACITY.md`.

## El plan

| | Valor |
|---|---|
| Plan contratado | **Ultra**: 75.000 peticiones/día, 450/min |
| Presupuesto interno (siempre por debajo del plan) | **60.000/día**, contado en la base de datos antes de cada petición y compartido por todos los procesos |
| Límite por minuto | compartido entre procesos (desde el 5 oct; antes cada proceso llevaba su propio contador y el 5 oct a las 02:46 el proveedor rechazó peticiones por minuto) |
| Suscripción | activa hasta el **29 oct 2026 04:31 UTC** — renovar o cambiar de plan es decisión del dueño |

## Consumo medido

| Día (UTC) | Total | Recurrente (sin feeds de referencia) | Partidos | Lo que más gastó |
|---|---:|---:|---:|---|
| 29 sep | 6.134 | 328 | 34 | migración del histórico 7.016 |
| 30 sep | 2.716 | 165 | 39 | migración 575 |
| 1 oct | 6.133 | 703 | 45 | migración 5.131 |
| 3 oct | 3.769 | 3.769 | 209 | cuotas en vivo 1.410, captura 1.142 |
| 4 oct | **29.418** | 15.093 | 77 | migración 8.934, captura 7.104 (antes del arreglo), referencia 3.049 |
| 5 oct (hasta 08:20) | 15.576 | — | — | migración 5.787 (terminada), referencia 4.200 (primer llenado), auditorías 1.110 |

Totales de los 5 días completos: mínimo 2.716 · P25 3.769 · **mediana 6.133** · P75 6.134 · P90 20.104 ·
**P95 24.761** · **máximo histórico 29.418**. Estos días incluyen cargas únicas (migración, primer llenado de los
feeds de referencia, auditorías) que no se repiten.

**Arreglo de hoy:** la captura pre-partido volvía a preguntar en cada ciclo por partidos que el proveedor no cotiza
(~8.000 peticiones/día de 4 oct). Ahora cada partido se pregunta una vez por ventana (25 → 1 llamada por ciclo,
verificado) y las ligas que el proveedor marca sin cuotas no se preguntan.

## Régimen estable (modelo de costes)

Por día = fijo 1.334 (cuotas en vivo, catálogo) + 32,3 por liga (calendario, contexto, referencia a ~3.500/día en
total) + 12,7 por partido (6,7 de cuotas pre-partido: una por ventana + lectura final; 6,0 de vivo y resultados).

| Ligas añadidas | Normal | Día cargado | P95 | Peor | Margen en P95 (interno / plan) |
|---:|---:|---:|---:|---:|---|
| 0 (124 seguidas) | 6.018 | 7.830 | **8.153** | 8.458 | **51.847 / 66.847** |
| +25 | 7.208 | 9.507 | 9.917 | 10.305 | 50.083 / 65.083 |
| **+50** | 8.337 | 10.962 | **11.430** | 11.873 | **48.570 / 63.570** |
| +75 | 9.451 | 12.360 | 12.879 | 13.369 | 47.121 / 62.121 |

Con +50 ligas el día P95 usaría ~19 % del presupuesto interno. **La API no es el límite**; lo son el almacenamiento
(`STORAGE_FORECAST.md`: +43 % de crecimiento) y la calidad de datos de las ligas menores (cobertura del proveedor).

## Las 50 ligas candidatas (puntuación: mercado, liquidez, datos, profundidad, interés, utilidad)

| # | Liga (id) | País | Partidos con cuotas ±7 d | Casas de media |
|---:|---|---|---:|---:|
| 1 | Veikkausliiga (244) | Finlandia | 6 | 8,2 |
| 2 | Primera División (268) | Uruguay | 10 | 8,8 |
| 3 | Clasificación Copa África (36) | Mundo | 24 | 8,4 |
| 4 | División Profesional Clausura (252) | Paraguay | 8 | 8,5 |
| 5 | Botola Pro (200) | Marruecos | 7 | 9,0 |
| 6 | FIFA Asean Cup (1247) | Mundo | 13 | 7,9 |
| 7 | National League (43) | Inglaterra | 36 | 9,0 |
| 8 | First Amateur Division (487) | Bélgica | 23 | 7,9 |
| 9 | Primera Nacional (129) | Argentina | 16 | 9,0 |
| 10 | First League (236) | Rusia | 10 | 2,9 |
| 11–20 | USL Championship (255), 1.ª RFEF G2 (436), J2 (99), 1.ª RFEF G1 (435), Prva Liga (287), J3 (100), Ligue 3 (63), National League South (60), 2. liga SVK (506), 2.ª RFEF G1 (875) | | | |
| 21–30 | Tweede Divisie (492), Ettan Södra (564), Liga de Expansión MX (263), Serie C Girone C (943), Primera C ARG (132), 2.ª RFEF G3 (877), Second League EGY (887), Serie C Girone A (138), 2.ª RFEF G2 (876), Ettan Norra (563) | | | |
| 31–40 | 2.ª RFEF G4 (878), USL League One (489), First Division IRL (358), Torneo Federal A (134), National League North (59), 2. Division NOR G1 (473), J-League Cup (101), 1. Division NOR (104), League One SCO (183), 2. Division NOR G2 (474) | | | |
| 41–50 | Segunda División URU (269), K3 League (295), Segunda División CHI (711), 3. liga MSFL (349), 2. SNL (374), Asian Games (803), Super League 2 GRE (494), Championship SCO (180), Division 2 Norra Svealand (593), Serie C BRA (75) | | | |

Recomendación: si se amplía, hacerlo **por tandas de 10–25**, empezando por ligas con tabla y estadísticas (puntuación
de datos 1,0), comprobando la cobertura real de cada tanda en *Calidad de datos* antes de la siguiente; y no antes de
tener la retención de precios en vivo diseñada. Ninguna liga nueva cambia la decisión de picks: los modelos no ganan
al mercado ni en las cinco grandes.

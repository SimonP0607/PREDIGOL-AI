# Arquitectura en vivo — qué consulta el worker y cuándo

Derivado de las cadencias oficiales (`06_UPDATE_FREQUENCIES.md`), no de intuición.

## 1. Línea de tiempo de un partido

| Momento | Endpoint | Peticiones | Por qué ahí |
|---|---|---:|---|
| **T-4 días** (12×/día) | `/fixtures?league&season&from&to` | 1/liga | el calendario cambia; en Ultra el horizonte ya no está limitado |
| **T-72h, T-48h, T-24h, T-12h, T-6h, T-3h** | `/odds?fixture=` | 6/partido | las cuotas se refrescan **cada 3 h**: cada ventana cae en un ciclo distinto |
| **T-45 min y T-20 min** | `/fixtures?ids=` (lote) | 2/lote de 20 | las alineaciones aparecen **entre 20 y 40 min antes**; un solo sondeo puede llegar pronto |
| **T-15…T-5 min** | `/odds/live?fixture=` | 1/partido | último precio antes del saque. **No es el cierre** hasta que pasen las 8 pruebas de §C del go-live |
| **En juego** (opcional) | `/fixtures?live=id-id` | 1/min | solo si queremos timeline en vivo; **no lo necesita el pipeline de decisión** |
| **T+2h** | `/fixtures?ids=` (lote) | 1/lote de 20 | resultado + eventos + alineaciones finales + estadísticas + jugadores, todo junto |
| **T+2h…T+48h** | `/fixtures?date=` | 3/día | red de seguridad: el proveedor puede tardar **hasta 48 h** en ligas sin livescore |
| **1/día por liga** | `/injuries?league&season` | 1 | se actualiza cada 4 h; más de una vez al día no aporta |
| **1/día por liga** | `/standings?league&season` | 1 | contexto, no decisión |

## 2. Presupuesto diario

| Alcance | Día medio | Día pico | Holgura en Ultra |
|---|---:|---:|---:|
| Tiers 1–2 (36 competiciones) | 384 | 819 | **98,5 %** |
| Tiers 1–3 (72) | 736 | 1.572 | 97,2 % |

Desglose del pico (tiers 1–2): cuotas pre 579 · near-close 96 · alineaciones 40 · detalle 20 ·
lesiones 36 · clasificaciones 36 · syncs 12.

## 3. Lo que **no** hacemos en vivo, y por qué

- **No sondeamos el marcador cada 15 segundos.** No operamos in-play. La última decisión es el
  near-close; después solo hace falta el resultado.
- **No llamamos a los cuatro endpoints de detalle por separado.** `ids=` los trae en una petición
  por cada 20 partidos. Solo tendrían sentido sueltos si quisiéramos estadísticas *durante* el
  partido.
- **No usamos `/predictions`.**
- **No nos pegamos al límite por minuto.** La política del proveedor permite bloquear por "picos
  anómalos" sin aviso. El `TokenBucket` reparte y el backfill cede el paso al vivo.

## 4. Reserva y prioridad

El backfill calcula su propia reserva para las próximas 24 h de ventanas de cuotas y syncs, y
**se abstiene** si lo que queda del día cae dentro de esa reserva. Con Ultra la reserva es ruido
(819 de 75.000), pero la regla se queda: protege el vivo si algún día se aprieta el alcance.

## 5. Lo que falta para poder llamarlo "operación en vivo"

1. **Un anfitrión que no se apague.** El 25 sep el worker murió a las 13:12 UTC y nadie se enteró;
   se perdieron la ventana near-close y el resultado. Hace falta arranque automático y aviso
   cuando el latido se detenga. **Decisión de Simon.**
2. **`payload_hash` en `near_close_snapshots`** (P0 del gap analysis).
3. **Las 8 pruebas del near-close** (§C del go-live) antes de llamarlo cierre y de calcular CLV.

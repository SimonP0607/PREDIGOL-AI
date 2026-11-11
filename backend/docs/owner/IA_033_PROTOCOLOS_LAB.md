# IA-033 — Protocolos preregistrados y potencia para el LAB (INT-T02)

*Plan Maestro de Evolución de PrediGol Intelligence 2026, ola 1. Registrado el 11-nov-2026.*

## Qué es

Cada experimento del LAB del plan fija **antes de mirar sus datos**: la pregunta, los datos y su ventana, cómo separa el tiempo (walk-forward), la métrica principal, la regla con la que **pasa** y la regla con la que **se rechaza**, la muestra mínima, las exclusiones y la regla de parada. Así un experimento no encuentra por azar lo que buscaba probando ventanas, mercados o segmentos hasta que algo sale.

- Código: `fbi.research.protocol` (`lab-protocol-v1`). Es aritmética pura: no lee la base de datos, no toca modelos, pronósticos, calibraciones, picks, umbrales ni agentes.
- Cada protocolo es una estructura congelada. Su **huella** es el SHA-256 de su JSON canónico. `tests/unit/test_research_protocols.py` fija la huella de cada uno: cambiar un protocolo registrado se ve en el diff y necesita su propio PR (y una versión nueva, `-v2`); git fecha el protocolo antes que el resultado.
- `require(clave)` es lo primero que llama un script del LAB del plan: **un experimento sin protocolo registrado no se ejecuta**. `stamp(clave)` es lo que lleva su resultado (clave, versión, huella), para poder comprobarlo contra el protocolo tal como era.

## Potencia

Para una media, o una diferencia pareada, con desviación típica *s*, ver una diferencia real *d* con una prueba bilateral al 5 % y potencia del 80 % pide unas **7,85·s²/d²** observaciones; `n_for_mean` lo calcula y `mde_for_mean` da la diferencia mínima que una muestra puede ver (2,80·s/√n). Para dos proporciones, la aproximación normal habitual (`n_for_two_proportions`: 0,50 frente a 0,60 pide 388 por grupo). Las tasas se informan con su intervalo de Wilson (`fbi.ai.intervals`, IA-027).

## Protocolos registrados

| Pieza | Versión | Huella (SHA-256) | Qué pregunta |
| --- | --- | --- | --- |
| `INT-A02` | `proto-int-a02-v1` | `2a1cdb3ec31a6b5075010a989e6205bf60bc699c54891a62ac861ad0fd69ae6d` | ¿Una calibración multiclase que suma 1 por construcción pronostica igual o mejor que la calibrada por selección y reescalada? |
| `INT-A09` | `proto-int-a09-v1` | `400778f85de7acdfc59b1d9e265d7f4c4d5fe42abc4abf71cb5785b33604bd36` | ¿Tiros, tiros a puerta y xG en los ratings mejoran el pronóstico y aportan algo que el mercado no tiene? |
| `INT-B09` | `proto-int-b09-v1` | `2b8e49fb115f5cecbcb5e61f52d9ac11d8c8464ce7b3da97af62b3f9382e9232` | Cuando PrediGol conoce una baja o una titularidad, ¿el precio se mueve después o ya lo sabía? |

Los demás LAB del plan (`INT-A08`, `INT-A11`, `INT-B10`, `INT-C02`, `INT-C03`) registrarán su protocolo aquí, antes de su primera ejecución.

### Reglas comunes de los tres

- **Una sola evaluación** con los datos disponibles al ejecutarla. No se repite cambiando la ventana, los días o los segmentos; un cambio de método es un protocolo nuevo registrado antes de mirar.
- **Sin fugas:** ningún dato posterior al momento de cada pronóstico o decisión.
- **Muestra mínima:** por debajo del mínimo, el resultado es «pendiente por muestra» y no se interpreta.
- **Intervalos:** bootstrap por día (A02, A09) o agrupado por partido (B09), con semilla fija `20261111`.
- **Nada se promociona solo:** un PASA abre la puerta a la validación (ola 4) y a tu decisión; un rechazo se archiva con su motivo.

## Qué no cambia

Ningún modelo, calibración, pronóstico, pick, umbral, agente, interruptor ni muestra de la sombra. No mueve el ancla del Gate B. No necesita migración ni gasto de API.

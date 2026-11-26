# IA-171 · Protocolo común de los ocho experimentos (RP-9.0, `exp-protocol-v1`)

Qué es: las reglas con las que se juzgan los experimentos EXP-E1 a EXP-E8 del plan de reestructuración de Intelligence, escritas **antes** de
mirar ningún resultado. Quedan en `backend/src/fbi/research/exp_protocol.py` (reglas y ayudas puras) y en el registro `EXPERIMENTS` (un
`Protocol` por experimento, con su huella). Registrados el 26-nov-2026.

Qué no es: no cambia ningún modelo, pronóstico, pick ni umbral, y no entrena ni promueve nada. Un éxito de un experimento **no promueve nada**:
una promoción pide además la prueba intacta, la sombra prospectiva con la muestra fijada, la coherencia de la §11 del plan y una propuesta firmada.

## Reglas comunes

1. **Preregistro.** Cada experimento tiene su `Protocol` congelado; su huella (SHA-256 del JSON canónico) está fijada en
   `tests/unit/test_exp_protocol.py`. Cambiar un protocolo registrado es una versión nueva con su propio PR; git fecha el protocolo antes del resultado.
2. **Sin protocolo no hay veredicto.** `fbi.research.protocol.require("EXP-E1")` lo encuentra; `exp_protocol.admit` rechaza un resultado cuyo
   protocolo no existe, cuya huella no coincide o que se calculó antes de la firma.
3. **Intervalos por días.** El intervalo del 95 % se obtiene remuestreando **días enteros** de partidos (los partidos de un día no son independientes).
4. **Comparaciones múltiples.** Corrección de Holm entre los segmentos o familias de un mismo experimento (como mucho 8 segmentos), y el mismo
   signo en las dos mitades del periodo.
5. **Datos ya mirados.** Los niveles 3 y 4 los señaló la auditoría mirando datos: solo valen para validar. Para el veredicto cuentan únicamente los
   partidos posteriores a la firma (`only_after`).
6. **Poblaciones iguales.** Modelo y comparador se puntúan sobre los mismos partidos (`equal_population`).
7. **Muestra fijada, una sola mirada.** El veredicto se mira una vez al llegar a la muestra; antes solo se informa el avance. No se añaden modelos,
   variables ni segmentos después de la firma. Con muestra insuficiente el veredicto es «insuficiente»: no se alarga.
8. **El veredicto es aritmético** (`difference_verdict`): *éxito* si la media y todo el intervalo quedan por debajo del umbral, con p ajustado de
   Holm < 0,05 y mismo signo en las dos mitades; *abandono* si el intervalo queda entero por encima; en otro caso *insuficiente*.
9. Sin árboles, redes ni más variables para el 1X2.

## Los ocho

| Experimento | Pregunta | Umbral | Muestra |
|---|---|---|---|
| EXP-E1 | ¿en algún segmento (≤ 8) el modelo en bruto queda a menos de +0,005 de pérdida logarítmica del cierre real sin margen? | diferencia < +0,005 | 1.000 partidos por segmento, solo posteriores a la firma |
| EXP-E2 | ¿una baja clave confirmada en la alineación oficial mueve el resultado más de lo que movió el precio previo? | residuo fuera de 2 errores estándar | 500 casos |
| EXP-E3 | ¿córneres y tarjetas calibrados sin leer el mercado igualan al mercado de la misma línea? | < +0,005 | 1.500 por familia |
| EXP-E4 | ¿el modelo jerárquico de tarjetas mejora fuera de muestra? | mejora mayor que su error en la mayoría de las competiciones | 81 competiciones con ≥ 200 partidos; entrenar 2024-25, elegir 2.ª mitad de 2025, probar 2026 hasta la firma |
| EXP-E5 | ¿condicionar la 2.ª mitad al marcador del descanso se acerca al mercado de la 2.ª mitad? | éxito < +0,010; abandono si sigue > +0,020 | 900 selecciones |
| EXP-E6 | ¿tras una racha de 10 partidos el mercado de más/menos se equivoca de forma sistemática? | residuo ≠ 0 con intervalo | lo guardado, sin ajustar |
| EXP-E7 | ¿dependen entre sí los sucesos del mismo partido? | descriptivo: razón conjunta/producto con intervalo | histórico |
| EXP-E8 | ¿algún criterio de reparto da más hechos confirmados por partido y por dólar? | descriptivo, con coste | 300 partidos por criterio |

Los umbrales numéricos de la auditoría están en `exp_protocol.THRESHOLDS` y no se han tocado.

## Pruebas

`tests/unit/test_exp_protocol.py`: huellas fijadas; protocolos completos y fechados; rechazo de un veredicto sin protocolo, con otra huella o
anterior a la firma; bootstrap por días reproducible y más ancho que el ingenuo cuando un día se mueve junto; Holm; mismo signo en mitades;
población igual; solo posteriores a la firma; los cuatro desenlaces del veredicto, incluida la zona intermedia de EXP-E5.

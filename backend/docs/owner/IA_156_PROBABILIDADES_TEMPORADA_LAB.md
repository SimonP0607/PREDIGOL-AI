# IA-156 · PM-09-07 · Probabilidades de temporada por simulación, validadas sobre temporadas cerradas

Plan Maestro PM, ola 6, tarea **PM-09-07** (OP-21). **Solo LAB: nada se publica.** Publicar unas probabilidades de temporada
exigiría además DM-14 y la firma del dueño. Validado **fuera del servidor**, sobre la exportación de solo lectura, con el protocolo
preregistrado `PM-09-07` (`proto-pm-09-07-v1`, huella `ed4015968c20…24ab`), fusionado en `main` (#461, 05:00:55 UTC) antes de tomar la
exportación.

## 1. Orden de los hechos (UTC, 21-nov-2026)

Protocolo empujado 03:24:45 (`fd0e5aa`) · código `scripts/lab_season_sim.py` 03:37:07 (`b7d68df`, probado con datos sintéticos) ·
fusión #461 05:00:55 (`194bf2f`) · exportación `lab-export-v2` 05:01:32–05:03:04 (carpeta `20261121T050132Z`, foto
`4765478:4765516:4765478`; tar SHA-256 `67204cc5…fc17`, `verify` correcto) · cálculo en el contenedor 05:05–05:07.

## 2. Qué se simuló (el protocolo, sin cambios)

* **Modelo**: exactamente `fbi.competitions.scenario_store.fit_scores`, la función que usa `scenarios-v2` (AD-B02, en sombra):
  Dixon-Coles con la especificación promovida exportada (`spec-v1`: xi 0,002, penalización 1,0, 730 días), respaldo Poisson,
  resultados conocidos 3 h después del saque, solo partidos de la misma competición. 10.000 temporadas por corte, semilla 20261121.
* **Referencia**: la misma simulación con todos los equipos iguales (Poisson con la media de goles local y visitante de la liga en
  la ventana de entrenamiento), partiendo de la misma tabla.
* **Temporadas**: ligas nacionales cerradas de 2019 a 2025 a doble vuelta exacta (10–24 equipos). De 549 consideradas: 388 no son
  doble vuelta exacta (apertura/clausura, fases, play-offs, calendarios incompletos), 29 descartadas porque la última tabla del
  proveedor no coincide en puntos con la calculada (sanciones o partidos adjudicados), 2 sin tabla del proveedor (se conservan);
  **130 liga-temporadas evaluadas** (≥ 100 que pide el protocolo), 8 cortes sin ajuste posible.
* **Cortes**: el saque del primer partido que deja jugado un tercio y dos tercios de la temporada. Desempate de la tabla: puntos,
  diferencia, goles a favor y sorteo (no hubo ningún empate exacto en la línea de un objetivo en la tabla final).

## 3. Resultado: **NO PASA**

| Objetivo | Corte | Equipos-temporada | Brier modelo | Brier referencia | BSS (IC 95 %) | ECE | Grupo p ≤ 0,1: media p / observada (n) | Grupo p ≥ 0,9: media p / observada [Wilson] (n) | Cumple |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- | --- | --- |
| Campeón | 1/3 | 2121 | 0,0319 | 0,0382 | 0,164 (0,068 a 0,263) | 0,004 | 0,006 / 0,009 [0,006–0,015] (1837) | 0,961 / 1,000 [0,758–1,000] (12) | sí |
| Campeón | 2/3 | 2181 | 0,0214 | 0,0230 | 0,068 (-0,028 a 0,168) | 0,001 | 0,003 / 0,003 [0,001–0,006] (1935) | 0,974 / 1,000 [0,914–1,000] (41) | no |
| Cuatro primeros | 1/3 | 2121 | 0,0891 | 0,0976 | 0,087 (0,020 a 0,155) | 0,034 | 0,014 / 0,034 [0,025–0,045] (1271) | 0,971 / 0,919 [0,875–0,948] (222) | no |
| Cuatro primeros | 2/3 | 2181 | 0,0552 | 0,0558 | 0,012 (-0,043 a 0,070) | 0,016 | 0,008 / 0,010 [0,006–0,017] (1414) | 0,982 / 0,961 [0,933–0,978] (309) | no |
| Tres últimos | 1/3 | 2121 | 0,0941 | 0,0961 | 0,021 (-0,034 a 0,077) | 0,038 | 0,014 / 0,030 [0,023–0,041] (1380) | 0,958 / 0,835 [0,746–0,897] (91) | no |
| Tres últimos | 2/3 | 2181 | 0,0600 | 0,0615 | 0,024 (-0,021 a 0,071) | 0,012 | 0,008 / 0,015 [0,010–0,023] (1497) | 0,970 / 0,953 [0,906–0,977] (149) | no |

BSS: mejora del Brier frente a la referencia de equipos iguales (IC por bootstrap de liga-temporadas, 2.000 réplicas). La regla
exige, en los seis casos, IC inferior del BSS > 0, ECE ≤ 0,03 y que la probabilidad media de los grupos extremos (≥ 20 casos) caiga
dentro del intervalo de Wilson de lo observado. Solo «campeón a un tercio» lo cumple.

## 4. Lectura

* **Sobreconfianza.** Lo que la simulación da por casi imposible (≤ 10 %) ocurre el doble de lo dicho (cuatro primeros a un
  tercio: 1,4 % dicho, 3,4 % observado; tres últimos: 1,4 % frente a 3,0 %), y lo que da por casi seguro (≥ 90 %) falla más
  de lo dicho (tres últimos a un tercio: 95,8 % dicho, 83,5 % observado). Es la firma de un modelo que trata sus fuerzas como
  conocidas: la simulación no propaga la incertidumbre de los parámetros ni el cambio de los equipos durante la temporada
  (lesiones, fichajes, entrenadores).
* **Poca ventaja sobre «todos iguales» a dos tercios.** Con dos tercios jugados la tabla ya dice casi todo; la fuerza del modelo
  apenas añade (BSS 0,01–0,07, intervalos que cruzan cero).
* **Lo que sí funciona:** el favorito al título a un tercio (BSS 0,16, bien calibrado) y la parte media de las probabilidades (ECE
  ≤ 0,04 en todos los casos). En las prioritarias el BSS es mayor (campeón 0,29 y cuatro primeros 0,23 a un tercio) pero no hay muestra
  para un veredicto propio.

**Consecuencia:** las probabilidades de temporada siguen **en sombra y privadas**. `scenarios-v2` no cambia: este LAB no toca
producción y un mal resultado nunca cambia una regla. Lo que se aprende para una v2 del protocolo (otra pieza, preregistrada antes de
mirar): propagar la incertidumbre de los parámetros (las extracciones de Laplace que ya tiene `fbi.models.goals`) o una contracción
hacia la media, y volver a medir sobre temporadas nuevas.

## 5. Criterios de aceptación y cierre

| Criterio | Estado |
| --- | --- |
| Protocolo sobre temporadas cerradas, privado hasta que pase y firme el dueño | **Cumplido**: nada salió del LAB |
| Veredicto registrado | **Cumplido: NO PASA** (130 liga-temporadas; 1 de 6 casos cumple) |
| Decisión del dueño anotada | **Pendiente**: ¿se archiva la línea con este motivo o se encarga un protocolo v2 con incertidumbre de parámetros? Publicar seguiría exigiendo DM-14 |

## 6. Reproducir

```
python scripts/lab_export.py verify <carpeta 20261121T050132Z>
python -m scripts.lab_season_sim <carpeta> --out pm0907.json
```

Resultado completo: `fbi_scratch\lab\results_20261121\pm0907_season_sim.json` en el portátil, SHA-256 `353756b5…a01b`.

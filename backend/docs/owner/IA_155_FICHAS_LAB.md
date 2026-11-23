# IA-155 · PM-08-07 · Las fichas que exigen medir antes de construir

Plan Maestro PM, ola 6, tarea **PM-08-07** (OP-18). Medido **fuera del servidor**, sobre la exportación de solo lectura del LAB, con el
protocolo preregistrado `PM-08-07` (`proto-pm-08-07-v1`, huella `3b3ac95d82db…1488`), registrado y fusionado en `main` (#461,
05:00:55 UTC) **antes** de tomar la exportación. No se construye nada: un PASA solo dice que los datos lo permitirían; construir es otra
tarea con la decisión del dueño. La trayectoria del entrenador no entra (va por OP-12).

## 1. Orden de los hechos (UTC, 21-nov-2026)

Protocolo empujado 03:24:45 (`fd0e5aa`) · código `scripts/lab_fichas.py` 03:37:07 (`b7d68df`, probado con datos sintéticos) · fusión
#461 05:00:55 (`194bf2f`) · exportación `lab-export-v2` 05:01:32–05:03:04 (carpeta `20261121T050132Z`, foto
`4765478:4765516:4765478`, 5.293.854 filas; tar SHA-256 `67204cc5…fc17`, `verify` correcto) · cálculo en el contenedor 05:05.

## 2. Veredicto por ficha

| Ficha | Regla del protocolo | Medida | Veredicto |
| --- | --- | --- | --- |
| **E · Estilo de juego** | ≥ 5 de 8 dimensiones con mediana de Spearman temporada → temporada ≥ 0,6 y cobertura de las 8 ≥ 80 % en ≥ 50 % de las liga-temporadas | 245 pares de liga-temporada (2021–2025). Mediana: pases **0,75**, precisión de pase **0,75**, posesión **0,73**, tiros **0,61**, córneres 0,50, faltas 0,40, proporción de tiros dentro del área 0,38, fueras de juego 0,30 → **4 de 8**. Cobertura de las 8 ≥ 80 % en el 59 % de 402 liga-temporadas | **NO PASA** |
| **P · Equipos parecidos** | IC 95 % inferior del Jaccard medio de los 3 vecinos (1.ª frente a 2.ª mitad) ≥ 0,40 y ≥ azar + 0,15 | 280 liga-temporadas: Jaccard medio **0,23** (IC 0,22–0,24) frente a 0,13 por azar | **NO PASA** |
| **A · Apercibidos** | Amarillas con jugador de los eventos = amarillas de las estadísticas en ≥ 95 % de los partidos-lado, en ≥ 80 % de las liga-temporadas; Y la regla de acumulación codificada | 336 competición-temporadas desde el 1-jul-2024: cumplen el 95 % el **78,6 %** (prioritarias 89 %, resto 78 %; mediana de coincidencia 97,7 %). Reglas codificadas (`config/rules`, 16 archivos): **ninguna** tiene umbral de acumulación; 7 solo usan las tarjetas como desempate de juego limpio | **NO PASA** (y sin regla sería INSUFICIENTE) |
| **T · Entrenador del partido** | `coach_id` en ≥ 90 % de los partidos-lado de competiciones seguidas | 151.194 partidos-lado de 372 competición-temporadas desde el 1-jul-2024: **90,4 %** (prioritarias 98,8 %) | **PASA** |
| **I · Identidad abierta** | ≥ 80 % de árbitros y ≥ 80 % de entrenadores con identificador externo (`core.entity_ids`) | Entrenadores: 2.822 de 8.096 (**34,9 %**; sistemas reep, transfermarkt, wikidata). Árbitros: **0** (6.653 alias distintos): `core.entity_ids` no tiene ningún árbitro | **NO PASA** |

## 3. Lectura

* **Estilo (E):** lo que se mantiene de una temporada a otra es el **volumen con balón** (pases, precisión, posesión) y algo los
  tiros. Córneres, faltas, fueras de juego y la proporción de tiros dentro del área cambian demasiado: una ficha de «estilo» con esas
  dimensiones describiría sobre todo la temporada, no al equipo. Una versión reducida a las cuatro estables sería otra ficha y otro
  protocolo (v2).
* **Parecidos (P):** los tres «equipos más parecidos» cambian casi por completo entre la primera y la segunda mitad de la misma
  temporada (solo un 23 % se repite, frente a un 13 % al azar). No es una ficha honesta hoy.
* **Apercibidos (A):** los datos de tarjetas son casi completos en las grandes ligas, pero **no hay ninguna regla de acumulación
  codificada** en el repositorio: sin leer el reglamento disciplinario de cada competición (ciclos, umbrales, qué tarjetas cuentan,
  si se limpian por fase) no se puede decir «a una amarilla de la sanción». Lectura humana pendiente (pregunta al dueño abajo).
* **Entrenador (T):** el entrenador del partido está en 9 de cada 10 alineaciones (casi todas en las prioritarias). Pasa justo.
* **Identidad abierta (I):** solo un tercio de los entrenadores y **ningún árbitro** tiene identificador externo. Enlazar árbitros
  con Wikidata u otra fuente abierta es trabajo previo de identidad (zona de Intelligence) y de licencia, no de esta ficha.

## 4. Corrección encontrada al leer la exportación: `lab-export-v3`

El alias de `core.fixture_officials` apunta a **`core.referee_aliases`** (migración 0083), no a `core.entity_aliases`: la lista
`lab-export-v2` (IA-154) se equivocó de tabla y sacó 9.760 filas de alias de jugadores, entrenadores y equipos **sin nombres** (solo
ids y tipos), que no sirven. Este PR la corrige (`lab-export-v3`: `core.referee_aliases` con id, árbitro, ámbito, base, quién lo colocó
y versión; nunca `name_key` ni `display`) y lo anota en la guía de PM-12-02. El veredicto de I **no cambia**: `core.entity_ids` no tiene
ninguna entidad de tipo árbitro, así que ningún árbitro tiene identificador abierto con cualquier enlace; por eso los árbitros se cuentan
como alias distintos (6.653, cota superior de personas). `scripts/lab_fichas.py` usa `core.referee_aliases` cuando la exportación la
trae. Las filas de v2 quedan solo en la copia del portátil y en `/tmp/predigol-lab` del worker (se va al recrear el contenedor).

## 5. Criterios de aceptación y cierre

| Criterio | Estado |
| --- | --- |
| Cobertura y estabilidad temporada a temporada medidas | **Cumplido** (E, P con estabilidad; A, T, I con cobertura) |
| Lectura del reglamento disciplinario | **Hecha sobre lo codificado**: ninguna regla de acumulación en `config/rules`; la lectura de los reglamentos disciplinarios oficiales queda **pendiente del dueño** (es lectura humana; no se simula) |
| Veredicto por ficha | **Cumplido**: E NO PASA · P NO PASA · A NO PASA · T PASA · I NO PASA |
| Decisión del dueño anotada | **Pendiente**: ¿se archiva E/P/A/I con su motivo y se deja T como dato disponible para una ficha futura? ¿Se encarga la lectura del reglamento disciplinario de la Liga BetPlay (la competición prioritaria) para codificar su acumulación? |

## 6. Reproducir

```
python scripts/lab_export.py verify <carpeta 20261121T050132Z>
python -m scripts.lab_fichas <carpeta> --out pm0807.json
```

Resultado completo: `fbi_scratch\lab\results_20261121\pm0807_fichas.json` en el portátil, SHA-256 `bd0d7b98…460d`.

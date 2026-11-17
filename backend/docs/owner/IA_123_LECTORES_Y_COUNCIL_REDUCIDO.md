# IA-123, IA-124 e IA-125 — Lectores especialistas, Council reducido y retirada condicionada de `review-v2`

Piezas AD-D09 (IA-123), AD-D10 (IA-124) y AD-D11 (IA-125) del plan de la arquitectura definitiva 2026. Todo queda en sombra: ningún lector
ni juez cambia una probabilidad, sube un estado, usa herramientas o llega a un lector del sitio. `decision-v1` no se toca y `FBI_PICKS_SOURCE`
sigue apagado.

## 1. Lectores especialistas (AD-D09, IA-123)

**Qué se corrigió.** El contrato de la deliberación (`IA_046_CONTRATO_DELIBERACION.md`) vigilaba tres violaciones: Jugadores recibía la
brecha entre modelo y mercado de un C06 con sus probabilidades (V1), Jugadores recibía hallazgos sobre el calendario, lo que se juega cada
equipo y el clima, que su porción no lee (V2), y Estadísticas recibía un C07 sobre traspasos (V3). La regla nueva `porcion-v1` entrega un
hallazgo a un lector solo si todo aquello en lo que se apoya (bloques `P:` y evidencias `E:`) está en su porción. La única excepción son
`P:market` y `P:models`, que en un C06 son los números del candidato: Partido y Estadísticas ya los leen en sus candidatos; Jugadores no lee
ningún número y nunca recibe un C06. Las tres pruebas pasan de «violación conocida» a obligatorias.

**Versiones nuevas.** Como cambia lo que reciben, los tres lectores tienen versión nueva, nacen CHALLENGER y no cambian ni prompt, ni contrato,
ni modelo, ni esfuerzo (su huella es la misma): `match-v6` (antes `match-v5`), `stats-v5` (antes `stats-v4`) y `player-v2` (antes
`player-v1`). Las filas de `ai.agent_runs` de las versiones anteriores se conservan; las nuevas se cuentan aparte. Ojo: el recuento de
salidas inválidas por versión empieza de cero con las versiones nuevas.

**Cuándo hablan (`readers-v1`).** Con `FBI_AI_READERS=e1` los lectores solo hablan en E1 (entre 24 y 12 horas antes del saque) y, después,
solo en una pasada con una contradicción material de `contra-v1`: una baja clave o del portero titular confirmadas (C01, C02), una rotación
juzgada con la alineación oficial (C03), la brecha modelo-mercado (C06) o evidencia en conflicto (C07). En E3 y E4 nunca (son solo código).
Si una pasada no es su momento, el Council de sombra de esa pasada se hace sin sus posturas y la fila de la pasada lo dice
(`model_status.readers`). Por defecto `FBI_AI_READERS=passes`: hablan en todas las pasadas, como hasta hoy.

**Lo que no cambia.** Los lectores no tienen herramientas, no escriben consultas ni direcciones y no tocan números; cada petición se construye
antes de preguntar a ninguno y con los mismos hallazgos calculados sin posturas, así que ninguno ve lo que dijo otro. Una respuesta fuera de
`aa-v1` o `pa-v1` se rechaza antes de guardarse (`output-guard-v1`, modo `enforce`).

## 2. Council reducido (AD-D10, IA-124)

**Qué hace.** `council-reduced-v1`, sobre `council-protocol-v1`. Para cada selección de cada pasada de la sombra:

1. **Las reglas por defecto.** Las posturas se agregan con la regla del protocolo: tirón de la postura × peso del historial del agente en la
   familia × novedad respecto de lo que el modelo ya sabe.
2. **El juez solo si se cumplen las tres condiciones:** una contradicción material (entre voces que pesan, o un C07), valor en juego (el
   mínimo de valor esperado de la capa de decisión, o la ventaja mínima si no hay valor esperado) y tiempo (al menos 30 minutos al saque).
3. **Tres lecturas y mayoría.** El juez lee tres veces la misma vista; su palabra solo vale si dos de las tres coinciden. Si no hay mayoría,
   o la mayoría se abstiene, quedan las reglas.
4. **Solo baja.** El resultado final es el de las reglas, salvo que la mayoría del juez sea más conservadora. La base de datos rechaza una
   fila en la que el Council suba (`council_reduced_only_lowers`).
5. **El brazo Haiku no es juez** en esta versión (el juez es el Council de `ma-v1`, Sonnet). El brazo `ma-v1-h` y sus filas siguen como
   estaban; quitarlo de los motores es `FBI_AI_ENGINES` sin `ma-v1-h`.

**Lo que guarda.** `ai.council_reduced` (migración 0161, solo añadir): una fila por pasada, candidato y versión, con el veredicto de las
reglas, si el juez hacía falta y por qué, la mayoría de sus lecturas y el veredicto final. En esta versión del pase **el juez no se llama**:
cuando haría falta, la fila queda `not_asked` y mandan las reglas. Así se mide cuántos casos tendría el juez (cada caso cuesta tres lecturas
de Sonnet) antes de gastar nada. No hay ninguna llamada a un modelo.

**Cómo se enciende.** `FBI_COUNCIL_REDUCED=shadow` en el worker (por defecto `off`: ni se programa). Corre cada 30 minutos
(`FBI_COUNCIL_REDUCED_MINUTES`, de 10 a 240).

## 3. Retirada condicionada de `review-v2` (AD-D11, IA-125) — preparada, no ejecutada

`review-v2` **no se retira**. Esta pieza deja tres cosas, y cada paso lo firmas tú:

**El criterio preregistrado (`review-retire-v1`, propuesto).** Sobre las mismas selecciones (las que `review-v2` revisó con modelo y
`decision-v2` decidió en sombra, con evaluación `eval-sel-v1` y precio de cierre): diferencia pareada, por selección examinada, del valor
frente al cierre de lo que deja pasar cada camino. No inferior si el extremo inferior del IC95 (remuestreo por días de Bogotá, 2.000 réplicas,
semilla fija) es mayor o igual que −0,005 (medio punto de CLV). Muestra mínima: 300 selecciones y 14 días. La ventana son las 4 semanas
siguientes a tu firma; nada anterior cuenta. Las cifras son propuestas hasta que las firmes.

**La medida del efecto.** `effect_of_removal` cuenta cómo cambiaría la revisión combinada (la que leen el filtro 6 de `decision-v1` y la
regla D1 del estado de usuario) si se quitara el modelo: queda la palabra de las reglas. Se mide antes de cada paso y la firmas.

**El interruptor por pasos (`FBI_REVIEW_V2`).**

| Valor | Qué hace |
| --- | --- |
| `on` (por defecto) | El camino de hoy, igual byte a byte. |
| `no_opus` | Paso 1: nunca se escala al modelo fuerte (ni L3 ni arbitraje de una contradicción). |
| `sample` | Paso 2: además, el modelo solo revisa una muestra aleatoria fija del 20 % de las selecciones, el grupo de control. |
| `off` | Paso 3: solo las reglas (`rules-review-v1`); no se pide ni se arrastra ninguna revisión con modelo. |

Cualquier otra palabra es `on`. Todas las filas de `ai.pick_reviews` se conservan en cada paso. Efecto en el lector hoy: ninguno, porque
nunca se ha publicado un pick y `FBI_PICKS_SOURCE` sigue apagado.

## 4. Cómo se apaga o se revierte

- Lectores: `FBI_AI_READERS=passes` (o quitar la variable) y reiniciar el worker. Volver a `match-v5`/`stats-v4`/`player-v1` es revertir el
  cambio; sus filas siguen en `ai.agent_runs`.
- Council reducido: `FBI_COUNCIL_REDUCED=off`. Las filas de `ai.council_reduced` se conservan; la migración 0161 tiene bajada (borra la tabla).
- `review-v2`: `FBI_REVIEW_V2=on` restaura el camino de hoy.

## 5. Lo que queda pendiente

- Llamar al juez de verdad (tres lecturas de Sonnet en el LAB, dentro del presupuesto por capacidad) cuando se sepa cuántos casos hay.
- `battery-v4` con el modelo real para las versiones nuevas, y al menos 100 respuestas por lector para medir las inválidas (≤ 3 %).
- La firma del protocolo de `review-v2` y, cuando haya muestra, la comparación en el tablero de AD-K02.

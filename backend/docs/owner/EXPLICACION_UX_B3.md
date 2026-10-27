# B3 · Explicación de picks y estados: cada pick dice su estado y por qué se eligió

Plan Maestro UX, fase B3 (sección 28; mantiene en verde G9). **Cada estado visible equivale a uno interno y todo pick publicado
responde «¿por qué?»**. La capa de usuario lee los estados de PrediGol Intelligence y los dice con palabras; no decide ninguno.
Coste: 0. Sin migración.

## 1. Qué ve el cliente

- **El estado de cada pick, con palabras y un icono** (nunca solo un color), en Picks, en Inicio, en el pick del día y en el
  partido:

  | Estado | Cuándo | Dónde se ve |
  | --- | --- | --- |
  | **Recomendado** | Pick publicado que pasa la regla de valor con la mejor cuota de ahora; con la revisión de la IA aplicada, además aprobado. Mientras la IA siga en sombra lleva debajo **«Revisión de contexto aún no aplicada»** | Picks, Inicio y partido |
  | **Cautela** | Con la revisión de la IA aplicada, la revisión lo rebaja | Picks y partido |
  | **No recomendado** | Sin valor con la mejor cuota de ahora, o la revisión aplicada lo rechaza | Solo en su partido, nunca en la lista |
  | **En evaluación** | Candidato de un modelo que aún no superó al mercado (pick en sombra) | Solo en tu vista previa; nunca un cliente |

- **Picks** muestra solo lo que se le puede recomendar al cliente (Recomendado y Cautela, primero los recomendados) y **cuenta
  lo demás**: «2 selecciones más no se recomiendan ahora: las ves en sus partidos, con el motivo.». Si la lista se queda vacía
  por eso, lo dice con la verdad: «Ninguna selección que cumpla la regla tiene valor al precio actual.» o, si alguna la rechazó
  la revisión aplicada, «Ninguna selección se recomienda ahora: en su partido, cada una dice por qué.».
- **El partido** muestra sus picks sea cual sea su estado («Las selecciones que PrediGol publicó para este partido, cada una
  con su estado ahora»), cada uno con su motivo; la tarjeta del análisis dice el mismo estado.
- **El pick del día** dice el estado **con el que entró en la selección del día** (no cambia después de publicarse).
- **«¿Por qué este pick?»** en cada pick publicado (la lista, el pick del día y la tarjeta del análisis) abre una hoja —desde
  abajo en el móvil, desde el lado en el escritorio— con:
  - el estado y su motivo en una frase («Pasa la regla de valor a su cuota. La revisión de contexto de PrediGol Intelligence
    todavía no se aplica a los picks.») y, en un pick del día, el estado con el que entró si hoy es otro;
  - **Conclusión**, abierta y primero: «PrediGol espera «Gana Millonarios»: le da un 50 % de probabilidad; el mercado, sin su
    margen, un 43 %.»;
  - plegadas en filas de 44 px: **Contexto y datos** (los hechos de la lectura del partido, cada uno con su referencia, o la
    narrativa validada cuando la puedan ver; si no hay, dice por qué), **Mercado** (las dos probabilidades, la cuota a la que
    se publicó, la mejor de ahora y si sigue teniendo valor), **Riesgos** («Aun así, esta selección falla aproximadamente 5 de
    cada 10 veces», la duda del modelo, los riesgos de la lectura y, solo mientras la revisión esté aplicada, los suyos) y
    **Cómo lo decidimos** (los cinco pasos de Transparencia, sin cifras internas, y si es pick del día; el enlace a «Cómo le va
    a PrediGol» solo si esa página está abierta para él);
  - al final, siempre, el aviso **«no garantiza · +18»** con los textos legales y el juego responsable.

## 2. Línea base

- **Producción no tiene picks publicados** (selección del día vacía; última medición, 26-oct, línea base de A12) y **la IA está
  en sombra** (la revisión no se aplica). Con B3 desplegado, cada pick publicado que llegue dirá «Recomendado · Revisión de
  contexto aún no aplicada» y tendrá su «¿Por qué?»; los que pierdan el valor con la cuota de ahora pasarán a su partido como
  «No recomendado» (hasta hoy seguían en la lista, atenuados, con «sin valor ahora»). **Cautela y No recomendado por la revisión
  no tendrán contenido mientras la IA siga en sombra**: salir de sombra es una decisión de Intelligence, fuera de este plan
  (no se toca `FBI_AI_MODE`).
- Hoy, sin B3: todo pick publicado dice «Recomendado» (con el rótulo de A1), sin explicación; el pick del día, igual.
- **En QA** se ven los cuatro estados con picks de ejemplo (base `fbi_qa_b3s`, `seed_b3.py`: una liga «QA Liga B3» con seis
  partidos y la revisión aplicada solo en esa copia). La base de QA de siempre no tiene picks: no se fabrican.

## 3. Lo que nunca cambia

- **PrediGol Intelligence:** nada. Ni modelos, probabilidades, calibraciones, umbrales, reglas que califican picks,
  liquidación, estados internos, gates de publicación ni SHADOW. El estado **solo lee** lo guardado: el estado del pick, la
  regla de valor con la mejor cuota de ahora (la misma puerta que ya usaba la lista) y la revisión de la IA.
- **La revisión de la IA cambia un estado solo cuando está aplicada**: `FBI_AI_MODE=enforce` **y** el último informe en sombra
  con su gate aprobado (`fbi.ai.gating`), igual que el resto del producto. Hoy no lo está: no cambia nada.
- **Igual para todos:** dos clientes reciben los mismos estados y la misma explicación (prueba de integración).
- **Nunca se fabrica:** un pick en sombra nunca se muestra como recomendación, ni en tu vista previa (allí es «En
  evaluación»); un cliente que lo pida recibe 404, como si no existiera.
- **La guarda de modelos sigue en `stop`:** el código nuevo (`fbi/picks/user_status.py`) no está entre los paquetes de los
  modelos, así que su huella no cambia.

## 4. Lo nuevo por dentro

- **`fbi/picks/user_status.py`, la única tabla:** de (publicado, valor ahora, decisión de la revisión, revisión aplicada) a uno
  de los cuatro estados con su motivo (`approved`, `value`, `not_reviewed`, `downgraded`, `rejected`, `no_value_now`,
  `evaluation`) y si lleva «revisión aún no aplicada». Sin dependencias: solo datos.
- **El contrato:** `user_status`, `status_reason` y `context_pending` en las tarjetas de Picks, Inicio, mejores cuotas, el día
  y el análisis; `withheld` en la lista (cuántos quedan en su partido); la razón `none_recommended`. La instantánea de las
  rutas del cliente se reescribió con su motivo.
- **`GET /api/v1/picks/{id}/explanation`:** las cinco capas desde lo guardado (nada se estima, no se llama a ningún modelo ni
  a la IA, nada se escribe), 30 s en caché, igual para todos; tu vista previa ve también los de sombra.
- **La revisión** se lee como la lee la IA (la más reciente de las últimas 12 horas), con una consulta propia fijada por una
  prueba a la de `fbi.ai.review`, para que la capa de usuario no importe el módulo de la IA.
- **Eventos:** `pick_opened` al abrir un pick y `pick_explanation_opened` una vez por cada apertura (los dos estaban en el
  catálogo de A6).

## 5. Decisiones que tomé

1. **«En evaluación» solo en tu vista previa.** La sección 28 lo deja para los clientes como recuento en Transparencia; tu
   vista previa ya mostraba los picks en sombra, y ahora los rotula «En evaluación» en vez de cualquier recomendación.
2. **No recomendado sale de la lista y queda en su partido, contado.** Es la regla de la sección 28 («solo en el partido,
   nunca en la lista»); la lista dice cuántos son y por qué, para no dar a entender que no hay nada.
3. **El pick del día conserva el estado con el que entró** (lo guardado al elegirlo); la explicación muestra los dos si hoy
   difieren. Una tarjeta publicada no cambia de estado sola.
4. **Un partido que ya empezó** se explica como se tomó: no se vuelve a calcular con las cuotas de ahora.
5. **«Cómo lo decidimos» sin cifras:** los mismos cinco pasos que Transparencia y la frase de lo que este pick pasó.
6. **Sin estado desconocido:** si una respuesta no trae un estado conocido (una API anterior durante una vuelta atrás), la web
   no muestra ninguno.

## 6. Pruebas

- **Backend (unitarias):** la tabla con todas las combinaciones (40 de picks y 60 de tarjetas del análisis, cada estado
  alcanzable, la revisión sin aplicar no cambia nada, sin dependencias), la revisión aplicada solo con `enforce` y el gate
  aprobado, y la consulta de revisiones igual a la de la IA.
- **Backend (integración, base real):** picks de ejemplo en cada estado en la lista, el pick del día, el análisis y la
  explicación, con la IA en sombra, aplicada, sin informe y con el gate suspendido; el orden (Cautela después); quién puede
  preguntar (404 a un cliente por un pick en sombra, la vista previa solo para ti); la lectura y su interruptor; dos clientes
  iguales; la razón de una lista vacía.
- **Web (unitarias):** el distintivo (cuatro estados con palabras e icono, colores distintos, el rótulo solo cuando toca,
  nada si el estado no es conocido), las líneas de las cinco capas en español e inglés, el orden y los pliegues de la hoja, el
  estado del día y la revisión solo aplicada, el enlace a Transparencia solo abierto.
- **e2e (`pickstates.spec.ts`, proyecto `states`, con `seed_b3.py`):** la lista con sus estados y su recuento, el día con el
  estado de entrada, la hoja en el escritorio (desde el lado, por teclado, el foco de vuelta al botón, el evento una vez) y a
  320 px (desde abajo, filas de 44 px, nada de lado), el partido con su pick rechazado o sin valor y su análisis, el pick en
  sombra invisible para un cliente y «En evaluación» en tu vista previa, y axe (WCAG 2.2 A y AA) sobre Picks y la hoja.

## 7. Puertas

- **Árbol final del paquete de B3 y B4** (`ux/rel-b4`: A3 a A16 y B1 a B4 sobre A2, *merge* `280b34b4` más `9d0c9ead` y
  `b8c9f348`): backend con ruff y mypy limpios y **8.037 pruebas pasadas**, 4 omitidas; web con lint en 0 errores (26 avisos
  de siempre), tipos, **1.039 pruebas** y build; Gitleaks del rango 0.
- **e2e sobre ese árbol** (27-oct, 04:45–05:49 UTC), con la base de QA migrada como producción (copia de `fbi_qa_a2ia` en la
  0113 → prueba de restauración → migración arriba, abajo y arriba → `fbi_qa_rel` en la 0102): estados de B3
  (`pickstates.spec.ts`) **10 de 10**, Postpartido (`postmatch.spec.ts`) **8 de 8**, la suite completa como arranca
  producción 168 pasadas, 3 fallidas y 19 omitidas, autoservicio 39 / 1 / 2, membresía 8 / 8, tickets apagados 7 / 7, axe
  35 / 35 y app instalable 8 / 8. Los 4 fallos fueron esperas de carga (una página aún cargando a los 60 s o un bloque aún sin
  pintar a los 15 s, con dos trabajadores) y, repetidos solos con un trabajador, pasaron 4 de 4.
- **Antes, sobre la rama de la fase:** backend 6.064 pruebas pasadas (4 omitidas) y web 935 pruebas; `pickstates.spec.ts` 10 de 10
  y la suite de tickets apagados 7 de 7.
- **El paquete que se despliega es `ux-b5`** (A3 a A16 y B1 a B5, sobre `ia-p02` de la IA, que llegó antes): sus puertas y su
  e2e completo se repiten sobre ese árbol final antes de desplegar (`MIS_PICKS_UX_B5.md` y `ESTADO_EJECUCION_UX.md`).

## 8. Despliegue

Backend y web juntos (el contrato cruza los dos), sin migración. Va en el paquete `ux-b5` con todo lo terminado después de A2
(A3 a A16 y B1 a B5), sobre `ia-p02`; el resultado del despliegue queda en `ESTADO_EJECUCION_UX.md`.
**Vuelta atrás:** la web anterior funciona con este backend (ignora los campos nuevos; la lista ya no trae los picks sin valor,
que siguen en su partido) o las dos publicaciones anteriores. No hay nada que encender ni apagar.

## 9. Acción manual

Ninguna.

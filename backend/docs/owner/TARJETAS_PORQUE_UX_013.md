# UX-013 · Una línea de «por qué» y chips de riesgo en los picks compactos

Plan de cierre de la UX, tarea 2.3. **Solo web: sin migración, sin interruptor nuevo y sin tocar la API.** «¿Por qué?» y «Explícame» siguen
exactamente igual en cada tarjeta.

## 1. Qué ve el cliente

En las tarjetas de pick **compactas** (los picks del día de Inicio y las listas compactas de Picks):

- **Una línea de «por qué»:** «PrediGol le da 52 % y el mercado, 45 %.» Son los mismos dos números que la tarjeta completa dibuja como
  barras, tomados del propio pick (los que tenía al elegirse en los picks del día; los de ahora en los picks vivos). Sin uno de los dos
  números, no hay línea.
- **Chips de riesgo** (hasta dos, en los picks del día): los riesgos que anotó la revisión de contexto de PrediGol al elegir el pick, uno
  por chip, cada uno en dos líneas como mucho y con su texto entero al mantener el dedo o pasar el ratón. **Solo se muestran cuando el
  lector puede ver la decisión de esa revisión** (la misma regla que ya aplica a la lista de riesgos de la tarjeta completa); en sombra no
  hay chips, y una revisión sin riesgos no deja ningún chip vacío.

Las tarjetas completas no cambian: ya muestran las barras de probabilidad y, en los picks del día, la decisión de la revisión con su motivo y
sus riesgos en una lista.

## 2. Lo que no hace

- **No inventa riesgos.** Un riesgo sale de lo que la revisión guardó con el pick; los picks vivos de la lista de Picks y del partido no traen
  revisión en su respuesta y por eso solo llevan la línea, sin chips. Poner chips ahí exigiría que la API los enviara (un cambio de
  contrato, aparte de este).
- No cambia picks, probabilidades, umbrales, la revisión ni nada de PrediGol Intelligence: lee lo que ya está guardado.
- No dice «seguro», «fijo» ni «garantizado» (probado en español e inglés).

## 3. Pruebas

`PickWhy.test.tsx` (la línea con números como texto o número, nada sin uno de los dos, sin palabras de certeza en ES y EN; los chips: dos
como mucho, texto entero en `title`, ninguno sin riesgos o con solo espacios, los espacios no gastan los dos sitios); `bun run lint`,
`typecheck` (también los tipos del e2e) y `test`.

## 4. Despliegue y vuelta atrás

Solo web. Vuelta atrás: revertir el PR. Hasta que se despliegue, producción sigue como estaba.

## 5. Acción manual

Ninguna. Al desplegar, mira Inicio en el teléfono: cada pick del día lleva su línea de «por qué» y, si la revisión anotó riesgos, hasta dos chips.

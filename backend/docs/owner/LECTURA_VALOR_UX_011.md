# UX-011 · Puntos clave, «Por qué hay valor» y factores en la lectura de un partido

Plan de cierre de la UX, tarea 2.1. **Sin migración, sin interruptor nuevo, sin IA y sin servicios externos.** La lectura
estructurada de un partido (A9) suma tres apartados escritos igual que ella, solo con lo que PrediGol ya tiene guardado. No cambia un
pick, una probabilidad, una calibración ni un umbral: la capa de usuario consume la inteligencia, no la altera.

## 1. Qué ve el cliente

En el **Resumen** del partido, arriba, antes del pronóstico y de los picks:

1. **Qué es el partido** (competición, ronda, si es una final…), como antes.
2. **Puntos clave** (hasta cinco, nunca rellenados): lo que limita la lectura (por ejemplo, «PrediGol solo describe este partido»),
   lo que PrediGol espera (o que todavía no hay pronóstico) y los factores que más se notan. Un partido con pocos datos tiene
   menos puntos; uno sin datos dice qué falta.
3. **Por qué hay valor**, **solo si PrediGol publicó un pick de ese partido** y el lector puede verlo (los mismos que la pestaña
   Picks del partido: solo «Recomendado», decisión UX-002). Por cada pick, hasta tres: la probabilidad que PrediGol le da frente a
   la que le da el mercado (con la diferencia en puntos porcentuales cuando es de al menos uno) y la cuota frente a la cuota justa
   del mercado y la «cuota según PrediGol». Antes del saque, la mejor cuota de ahora; una vez empezado, la cuota con la que se
   tomó. Debajo, una nota fija: «Es la diferencia entre lo que PrediGol calcula y lo que paga el mercado. Un pick con valor puede
   perder: no es una promesa de resultado».
4. **Riesgos principales** (los dos primeros), como antes, y «Ver el análisis completo».

**Sin pick, no hay «Por qué hay valor»**: el apartado no existe (no se escribe «no hay valor»). Un pick de evaluación nunca llega
aquí, ni siquiera en la vista previa del dueño. Cada frase aparece una sola vez: el resumen no repite lo que ya dicen los puntos clave,
y los puntos clave no repiten el pick que «Por qué hay valor» explica justo debajo.

La pestaña **Análisis** no cambia: sigue siendo los seis apartados de siempre (o la narrativa de A11, si la enciendes). Los tres
nuevos se leen en el Resumen; los **factores** (hasta seis hechos de la propia lectura que destacan: lo que se juega cada equipo, la
ida de la eliminatoria, bajas importantes, una racha larga, un mercado que se movió) llegan por la API y alimentan los puntos clave;
la pantalla todavía no los lista aparte.

## 2. De dónde sale cada cosa

| Apartado | Sale de |
| --- | --- |
| Puntos clave | Los apartados de la propia lectura: el hecho de «solo descripción» (si lo hay), el resultado esperado o «sin pronóstico», hasta dos hechos de valor y hasta dos factores. |
| Por qué hay valor | Las mismas tarjetas de pick que muestra la pestaña Picks del partido (`product.picks_board`, ventana de 168 h, el corte de los lectores): la probabilidad calibrada de PrediGol, la probabilidad del mercado sin margen y la mejor cuota (o la cuota tomada). |
| Cuota justa | 1 / probabilidad del mercado (el glosario: «cuota justa»). |
| Cuota según PrediGol | 1 / probabilidad de PrediGol (el glosario: «cuota según PrediGol»). |
| Factores | Los hechos de contexto, datos y mercado que la lectura ya elige con sus reglas (racha de cuatro o más, movimiento de dos puntos o más, jugador clave fuera…). Una presión «sin nada en juego» no cuenta. |

Un dato que falta se deja fuera, nunca se inventa: sin probabilidad del mercado no hay la frase de «el mercado, 45 %»; sin cuota no hay
la de la cuota; sin una cuota justa, esa cláusula no se escribe.

## 3. Lo que no hace

- **No toca PrediGol Intelligence ni la lectura base.** `reading-v1` y su huella (`reading_hash`) siguen igual; la narrativa de A11
  **no lee** estos tres apartados (el modelo de IA tiene prohibido decir «valor» o «pick»: plan 2.4). Se componen en la ruta de la API
  (`routers/reading.py`), no dentro del servicio de la lectura, porque ese servicio lo carga la IA de los lectores y la prueba de
  aislamiento (`test_user_layer_isolation`) le prohíbe llegar a la capa de usuario.
- **No cambia lo que sale de la API en los seis apartados** (siguen sin cuotas, casas ni probabilidades propias de los modelos). Los
  números de «Por qué hay valor» son los que la tarjeta del pick y su explicación **ya muestran** a quien lo ve, ni uno más.
- **No dice «seguro», «fijo» ni «garantizado».** Las plantillas de «Por qué hay valor» viven en un espacio propio (`match.understand`)
  con su prueba (ninguna palabra de certeza, ni de ganancia, en español ni en inglés); la prohibición de la palabra «valor» en las
  frases de la lectura base (`match.facts`) sigue como estaba. La palabra «valor» solo está en el título y en la nota del apartado.
- **No reemplaza al pick:** si ningún pick pasó las condiciones, el Resumen sigue diciendo lo que ya decía.

## 4. Interruptores

Ninguno nuevo. Los apartados nuevos viajan con la lectura: `FBI_READING_USERS=0` los oculta con ella, sin despliegue (mapa en
`INTERRUPTORES_UX.md`).

## 5. Pruebas

- Backend: `tests/unit/test_reading_value.py` (frases de pick y de cuota, datos que faltan, pick ya empezado, factores y su tope,
  orden y tope de los puntos clave, lectura escasa, un hecho repetido una vez, lectura oculta intacta, claves disjuntas de las seis),
  `tests/integration/test_reading_value.py` (la ruta con un pick recomendado, uno en evaluación que no sale y uno ya empezado),
  `tests/integration/test_reading_api.py` y `tests/unit/test_reading_codes.py` (los códigos de la web y de la API son los mismos).
- Web: `text.test.ts` (cada código con su frase en español e inglés, la diferencia en puntos como la de las dos cifras mostradas,
  nada de certeza), `ReadingBlock.test.tsx` (Análisis solo con los seis; Resumen con puntos clave, valor y riesgos, cada frase una
  vez; sin pick no hay valor), y `glossary.test.ts` (las frases de «cuota justa» declaran que es el precio del mercado).

## 6. Despliegue y vuelta atrás

Cambia el contrato de la API (tres claves nuevas de apartado) y la web que lo lee **en el mismo cambio**, y la API y la web salen en la
misma versión del kit de lanzamiento. Una web nueva con una API vieja simplemente no muestra los apartados nuevos; **una web vieja con la
API nueva los mostraría en Análisis sin título**, por eso no conviene desplegar la API sola. Vuelta atrás: revertir el PR; no hay
migración ni datos nuevos. Hasta que se despliegue, producción sigue con lo anterior.

## 7. Acción manual

Ninguna para este cambio. Cuando se despliegue, mira un partido con pick publicado y uno sin él: el primero muestra «Por qué hay
valor» y el segundo no.

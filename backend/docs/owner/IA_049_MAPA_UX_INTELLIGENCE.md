# IA-049 — Mapa de Intelligence sobre los componentes de «Noche de partido»

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-E02, ola 1. 11-nov-2026.*

Este documento es para la sesión de UX. Para cada campo del contrato de Intelligence (`INT-E01`) dice:

- en qué lámina y en qué componente de «Noche de partido» se muestra hoy;
- qué hacer cuando falta el dato;
- y qué pieza nueva hace falta.

**No es un sistema de diseño ni un cambio de pantallas.** Solo dice qué necesita Intelligence y dónde podría encajar. Dónde va cada cosa lo decide UX, con el dueño cuando haga falta. El mapa respeta lo que ya decidió el plan de UX y sus doce propuestas abiertas:

- las decisiones 3, 4, 10 y 11;
- las olas 4, 6, 7, 8 y 12.

**Fuentes (solo lectura, 11-nov-2026).**

- **Lienzo de la etapa 2.** Es la v23 según el proyecto; versión publicada `1794363585-5443`. Láminas leídas:
  - Partidos: P03, P04, P06, P10, P11 y P12.
  - Picks: K02, K03, K04, K05 y K07.
  - Transparencia: T01, T02, T05, T06 y T07.
  - Cuotas: C05.
  - Sistema: S4 y S5.
- **Documentos del proyecto.** `PLAN_MAESTRO_IMPLEMENTACION_UX_2026.md` y `DISENO_INTEGRAL_ETAPA2_20261110.md`.
- **Plan maestro de Intelligence.** Su sección 6 y la ficha de `INT-E01`.
- **Código de `main` `77518df0`.** Solo para ver los textos y los estados que ya existen.

**Límite.** `INT-E01` todavía no existe: es de la ola 2. Por eso los campos llevan el nombre descriptivo de su ficha, no nombres de API.

## 1. Reglas de producto

1. **Solo «Recomendado».** Al usuario solo le llega como pick lo «Recomendado», en dorado y con corona. Lo que queda en cautela, no recomendado, en vigilancia o en observación nunca se pinta como pick: ni tarjeta, ni corona, ni sello, ni resaltado de su mercado.
2. **Sin pick, el motivo.** Se explica qué condición faltó en el partido, sin nombrar el mercado que no se recomienda.
3. **La cuota, en neutro.** La cuota y su movimiento no van ni en verde ni en rojo. El dorado pertenece al sello «Recomendado», no al precio.
4. **El valor sale del análisis.** No sale de que una casa pague más que otra.
   - La ventaja se mide entre la cifra única y el mercado sin margen: es la condición Estadística.
   - El mejor precio de una casa solo cuenta para la condición Precio, que comprueba que el valor siga al precio de ahora. Nunca es el origen del valor.
   - La casa es un dato del precio, no un motivo del pick.
5. **Una sola cifra.** Cada selección lleva una única cifra, la misma que usa la decisión. Si no está calibrada, lleva una vez el sello gris «Sin calibrar».
6. **Hechos con sello.** Cada hecho lleva su sello, su fuente y su hora. El rumor no aparece en los bloques de Intelligence.
7. **Incertidumbre y validación.** La incertidumbre se dice en palabras y con su rango. Siempre se dice el estado de validación del mercado. Hoy sería «Solo informativo» en todos los mercados, porque ningún par de liga y mercado tiene ventaja validada.
8. **Nada sin origen.** Cuando falta un dato, se dice por qué y qué sigue valiendo, como en el patrón de estados de S5. Nunca se rellena con otra fuente, como la predicción del proveedor.
9. **Mismo espacio para fallos y aciertos.** La decisión se juzga por el precio y por muestras, no por un resultado suelto.

**De dónde salen.**

- Reglas 1 y 4: criterio del dueño (sección 3 del plan y `INT-A10`).
- Regla 2: `INT-D03`.
- Reglas 3, 5, 6, 7 y 9: sección 6 del plan.
- Regla 8: el gate de `INT-E01` y la lámina S5.

## 2. Tabla de correspondencias

Del campo del contrato a la lámina, al componente que ya lo muestra, a lo que se hace sin datos y a la pieza nueva que falta.

| Campo (`INT-E01`) | Pantalla / lámina | Componente de «Noche de partido» que lo muestra | Sin datos | Pieza nueva |
| --- | --- | --- | --- | --- |
| Pronóstico: cifra única | P03 («Pronóstico PrediGol» y «Lo más probable»); P06 («PrediGol estima»); K02 («Por qué tiene valor») | Barra de probabilidad de S4 (barra de PrediGol con la marca del mercado, y barra 1X2) y tarjeta de pick de S4 | No se pinta la barra y la sección dice el motivo («datos que no alcanzan»). Nunca se usa la cifra de otra fuente | — |
| Pronóstico: rango | P03 («entre 48 y 63 %», con su franja); S4 («Rango […] La cifra es el centro, no una certeza») | Franja de rango de la barra (S4) | «sin rango medido», texto que ya existe (`match.json`, `forecast.rangeNone`) | — |
| Pronóstico: calibración | P03 (sello «Calibrado») | Etiqueta verde con insignia (S4, P03) | «Sin calibrar», en gris y una sola vez, texto que ya existe (`forecast.uncalibrated`) | — |
| Precio: cifra y casa | P03 («Mejores cuotas»); P06; K02 («te pagan»); S4 («Tabla de cuotas») | Botón de cuota y tabla de cuotas (S4, PR-12) | Estado «Sin cuotas», que el plan da por dibujado (sección 6) aunque no lo encontré en P03 ni en P11; en C05, «Sin precio hoy». Sin precio no hay pick, porque falla la condición Precio | — |
| Precio: edad | P03 y P06 («Precios de hace 7 min»); C05 | Precio con su antigüedad (PR-12) | Un precio viejo lleva reloj y hora exacta (regla de UX). Un precio sin hora no se presenta como vigente | — |
| Precio: estado (vigente, caducado, movido o sin valor al precio de ahora) | K02 («Mientras encuentres 1,79 o más […]»); C05 (decisión 4, pendiente) | Nota y banda de atención (S5) | Si está caducado: aviso neutro con la hora, y el pick no se publica | Fila «Precio» de la lista de condiciones |
| Precio: movimiento | P04 («Mercado», de la apertura a ahora); C04 | Gráfico de movimiento (PR-12, «movimiento en neutro») | Sin historial, solo el precio actual con su edad | — (ver la sección 4, P04) |
| Veredicto: estado | P03 («Pick de PrediGol»); K01 y K02; P12 (administración) | Tarjeta de pick con el sello «Recomendado» (S4, PR-13) y los siete estados del pick (K05) | Solo un pick RECOMENDADO tiene tarjeta. Si no lo hay: «Sin pick» en P03, «Hoy no hay pick» en K07 | — |
| Veredicto: motivo | P04 («Conclusión de PrediGol»); K02 («En una frase»); K03 («Conclusión»). Sin pick: P03 y K07 («Dónde se quedaron») | Tarjeta dorada de conclusión (P04) y embudo «Dónde se quedaron» (K07) | El motivo se dice en lenguaje claro, sin nombrar el mercado | Caso nuevo de «Sin pick»: evidencia insuficiente (falta según la sección 6 del plan) |
| Cuatro condiciones (estadística, precio, evidencia y controles), cada una con su estado y su porqué | K03 (acordeón «Cómo lo decidimos»); K02 («Ficha del pick» → «Cómo lo decidimos»); P12 («Cadena de decisión del pick», administración) | Acordeón dentro de la hoja (K03) y filas de clave y valor (K02) | Sin registro de la decisión, la lista no se pinta ni se deduce | **Lista de condiciones** |
| Evidencia: estado, fuente, hora, enlace y cita breve | P04 («Contexto» y «Fuentes»); K02 («Lo que pesa a favor»); K03; bloque Intelligence de P03 y P11; «Noticias del partido» en P11 | Línea de hecho con la «cita de fuente con sello» (P04) y sellos de «Certeza de una noticia» (S4) | Se dice si se buscó o no: «no buscado todavía» no es «nada encontrado», regla que ya cumple `api/services/news.py`. El rumor no se muestra | **Sello de evidencia con estado** |
| Evidencia: contradicción | Hoy solo en Noticias, donde la API agrupa una contradicción en una tarjeta con las dos fuentes | Tarjeta de noticia contradictoria (ya existe en la API de noticias) | Si bloquea, falla la condición Evidencia y se dice | Estado «contradicción» del sello de evidencia |
| Riesgos verificados | P03 («Qué puede salir mal»); P04 («Riesgos»); K02 («Qué puede salir mal») | Banda de atención (S5) y líneas de hecho (P04) | Si no hay riesgos verificados, la sección queda vacía y nunca se inventan. Cómo se ve ese vacío lo decide UX | — |
| Estado de validación del mercado | Ninguna lámina | — | Hoy, «Solo informativo» en todo | **Estado de validación** |
| Crónica vigente | P04 («Resumen» y «Contexto»); párrafo del bloque Intelligence de P03 | Bloque de la crónica. Es de la sesión de la crónica v4: UX solo toca el contenedor. La crónica no ve ni el pronóstico, ni las cuotas, ni los picks: la «Conclusión» de P04 sale del veredicto, no de la crónica | Sin crónica vigente se usa la plantilla (`INT-D03`) con «Actualizado HH:MM». Si hay poca información, un resumen corto | — |
| Revisión posterior | P10 (por la decisión 11, se pone arriba del Resumen cuando termina el partido); T02 («Ver el porqué»); T01 y T07 («¿Estima bien?») | Tarjeta dorada «Pick prepartido» y lista «Pronóstico frente a resultado» (P10); barras de calibración (T01) | Antes de la revisión, «revisión pendiente», sin juzgar por el resultado | **«Después del partido»** |
| Hora del conocimiento | P03 y P11 («Datos de las 17:18»); P04 («Actualizado 17:18») | Etiqueta de hora; estado «Sin conexión» con «Datos de las HH:MM» (S5) | Con datos viejos se dice la hora de lo que se ve | — |
| Expediente interno: posturas, contradicciones, coste y versiones | P12, que por la decisión 11 pasa a ser un botón del administrador | Tablas «Cadena de decisión», «Registro del partido» y «Versiones» (P12) | Solo administradores (`INT-E03`), nunca en la vista del usuario | — |

## 3. Las cuatro piezas nuevas

Aquí se describe qué contiene cada pieza, no cómo se dibuja.

### Lista de condiciones

- **Qué muestra.** Cuatro filas: Estadística, Precio, Evidencia y Controles. Cada fila lleva su estado (cumple, no cumple o pendiente) y una línea de porqué, con números calculados por código.
- **Regla.** En un pick, las cuatro condiciones se cumplen. Sin pick, se dice cuál faltó, sin nombrar el mercado.
- **Origen.** El registro de la decisión (`INT-C06`). Si no hay registro, la lista no se pinta.
- **Dónde podría ir** (lo decide UX):
  - el acordeón «Cómo lo decidimos» de K03;
  - la «Ficha del pick» de K02;
  - para el administrador, junto a la «Cadena de decisión» de P12.

### Sello de evidencia con estado

- **Qué muestra.** El estado (oficial, confirmado o reportado, además de contradicción y caducado), la fuente, la hora de publicación y el enlace. La cita breve, solo si el abogado la autoriza (`IA-044`).
- **Colores.** Verde para lo verificado y ámbar para lo reportado. El rumor no tiene sello, porque no se muestra.
- **Accesibilidad.** Siempre icono y texto, nunca solo color, como pide la regla de S4.
- **Relación con lo que existe.** Amplía la «cita de fuente con sello» de P04.

### Estado de validación del mercado

- **Qué muestra.** Uno de tres estados por par de liga y mercado: «Validado frente al mercado», «En observación» o «Solo informativo». Lleva la muestra, si la hay.
- **Hoy.** «Solo informativo».
- **Dónde podría ir:**
  - junto al sello de calibración de P03;
  - en «Por qué tiene valor» de K02;
  - explicado en Metodología (T06).

### «Después del partido»

- **Qué muestra:**
  - qué sabíamos: los hechos, con su sello y su hora;
  - qué decidimos: el veredicto y sus condiciones;
  - qué pasó;
  - cómo se movió el precio después de decidir;
  - qué fuentes acertaron.
- **Regla.** La decisión se juzga por el precio y por muestras; un resultado suelto no la califica.
- **Dónde podría ir.** En el Resumen del partido terminado (decisión 11) y en el enlace «Ver el porqué» de T02.

## 4. Láminas que hoy chocan con una regla

Son diferencias para que UX decida; aquí no se resuelve ninguna.

| Lámina | Qué dibuja | Regla que choca | Pregunta para UX |
| --- | --- | --- | --- |
| P03, P11, K02, K05, S4, T05 | La cuota del pick en dorado (`price gold`) y el «te pagan» en dorado | 3 | ¿El precio va en neutro y el dorado queda solo para el sello? |
| S4, P03, P06, P11, P12 | La mejor cuota, resaltada en verde. En S4 el verde marca la mejor cuota de cada columna; en P06, «donde PrediGol ve valor» | 3 y 4 | ¿Un mismo verde con dos significados, y en una cuota? |
| P04, bloque «Mercado» | «−0,15 desde la apertura» en rojo, y la línea del precio en verde | 3, y también la regla del propio plan de UX: el movimiento, «nunca en rojo o verde» | ¿Se ajusta al construir la lámina? |
| P06 | El borde verde de valor aparece también en un mercado sin pick («Más de 2,5 goles», a 1,98) | 1 y 2 | ¿Se quita la marca de valor de lo que no es «Recomendado»? |
| P03, P11, K02, T02 | «Casa Dos» debajo de la cuota del pick | 4 | ¿La casa sigue en la tarjeta o pasa a «Mejores cuotas»? |
| P10, «Por qué terminó así» | A favor y en contra, según el resultado | 9 | ¿Convive con «Después del partido» o lo sustituye? |
| K07, T06, P12 | Una cadena de ocho pasos: Datos, Mercado, Modelo, Calibración, Valor, Riesgo, Intelligence y Selección | Las cuatro condiciones | ¿Se agrupan los ocho pasos en las cuatro condiciones, o conviven? Ver abajo |
| S4, «Certeza de una noticia» | Confirmado; Probable (azul); Rumor y Contradictorio (ámbar); Desactualizado | 6 | Las dos escalas no coinciden; tabla de correspondencia por acordar entre UX e IA. Ver abajo |

**Correspondencia propuesta para la cadena de ocho pasos.** Hay que validarla con la línea Picks.

- Estadística = Modelo + Calibración + Valor + par validado.
- Precio = Mercado.
- Evidencia = Intelligence.
- Controles = Riesgo + Selección + aprobación del dueño.

**Las dos escalas de evidencia.**

- La del producto tiene cinco estados, los de `ai.evidence`.
- La del motor de evidencia (`evidence-engine-v1`) tiene cuatro: Oficial, Confirmado, Reportado y Rumor.

## 5. Dependencias

**Datos.**

- `INT-E01`: el contrato, de la línea Picks.
- `INT-A03` y G-COH: la cifra única. Hasta entonces, el Match Center y la decisión pueden diferir (mediana de 1,82 pp, Parte I de la investigación), así que no deben mostrarse las dos cifras.
- `INT-A06` y G-PRECIO: el precio con su edad.
- `INT-C06`: el registro de la decisión y sus cuatro condiciones.
- `INT-B06`: las afirmaciones con su estado y su procedencia.
- `INT-D02`, `INT-D04` y G-CRON: la crónica v4.
- `INT-D03`: el motivo del veredicto.
- `INT-D05` e `INT-B10`: la revisión posterior y qué fuentes acertaron.
- El registro de pares de liga y mercado con ventaja validada, para el estado de validación. Hoy está vacío.

**UX.**

- Ola 4: PR-04 (sellos), PR-12 (precio con su antigüedad y barra de probabilidad) y PR-13 (tarjeta de pick).
- Ola 6: PR-16 y PR-17 (decisión 11).
- Ola 7: PR-18 y PR-19 (decisión 3, detalle del pick).
- Ola 8: PR-21 y PR-22 (decisión 4, estado de los precios).
- Ola 12: PR-34 (decisión 10, Metodología).
- La consola, para `INT-E03`.

**Legal.** `IA-044`: la cita literal dentro del sello espera la respuesta del abogado.

**Activación.** `INT-E04` se activa por partes y con la decisión del dueño. `FBI_PICKS_SOURCE` sigue apagado.

## 6. Preguntas abiertas para la sesión de UX

No se decide nada por ella.

1. ¿El sello de evidencia reutiliza «Certeza de una noticia» (S4) o es una variante suya? ¿Qué tabla de correspondencia une las dos escalas? Se acuerda entre UX e IA.
2. ¿K07, T06 y P12 hablan de ocho pasos o de cuatro condiciones?
3. ¿Dónde vive el estado de validación? ¿Cómo se distingue «En observación», que es de un par de liga y mercado y dura semanas, de «en vigilancia», que es de un candidato y dura minutos?
4. Si no hay riesgos verificados, ¿se oculta la sección o se dice «Sin riesgos verificados»?
5. ¿La regla de no mostrar rumores en Intelligence se extiende a Noticias? Hoy la API de noticias los muestra al final, con su estado (`api/services/news.py`), y la lámina N02 («Rumores y polémicas») los pinta con su certeza. Esto lo decide el dueño.
6. Si el dueño no aprueba K02 (decisión 3), ¿la lista de condiciones vive solo en K03?
7. ¿Una sola hora de datos para todo el contrato, o una hora por bloque?
8. ¿Dónde van las piezas nuevas en tableta y en escritorio (P11, T07)?
9. Las diferencias de la sección 4, ¿se corrigen en las láminas o se anotan en cada PR, como prevé el plan de UX para toda diferencia con su lámina?
10. Nota de origen: el criterio del dueño del 5-nov hablaba de «verde Recomendado», pero el sistema vigente lo pinta en dorado (#EEB747, ya en el código). Este mapa sigue el sistema.

## 7. Método y límites

- Todo fue de solo lectura: lienzo, documentos y código. No se cambió ninguna pantalla, ni el código, ni el lienzo. Las láminas usan datos de ejemplo.
- No se leyeron las pestañas «Sistema de diseño» y «Pantallas» del documento de diseño. Los nombres de los componentes salen de las láminas S4 y S5 y del plan de UX.
- El plan da por dibujados en P03 los estados «Sin pick», «Sin cuotas» y «Sin calibrar». En P03 y P11 solo encontré el caso con pick y el sello «Calibrado». El producto ya tiene los textos «Sin calibrar» y «sin rango medido».
- Las correspondencias de la sección 4 son propuestas para discutir. El gate de esta pieza es el acuerdo de UX.

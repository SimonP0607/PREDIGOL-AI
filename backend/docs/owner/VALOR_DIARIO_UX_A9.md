# A9 · Valor diario: Inicio y centro de partido

Plan Maestro UX, fase A9. **Sin migración y sin servicios externos; no llama a la IA.** Solo lee lo que PrediGol ya
calcula: pronósticos (`models.match_forecasts`), calendario, conocimiento postpartido y los paquetes del partido que
guarda PrediGol Intelligence (`ai.match_packets`). Ninguna regla de picks, probabilidad, calibración, liquidación ni
estado interno cambia: la capa de usuario consume la inteligencia, no la altera (lo vigilan las pruebas de aislamiento).

## 1. Qué cambia para el cliente

**Inicio, en el orden de la sección 24, útil haya o no picks:**

1. **Hoy en las ligas sugeridas.** Mientras el cliente no elige sus ligas (A13), las que más se siguen en Colombia:
   Liga BetPlay, la Selección, Libertadores, Champions y las cinco grandes de Europa, nombradas arriba y con el rótulo
   «Sugerida» en cada partido (con su porqué al tocarlo). En vivo primero, la hora en la zona del cliente, el pronóstico
   de PrediGol con «sin calibrar» cuando es el número del propio modelo, y una línea de la lectura. Sin partidos hoy, lo
   dice y muestra los próximos. Aún no hay botón «Elige tus ligas»: llega con A13 (nada ofrece lo que no existe).
2. **Picks del día.** Los publicados con su estado real. Un día sin picks dice, palabra por palabra: «Hoy ningún partido
   cumplió las condiciones para publicar un pick. Preferimos no publicar a publicar por publicar», y debajo el **motivo**
   (por ejemplo «Ningún mercado mostró ventaja frente al precio del mercado»). Si el set del día aún no existe: «Todavía
   estamos revisando los partidos de hoy», sin prometer hora. Lo mismo en la página Picks. Nunca se rellena con picks de
   evaluación ni con la palabra «valor».
3. **Parlays de PrediGol.** Si ninguno está armado, una sola línea honesta y el enlace a Parlays (allí cada uno explica
   por qué no hay: nada pasa todas las reglas, nada crece en conjunto, o el día terminó sin uno).
4. **Partidos relevantes:** de 3 a 5 partidos de hoy de otras competiciones que seguimos, con análisis (si no hay, el
   bloque no aparece).
5. **Qué se juega:** en los próximos partidos de las ligas sugeridas, la tabla o la eliminatoria, el descanso y el
   próximo partido, cada línea con su referencia (si no hay, no aparece).
6. **Resultados:** las últimas 48 horas de las ligas sugeridas, cada uno a su Postpartido.

Después siguen «En vivo ahora» y «Mejores cuotas», como antes. La lista «Próximos partidos» sale de Inicio (sigue en
Partidos). Cada bloque carga, falla con su referencia y «Reintentar», y dice a qué hora se actualizó, por separado.

**Centro de partido en secciones:** Resumen, **Análisis**, Estadísticas, Mercados, Alineaciones y, terminado el
partido, **Postpartido**. Abre según el estado (en vivo: Estadísticas; terminado: Postpartido) y un enlace puede nombrar
la sección en español o inglés (`?s=analisis`, `?s=stats`); el antiguo `#picks` abre el Resumen, donde ahora viven los
picks del partido. Las pestañas responden a las flechas, Inicio y Fin.

- **Resumen:** el resumen de la lectura y sus dos riesgos principales (con «Ver el análisis completo»), el pronóstico
  rotulado y los picks publicados del partido con su estado.
- **Análisis PrediGol (lectura estructurada):** seis apartados — resumen, contexto, datos, mercado, riesgos y
  conclusión — escritos con plantillas en español e inglés a partir de hechos que el servidor ya tiene; cada hecho lleva
  su referencia y el bloque dice la hora de sus datos. Sin paquete del partido, una lectura más corta que lo dice. Los
  riesgos nunca están vacíos. La conclusión es lo más probable de cada mercado con su rótulo y la advertencia: «Es una
  probabilidad, no una recomendación: un pick de PrediGol es otra cosa, y se publica aparte».
- **Postpartido:** resultado, el pronóstico frente a lo que pasó (o que no había), la base del postpartido (capas
  c1–c6) y cómo terminaron los picks; lo guardado por el cliente, en Mis picks.

**Lo que nunca sale de la API al cliente:** probabilidades propias de los modelos, ventajas, Elo, nombre del modelo,
cuotas o casas en la lectura, ni el texto, la fuente o el enlace de una noticia o un rumor (solo cuántos hay, por
estado). Ninguna plantilla dice «seguro», «fijo», «garantizado» ni «valor» (probado), y «margen» sigue siendo solo el de
las casas.

**Armador de parlays:** cada motivo de «no hay parlay» abre las palabras del glosario que lo explican, y la ventana sin
selecciones lo dice como Inicio. El enlace a «Cómo le va a PrediGol» llega con su página (A12).

## 2. Interruptores (todos encendidos por defecto desde A9)

| Variable | Qué muestra | Apagar |
| --- | --- | --- |
| `FBI_FORECAST_USERS` | El pronóstico de PrediGol (rotulado) | `=0` |
| `FBI_CALENDAR_USERS` | Descanso y partidos cercanos | `=0` |
| `FBI_KNOWLEDGE_USERS` | La base del postpartido (c1–c6) | `=0` |
| `FBI_READING_USERS` | La lectura estructurada (Análisis, el resumen del Resumen, la línea y el contexto de Inicio) | `=0` |

La línea ausente es **encendido** (lo aprobaste con el plan). `=0` lo oculta otra vez **sin desplegar**: una línea en
`/etc/predigol/app.env` (fichero de seguridad: copia fechada, candado de despliegue, ventana propia) y se recrea la API.
Un valor que no se entiende cuenta como apagado. Con uno apagado, el cliente no ve un hueco: el bloque desaparece o dice
que no está disponible. Tu vista previa de la consola no depende de ellos.

## 3. El motivo de un día sin picks: de dónde sale

Del **embudo del propio set publicado** (`fbi.picks.funnel`, el mismo que ves en la consola, solo con la fuente
`qualified`): la etapa más avanzada que alcanzaron las selecciones del día y su motivo más común. El plan nombraba
`intel.decisions`; esa tabla es la capa de decisiones de PrediGol Intelligence, **en sombra**, no la regla que publica:
un motivo sacado de ahí describiría otro proceso. Es una desviación deliberada y la dejo escrita aquí. Nunca se leen ni
se cuentan picks de evaluación. Se calcula como mucho cada 5 minutos para todos (el tablero de Inicio, cada minuto).

Motivos posibles, en palabras del cliente: sin partidos, ningún modelo habilitado con selecciones, problemas de datos o
de precios del mercado, modelos que no han superado al mercado, sin rango de probabilidad medido, sin ventaja frente al
mercado, cuotas por encima del límite de riesgo y la revisión de contexto de PrediGol Intelligence sin terminar a tiempo.
Una prueba obliga a que cada motivo que puede enviar la API tenga su frase en español e inglés.

## 4. Despliegue y vuelta atrás

- **Copia previa al despliegue** (sin migración): la de siempre, con su prueba de restauración.
- **Vuelta atrás sin desplegar:** cualquiera de los cuatro interruptores a `=0` devuelve `not_available` en su bloque.
- **Vuelta atrás completa:** la imagen anterior (no hay datos nuevos que deshacer).
- **Coste:** 0. Ninguna visita llama a la IA; los tableros se guardan en caché compartida (Inicio 1 minuto, el motivo 5).

## 5. Acción manual

Ninguna. Para ver un día sin picks real, basta abrir Inicio el próximo día sin picks: el bloque 2 dirá el motivo.

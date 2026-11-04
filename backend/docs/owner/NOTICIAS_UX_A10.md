# A10 · Noticias verificadas con fuente

Plan Maestro UX, fase A10. **Sin migración, sin servicios externos y sin IA.** Solo lee lo que PrediGol Intelligence ya
investigó y verificó (`ai.evidence`): ninguna visita hace una búsqueda, llama a un modelo ni gasta nada nuevo, y ningún estado
cambia. El estado de cada noticia es el que decidió el servidor (`fbi.ai.evidence`), que ni se importa ni se toca: la capa de
usuario consume la inteligencia, no la altera (lo vigilan las pruebas de aislamiento).

## 1. Qué ve el cliente

**Centro de partido, sección Noticias** (entre Alineaciones y Postpartido; un enlace puede nombrarla: `?s=noticias` o
`?s=news`). Cada tarjeta tiene los siete elementos de la sección 27:

| Elemento | Qué muestra |
| --- | --- |
| Titular | El tipo y su protagonista: «Baja por lesión · QA Jugador Uno (QA Bahía)»; una contradicción, por su tema («Sanción · …»), sin tomar partido |
| Fuente | El medio y su nivel en palabras: «sport.es · medio de comunicación», «fuente sin clasificar», «agregador»… |
| Hora | Relativa y en la zona del cliente («Publicada hace 3 h»); si la fuente solo dio el día, el día («Publicada el sáb, 24 oct», nunca la noche anterior en América); si no dio fecha, cuándo la vio PrediGol |
| Resumen propio | La frase que escribió el extractor de PrediGol, en español; **nunca** el texto, el titular ni las fotos del medio |
| Relevancia | Alta, media o baja, con su explicación al tocarla (apartado 3) |
| Estado | Confirmado, Probable, Contradictorio, Rumor o Desactualizado, **en texto** (el color solo acompaña) y con su explicación al tocarlo |
| Enlace | «Leer en la fuente», en una pestaña nueva y con `rel="noopener noreferrer"` |

- **Orden:** confirmadas y probables primero (las más relevantes y luego las más recientes), después las contradicciones (una
  tarjeta con cada afirmación y su fuente), los rumores (al final, rotulados y con la advertencia «no las tomes como un hecho»)
  y las desactualizadas. Cuando hay algo verificado encima, rumores y desactualizadas quedan plegados bajo un toque
  («Rumores 7»); si es todo lo que hay, se ven abiertos.
- **Sin cobertura**, la frase exacta: «No encontramos noticias verificadas relevantes para este partido.»
- **Alineaciones:** «Bajas en la prensa» — lo que dicen los medios sobre quién no juega o está en duda (confirmado, probable o
  contradicho; **nunca un rumor**), con su estado y su fuente, y «Ver en Noticias». El bloque de bajas del proveedor ahora dice
  su fuente: «Fuente: parte de bajas de nuestro proveedor de datos, actualizado hace 2 h».
- **Inicio, bloque 4 «Noticias»** (entre «Partidos relevantes» y «Qué se juega»): hasta cuatro noticias **confirmadas o
  probables** de los partidos de hoy de las ligas sugeridas (en vivo o que empiezan hoy en la zona del cliente), cada una con su
  partido y el camino a sus Noticias. Si no hay, el bloque no aparece: nunca se rellena con noticias genéricas.
- **En inglés,** los resúmenes siguen en español y se rotulan «(in Spanish)» hasta que A11 los traduzca.

## 2. Lo que nunca sale de la API

- **El texto, el titular o las fotos de un artículo.** La caché de investigación (`ai.research_cache`) no se lee; el título
  guardado con cada evidencia solo sirve para comprobar que el resumen no lo repite (si lo repite, no se envía). Lo prueba una
  prueba de integración con un artículo y su título sembrados.
- **Noticias de otro partido,** aunque sea de los mismos equipos, o genéricas para rellenar: solo `fixture_id` = el partido.
- **Las notas del dueño** (`origin = owner`) y **los partes del proveedor** (`origin = provider`): el parte de bajas y la
  alineación confirmada son datos del partido, y se muestran en Alineaciones con su fuente.
- **Un resumen que no se lee como español.** El extractor tiene la orden de escribir en español, pero de vez en cuando contesta
  en el idioma de la fuente (en producción hay resúmenes en turco). La tarjeta se queda con su tipo, jugador, equipo, fuentes y
  estado, y PrediGol escribe la frase: «QA Bahía tendrá bajas, según qa-haber.example.»
- Un enlace que no sea una dirección web normal (`http`/`https`).

## 3. Decisiones que tomé (desviaciones deliberadas, escritas)

- **Relevancia.** El número guardado (`ai.evidence.relevance`) vale 0,600 en **todas** las evidencias de la web (2.380 de 2.380
  en la línea base): no distingue nada, y mostrarlo diría «media» siempre. La relevancia del cliente sale de qué dice la
  noticia: **alta**, quién juega o no (una baja, una duda, un regreso o una alineación, de un jugador nombrado o del once);
  **media**, lo mismo sin nombrar a nadie, o el entrenador; **baja**, el resto del contexto. La explicación está en la tarjeta.
- **Los partes del proveedor van a Alineaciones, no a Noticias** (apartado 2).
- **Rumores plegados** cuando hay algo verificado: el plan pide «al final y rotulados»; plegarlos evita que un partido con 30
  rumores entierre lo confirmado en el móvil.

## 4. Línea base de producción (26-oct, 02:38 UTC, solo lectura)

- `ai.evidence`: 7.436 filas del proveedor y 2.380 de la web; ninguna sin partido.
- Web por estado: confirmadas 121, probables 371, contradictorias 10, **rumores 1.842**, desactualizadas 36. Por nivel de la
  fuente: sin clasificar 1.512, agregadores 428, medios 367, competición 37, club 36.
- Entre 15 y 30 partidos al día con evidencias de la web (últimos diez días); 0 resúmenes repiten el título de su resultado.
- Qué significa: la mayoría de las tarjetas serán rumores (al final, plegados); en Inicio solo salen confirmadas y probables, y
  la investigación de la web llega cerca del partido, así que el bloque 4 aparecerá sobre todo el mismo día.

## 5. Interruptor

`FBI_NEWS_USERS`: **encendido** con la línea ausente (aprobado con el plan). `=0` lo apaga **sin desplegar**: una línea en
`/etc/predigol/app.env` (fichero de seguridad: copia fechada, candado de despliegue, ventana propia) y se recrea la API.
Apagado, Noticias dice «Las noticias no están disponibles en este momento», Inicio no muestra el bloque y Alineaciones no
muestra la prensa. Un valor que no se entiende cuenta como apagado.

## 6. Coste y rendimiento

**0.** Sin IA y sin búsquedas. Una consulta por partido con su índice (`ai_evidence_fixture`), como mucho 400 filas; el bloque
de Inicio se guarda dos minutos en la caché compartida (igual para todos).

## 7. Eventos

`news_opened` (al abrir las Noticias de un partido, una vez por partido y visita) y `news_link_clicked` (al tocar «Leer en la
fuente»), del catálogo de A6: sin texto, sin direcciones y solo si el lector aceptó la medición.

## 8. Despliegue y vuelta atrás

- Sin migración. Copia previa al despliegue con su prueba de restauración.
- Vuelta atrás sin desplegar: `FBI_NEWS_USERS=0`. Completa: la imagen anterior (no hay datos nuevos que deshacer).

## 9. Recomendación para el plan de Intelligence (no la ejecuto)

`ai.research_cache` guarda los resultados de las búsquedas (680 filas, 2,5 MB, todas caducadas) y las direcciones ya leídas
(3.324 filas, 1.953 caducadas) desde el 8-oct, **sin purga programada** (la purga existe). Recomendación: programarla a 30 días.
Es una tabla de PrediGol Intelligence y A10 ni la lee ni la toca: la decisión es tuya, para ese plan.

## 10. Acción manual

Ninguna.

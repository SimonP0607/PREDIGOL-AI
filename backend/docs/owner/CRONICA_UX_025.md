# UX-025 · La crónica de cada partido (IA, validada y con presupuesto propio)

Sustituye en lo visible a la «narrativa» de A11 (`NARRATIVA_UX_A11.md`): misma tubería, mismo presupuesto aparte, mismos controles de
fondo; cambia **qué se cuenta y cómo se lee**. **Nace apagada y sin gastar nada.** Hoy, con el interruptor ausente, los lectores ven la
lectura estructurada de siempre.

La capa de usuario consume la inteligencia y no la altera: la crónica no cambia modelos, probabilidades, calibraciones, umbrales,
decisiones, picks, liquidación, gates ni histórico. No ve el pronóstico, las cuotas ni un pick, y nada de Intelligence la lee.

## 1. Qué ve el cliente

En **Centro de partido → Análisis**, cuando hay una crónica validada para la historia del partido:

- **Una entrada** (qué partido es y qué se juega cada equipo), **un párrafo seguido por equipo** bajo su nombre (cómo llega: últimos
  resultados con marcador y rival, rachas, goles, quién es baja o duda y por qué, qué se juega, su goleador, su récord en casa o fuera,
  lo que dicen las noticias verificadas), el **historial directo** (últimos cruces con marcador), **«Qué puede salir mal»** y, debajo,
  **«Fuentes»** con los medios de las noticias que cuenta.
- Rótulos: «Redactado con IA y validado contra los datos de PrediGol» y «Escrito con datos de las 12:30». En inglés, los mismos.
- **Sin pliegues**: se lee como un texto, de arriba abajo, también a 320 px.
- **El pronóstico, el mercado y los picks no están en la crónica.** Debajo siguen «Mercado» y «Conclusión de PrediGol», escritos con las
  plantillas de siempre (con su advertencia: «Es una probabilidad, no una recomendación»). «Por qué hay valor» sigue en el Resumen y solo
  existe cuando PrediGol publicó un pick.
- **Sin crónica** (apagada, rechazada por los controles, sin historia suficiente o con datos que cambiaron): la lectura estructurada,
  igual que hoy. Nunca un texto que el servidor no validó.

La misma crónica alimenta el contexto y los riesgos de «¿Por qué PrediGol eligió este pick?».

## 2. De dónde sale cada frase

Cada frase cita los hechos de los que sale (`P:…` un hecho del partido, `E:<id>` una noticia) y el servidor comprueba que cite solo lo que
se le dio y que **cada cifra** (marcadores, goles, minutos, meses) esté en lo que cita. Los nombres y las palabras los sostiene el prompt (la IA
solo recibe estos hechos y no puede añadir otros) y la revisión de la muestra antes de encender. La IA recibe solo:

- de la lectura estructurada, los hechos que **solo cambian cuando pasa algo**: qué se juega cada equipo, su forma (con victorias,
  empates y derrotas ya contadas), su racha, su goleador, su récord en casa o fuera, el cara a cara;
- los **últimos cinco resultados** de cada equipo (marcador a los 90 minutos, rival, local o visitante, competición), tal como estaban
  asentados en el momento de los datos;
- las **bajas y dudas con nombre**, con el motivo del proveedor (limpiado: solo letras) y si es titular habitual;
- los **últimos cruces** entre los dos con marcador;
- las **noticias de la web** verificadas del partido (su estado, su medio y su texto, que se trata siempre como dato y nunca como
  instrucción).

**Nunca**: probabilidades propias de los modelos, pronóstico, Elo, cuotas, casas, un pick, ni nada de un cliente. El prompt le prohíbe
inventar declaraciones, citas o curiosidades: solo puede contar lo que una noticia verificada diga.

## 3. Cuánto escribe

El largo lo marcan los datos, no el nombre de la liga. Tope de frases por apartado, calculado en el servidor: la entrada 2, el historial
2, los riesgos 3 y cada equipo de 2 (solo resultados) a 5 (con baja nombrada, racha, lo que se juega, goleador y una noticia
verificada). Un apartado sin nada que contar **no existe** (no se rellena). Un partido al que le faltan los últimos resultados de un
equipo (menos de dos) **no tiene crónica**: el lector se queda con la lectura estructurada. Por eso las crónicas largas salen sobre todo
en las ligas grandes, que son las que traen bajas con nombre y noticias.

## 4. Qué se comprueba antes de enseñar una frase

Todo lo de A11 (referencias, cifras exactas también las pequeñas y las escritas con letra, ninguna certeza ni palabra de apuesta, el
cara a cara y los escenarios no son causas, un rumor solo en riesgos y llamado rumor, una noticia probable se atribuye, ES = EN frase por
frase), más lo propio de la crónica:

- un resultado y un cruce se citan por su propia referencia (nunca por el bloque entero), y sus cifras son las únicas que esa frase puede
  usar; un cruce se cuenta «hace N meses», sin fechas;
- un jugador en duda se cuenta como duda, y una causa que el proveedor no dio no se inventa (una sanción no es una lesión);
- ningún apartado que la historia no tenga, ninguno más largo que su tope, ninguno vacío;
- las palabras de apuesta y de certeza («valor», «pick», «seguro», «garantizado»…) están prohibidas, y la IA no recibe pronóstico,
  probabilidades ni cuotas que pudiera repetir.

**Una frase mal y la crónica no se enseña**: se pide una vez más diciendo qué falló; si vuelve a fallar, el lector ve la lectura
estructurada y el rechazo queda registrado con sus motivos (`ai.user_narratives.status = rejected`). Lo que ya tuvo respuesta no se paga
dos veces.

## 5. A qué partidos, en qué orden y cuándo se reescribe

- Partidos que PrediGol Intelligence ya analizó (cualquiera de sus pasadas: primera, previa o final), que empiezan en las próximas 26 h o
  empezaron hace menos de 2 h. **Ninguna visita llama a la IA.**
- Cada 10 minutos, como mucho 8 llamadas, en este orden: partidos con un pick que el lector puede ver, luego primera categoría (las cinco
  grandes ligas y la Champions), luego los que más tienen que contar (bajas con nombre, noticias verificadas), luego el saque más cercano.
  Cuando se acaba el dinero del día, el resto espera a mañana.
- La crónica va atada a la **historia** del partido (`reading_hash` = hash de los hechos de arriba), **no al paquete**: los datos se
  reconstruyen cada 10 o 20 minutos (mercado, pronóstico, alineaciones) y eso no la esconde. Una baja nueva, un resultado nuevo o una
  noticia nueva sí cambian la historia: el lector vuelve a los hechos hasta que se escribe otra (como mucho, una cada 2 horas y 3 por partido
  y día).

## 6. Dinero

- Presupuesto **aprobado por el dueño: 20 US$ al mes** (`FBI_AI_USER_MONTHLY_BUDGET_USD=20`), aparte del de Intelligence, que no toca (una
  prueba de integración demuestra que el estado del presupuesto de Intelligence es idéntico con y sin gasto de lectores).
- Ritmo: el mes entre los días que quedan por día (≈0,67 US$) y un tope de 1,5 veces (≈1 US$ al día); avisos `ai_user_budget` al 50, 70, 85, 95
  y 100 % del mes, una vez cada uno. Con el presupuesto en 0 no gasta nada.
- Modelo: Haiku 5.5, el económico (0,10 / 0,50 US$ por millón de tokens de entrada / salida con prompts de menos de 100.000 tokens, según la
  tabla de precios del repositorio y las fuentes públicas del lanzamiento). En las pruebas, una llamada de 6.000 tokens de entrada y 2.500 de
  salida cuesta 0,00185 US$ (**estimación**, no una medida de producción): lo esperado queda muy por debajo del tope. El gasto real se lee en
  la consola de IA → Costes → «IA de lectores» en cuanto esté en `shadow`.

## 7. Cómo encenderla (tareas del servidor, solo con tu OK)

1. En `/etc/predigol/app.env` (copia fechada, candado de despliegue, ventana propia): `FBI_AI_USER_MONTHLY_BUDGET_USD=20` y
   `FBI_USER_NARRATIVE=shadow`; recrear worker y API.
2. Dejar correr y revisar unas **50 crónicas** en la vista previa de la consola (los lectores aún no ven nada): cada cifra debe estar en
   su referencia; que no haya certezas, valor ni declaraciones inventadas.
3. Si te gustan: `FBI_USER_NARRATIVE=on`. Apagarla: `FBI_USER_NARRATIVE=0` (sin desplegar; la web vuelve a la lectura estructurada).

## 8. Lo que tienes que saber

- **Hoy no hay picks recomendados** (todos están en sombra): la parte «por qué hay valor» no aparecerá hasta que haya un pick que un lector
  pueda ver; la crónica en sí funciona para todos los partidos con datos.
- **Largas solo donde hay datos.** Un partido con solo resultados tiene una crónica corta; sin resultados, ninguna. No se rellena con
  inventos.
- **Declaraciones y curiosidades**: solo las que una noticia verificada traiga (el servidor no puede comprobar una cita palabra por palabra:
  lo vigila el prompt y la muestra de 50). Hoy son escasas, así que serán la excepción.
- Con el modelo económico la prosa es sobria y correcta, no brillante: los controles garantizan que no inventa, no que escriba bien. La
  muestra de 50 sirve para decidir si basta o si conviene un modelo mejor (cambia el presupuesto: te lo diría antes).

## 9. Aislamiento y vuelta atrás

- Versión del prompt `user-narrative-v2`; la API solo enseña esa versión y solo cuando el hash de la historia coincide.
- El trabajo `user_narrative` del worker escribe únicamente `ai.user_narratives`, `ai.evidence_translations` y `ai.user_usage` (una prueba
  de integración vigila qué tablas escribe una pasada); la API no tiene claves de IA; una prueba estática impide que cualquier módulo de
  Intelligence nombre esas tablas.
- **Sin migración nueva** (usa las de A11, la 0100). Se despliega apagada y con presupuesto 0. La vuelta atrás es el interruptor; la
  completa, la imagen anterior (que no conoce la v2 y no la muestra).

## 10. Pruebas

- Unitarias: `tests/unit/test_story.py` (la historia, sus topes y su hash) y `tests/unit/test_user_narrative.py` (el validador, el glosario,
  la prioridad, el presupuesto), más `test_user_layer_isolation.py`.
- Integración, `tests/integration/test_user_narrative.py` (12) contra una base real: se guarda con sus traducciones y su coste, se enseña
  mientras la historia es la misma (aunque cambien mercado y alineaciones) y se esconde con una baja o un resultado nuevo; partido sin
  resultados de los dos lados, sin llamada; cualquier pasada de Intelligence sirve; el orden de los partidos y el límite por pasada; el
  rechazo con motivos y sin pagar dos veces; fallo del proveedor reintentado; sin presupuesto no gasta; el presupuesto de Intelligence
  idéntico; una pasada solo escribe las tablas de lectores.
- Web: `ReadingBlock.test.tsx`, `explanation.test.tsx`; e2e `user.spec.ts` y `responsive.spec.ts` (contra staging).

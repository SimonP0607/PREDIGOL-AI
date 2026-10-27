# B4 · Postpartido: el partido terminado explica lo guardado y cada pick

Plan Maestro UX, fase B4 (sección 31; mantiene en verde G9). **Un partido terminado explica el resultado, la liquidación, el cierre
del mercado y el pronóstico frente al resultado.** La capa de usuario lee lo que PrediGol Intelligence ya guardó: la liquidación, el
análisis posterior de cada pick (el post-mortem) y el pronóstico; no calcula ni decide nada. Coste: 0. Sin migración.

## 1. Qué ve el cliente

Cuando el partido termina, la página del partido abre en **Postpartido** (así era ya desde A9), y ahora dice:

- **El resultado** (como hasta ahora).
- **«Lo que guardaste»:** cada selección que el cliente guardó en ese partido, con su resultado (Ganado, Perdido, Devuelto,
  Anulado, Medio ganado, Medio perdido), la cuota (la suya, si la puso: «a tu cuota de 2,00») y sus unidades; si aún no se
  liquidó, «Se liquida en cuanto el resultado sea oficial.»; si se volvió a liquidar porque el proveedor corrigió el resultado, lo
  dice. Si no guardó nada en ese partido, el bloque no aparece.
- **«Por qué terminó así», debajo de cada pick que PrediGol publicó** (en su tarjeta, con la cuota y la hora a la que se tomó):
  - cómo terminó («Ganó.», «Perdió. Una selección así falla aproximadamente 5 de cada 10 veces.», «Se devolvió: el resultado cayó
    exactamente en la línea.»…);
  - la probabilidad que PrediGol le daba y la del mercado, sin su margen, **al cierre**;
  - **los hechos del partido que lo explican**, cada uno marcado **«A favor»** o **«En contra»** de la selección: «Expulsión en
    Santa Fe, en el minuto 58.», «Penalti convertido por Santa Fe, en el minuto 77.», «Gol de Millonarios en el minuto 9: el
    partido cambió pronto.», «Las ocasiones no respaldaban esta selección: goles esperados Millonarios 0,71 – 1,90 Santa Fe.», «9
    tarjetas, muy por encima de las 4,1 que este árbitro saca de media.», «2 cambios antes del minuto 30 (posible lesión).»;
  - o, si no hubo nada fuera de lo normal, «No pasó nada fuera de lo normal en el partido que lo explique.»; o, si el análisis aún
    no está, «El análisis del partido todavía no está: se escribe la noche siguiente.».
- **El pronóstico frente al resultado en tres mercados** (antes solo el resultado): el resultado (1X2), los goles a 2,5 y ambos
  marcan, cada uno con su nombre, lo que PrediGol veía más probable, cómo terminó y si coincidió.
- **«Después del inicio»:** las noticias publicadas una vez empezado el partido (con su hora exacta; una noticia fechada solo por
  su día se queda en Noticias, porque podría ser de antes del pitido).
- **Los caminos hasta aquí:** la lectura del partido (Análisis y el resumen del Resumen) termina, si el partido acabó, con «Qué pasó
  en el partido: ver el Postpartido»; y en **Mis picks**, una selección ya liquidada abre su partido directamente en el Postpartido
  (`/matches/{id}#postmatch`: **el mismo enlace que usará el aviso de resultado** cuando exista, U23, que no está construido).

## 2. Lo que nunca llega al cliente

- **Lo que el post-mortem JUZGA:** su veredicto (MERECIDO, VARIANZA, SUERTE, ERROR…), la clase de una pérdida (error del modelo,
  de mercado, varianza normal…), la calidad de la decisión, el precio frente al cierre (CLV), lo que decidió la revisión de la IA y
  sus frases. La consulta **ni siquiera los selecciona**, y una prueba recorre el código y falla si alguien lo intenta.
- **Las frases del post-mortem:** están escritas para ti, en su español; el cliente recibe solo el código y las cifras de cada
  hecho, y la web los dice con sus propias plantillas, en español o en inglés.
- **Un análisis que no corresponde a la liquidación:** si el resultado se corrigió después de escribirse el post-mortem, ese
  post-mortem no se usa y el pick espera al nuevo (dice que el análisis aún no está).
- **PrediGol Intelligence no cambia:** ni modelos, ni probabilidades, ni umbrales, ni reglas, ni liquidación, ni post-mortems
  (solo se leen). La vista de «conocimiento» del partido (A9) no cambia y su prueba sigue vetando veredictos, post-mortems y
  beneficios.

## 3. Lo nuevo por dentro

- **`GET /api/v1/matches/{id}/postmatch`** (detrás de las mismas puertas que el resto del producto): lo guardado por **ese**
  cliente en el partido (los mismos registros de Mis picks, ahora leídos también por partido) y los picks publicados del partido
  con su liquidación, la probabilidad de cierre del mercado y los hechos del post-mortem (pm-v6, el más reciente de cada
  selección). La parte de los picks es igual para todos y se guarda un minuto en caché.
- **Interruptor:** el mismo del conocimiento del partido, `FBI_KNOWLEDGE_USERS` (`=0` lo oculta todo, sin desplegar). Tu vista
  previa lo ve siempre y añade los picks en sombra (rotulados «Modo evaluación»).
- **El post-mortem tiene un lector nuevo, declarado:** la prueba de aislamiento del post-mortem (que impide que lo aprendido de
  un partido entre en lo que se dice antes de otro) lo admite por escrito, con lo único que puede leer, y su ruta es la única con
  la etiqueta `postmatch`.

## 4. Línea base

- **En producción hoy no hay ningún pick publicado** (la selección del día está vacía; última medición, 26-oct): el «Por qué
  terminó así» de los picks de PrediGol no tendrá contenido hasta que haya picks publicados y su post-mortem (se escribe a las
  07:50 UTC de la noche siguiente). **Lo guardado por los clientes sí:** cualquier selección guardada de un partido terminado ya se
  explica con su liquidación.
- Hoy, sin B4: el Postpartido muestra el resultado, el pronóstico solo del 1X2, el conocimiento del partido y las tarjetas de los
  picks tomados, y manda a Mis picks para ver lo guardado; nada explica por qué un pick ganó o perdió.
- **En QA** se ve todo con un partido terminado de ejemplo (`seed_b4.py`, base `fbi_qa_b4p`: «QA Bambú 2-1 QA Cedro», tres picks
  publicados liquidados —uno ganado y otro perdido con su post-mortem, otro sin análisis aún—, el pronóstico previo y una noticia
  posterior al inicio). La base de QA de siempre no tiene picks: no se fabrican.

## 5. Decisiones que tomé

1. **El porqué va debajo de cada tarjeta, no en una lista aparte:** cada pick aparece una sola vez, con su precio, su hora, su
   resultado y su porqué juntos.
2. **Solo hechos, nunca un juicio:** «a favor» o «en contra» dice de qué lado jugó un hecho (una roja al rival juega a favor), no
   si la decisión fue buena. La clase de la pérdida y el veredicto se quedan en tu Consola.
3. **Una pérdida dice cuántas veces falla una selección así**, con la misma regla de «Aun así, esta selección falla
   aproximadamente {n} de cada 10 veces» que ya se ve antes del partido.
4. **La probabilidad del mercado al cierre** se muestra (es un hecho del mercado, como el bloque de mercado del conocimiento); el
   CLV, no.
5. **El aviso de resultado no existe todavía** (U23): B4 deja fijado su destino (`#postmatch`) y lo usa ya desde Mis picks.
6. **Las noticias «después del inicio» exigen hora exacta:** una fecha de solo día podría ser de antes del partido.

## 6. Pruebas

- **Backend (unitarias):** los hechos que puede recibir un cliente (solo los códigos que escribe el post-mortem, nunca su frase,
  lo que no puede llevar se descarta y no se adivina, el más revelador primero), cuándo un pick se explica (solo con un
  post-mortem de su propia liquidación), que el contrato no tiene campo para nada de lo que el post-mortem juzga, y la prueba de
  aislamiento que recorre la consulta.
- **Backend (integración, base real):** un partido terminado con picks ganado, perdido, corregido después de su post-mortem, sin
  analizar y sin liquidar; dos clientes, cada uno con lo suyo y los mismos picks; tu vista previa con el pick en sombra (y 403 para
  un cliente); un partido sin nada y otro sin terminar; el interruptor; y que ninguna clave ni palabra de lo que juzga el
  post-mortem llega a la respuesta.
- **Web (unitarias):** los tres mercados frente al marcador (con la línea exacta que devuelve), las frases de cada resultado y de
  cada hecho en español e inglés, lo que no se dice sin cifras, la línea de lo guardado, las noticias después del pitido y el
  camino de la lectura al Postpartido.
- **e2e (`postmatch.spec.ts`, proyecto `postmatch`, con `seed_b4.py`):** el partido abre en Postpartido; lo guardado con su
  liquidación; el porqué bajo cada pick, sin ninguna palabra de lo que juzga el post-mortem; el pronóstico en tres mercados; las
  noticias posteriores; la lectura y Mis picks llevando al Postpartido; axe (WCAG 2.2 A y AA) sobre la pestaña; y a 320 px los
  bloques en orden sin nada de lado.

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
- **Antes, sobre la rama de la fase:** `postmatch.spec.ts` 8 de 8; la puerta del backend halló dos pruebas de aislamiento que no
  conocían el Postpartido (su router y su lectura del conocimiento), corregidas en `d6b91c8d` con su razón.
- **El paquete que se despliega es `ux-b5`** (A3 a A16 y B1 a B5, sobre `ia-p02` de la IA, que llegó antes): sus puertas y su
  e2e completo se repiten sobre ese árbol final antes de desplegar (`MIS_PICKS_UX_B5.md` y `ESTADO_EJECUCION_UX.md`).

## 8. Despliegue

Backend y web juntos (el contrato cruza los dos), sin migración. Va en el paquete `ux-b5` con todo lo terminado después de A2
(A3 a A16 y B1 a B5), sobre `ia-p02`; el resultado del despliegue queda en `ESTADO_EJECUCION_UX.md`.
**Vuelta atrás:** `FBI_KNOWLEDGE_USERS=0` (oculta el Postpartido del cliente, sin desplegar) o las publicaciones anteriores.

## 9. Acción manual

Ninguna.

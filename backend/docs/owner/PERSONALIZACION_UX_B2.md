# B2 · Personalización: su fútbol primero, siempre con el porqué

Plan Maestro UX, fase B2 (sección 38; mantiene en verde G9). Se personaliza **la experiencia, nunca la inteligencia**:
lo que el cliente sigue y lo que él mismo consulta ordenan y filtran lo que ve, y cada cosa personalizada dice por qué
aparece. Los picks, las probabilidades, los estados y las cuotas son los mismos para todos. Coste: 0. Sin migración.

## 1. Qué ve el cliente

- **Partidos:** si ya eligió sus ligas y equipos, la página abre en **los suyos**, con dos botones contados: «Tus ligas ·
  12» y «Todos · 340». Primero lo que se juega en vivo, luego sus ligas en el orden en que las eligió. Cada liga suya dice
  **«Tu liga»** y cada partido de un equipo que sigue en otra competición dice **«Sigues a Nacional»**: una sola línea que
  se recorta antes que romper la fila a 320 px, y con un toque la frase entera («Te mostramos este partido porque sigues a
  Atlético Nacional»). Un día sin partidos suyos lo dice («Hoy no juegan tus ligas ni tus equipos.»), cuenta los demás
  con «Ver todos los partidos» y muestra **sus próximos partidos** (el calendario de sus favoritos). Mientras siga con las
  sugeridas para Colombia (no eligió), la página abre en «Todos» y las sugeridas quedan a un toque («Sugeridas · 25»).
- **Picks:** **el pick del día no cambia nunca**: es el de PrediGol, igual para todos, sin filtrar, sin reordenar y sin
  ninguna etiqueta de «sigues a» (no se eligió para nadie). La lista de todas las selecciones abre en **sus ligas**, con
  las demás contadas y a un toque: nunca dice «no hay picks» si hay alguno en otra liga («Ninguna de tus ligas ni de tus
  equipos con estos filtros. Hay 7 en otras ligas.» y «Ver las 7 de otras ligas»).
- **Un partido, «Mercados»:** **los mercados que el cliente más consulta van primero**, con la regla dicha: «Primero, los
  mercados que más consultas: Más/Menos de goles (3) y Ambos marcan (2).»; con un toque, qué se cuenta y que las
  probabilidades y los precios son los mismos para todos; y **«Orden de siempre»** (y luego «Volver a mi orden») cuando
  no lo quiere.
- **Inicio:** **una sugerencia, con su motivo y su confirmación**: «¿Agregas Serie A a tus ligas?» o «¿Sigues a
  Millonarios?», «Abriste 4 partidos suyos en los últimos 30 días.» y «Te lo sugerimos porque lo abres a menudo y no está
  entre tus favoritos. Solo se agrega si tú lo confirmas.» «Agregar» la suma a sus favoritos (sin quitarle nada) y «No,
  gracias» hace que **no vuelva nunca**. Las **noticias** de Inicio son ya las de **sus ligas y equipos**, cada una con su
  porqué; mientras no elija, las de las sugeridas, rotuladas como hasta ahora.

## 2. Lo que nunca cambia

- **PrediGol Intelligence:** nada. Ni un pick, una probabilidad, un estado, una cuota ni un modelo. Los tableros siguen
  siendo uno para todos (en caché) y lo del cliente se aplica encima.
- **Picks iguales para todos:** una prueba de integración pide, para **dos clientes con favoritos y hábitos distintos**,
  Inicio, el tablero de hoy, el estado del día, los picks, el pick del día, los que ya empezaron, el partido, su
  pronóstico, su lectura, sus noticias, sus cuotas, las mejores cuotas y los partidos del día, y exige respuestas
  idénticas; lo personal vive solo en `/me`. El e2e lo repite en el navegador con dos cuentas.
- **Sin perfil de apostador:** solo lo que el cliente sigue y lo que abre, contado. Nunca importes, banca, resultados ni
  apetito de riesgo. **Sin aprendizaje automático:** reglas que se leen.

## 3. Lo nuevo por dentro

- **`GET /api/v1/me/personal`** (detrás de la puerta de consentimiento, como los eventos que lee; no detrás de la de
  membresía): el orden de mercados del cliente (sus `market_viewed` de los últimos **30 días**, desde **2 veces**, el
  más consultado primero) con cuántas veces cada uno, y **una** sugerencia: una liga que PrediGol sigue, o un equipo que
  juega en una, cuyos partidos el cliente abre **fuera de lo que ya sigue**: **3 partidos distintos en 2 días distintos o
  más** de los últimos 30. Un equipo va antes que su liga si empatan (es el motivo más cercano); nunca uno descartado,
  nunca un equipo que no se puede seguir y nunca pasado el límite (10 ligas, 20 equipos).
- **`PUT /me/personal/markets`** (el orden de siempre o el suyo) y **`POST /me/personal/suggestion/dismiss`** («No,
  gracias»). Aceptar es guardar los favoritos con la sugerencia (`PUT /me/favorites`, el de siempre).
- **Solo con la analítica midiendo:** el orden y las sugerencias leen únicamente los eventos del propio cliente y solo
  mientras se registran (`FBI_PRODUCT_EVENTS=on`, o `consent` con su consentimiento de analítica; nunca tus cuentas ni el
  robot del recorrido). **Con la analítica apagada —como nace en producción—, el orden de siempre y ninguna sugerencia.**
- **El evento `market_viewed`** (estaba en el catálogo de A6, sin pantalla): se registra cuando el cliente toca algo de
  un mercado —un precio, sus casas o todas sus líneas—, **una vez por mercado y visita**.
- **Las noticias de Inicio** (`GET /today/news`) por favoritos: el mismo tablero para todos los que siguen lo mismo, dos
  minutos en caché; cada partido con su porqué; una noticia es idéntica para todos los que la ven.
- **Partidos y Picks se filtran en la página**, encima de los tableros comunes que ya llegan enteros al navegador: el
  servidor no calcula nada por cliente para ellos.
- **`FBI_PERSONALIZATION=0`** (la línea de A13): la vista común en todas partes —Partidos y Picks sin filtro, el orden de
  siempre, ninguna sugerencia, las noticias de las sugeridas—, sin desplegar.

## 4. Línea base

Hoy (B1) todos los clientes ven lo mismo, sigan lo que sigan:

| Dónde | Hoy | Con B2 |
| --- | --- | --- |
| Partidos | Todos los partidos del día por competición: primero lo que se juega en vivo, luego las competiciones seguidas por orden alfabético. En producción, la ventana de Inicio tenía **607 partidos de 133 competiciones seguidas** (línea base de A13, 26-oct): una liga del cliente aparece donde la pone su nombre | Abre en sus ligas y equipos («Tus ligas · N» al lado de «Todos · M»), sus ligas primero en su orden, lo demás contado y a un toque |
| Picks | La lista de todas las selecciones, sin distinguir sus ligas | Abre en sus ligas; las demás contadas y a un toque; el pick del día, igual |
| Noticias de Inicio | Las de las ligas sugeridas, aunque el cliente haya elegido otras | Las de sus ligas y equipos, con su porqué |
| Mercados de un partido | El mismo orden para todos: 1X2, Más/Menos de goles, Ambos marcan, Hándicap asiático y Doble oportunidad | Los que el cliente más consulta primero, con la regla dicha y «Orden de siempre» |
| Sugerencias | Ninguna | Una, con su motivo y su confirmación |
| `market_viewed` | En el catálogo de A6 desde el principio, pero nunca se registraba (no había dónde) | Se registra al tocar un mercado, una vez por mercado y visita |

**Medido en QA** (base `fbi_qa_b2`, cuentas de la prueba): con favoritos distintos, cada cuenta ve «Tus ligas · 1» y «Todos ·
2» en el día de QA (dos ligas con un partido cada una), cada una su liga con «Tu liga» y, con un equipo de la otra, «Sigues a
…» en su fila; tras 3, 2 y 1 consultas de Más/Menos, Ambos marcan y Doble oportunidad, el partido abre con Más/Menos primero y
«(3)» y «(2)» en la frase; tras abrir 3 partidos de otra liga en 3 días distintos, Inicio sugiere esa liga con «Abriste 3
partidos suyos». **La base de QA no tiene selecciones en la ventana** (no fabrica picks): el e2e comprueba que las selecciones
son idénticas para las dos cuentas, y la lista de Picks por favoritos se ejercitará con selecciones cuando lleguen los datos de
ejemplo de los cuatro estados de B3; hasta entonces la cubre la misma regla, probada en las unitarias.

## 5. Decisiones que tomé

1. **El filtro por defecto, solo con favoritos elegidos.** La sección 38 lo ata a los favoritos «del onboarding o del
   perfil»; mientras el cliente siga con las sugeridas (no eligió), Partidos y Picks abren en «Todos» y las sugeridas quedan
   a un toque. Así nadie ve su lista recortada por algo que no eligió.
2. **El pick del día no se filtra, no se reordena y no lleva «sigues a».** Es el de PrediGol para todos; una etiqueta haría
   creer que se eligió para él. El filtro y el porqué van en la lista de todas las selecciones.
3. **Consultar un mercado es tocarlo.** Los cinco mercados se ven a la vez, así que contar «lo que pasó por la pantalla»
   no diría nada; cuenta tocar un precio, abrir sus casas o todas sus líneas, una vez por visita.
4. **El orden de mercados sale de los eventos crudos del cliente (30 días), no de `activity_daily`.** La ficha nombra la
   agregación diaria, pero esa guarda cuántos eventos de cada tipo, no de qué mercado; los crudos se guardan 90 días.
5. **Una sola sugerencia y solo con lo que el cliente abre fuera de lo que sigue.** Si ya sigue la liga, sus partidos ya
   están en su vista: sugerir el equipo sería ruido.
6. **Sin migración:** lo que el cliente decide (el orden de siempre, cada sugerencia descartada) se guarda en
   `customer.preferences.hints_seen`, la lista de lo que ya vio y descartó (A13), con nombres propios (`order:markets`,
   `suggest:league:<id>`); `/me/onboarding` sigue devolviendo solo las pistas de las páginas. La exportación del cliente
   ya incluía esa lista.
7. **Detrás de la puerta de consentimiento** (no de la de membresía): lee lo medido, como `POST /events`; una cuenta
   limitada sigue viendo su orden.
8. **El calendario de sus favoritos** son Partidos filtrado por los suyos día a día y, en un día sin los suyos, sus
   próximos partidos (los mismos de Inicio, A13).

## 6. Pruebas

- **Backend (unitarias):** la regla del orden (desde 2 veces, el más consultado, el último en un empate, el orden de
  siempre al final, solo los cinco mercados), la de la sugerencia (3 partidos en 2 días, lo que ya sigue no cuenta, un
  partido abierto dos veces es uno, un equipo antes que su liga, nunca uno descartado ni uno que no se puede seguir ni
  pasado el límite) y la del porqué, la misma para Inicio y sus noticias.
- **Backend (integración, con sesión real):** el orden y la vuelta al de siempre; los eventos de otro cliente o de hace más
  de 30 días nunca cuentan; nada se usa con la analítica apagada, en `consent` sin consentimiento, para tu cuenta ni con
  `FBI_PERSONALIZATION=0`; la sugerencia con su motivo, aceptada (desaparece) y descartada para siempre; los límites; las
  noticias de Inicio por favoritos con su porqué y la misma noticia para todos; solo lo propio, 401 sin sesión y 403 desde
  otro sitio; y **dos clientes con favoritos y hábitos distintos, mismas respuestas** en todo lo que muestra picks,
  pronósticos, cuotas y estados.
- **Web (unitarias):** el porqué (igual que el de la API), sin personalización ninguna vista propia, el orden del día, el
  interruptor con sus cuentas en español e inglés, el orden de mercados y su frase, una sugerencia aceptada sin perder nada,
  el lugar de la sugerencia en Inicio y el porqué de las noticias.
- **e2e (`personal.spec.ts`):** dos cuentas con favoritos distintos en Partidos (cada una lo suyo con su cuenta, «Tu liga»
  y «Sigues a…», «Todos» igual para las dos), el pick del día y las selecciones idénticos, Picks abriendo en lo suyo con
  las demás contadas; a 320 px cada porqué en una línea dentro de la pantalla y nada de lado; los mercados en el orden del
  cliente, la regla dicha, el de siempre y de vuelta, y un toque registrado una vez; la sugerencia con su motivo, «No,
  gracias» para siempre y «Agregar» siguiéndola.

## 7. Puertas

- **Backend** (árbol `36f3db56`): ruff sin avisos; mypy estricto (506 ficheros) y del árbol entero (1.197), sin errores;
  pytest **5.935 pasadas**, 4 omitidas y 1 fallida por carga: `test_match_knowledge_builder` (un tiempo que se agota a
  mitad de una pasada, con la máquina ocupada por otra puerta al lado), repetido solo sobre el mismo árbol: 34 de 34.
- **Web** (árbol `bab81a34`): lint 0 errores (26 avisos de siempre), tipos, **918 pruebas**, build de producción.
- **e2e sobre esos árboles**, con la base de QA `fbi_qa_b2` (una copia de la de B1 tras su copia y su prueba de
  restauración; sin migración):
  - `personal.spec.ts` sola: 4 de 4 (2,1 minutos).
  - La suite completa como arranca producción (narrativa apagada, «Cómo le va a PrediGol» cerrada, tickets encendidos,
    sin WhatsApp): **168 pasadas** (contando los 6 inicios de sesión de preparación), 3 fallidas y 19 omitidas, 44,6
    minutos (26-oct 23:23 – 27-oct 00:08 UTC). Las 3 fueron carga: una página aún cargando con dos trabajadores mientras
    la puerta de otra fase corría al lado (la membresía de la prueba a la renovación, el perfil en un escritorio y las
    direcciones del perfil). Repetidas con un solo trabajador sobre el mismo árbol: **3 de 3**.
  - Autoservicio con el messenger de QA (cuenta, onboarding, anónimo, soporte, los dos recorridos y el perfil): 34
    pasadas y 2 omitidas (7,5 minutos).
  - La membresía exigida: 2 de 2. Tickets apagados (`FBI_SUPPORT=0`): 1 de 1.
  - axe (WCAG 2.2 A y AA) con la configuración encendida: 29 medidas, 0 violaciones.
- **Gitleaks** sobre los commits de B2 (`e00d6dfb..d82be29e`): 0 hallazgos.
- **Rama:** `ux/b2` lleva además, fusionada, la guía de B1 (`609dc20e`, solo documentos), para que el paquete de B2 la
  incluya.

## 8. Despliegue

Backend y web juntos (el contrato cruza los dos), sin migración. Va en la cola de UX después de A15, del gate y de B1.
**El orden de mercados y las sugerencias necesitan la analítica de A6 midiendo** (`FBI_PRODUCT_EVENTS`, que nace apagada:
tu decisión, con P5); sin ella todo lo demás funciona (filtros, porqués, noticias) y esas dos piezas esperan sin decir
nada. **Vuelta atrás:** `FBI_PERSONALIZATION=0` (vista común, sin desplegar) o las publicaciones anteriores.

## 9. Acción manual

Ninguna.

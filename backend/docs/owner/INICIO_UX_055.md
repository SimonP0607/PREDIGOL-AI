# Inicio rehecho: qué enseña, qué puede tocar el dueño y cómo comprobarlo (UX-039 a UX-049)

Plan: `PLAN_INICIO_PREDIGOL` (en el Project). Este archivo cuenta, para el dueño, cómo queda Inicio al cerrar las cuatro fases, qué decide cada bloque y dónde se apaga o se vuelve atrás. Nada de esto cambia modelos, probabilidades, picks, IA, mercados ni la liquidación: Inicio solo lee y ordena.

## Qué ve cada lector

Dos capas, cada una un bloque con nombre propio:

1. **Para ti** (solo si el lector eligió algo): sus partidos (en vivo, de hoy y el próximo de cada favorito), sus noticias (2 como máximo), sus jugadores con partido (titular, banca, fuera, baja o duda), el **aviso de coincidencias** («N picks de hoy coinciden con tus favoritos», cada línea baja a su tarjeta en PrediGol y la resalta, sin repetirla), sus avisos y sus resultados. El botón **Editar favoritos** abre una hoja (a un lado en escritorio, desde abajo en móvil) con el mismo selector de la bienvenida; cada cambio se guarda al instante y Inicio se actualiza detrás.
2. **PrediGol** (igual para todos), de arriba abajo: **Picks del día** (con su estado real, o por qué no hay), **Parlays** (del día y multi-día), **Partidos relevantes** (en vivo con un motivo que elige el servidor), **Qué se juega** (próximas 36 h, una frase por partido), **Noticias** (resumen de 3), **En vivo** (el resto, 6 como máximo) y **Últimos resultados** (24 h, 6 como máximo). Un bloque sin contenido no aparece; un fallo se ve con su referencia y su reintento, nunca como lista vacía.

Sin favoritos, el lector ve la capa PrediGol completa y una línea discreta «Elige tus favoritos» (se puede cerrar). En la tarjeta general, un pick que coincide con los favoritos lleva un chip «Tu equipo», «Tu jugador», «Tu liga» o «Tu mercado».

## Reglas que decide el servidor

- **Partidos relevantes** (`api/services/home_board.py`): final, vuelta de una eliminatoria y cómo va, pelea por título, Europa, descenso o ascenso, y remontada, calculados de la lectura del partido y del historial en vivo. Un partido sin motivo no aparece. Amistosos: ningún motivo.
- **Orden de la capa general**: por prioridad de competición de PrediGol (`fbi.intel.day_priority`, más Primera A y Libertadores), después nivel, hora y número.
- **Últimos resultados**: terminados en las últimas 24 h, el más reciente arriba. Un partido es resultado cuando el feed de partidos lo da por terminado o, al instante, cuando el feed de fixtures dice FT, AET o PEN.
- **Noticias**: «Confirmado» exige **fuente oficial o dos medios distintos** (dos páginas o dos subdominios del mismo sitio son un medio; agregadores y redes no cuentan); si no, Inicio lo muestra como «Probable». Como mucho **un rumor**, solo si queda sitio, rotulado «Rumor». Como mucho dos por partido. El arreglo de fondo de la canalización de evidencias (`ai/evidence.py`) queda para la línea de IA: este módulo no la toca.
- **Picks (decisiones aprobadas)**: **D1** un pick que la revisión de contexto rechazó o rebajó no se enseña a los lectores, aunque esté en sombra; **D2** «Hoy en las ligas sugeridas» salió de la capa general; **D3** la tarjeta lleva cuota de referencia sin casa de apuestas y nivel «Alto» si hasta la estimación prudente supera al mercado, «Medio» si solo la central.

## Interruptores

| Variable | Valor si falta | Qué controla |
| --- | --- | --- |
| `FBI_NEWS_USERS` | encendido | `=0` oculta las noticias de Inicio (y las del partido) sin desplegar; la API necesita reiniciarse |
| `FBI_PERSONALIZATION` | encendido | `=0` da a todos la vista común: sin «Para ti» ni «Editar favoritos» |

No hay interruptor propio de los bloques nuevos: si algo falla, se vuelve atrás el PR (squash) correspondiente.

## Cómo comprobarlo tras desplegar

Con la sesión del dueño y con la de un lector con y sin favoritos:

1. **Orden**: cabecera, (Para ti), Picks, Parlays, Relevantes, Qué se juega, Noticias, En vivo, Resultados; ningún partido repetido dentro de una capa.
2. **En vivo / Resultados**: un partido terminado sale de «En vivo» y entra en «Últimos resultados» sin pasar por ninguno de los dos a la vez; uno por empezar no está en «En vivo». Con prórroga o penales, «Final (prór.)» o «Final (pen.)» y la tanda.
3. **Noticias**: 3 como máximo (2 en «Para ti»), ninguna «Confirmado» sin fuente oficial ni dos medios, un solo rumor rotulado.
4. **Editar favoritos**: añadir y quitar un equipo guarda sin recargar y cambia «Para ti» detrás; un fallo de red deja el cambio y ofrece «Reintentar».
5. **Móvil (320 a 430 px)**: sin desplazamiento horizontal de la página; «Ver N más» en las listas largas; «En vivo» desliza; acciones de 44 px. Medir el largo de Inicio en una jornada cargada (objetivo: 5 pantallas o menos).
6. **Sin conexión** (modo avión con la PWA abierta): una línea lo avisa y se conserva lo que ya había cargado.

## Lo que queda anotado

- `/me/today` no trae tus partidos ni tus noticias (siguen en `/today` y `/today/news`); el plan lo preveía para reducir consultas. Se decide con medidas del despliegue 4 (peso y número de consultas).
- Los e2e no corren en el CI y no se pudieron ejecutar en esta entrega: las alturas reales de móvil y los anchos de 320 a 1024 px se verifican en el navegador.
- Medir tras el despliegue 1 la transición de en vivo a resultado en una jornada cargada, y esperar un partido con prórroga o penales para validar el reloj y la tanda.

## Novedades (texto listo para publicar, en Admin → Comunicados)

**Es:** «Inicio es más claro. Arriba, lo tuyo (si elegiste favoritos); debajo, lo de todos: los picks del día, los parlays, los partidos que importan ahora y lo que se juega hoy y mañana, noticias resumidas y los últimos resultados. Y ahora puedes editar tus favoritos sin salir de Inicio.»

**En:** «Home is clearer. On top, what is yours (if you chose favourites); below, what is for everyone: the day's picks, the parlays, the matches that matter now and what is at stake today and tomorrow, summarised news and the latest results. And you can now edit your favourites without leaving Home.»

Publicarlo es decisión del dueño (un comunicado llega a los lectores); no se ha publicado.

## Volver atrás

Cada paso es un PR de squash en `main`; se revierte el que falle y se despliega. Los contratos añadidos son opcionales (`Home.relevant`, `at_stake`, `results`; `ParlayRecordLeg.why`; `RelatedPick.players`; `/today/news?scope=general`): una web anterior los ignora. Ninguna migración.

# UX-016 · Datos de comportamiento responsables

Plan de cierre de la UX, tarea 3.3. **Sin migración, sin interruptor nuevo, sin IA y sin servicios externos.** Se amplía el catálogo
cerrado de eventos de uso (UX-008 lo dejó detrás de su casilla opcional) con tres datos que ayudan a decidir qué mejorar, y la vista del
dueño los muestra por grupos. No toca PrediGol Intelligence: no hay un modelo, una probabilidad, una calibración, un umbral, un pick ni
su liquidación en nada de esto, y nada de lo medido vuelve a la capa de decisión.

## 1. Qué se mide ahora, y qué no

Siempre con un identificador seudónimo, solo si el lector marcó la casilla de estadísticas de uso (modo `consent`), y nunca la cuenta del
dueño ni la del robot de monitoreo.

| Dato | Cómo se dice | Qué lo acompaña |
| --- | --- | --- |
| **Mercado al guardar un pick** | `pick_saved` ya existía; ahora puede llevar `market` | Uno de los cinco mercados que PrediGol lee: 1X2, OU, BTTS, AH, DC |
| **Mercado al añadir al parlay** | `slip_leg_added` ya existía; ahora puede llevar `market` | Los mismos cinco; el mercado de la selección que se añade |
| **Pantalla vista, por grupo** | Evento nuevo `screen_viewed` con `screen` | Una de 15 palabras de una lista cerrada: inicio, partidos, un partido, en vivo, picks, mis picks, parlays, cuotas, novedades, transparencia, perfil, ayuda, textos legales, bienvenida, otra |

**Nunca viaja:** la dirección de la página, lo que el lector busca, el identificador de un partido o de un pick dentro de la pantalla, el
texto de nada, el correo ni la IP. Un evento o una propiedad fuera del catálogo se rechaza entero (422), igual que antes: el catálogo del
servidor y el de la web son el mismo archivo y una prueba comprueba que no se separen (ahora son 40 eventos: UX-032 añadió los cuatro de las guías).

**Equipos y ligas consultados: no se recogen.** El evento `match_opened` ya lleva el partido que se abrió; la liga y los dos equipos se
**deducen en el servidor cuando el dueño abre la página**, uniendo ese partido con el calendario. No se guarda nada nuevo: ni una columna,
ni un evento, ni una tabla.

## 2. Qué ve el dueño

En Admin → Producto, debajo del uso por función, un bloque «Qué miran los lectores (30 días)» con cuatro listas: pantallas por tipo,
mercados de los picks guardados y de las selecciones añadidas al parlay, ligas de los partidos abiertos y equipos de los partidos
abiertos. Cada línea muestra las veces y los lectores.

**Regla de privacidad del servidor:** una línea solo se lista si hay al menos `FBI_PRODUCT_MIN_SUBJECTS` lectores distintos detrás (20 por
defecto, la misma regla de las cifras globales). Con menos, la línea no aparece: nunca se enseña lo que hizo un puñado de personas. Hasta
15 líneas por lista.

## 3. El texto de la política

La política dice ahora, dentro de lo que se mide solo con la casilla, el tipo de pantalla, el mercado en que se guarda un pick o se
añade una selección al parlay, y la liga y los equipos de los partidos que se abren («los deducimos del partido, no los recogemos
aparte»). Es una versión nueva del texto (`2026-11-05-draft5`), **no material**: detalla lo que ya decía («qué pantallas y funciones usas»)
y no añade un dato ni un uso; nadie tiene que aceptar de nuevo. Sigue siendo un borrador pendiente de la revisión del abogado (P5).
La frase de la casilla (lo que el lector acepta) no cambia.

## 4. Lo que no hace

- **No enciende nada por sí solo.** `FBI_PRODUCT_EVENTS` sigue apagado hasta que el dueño o yo lo cambiemos en el servidor; con `off` la web
  envía los eventos y el servidor responde `recorded: 0`.
- **No cambia los plazos:** 90 días en bruto y 13 meses agregados; la purga sigue en `dry` (cuenta, no borra) hasta que se encienda.
- **No mide tiempo en la app, ni qué se escribe, ni la ubicación.**
- **No mide el partido que se abre dentro de «pantalla»:** eso ya es `match_opened`, con su origen.

## 5. Despliegue

Sin migración y sin interruptor nuevo. **La API va primero:** la web nueva envía `screen_viewed` y el `market` de un pick o una selección, y
la API de antes rechazaría con 422 ese lote entero (la web no reintenta: se pierden esos eventos, el lector no ve nada). Con la API
primero no se pierde ninguno.

**Encender la medición** (tarea del servidor, tras desplegar y no antes):

1. Confirmar en Admin → Producto que el estado dice «Purga en ensayo» y la medición «apagada».
2. `FBI_PRODUCT_EVENTS=consent`: solo se registran los lectores que marcaron la casilla; el modo `on` registraría a todos y queda para
   cuando el abogado lo decida.
3. Dejar pasar un día completo en seco: el mensajero cuenta lo que borraría la purga y no borra nada. Revisar que la cuenta cuadra.
4. `FBI_EVENTS_PURGE=on`: crudos a 90 días, agregados a 13 meses.

## 6. Cómo se probó

- Unitarias (`tests/unit/test_product_events.py`): el catálogo de 40 eventos en sus grupos; el mercado y la pantalla aceptan solo su lista;
  una dirección, una búsqueda, un identificador o una pantalla desconocida se rechazan. (`tests/unit/test_customer_legal.py`): la política
  nombra lo que se mide y sigue siendo solo con la casilla; la versión nueva no es material.
- Integración (`tests/integration/test_product_events.py`): con tres lectores y el mínimo en 3, la vista del dueño lista la pantalla, el
  mercado, la liga y los dos equipos con sus cuentas exactas; una pantalla con un lector, un mercado con dos y un partido que ya no existe
  no salen; con el mínimo en 4 no sale ninguna lista; nada de la liga ni de los equipos queda guardado; el mismo resultado por la API.
- Web (`track.test.ts`, `product.test.tsx`): el catálogo de la web es el del servidor; `screenOf` devuelve siempre un valor de la lista y
  nunca la dirección; cada pantalla y cada mercado tiene su texto en español e inglés; el e2e comprueba que el lote de un recorrido trae
  `screen_viewed` con «inicio» y «un partido» y ningún dígito ni barra.

## 7. A revisar a mano tras el despliegue

Con la medición encendida y la casilla marcada en una cuenta de lector: navegar Inicio → un partido → Mis picks, guardar un pick y añadir
una selección al parlay, y ver en Admin → Producto que las cuentas suben (las listas por grupos solo aparecen con el mínimo de lectores:
en una cuenta sola se ve el uso por función y no estas listas, a propósito).

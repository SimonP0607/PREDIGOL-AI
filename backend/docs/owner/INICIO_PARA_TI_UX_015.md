# UX-015 · Inicio en dos capas: «Para ti» y PrediGol

Plan de cierre de la UX, tarea 3.2. **Sin migración, sin interruptor nuevo, sin IA y sin servicios externos.** Un endpoint nuevo de solo
lectura, `GET /me/today`. Inicio se ordena en dos capas: **Para ti** (lo que el lector eligió seguir) y **PrediGol** (lo mismo para todos).
La capa de usuario consume la inteligencia, no la altera: nada de aquí calcula una probabilidad, pone precio a una selección, elige un pick
ni cambia uno.

## 1. Qué ve el cliente

- **Sin favoritos** (ni ligas, ni equipos, ni jugadores, ni mercados): solo la capa **PrediGol**, y encima una tarjeta discreta
  «Elige tus favoritos» con el camino a Perfil → Tu fútbol. Las ligas y la selección que PrediGol sugiere mientras tanto **ya no cuentan
  como suyas**: siguen en Inicio, rotuladas «sugeridas», dentro de PrediGol. No se oculta nada del producto.
- **Con algún favorito**: aparece **Para ti** encima de PrediGol, con una banda que lleva el camino «Cambiar favoritos». Sus partes, en
  este orden y cada una solo si tiene algo que decir:
  1. **Hoy en tus ligas** (sus próximos partidos, o el próximo de cada favorito si hoy no juegan), con por qué cada partido es suyo.
  2. **Noticias** de sus partidos, las mismas confirmadas o probables de siempre.
  3. **Tus jugadores:** cada jugador que sigue, en el orden en que los eligió, con el estado del próximo partido de su equipo.
  4. **Qué se juega** en sus próximos partidos.
  5. **Picks de tus partidos:** los picks publicados hoy que son de sus equipos, de sus ligas o de un mercado que sigue, con la razón en
     una ficha («Sigues a Nacional», «Tu liga», «Mercado que sigues: Más/Menos goles»). Si ninguno lo es, lo dice y dice cuántos picks
     hay hoy; si hoy no hay picks publicados, lo dice también. Nunca rellena el espacio.
  6. **Tus avisos:** las campanas que puso para partidos por jugar (hasta tres a la vista, y cuántas más) y, si sigue equipos, si las
     alineaciones de sus equipos les llegan a sus dispositivos (con el camino a activarlos o cambiarlos).
  7. **Resultados** de sus equipos y ligas de las últimas 48 horas.
- **Solo un jugador o un mercado** (sin ligas ni equipos): «Para ti» trae los jugadores, los picks del mercado y los avisos; los partidos,
  las noticias, qué se juega y los resultados siguen siendo los de las ligas sugeridas, en PrediGol, rotulados como sugeridos.
- **PrediGol** no cambia para nadie: los picks del día (y los de ayer si aún no terminaron), los parlays del día y de varios días, los
  partidos relevantes, lo que se juega en vivo y los mejores precios.
- Las dos capas son regiones con nombre para quien navega con lector de pantalla; los bloques de dentro conservan sus títulos.

## 2. Qué dice cada parte y de dónde sale

**El estado de un jugador** se cuenta con lo que dicen los datos y nada más, para el próximo partido de su equipo (su club, o su selección
si esa juega antes; el equipo de su última alineación en una liga que PrediGol sigue, en los últimos 400 días):

| Estado | Cuándo |
| --- | --- |
| Titular / Suplente | La alineación está publicada y lo nombra |
| Fuera de la alineación | La alineación del equipo está publicada y no lo nombra |
| Baja / Duda | La lista **vigente** de bajas del proveedor lo nombra («Missing Fixture» y cualquier otra: baja; «Questionable»: duda), con su motivo (lesión, sanción, enfermedad u otro, como en las «Bajas» del partido) |
| Aún sin alineación ni bajas | Ninguna de las dos cosas todavía |
| Sin partido próximo | Su equipo no tiene partido en los próximos 120 días, o no jugó en ningún equipo que PrediGol sigue en 400 días |

La alineación publicada es la palabra más nueva: quien está en ella juega aunque una baja vieja siga en la lista. La lista de bajas es la
**vigente** de la misma regla que las «Bajas» del partido: un jugador que la respuesta más reciente del proveedor ya no nombra se recuperó o
nunca estuvo fuera. Un jugador sin partido por jugar no es un enlace y no se le inventa partido.

**Los picks de tus partidos** salen del conjunto publicado del día (el mismo que ve todo lector, «solo verde»): el servidor marca cuáles son
del lector por su posición y su partido; la tarjeta es la misma que ya muestra «Picks del día». Si la tarjeta ya no existe en la lectura de
la pantalla (el conjunto cambió entre dos lecturas), no se muestra: no se inventa ni se pone otra.

**Los avisos** salen de las campanas que el lector puso (`customer.match_alerts`) y del estado de sus dispositivos y de su categoría de
alineaciones (`GET /me/push`): nada nuevo se guarda ni se envía.

## 3. Reglas del servidor

- `GET /me/today` es de lectura y solo para lectores. **`chosen`** es verdadero cuando el lector eligió al menos una liga, un equipo, un
  jugador o un mercado y la personalización está encendida; las ligas y la selección sugeridas **nunca** lo hacen verdadero. La cuenta de
  consola del dueño no tiene capa propia: `chosen` falso.
- `FBI_PERSONALIZATION=0`: vista común, sin «Para ti» y sin la tarjeta para elegir; lo elegido se conserva.
- Sin favoritos, el servidor no calcula nada más (no lee jugadores, picks ni avisos): `picks` y `notices` van vacíos.
- «Picks de tus partidos» solo se calcula si el lector sigue una liga, un equipo o un mercado; un jugador solo no lo activa.
- Cada lector recibe los mismos picks, pronósticos y estados; solo cambia cuáles están marcados como suyos (una prueba de integración lo
  mantiene, como la de A13).
- La lectura del conjunto del día usa la misma caché de 30 segundos que Inicio; el resto son consultas pequeñas por lector (como mucho 20
  jugadores y 30 campanas).

## 4. Lo que no hace

- **No toca PrediGol Intelligence:** ni un modelo, una probabilidad, una calibración, un umbral, un pick ni su liquidación.
- **No sigue nada sin tocar:** las sugerencias de ligas siguen siendo una tarjeta con «Agregar» y «No, gracias»; «Elige tus favoritos» solo
  lleva al selector.
- **No crea estados:** «Aún sin alineación ni bajas» es lo que es; no promete que el jugador jugará ni que no.
- **No hay jugador desde las noticias todavía** (queda como en UX-014).

## 5. Despliegue

Sin migración y sin interruptor. La web nueva llama a `/me/today`: contra la API de antes (404) a un lector con favoritos le mostraría, en
«Picks de tus partidos», el fallo con su referencia y un reintento (nunca una lista vacía). Por eso **la API va primero**, como ya exige
UX-014 (la API de antes rechaza con 422 los jugadores y mercados nuevos).

## 6. Cómo se probó

- Unitarias (`tests/unit/test_me_today.py`): la regla del estado de un jugador y de «duda»; qué picks del día son del lector por equipo,
  liga o mercado; el día sin conjunto.
- Integración (`tests/integration/test_customer_favorites.py`): vacío hasta que el lector elige (las sugeridas no cuentan, el dueño
  tampoco, con la personalización apagada tampoco); un jugador seguido pasa por titular, suplente, fuera de la alineación, baja, duda,
  «aún sin nada» y sin partido; la lista de bajas vigente; los picks de un equipo, de una liga, de un mercado, de otra liga y de un
  jugador solo; las campanas de cada lector; los picks son los mismos para todos.
- Web: capas (`layers.test.ts`), cartas relacionadas (`related.test.ts`), partes de «Para ti» y bandas (`ParaTi.test.tsx`); los bloques
  de siempre conservan sus pruebas; el e2e comprueba que sin favoritos no hay «Para ti» y sí la tarjeta, que un mercado solo la crea y
  que quitarlo la quita.

## 7. A revisar a mano tras el despliegue

Seguir un jugador y un mercado en una cuenta de lector real y mirar Inicio: «Para ti» arriba, los estados del jugador, los picks del
mercado; a 320 px de ancho sin desplazamiento lateral y con el chequeo de accesibilidad (axe).

# UX-014 · Más favoritos: jugadores y mercados

Plan de cierre de la UX, tarea 3.1. **Una migración (0122), sin interruptor nuevo, sin IA y sin servicios externos.** Además de ligas y
equipos, el lector puede seguir **jugadores** y **mercados**. Son favoritos como los demás: ordenan y filtran lo que se le muestra (las
capas de Inicio de la tarea 3.2) y no cambian un pick, una probabilidad, un estado ni una cuota: la capa de usuario consume la
inteligencia, no la altera.

## 1. Qué ve el cliente

- **Perfil → Tu fútbol** (y la bienvenida): el mismo selector, ahora con **jugadores** y **mercados**.
  - La búsqueda dice «Busca una liga, un equipo o un jugador». Un jugador se busca **desde tres letras** (dos listarían media liga),
    sin tildes ni mayúsculas, y solo aparecen jugadores que estuvieron en una alineación de una liga que PrediGol sigue en los últimos
    400 días; cada resultado dice su posición y el equipo de su última alineación para distinguir dos del mismo nombre.
  - **«Mercados que lees»:** cinco botones, los cinco que PrediGol lee (Resultado final, Más/Menos goles, Ambos marcan, Hándicap
    asiático y Doble oportunidad). Debajo: «Quedan en tus favoritos. Solo ordenan lo que ves: no cambian ningún pick, probabilidad ni
    cuota.»
  - Lo elegido se ve arriba como fichas que se quitan con un toque, con las cuentas contra los límites: **20 jugadores y 5 mercados**
    (las ligas y los equipos siguen en 10 y 20). El límite se dice antes de llegar a él y, en el límite, no se añade nada.
- **Una ficha de jugador** (tocar su nombre en una alineación o en las bajas de un partido): el botón **«Seguir»** / **«Siguiendo»**,
  de 44 px, que dice su estado. Un toque sigue o deja de seguir y avisa con un mensaje breve («Ahora sigues a …»).
- **Un partido → Mercados:** el mismo botón al lado del nombre de cada mercado que se puede seguir.
- El botón solo lo ve un lector con la personalización encendida (`FBI_PERSONALIZATION`); la cuenta del dueño nunca lo ve.

## 2. Qué se guarda y qué no

- La tabla `customer.favorites` suma dos tipos, `player` y `market`, con dos columnas nuevas (`player_id`, `market_key`). Las filas de
  ligas y equipos no se tocan. Un jugador o un mercado que desaparece se lleva su favorito.
- Una restricción dice qué lleva cada tipo (su columna y ninguna otra), de modo que una fila nunca apunta a dos cosas, y un índice único
  deja una sola fila por lector y favorito.
- **Exportación de datos:** `favorites` suma jugadores (con su nombre) y mercados (con su clave: no tienen número). **Borrado de
  cuenta:** se borra todo por usuario, sea cual sea el tipo.
- **Nunca un perfil de apostador.** Un mercado se sigue por lo que es, un nombre; no se guarda cuánto, ni qué selección, ni qué cuota.
  La política de privacidad ya habla de «tus preferencias»; si el abogado (P5) prefiere nombrar los jugadores y los mercados, es un
  texto nuevo con su versión: no se cambia aquí.

## 3. Reglas del servidor

- `PUT /me/favorites` acepta ahora `players` y `markets` además de `leagues` y `teams`. **Dejar fuera `players` o `markets` los
  conserva:** una pantalla de antes de este cambio que guarda solo ligas y equipos nunca borra los jugadores ni los mercados de nadie.
  Una lista vacía los borra.
- **Se rechaza, no se recorta** (422): `too_many_players`, `too_many_markets`, `unknown_player` (no existe, jugó hace más de 400 días o
  solo en una liga que PrediGol no sigue) y `unknown_market` (uno de los cinco). Un campo de importe o de banca sigue siendo un 422.
- **Un jugador que ya se sigue se queda** aunque salga de la ventana de 400 días (se retira o deja de jugar): no se le vuelve a
  preguntar, y un favorito viejo nunca impide guardar otro cambio. Al quitarlo, si lo vuelve a pedir, se pregunta como a cualquier otro.
- Mientras el lector no elija ligas ni equipos, ve las **sugeridas** (rotuladas como tales) aunque siga jugadores o mercados: seguir un
  jugador no convierte las sugeridas en suyas.
- `GET /me/favorites/options?q=` devuelve también los jugadores (desde tres letras).
- Las analíticas del producto suman `player` y `market` a los eventos `favorite_added` y `favorite_removed` (un mercado se nombra por su
  clave, no tiene número); el catálogo del servidor y el de la web siguen siendo el mismo, con su prueba.

## 4. Lo que no hace (todavía)

- **Este cambio solo los guarda.** Quien los lee es la tarea 3.2 (UX-015, Inicio en dos capas, «Para ti»: el estado del próximo partido de
  cada jugador y los picks del día que son de un mercado que sigues). Hasta que esa se despliegue, el selector lo dice con la frase de
  arriba y no promete más.
- **Seguir a un jugador desde una noticia** (el plan lo menciona) queda fuera de este cambio: las noticias de PrediGol no traen todavía
  el jugador como dato propio, y no se inventa. Se puede seguir desde la alineación, las bajas del partido y la búsqueda.
- **No toca PrediGol Intelligence:** ni un modelo, una probabilidad, una calibración, un umbral, un pick ni su liquidación.

## 5. Interruptores

Ninguno nuevo. `FBI_PERSONALIZATION=0` esconde los botones de seguir (y deja a todos con la vista común), sin desplegar.

## 6. Pruebas

- Migración: `tests/integration/test_migration_0122_favorite_players_and_markets.py` (arriba y abajo: la forma de las filas de ligas y
  equipos no cambia, las nuevas filas de jugador y de mercado, lo que rechaza la base de datos, el borrado en cascada, la bajada
  rechazada mientras haya jugadores o mercados y las restricciones de antes que vuelven).
- Servidor: `tests/unit/test_customer_favorites.py` (límites, mercados y jugadores válidos, el jugador que ya se sigue, y que la lista de
  mercados es la `MarketKey` del producto) y `tests/integration/test_customer_favorites.py` (el orden del lector, guardar sin ellos los
  conserva, vacío los borra, lo que se rechaza, el jugador que sale de la ventana, la búsqueda sin tildes y desde tres letras, la
  exportación y el borrado de la cuenta).
- Web: `favorites.test.tsx` (límites y orden de jugadores y mercados, lo que se envía, que seguir un jugador no hace suyas las
  sugeridas, los cambios y sus eventos aceptados por el catálogo, el selector con sus cuentas y sus 44 px) y
  `track.test.ts` (el catálogo de la web es el del servidor). e2e: `onboarding.spec.ts` (elegir un mercado en el perfil, que un guardado
  sin él lo conserva y que `CS` y un importe se rechazan).

## 7. Despliegue y vuelta atrás

Migración **0122** (encima de la 0121 de los cupones): se aplica con `lock_timeout = '10s'` y toca una tabla pequeña. La API y la web
salen en la misma versión: **una web nueva con una API vieja recibe un 422 al guardar** (la API vieja no conoce los campos nuevos),
así que no se despliega la web sola. Una web vieja con la API nueva funciona (no envía jugadores ni mercados y los suyos se conservan).
Vuelta atrás: revertir el PR; la migración baja solo mientras nadie siga a un jugador o un mercado (con ellos, el código vuelve y las
columnas se quedan: el código viejo lee solo ligas y equipos).

## 8. Acción manual

Ninguna. Al desplegar: con una cuenta de lector, seguir un mercado en un partido y un jugador desde su ficha, y ver los dos en
Perfil → Tu fútbol.

# BE-025 · «Seguir» en todos los mercados del catálogo

Plan Cuotas, fase 6. **Una migración (0131), sin interruptor nuevo, sin IA y sin servicios externos.** Hasta ahora el lector podía seguir
cinco mercados (1X2, más/menos, ambos marcan, hándicap y doble oportunidad). El catálogo de «Mercados» de un partido trae muchos más
(córners, tarjetas, tiros, las mitades). Ahora cada mercado del catálogo tiene su «Seguir», y los que el lector sigue salen primero en su
categoría. Es un favorito como los demás: **solo cambia el orden en que el lector ve los mercados**; no cambia un pick, una probabilidad,
un estado ni una cuota, y no toca el estado SHADOW ni las reglas de publicación.

## 1. Qué ve el cliente

- En cada mercado del catálogo que **no** es uno de los cinco, junto a su nombre: **Seguir / Siguiendo**. Los cinco clásicos siguen
  exactamente igual que antes (su propio botón, su propia lista y su límite de 5).
- Dentro de una categoría (córners, tarjetas...), los mercados seguidos van primero, en el orden en que el lector los eligió; el resto
  conserva el orden de siempre.
- **Perfil → Tu fútbol** muestra cada mercado seguido como una etiqueta que se quita con un toque («Más/menos córners · 1.ª parte»).
- Límite: **10** mercados del catálogo (aparte de los 5 clásicos). Al llegar, el botón lo dice y no cambia nada.

## 2. Qué se guarda

`customer.favorites` recibe un tipo nuevo, `catalog`, con su columna `catalog_key` (la clave que el propio catálogo da al mercado:
`código.periodo.sujeto`, p. ej. `corners_over_under.FT.match`). Sin importes, sin apuestas, sin perfil de riesgo: solo el nombre del
mercado que el lector lee. Los favoritos se borran al anonimizar la cuenta (A7) y salen en la exportación de datos personales
(`kind = catalog`, la clave en `market`).

## 3. Reglas del servidor

- `PUT /me/favorites` acepta `catalog_markets` (hasta 20 en el cuerpo, 10 válidos). Omitido, **se conservan**; `[]` los borra. Una página
  anterior que no lo envía no borra nada.
- La clave debe ser de un mercado que la taxonomía produce (código conocido, o `bet_<id>` de una apuesta que conoce; periodo FT/1H/2H/
  INTERVAL/OTHER; sujeto match/home/away/player/keeper). 422 `unknown_catalog_market` si no, 422 `too_many_catalog_markets` si pasa
  del límite; nunca se recorta. Una clave ya seguida se conserva aunque la taxonomía la olvide: un favorito nunca bloquea un guardado.
- `GET /me/favorites` devuelve `catalog_markets` y `max_catalog_markets`.
- Los eventos de analítica (`favorite_added` / `favorite_removed`) **no** anuncian estos favoritos: su catálogo de propiedades solo
  conoce los cinco clásicos, y no se amplía.

## 4. Pruebas

Unitarias: toda clave que el catálogo puede mostrar se puede seguir; lo que no es clave se rechaza. Integración: orden del lector,
conservación al omitir, `[]`, límites, claves inválidas, favorito antiguo que no bloquea, exportación y anonimización. Migración 0131 en
una base de prueba desde la 0130: forma de cada tipo, duplicados, bajada rechazada mientras alguien siga un mercado del catálogo y
restitución del índice y la restricción anteriores. Web: reglas del selector, orden, nombre en palabras del lector, el botón por mercado
y que los cinco clásicos no cambian.

## 5. Despliegue y vuelta atrás

Migración **0131** (encima de la 0130): se aplica con `lock_timeout = '10s'` sobre una tabla pequeña. API y web salen en la misma versión:
**una web nueva con una API vieja recibe 422 al guardar** (la API vieja no conoce `catalog_markets`), así que no se despliega la web sola.
Una web vieja con la API nueva funciona. Vuelta atrás: revertir el PR; la migración baja solo mientras nadie siga un mercado del catálogo
(con ellos, el código vuelve y la columna se queda: el código viejo ignora el tipo nuevo).

## 6. Acción manual

Ninguna. Al desplegar: con una cuenta de lector, seguir un mercado de córners en un partido, ver que sale primero al recargar y que
aparece en Perfil → Tu fútbol.

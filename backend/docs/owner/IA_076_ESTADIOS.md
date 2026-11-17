# IA-076 · Estadios: coordenadas, altitud y enlace del partido con su estadio

*Plan maestro de la arquitectura definitiva 2026, pieza AD-H04. Medido en producción (solo lectura) el 16 y 17-nov-2026.*

Esta pieza no cambia nada de lo que ve el lector. No toca modelos, probabilidades, picks ni liquidaciones, y no hace ninguna llamada a API-Football. Prepara dos cosas para los perfiles de club y de selección (AD-H07, bajo `FBI_PROFILES`, apagado): dónde está cada estadio y a qué altura, y en qué estadio se juega cada partido.

## 1. Qué problema resuelve

- `core.venues` no tiene columnas de coordenadas ni de altitud: la cobertura es del 0 %. La capacidad sí está, y la manda el proveedor: 1.290 de los 1.301 estadios usados en el último año (99,2 %).
- De los 1.288 partidos de los próximos 14 días, solo **425 (33,0 %)** traen el id de su estadio. 633 traen el nombre sin id y 230 no traen nada. El proveedor manda el nombre del estadio de cada partido, pero a menudo sin su id. Ahora `core.fixtures.venue_id` queda vacío en esos casos, porque un nombre sin id no se puede deduplicar (`ingestion/fixtures.py`).

## 2. De dónde salen los datos

**Wikidata (CC0 1.0).** No se busca el estadio por su nombre. Se llega a él por el **club**: el QID del club, de AD-H01 (`core.entity_ids`), da su estadio local (propiedad P115). De ese estadio se toman:

- etiquetas y alias en unos pocos idiomas,
- coordenadas (P625),
- capacidad (P1083),
- altitud (P2044),
- país (P17) y lugar (P131).

El volcado completo de Wikidata ocupa unos 130 GB. Por eso la instantánea se hace con **pocas consultas por lotes**: 200 clubes en cada una y una por minuto, que era el límite del servicio el 16-nov. Si el servicio está sobrecargado (429/5xx), se reintenta con pausas más largas; si un lote no responde, no se escribe nada. Todo se guarda **una vez** en un JSON con su sha256. El cargador no vuelve a preguntar a Wikidata: lee ese fichero, comprueba su sha256 y lo apunta en la carga.

**Altitud: Copernicus DEM GLO-90.** Es un modelo de elevación mundial de unos 90 m de resolución, publicado como GeoTIFF en el bucket abierto `copernicus-dem-90m` (AWS Open Data), sin cuenta. Su licencia, leída el 16-nov-2026, lo da «on a free basis for the general public» y permite reproducir, distribuir, comunicar al público y combinar con otros datos, con una condición: citar esta nota.

> produced using Copernicus WorldDEM-90 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved

La nota queda guardada en cada carga (`licenses.dem_notice`) y tendrá que aparecer donde se muestre la altitud.

Del modelo se lee solo lo necesario: la cabecera del fichero y el bloque que contiene el punto, por peticiones de rango. Son unos 4 MB por cuadrícula de 1°×1°, y cada cuadrícula se lee una sola vez para todos los estadios que caen en ella.

Es un modelo **de superficie**: las gradas y la cubierta entran en la medida. La altitud de un estadio queda con unos ±30 m de margen, que basta para lo que importa: 500 m y 2.850 m son partidos distintos; 35 m y 60 m, no. Si Wikidata trae su propia altitud (P2044), se compara: diferencias de 150 m o menos se dan por coincidentes. El P2044 de un estadio suele ser el de la ciudad.

No se usa scraping ni ninguna API de pago. OpenStreetMap queda como respaldo posible, pero no se usa.

## 3. Las reglas

### Estadio → ítem de Wikidata (`venue-geo-v1`)

1. Candidatos: los estadios locales actuales (sin fecha de fin y no obsoletos) de los clubes cuyo campo es este estadio.
2. Si **el nombre** coincide con una etiqueta o alias del candidato (las palabras distintivas, como en el resto del código: `fbi.core.places.same_place`), se acepta con el método `home_venue_name`. La confianza es 0,95 si la ciudad también coincide, o no se conoce, y 0,9 si no.
3. Si no coincide el nombre, pero hay **un solo** candidato y **la ciudad** coincide, se acepta con `home_venue_city` y confianza 0,8. Es el caso de un nombre de patrocinio: «Mercari Stadium» frente a «Kashima Soccer Stadium».
4. Todo lo demás va a la **cola de revisión**: varios candidatos con el nombre, varios candidatos sin confirmar, uno solo sin confirmar o un país que no cuadra.
5. Si un mismo ítem queda enlazado a dos estadios nuestros, solo se conserva donde coincidió el nombre. El otro va a la cola (`shared_qid`).
6. Si un ítem tiene dos coordenadas a más de 1 km, conserva su QID pero queda sin coordenadas.

### Partido sin id → estadio (`venue-link-v1`)

En orden, la primera regla que decide:

| Método | Regla | Confianza |
| --- | --- | ---: |
| `provider_history_team` | El proveedor dio un id a ese mismo nombre para el mismo club local en otros partidos. | 0,97 |
| `provider_history_city` | El proveedor dio un id a ese mismo nombre y ciudad en otros partidos. | 0,93 |
| `home_ground` | El campo del club local, con el mismo nombre. **Nunca en sede neutral.** | 0,90 |
| `venue_name_city` | El único estadio con ese nombre en esa ciudad. | 0,85 |

Lo ambiguo va a la cola: dos candidatos, el mismo nombre en otra ciudad, un nombre sin ciudad, o el campo del club con otro nombre en la misma ciudad. Un partido sin nombre de estadio no se enlaza.

`core.fixtures.venue_id` no se escribe nunca. El enlace inferido vive en su tabla, con su método, y la vista `core.fixture_venue_resolved` da para cada partido:

- el id del proveedor si lo mandó (`provider`);
- si no, lo que aceptó una persona (`manual`);
- si no, el enlace inferido más reciente que nadie haya rechazado.

## 4. Qué se añade (migración 0144, compartida con IA-075)

| Pieza | Qué es |
| --- | --- |
| `core.venue_geo_loads` | Una carga por instantánea (su sha256), con el modelo de elevación y las licencias. Se puede **retirar**: es el único UPDATE de estas tablas. |
| `core.venue_geo` | QID, latitud, longitud, altitud, fuente y comprobación de la altitud, capacidad de Wikidata, método, confianza y evidencia (incluido el sha256 del bloque del modelo), por carga. |
| `core.fixture_venue_links` | El estadio inferido de un partido sin id, con su regla. |
| `core.venue_review_queue` y `core.venue_review_decisions` | La cola de revisión y lo que decide una persona: `accept`, `reject`, `dismiss` o `undo`. |
| Vistas `core.venue_geo_live`, `core.fixture_venue_resolved`, `core.venue_review_open` | Lo que está en vigor. |
| `fbi/venues/` y `scripts/venue_geo.py` | Las reglas, el lector del modelo, la instantánea, la carga y la consola. |

Las tablas nuevas son de **solo añadido** (un disparador rechaza UPDATE y DELETE). `core.venues` y `core.fixtures` no se tocan. La ficha pedía columnas nuevas en `core.venues`; el encargo pedía una tabla, y se hizo una tabla. Así la ingesta, que reescribe `core.venues`, no puede pisar estos datos, y cada versión queda guardada.

## 5. Lo que se midió (producción, solo lectura, 16 y 17-nov-2026)

**Antes.** Consultas `psq` del 16-nov-2026, ~23:00 UTC:

- `core.venues` tiene 7.159 estadios, todos con id del proveedor. Coordenadas y altitud: 0, porque no hay columnas.
- Estadios usados en partidos del último año y de los próximos 14 días: **1.301**. De ellos, 1.290 (99,2 %) tienen capacidad del proveedor.
- Partidos de los próximos 14 días: **1.288**. 425 traen id de estadio (**33,0 %**), 633 traen solo el nombre y 230 no traen nada. Todos son de competiciones seguidas.
- Partidos del último año sin id de estadio: 22.684, de los que 13.308 traen el nombre.

**Instantánea de Wikidata (LAB, 17-nov-2026 ~04:00 UTC).** Se tomó desde el servidor, en la imagen del backend.

- Los QID de los clubes salieron de la release fijada de Reep (la misma de IA-071, con los sha256 comprobados): se tomaron los clubes con **un solo** QID. Es una aproximación a lo que cargará AD-H01 con sus reglas.
- De los 1.642 clubes cuyo campo es uno de esos 1.301 estadios, 1.208 tienen QID. Así se puede llegar a **1.087 estadios** (83,6 %).
- **7 consultas**, una por minuto, en 426 s. La instantánea ocupa 1,29 MB y su sha256 es `7e56907a2609eac0e3f8ae70f534d1b0c844b151bad31ca93cef69db1e24656e`.
- 1.126 clubes tienen estadio local en Wikidata, con 1.200 ítems de estadio.

**Después de las reglas, esperado** (`venue-geo-v1`, sobre los 1.301 estadios usados):

| | Estadios | % de 1.301 |
| --- | ---: | ---: |
| Con ítem de Wikidata | 956 | 73,5 % |
| … por el nombre | 876 | |
| … por la ciudad, con un solo candidato | 80 | |
| Con coordenadas | 955 | 73,4 % |
| Con altitud de GLO-90 | 955 | 73,4 % |
| A la cola de revisión | 68 | 5,2 % |

La cola: 39 con un solo candidato sin confirmar, 10 con varios candidatos, 9 con un país que no cuadra, 6 con un QID compartido y 4 con varios candidatos por nombre.

- **Lectura del modelo de elevación:** 543 cuadrículas, 1.682 MB y 293 s. Las 955 lecturas fueron válidas.
- **Altitudes:** de −19,7 m a 4.084 m, con mediana de 71,5 m. 25 estadios están por encima de 2.000 m: Cusco 3.363 m, Quito (Rodrigo Paz) 2.729 m, Bogotá (El Campín) 2.552 m, Pachuca 2.387 m, Puebla (Cuauhtémoc) 2.213 m, Manizales 2.134 m…
- **Contraste con Wikidata:** solo 3 estadios traen P2044. Uno coincide y dos no:
  - Cuauhtémoc: 45,9 m en Wikidata frente a 2.213 m del modelo. Puebla está a unos 2.150 m, así que el error es de Wikidata.
  - Loftus Versfeld: 1.200 m frente a 1.351 m. Pretoria está a unos 1.340 m.

**Muestra revisada a mano (40 al azar, semilla 76).**

- Las 40 coordenadas caen en la ciudad del estadio.
- Las altitudes cuadran con la de la ciudad: Bogotá 2.552 m, Bucaramanga 1.017 m, Heidenheim 553 m, Ginebra (Lancy) 378 m.
- Hay **un estadio distinto en la misma ciudad**: «Gwangju Football Stadium» quedó enlazado, por la ciudad, al ítem del estadio mundialista de Gwangju, que es el que Wikidata da como campo del club. El método por ciudad (80 casos, confianza 0,8) tiene ese riesgo, y queda señalado por su método.
- **0 de 40 en otra ciudad.**
- En las 10 preguntas de la cola revisadas, mandarlas a revisión fue correcto. Ejemplos: el Lobanovski de Kiev con dos candidatos; el «Sanga Stadium by Kyocera», cuyo único candidato es el campo antiguo del club; el BC Place de Vancouver, con el Swangard como candidato.

**Partidos sin id (`venue-link-v1`)**, sobre las exportaciones de los partidos sin id del último año y los próximos 14 días:

| | Próximos 14 días | Último año + 14 días |
| --- | ---: | ---: |
| Partidos sin id | 863 | 22.684 |
| … con nombre | 633 | 13.308 |
| Enlazados | **394** | **8.078** |
| … `provider_history_team` | 341 | 6.569 |
| … `provider_history_city` | 11 | 378 |
| … `home_ground` | 40 | 1.028 |
| … `venue_name_city` | 2 | 103 |
| A la cola | 186 | 3.678 |
| Sin nada en que apoyarse | 283 | 10.928 |
| Enlaces a un estadio de otra ciudad (por texto) | **0** | **0** |

Con esto, los partidos de los próximos 14 días con estadio pasan de **425 (33,0 %)** a **819 (63,6 %)**.

**Sobre la primera versión de la regla.** Enlazaba por nombre y ciudad del historial sin comparar con la ciudad del estadio. Dejaba 56 enlaces cuya ciudad no coincidía, algunos de verdad erróneos: «Estadi de la FAF / Encamp» acababa en el Estadi Nacional de Andorra la Vella, y «HATO Stadium / Hikone» en Higashiomi. Ahora esos casos van a la cola (`city_differs`: 63 en los próximos 14 días). También van a la cola los que solo cambian de idioma, como Cologne/Köln o Cardiff/Caerdydd, porque un nombre en otro idioma no se adivina.

**Muestra de enlaces revisada a mano (60 al azar, semilla 761).**

- 0 en otra ciudad.
- Dos dudosos dentro de la misma ciudad:
  - «Jassim Bin Hamad Stadium» quedó enlazado al estadio Hamad bin Khalifa de Doha, porque el proveedor ya había dado ese id a ese nombre para el mismo club.
  - «Gifu Memorial Center Nagaragawa Ball Field» quedó enlazado al Nagaragawa Stadium, que está en el mismo recinto.
- El resto son el mismo estadio con otro nombre o con el patrocinio: Woudestein / Van Donge & De Roo, Anoeta / Reale Arena, Beira-Rio / José Pinheiro Borda, Morumbis / Cícero Pompeu de Toledo…

**Meta preregistrada para el cierre.** Medida tras cargar en producción, con los QID que acepte AD-H01:

- coordenadas en al menos el **70 %** de los estadios usados (esperado: 73,4 %);
- estadio en al menos el **60 %** de los partidos de los próximos 14 días (esperado: 63,6 %);
- **0 enlaces a otra ciudad** en una muestra de 60 revisada a mano.

Los scripts están en `docs/owner/lab/IA_076/lab_geo.py.txt`. Todo lo del servidor (`/tmp/lab_h03`) se borró.

## 6. Cómo se activa tras desplegar (manual, en el servidor, fuera de `fixtures_sync`)

Requiere que IA-071 esté cargada: sin QID de clubes no hay nada que buscar, y `fetch` lo dice.

```
python -m scripts.venue_geo fetch --out /srv/lab/venues/wd_AAAAMMDD.json   # ~7 consultas, una por minuto; imprime el sha256
python -m scripts.venue_geo load --snapshot /srv/lab/venues/wd_AAAAMMDD.json --sha256 <sha> --dem          # ensayo
python -m scripts.venue_geo load --snapshot /srv/lab/venues/wd_AAAAMMDD.json --sha256 <sha> --dem --apply  # cargar
python -m scripts.venue_geo link            # ensayo: enlaces de los partidos sin id (último año y próximos 14 días)
python -m scripts.venue_geo link --apply    # escribirlos; repetirlo no escribe nada
python -m scripts.venue_geo queue --kind fixture_venue --limit 30
python -m scripts.venue_geo decide 17 accept --chosen 556 --apply
python -m scripts.venue_geo status          # cobertura
```

- La lectura del modelo descarga unos 4 MB por cuadrícula: unos 2 GB en total la primera vez. No se guarda nada en disco.
- `link --apply` puede repetirse cada semana para los partidos nuevos. No hay tarea del worker.

## 7. Vuelta atrás

- **Una carga:** `python -m scripts.venue_geo retire ID --note "motivo" --apply`. Sus filas dejan de verse.
- **Un QID o un enlace:** `decide ... reject --chosen <qid|venue_id> --apply`.
- **Todo:** no leer las vistas. El dato del proveedor sigue intacto.
- **La migración:** su `downgrade` borra solo lo añadido; se perderían las decisiones de las personas. Haz antes la copia habitual.

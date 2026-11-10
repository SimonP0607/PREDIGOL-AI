# Ciudad y país de los estadios: el control y la reparación (BE-005)

Hallazgo C1 del plan de Partidos y Match Center (7-nov-2026): `GET /matches/9207` (Valencia–Real Madrid, LaLiga)
dice «Estadio de Mestalla, Avenida de Suecia, Spain» y ciudad **«Valdivia»** (Chile). Ningún control lo veía. Ahora hay
uno, y un script que propone la corrección **en seco** y solo escribe si tú lo pides.

Nada de esto pide nada al proveedor: lee la base y los payloads ya guardados (RAW).

## 1. Qué mira el control

Forma parte de la auditoría de verdad (`fbi/truth/venues.py`, dentro de los controles internos). Revisa cada estadio
donde se juega en casa un partido de la temporada actual de una **liga doméstica seguida** y deja un hallazgo
(conjunto `venues`, en `audit.truth_findings` y en la página de Verdad de datos) cuando:

| Campo | Cuándo avisa | Severidad |
|---|---|---|
| `country` | El país del estadio no es el de la competición **ni** el del club local (un club galés en la liga inglesa juega en Gales: eso no avisa) | Media |
| `city` | El último payload guardado del proveedor para ese estadio (`/venues?id`, `/teams?id` del club o el payload de origen) trae otra ciudad | Media (`mismatch`) |
| `city` | La mayoría de los partidos del propio estadio (su payload) dan otra ciudad | Media; Baja si el registro del proveedor coincide con la guardada (dos grafías del proveedor) |
| `city` | Esa ciudad solo es de estadios de **otro país** en la propia tabla y los partidos no la confirman (Valdivia: solo estadios chilenos) | Media |
| `venue_city` | Un partido concreto dice una ciudad que no dan los demás partidos del club en ese estadio (la ficha del partido enseña primero la ciudad de su propio payload) | Media |

Cada hallazgo trae el valor esperado («api»), el guardado («db») y la nota con las pruebas (qué payload, cuántos
partidos). El control **no corrige nada**.

Para verlo sin gastar peticiones:

```
docker exec -w /app predigol-worker python -m scripts.truth_audit --internal-only
```

Busca en el informe los hallazgos del conjunto `venues` (o en la página de Verdad de datos, filtro «Estadios (ciudad y país)»).

## 2. La reparación, en seco primero

```
docker exec -w /app predigol-worker python -m scripts.repair_venue_city --venue 80   # solo el estadio 80 (Mestalla)
docker exec -w /app predigol-worker python -m scripts.repair_venue_city              # todos los marcados
```

En seco **no escribe nada**. Imprime:

* `VENUE ... city 'Valdivia' -> 'Valencia' [payload ...]`: la ciudad del estadio se restauraría desde el último payload
  guardado del proveedor (se comprueba antes que el archivo vuelva a dar su hash).
* `FIXTURE ... venue_city 'Valdivia' -> 'Valencia'`: un partido cuya ciudad no dan los demás partidos del club en ese
  estadio; se le pondría la que dan ellos.
* `UNDECIDED ...`: lo que el script **no** corrige, con las pruebas. Dos casos: el propio proveedor dice la ciudad
  equivocada (no sirve corregirlo a mano: el próximo refresco de `/venues` o `/teams` la volvería a escribir; hay que
  avisar al proveedor), o no hay payload guardado que traiga ciudad. También si el payload del proveedor contradice a la
  mayoría de los partidos.
* `PROBLEM ...`: un archivo RAW que falta o no da su hash (se salta).

## 3. Aplicar (solo con tu OK)

1. Copia previa verificada: `docker exec -w /app predigol-worker python -m scripts.backup create --restore-test`.
2. Repite el seco y revisa la lista.
3. Aplica lo mismo que viste:

```
docker exec -w /app predigol-worker python -m scripts.repair_venue_city --venue 80 --apply
```

Cada valor cambiado deja una fila en `audit.data_repairs` (regla `venue_city_from_provider` o `fixture_venue_city`,
valor anterior, nuevo, motivo y el payload usado). Si algo cambió entre la lectura y la escritura, ese valor se salta y
sale como `PROBLEM`. Una segunda pasada no encuentra nada que hacer.

4. Comprueba: la ficha del partido 9207 debe decir «Valencia», y
   `python -m scripts.truth_audit --internal-only` ya no marca el estadio 80.

## 4. Si hay que deshacerlo

Los valores anteriores están en `audit.data_repairs` (`before_value`). La vuelta segura es restaurar la copia del
paso 1; no escribas SQL a mano en la base viva.

## 5. Restituir una reparación que se equivocó (BE-029)

La regla `fixture_venue_city` pone a un partido la ciudad que dan los demás partidos del club «en ese estadio». Si el
proveedor usa un mismo nombre para dos estadios de ciudades distintas (la Raiffeisen Arena de Pasching y la de Linz, el
Estadio Banco Guayaquil de Sangolquí, el Jawaharlal Nehru de Margao y el de Chennai), la mayoría puede ser la ciudad
equivocada. Una persona comprueba con fuentes que el valor del proveedor era el bueno y, solo entonces:

```
docker exec -w /app predigol-worker python -m scripts.restore_venue_city --venue 5094 --reason "motivo y fuente"          # en seco
docker exec -w /app predigol-worker python -m scripts.restore_venue_city --venue 5094 --reason "motivo y fuente" --apply  # escribe
```

* `--venue` es el id de `core.venues` (se puede repetir). Solo se tocan los partidos de esos estadios y solo los que
  siguen con la ciudad que puso la reparación: una ciudad cambiada después (por el proveedor o a mano) se deja.
* Cada partido deja una fila `audit.data_repairs` con la regla `fixture_venue_city_restored`: la ciudad que tenía, la que
  recibe, el motivo y la fila de reparación que deshace. Las filas originales no se borran.
* `repair_venue_city` y el control diario (BE-031) respetan lo restituido mientras el partido conserve esa ciudad.
* Ejecútalo en el contenedor del **worker** (el de la API no escribe en `core.fixtures`), con una copia de restauración
  probada y sin un despliegue en curso. Una segunda pasada no encuentra nada que hacer.

## 6. Reasociar partidos al estadio donde se jugaron (BE-037)

El proveedor guarda a veces **un mismo id de estadio para dos estadios distintos**: el id 143 es la Raiffeisen Arena de
Linz (abierta en 2023) y también el estadio del LASK en Pasching hasta 2022; el id 2276, los dos Jawaharlal Nehru.
`core.venues` ya tiene un registro por estadio, pero los partidos antiguos quedaron asociados al que lleva ese id y la
ficha mezclaba el nombre y la ciudad del partido con la capacidad y la dirección del otro estadio. No se crea ningún
registro: se reasocian los partidos.

```
docker exec -w /app predigol-worker python -m scripts.reassign_fixture_venue --from-venue 1334 --to-venue 9875 --city Pasching --reason "motivo y fuente"          # en seco
docker exec -w /app predigol-worker python -m scripts.reassign_fixture_venue --from-venue 1334 --to-venue 9875 --city Pasching --reason "motivo y fuente" --apply  # escribe
```

* Mueve solo los partidos del estadio de origen (`--from-venue`) cuyo propio campo ciudad es `--city`; el resto se queda.
  El en seco cuenta los que se moverían y los que se quedan.
* Se niega, sin escribir nada, si el estadio de origen no está demostrablemente en otra ciudad, si el de destino no está
  en la pedida o si alguno de los dos no existe. El id del proveedor, por sí solo, no es prueba suficiente.
* Una fila `audit.data_repairs` por partido con la regla `fixture_venue_reassigned` (`before_value`: el id de estadio que
  tenía; `after_value`: el nuevo). No cambia el nombre ni la ciudad del partido ni toca los estadios.
* La sincronización de partidos conserva el estadio nuevo mientras el proveedor siga mandando el id viejo (solo si hay
  fila de auditoría de ese partido); un id distinto se toma como siempre. El control diario no cuenta como diferencia de
  estadio un partido reasociado a propósito.
* La ficha de un partido reasociado enseña el nombre y la ciudad que dio el proveedor y adjunta capacidad y dirección solo
  si el nombre coincide con el del registro nuevo.
* Una segunda pasada no encuentra nada que hacer. Para deshacerlo, la vuelta segura es la copia previa; las filas de
  auditoría dicen qué partidos cambiaron y desde qué id de estadio (`before_value`).

**Aplicado el 10-nov-2026, 22:41 UTC** (ya desplegado BE-037 y con la copia de restauración probada del lanzamiento
`20261110T1608Z-auto-f544296`): 88 partidos de liga del LASK (51) y del LASK Juniors (37), de 2019 a 2022, pasaron del
estadio de Linz (`core.venues` 1334) al de Pasching (9875). Linz conserva sus 71 partidos, Pasching tiene 88, hay 88 filas
`fixture_venue_reassigned` y la segunda pasada no encontró nada que hacer. La ficha de esos partidos dice
«Raiffeisen Arena, Pasching» sin la capacidad ni la dirección del estadio de Linz.

## 7. Lo que queda abierto

* No sabemos todavía de dónde salió «Valdivia» (del proveedor o de un bloque de partido antiguo): lo dirá la línea del
  seco del estadio 80. Si sale `UNDECIDED ... the provider's own record says the same`, el fallo es del proveedor.
* Si el payload de un partido del proveedor repite la ciudad equivocada, la sincronización de partidos ya no la vuelve a
  escribir (BE-008, 8-nov-2026): antes de cambiar `venue_city`, mira en `audit.data_repairs` si esa misma ciudad fue la que
  corrigió la reparación (`fixture_venue_city`) y, si es así, deja la reparada. Una ciudad distinta que mande el proveedor
  se toma como siempre. El 8-nov la ficha de Valencia–Real Madrid volvió a «Valdivia» dos horas después de reparar: tras
  desplegar BE-008 basta con repetir el paso 3 una vez.
* Una ciudad con el mismo nombre en dos países (Córdoba, Mérida, León) solo se marca si sus partidos no la confirman.

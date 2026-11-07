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

## 5. Lo que queda abierto

* No sabemos todavía de dónde salió «Valdivia» (del proveedor o de un bloque de partido antiguo): lo dirá la línea del
  seco del estadio 80. Si sale `UNDECIDED ... the provider's own record says the same`, el fallo es del proveedor.
* Si el payload de un partido del proveedor repite la ciudad equivocada, la próxima sincronización de partidos la
  vuelve a escribir en ese partido; el control lo volverá a marcar.
* Una ciudad con el mismo nombre en dos países (Córdoba, Mérida, León) solo se marca si sus partidos no la confirman.

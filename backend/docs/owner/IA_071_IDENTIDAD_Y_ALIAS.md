# IA-071 · Identidad externa, alias y una sola clave de jugador

*Plan maestro de la arquitectura definitiva 2026, piezas AD-H01, AD-H02 y AD-H09 (sigue a IA-041, pieza INT-B03). Medido el 16-nov-2026.*

Esta pieza no cambia nada de lo que ve el lector. No toca modelos, probabilidades, picks ni liquidaciones, y no hace ninguna llamada a API-Football. Prepara tres cosas que luego usarán los perfiles (AD-H07, bajo `FBI_PROFILES`, apagado), la búsqueda (AD-I01) y el enlace de noticias con jugadores (AD-C06).

## 1. Qué problema resuelve

- **Identidad externa.** Hoy PrediGol solo guarda el id de API-Football. No hay ninguna columna con el QID de Wikidata, el id de Transfermarkt o el de Reep (lo comprobé en producción el 16-nov). Sin esos ids no se puede cruzar un jugador con otra fuente sin adivinar por el nombre.
- **Nombres dispersos.** Los alias están en dos tablas que no se hablan: `core.team_aliases` (119 filas, todas de football-data.co.uk) y `core.referee_aliases` (9.936 grafías de 6.111 árbitros). El resto de nombres está repartido por las columnas de cada tabla.
- **Dos claves de jugador.** Las plantillas y las noticias usan `provider_player_id`; favoritos y estadísticas usan `core.players.id`. Además, la posición viene en dos vocabularios: «Midfielder» en 55.118 jugadores y «M» en 11.393, más «SUB» (5) y «U» (1).

## 2. Qué se añade

Todo va en la **migración 0141** (`0141_entity_ids_aliases.py`, encadenada sobre la 0137). Solo añade cosas.

| Pieza | Qué es |
| --- | --- |
| `core.entity_id_loads` | Cada **carga** es una versión. Puede ser una release fijada de Reep (con el sha256 de su lista y de cada fichero) o una sincronización de nuestros propios nombres (`core`). |
| `core.entity_ids` | Un id externo de una entidad nuestra: Reep, QID de Wikidata o id de Transfermarkt. Guarda también el método, la confianza, la revisión de las reglas (`accepted` o `pending`), la evidencia y la carga de la que viene. |
| `core.entity_aliases` | Un nombre de una entidad nuestra: texto, clave normalizada, tipo (oficial, completo, corto, código, apodo, transliteración, localizado, anterior, alternativo), idiomas, escritura, fuente y el id de Reep por el que llegó. |
| `core.entity_identity_retirements` | Las filas que una carga posterior ya no trae. Nada se borra ni se reescribe: la fila queda oculta. |
| `core.entity_identity_queue` (+ `_queue_seen`) | La **cola de revisión**: lo que tiene que mirar una persona. |
| `core.entity_identity_decisions` | Lo que decide una persona (aceptar, rechazar, mismo, distinto, descartar) y cómo se deshace. |
| Vistas `core.entity_ids_live`, `core.entity_aliases_live`, `core.entity_identity_queue_open` | Lo que está en vigor ahora mismo. Los lectores futuros leen de aquí. |
| `core.position_group(text)` | El vocabulario único de posiciones (la misma tabla que `fbi.players.positions`). |
| `player_id` en `core.squad_members` y `ai.evidence` | `core.players.id` del `provider_player_id` de cada fila. Lo mantiene un disparador (`core.player_key_fill`), y las filas antiguas se rellenan por lotes. `provider_player_id` se conserva. |

Las tablas nuevas son de **solo añadido**: un disparador rechaza cualquier UPDATE o DELETE. La única excepción es el estado de una carga, que es lo que permite retirarla.

**Qué tienen todas las tablas de entidad en común:**

- `entity_type`: player, team, coach, competition, referee o venue.
- `entity_id`: siempre nuestro id (`core.players.id`, `core.teams.id`, `core.coaches.id`, `core.competitions.id`, `core.referees.id`, `core.venues.id`).

## 3. De dónde salen los ids y con qué reglas (`entid-v1`)

**Fuente.** Reep v1, release `2026-10-19.1`, la misma que midió IA-041. Es CC0 1.0. Se descarga en el servidor, en una carpeta de trabajo: el repositorio no guarda los datos, solo sus huellas (`fbi/people/identity/reep.py`, `RELEASES`). Si un fichero tiene otro sha256, la carga se rechaza. Para usar una release nueva hay que cambiar el código, y ese cambio se revisa como cualquier otro.

**Qué no se toca:**

- Wikidata: ninguna consulta en vivo.
- Transfermarkt: ni una página. De Transfermarkt solo se guarda el id tal como lo escribe Reep.
- API de pago de Reep: no se usa.

**Reglas** (`fbi/people/identity/rules.py`; las del Doc 3 son las cinco primeras):

1. **Solo por id.** Una entidad llega a Reep por el id de API-Football que ya tenemos. Ninguna regla busca por nombre.
2. **Un id, una entidad.** Si un id de API-Football apunta a dos entidades de Reep, no se enlaza nada y el caso va a la cola (`bridge_conflict`). Si un id externo le tocaría a dos entidades nuestras, no se le da a ninguna y va a la cola (`shared_external`).
3. **Menores sin enlazar.** Un jugador menor de 18 años el día de la carga, según su fecha de nacimiento, no recibe nada. Reep, además, ya retiene a 9.116 menores conocidos.
4. **El nombre no puede contradecir al id.** Los nombres de ambos lados tienen que compartir un apellido, o una inicial con su apellido («M. Salah» con «Mohamed Salah»). Si no lo comparten, el enlace queda como `pending` y va a la cola (`name_mismatch`). Detalles:
   - Un nombre de pila compartido no basta: dos «Mohamed» no son el mismo hombre.
   - Para equipos, competiciones y estadios se ignoran las palabras que tiene cualquier club («FC», «Club», «Real»…).
   - Unas siglas en mayúsculas valen como las iniciales del nombre largo («QPR» con «Queens Park Rangers»).
5. **QID y Transfermarkt van detrás del enlace de Reep.** Son los que Reep tiene para esa entidad. Su confianza es la del puente por la del enlace. Si el enlace de Reep está pendiente, ellos también.
6. **Homónimos.** Que dos jugadores nuestros se llamen igual no significa nada. Solo van a la cola dos casos:
   - mismo nombre y misma fecha de nacimiento (`possible_duplicate`: el proveedor puede tener al mismo hombre dos veces);
   - mismo nombre y fechas a 1–5 días (`near_birth_date`).

   Nunca van a la cola los gemelos (mismo apellido y fecha, distinto nombre de pila) ni padre e hijo (mismo nombre, una generación de diferencia).

**Una decisión de una persona sobrevive a la siguiente release.** Un enlace rechazado sigue rechazado aunque la próxima release lo vuelva a traer, y deshacer la decisión devuelve el caso a la cola. Una pregunta que una release posterior ya no plantea se cierra sola.

## 4. Qué se midió antes de cargar (producción, solo lectura, 16-nov-2026)

**Método.**

- Copié en CSV, en el servidor, las tablas de entidades: 196.445 jugadores, 18.494 entrenadores, 8.310 equipos, 165 competiciones y 7.159 estadios.
- Descargué la release fijada. Los siete sha256 coincidieron con los fijados.
- Pasé las reglas reales del código, sin base de datos, en la imagen del backend (`--network none`, 1 CPU, 3 GB). Tardó 266 s y usó 1,26 GB de memoria como máximo.
- Pasé las reglas dos veces, con la entrada en orden inverso: salieron las mismas 283.207 filas de ids.
- Scripts en `docs/owner/lab/IA_071/`.

**Cobertura por tipo de entidad.**

| Entidad | Nuestras | Con puente de API-Football en Reep | Reep aceptado | QID | Transfermarkt | Pendientes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Jugadores | 196.445 | 97.318 | 97.124 (49,4 %) | 64.505 (32,8 %) | 90.336 (46,0 %) | 10 |
| Entrenadores | 18.494 | 5.606 | 5.601 (30,3 %) | 3.760 | 5.450 | 5 |
| Equipos | 8.310 | 6.893 | 6.887 (82,9 %) | 3.189 | 5.831 | 6 |
| Competiciones | 165 | 160 | 156 (94,5 %) | 17 | 137 | 4 |
| Estadios | 7.159 | 20 | 18 (0,3 %) | 0 | 18 | 2 |
| Árbitros | 6.111 | — | — | — | — | — |

Notas sobre la tabla:

- Los árbitros no tienen id del proveedor, así que no hay puente posible y se quedan solo con sus nombres. Enlazarlos por nombre está prohibido.
- 184 jugadores menores no se enlazaron.
- La mitad de los jugadores sin enlace no tiene puente en Reep: son, sobre todo, jugadores de ligas menores y de alineaciones antiguas.

**Plantillas actuales.** 66.435 jugadores distintos: 35.718 con Reep (53,8 %), 27.411 con QID y 33.941 con Transfermarkt. Entre los 44.811 que tienen fecha de nacimiento, 35.635 tienen Reep (79,5 %). El universo es más amplio que el de IA-041, que solo medía las competiciones prioritarias (75,7 % por id exacto).

**Cola de revisión: 30 preguntas de enlace y 140 de homónimos.**

| Tipo | Jugadores | Entrenadores | Equipos | Competiciones | Estadios |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bridge_conflict` | 0 | 0 | 0 | 0 | 0 |
| `shared_external` | 4 | 1 | 4 | 0 | 1 |
| `name_mismatch` | 6 | 3 | 6 | 4 | 1 |
| `possible_duplicate` (homónimos) | 110 | — | — | — | — |
| `near_birth_date` (homónimos) | 30 | — | — | — | — |

Lo que se ve en la cola:

- En los `shared_external` de equipos, dos equipos nuestros comparten QID: «Tottenham» y «TOT», «Malmo FF» y «MAL». Es el equipo principal frente a un filial o un equipo femenino al que Reep da el mismo ítem de Wikidata.
- En los estadios hay un caso claro de enlace dudoso: «Etihad Stadium» frente a «The City Ground».
- Los `name_mismatch` de competiciones son cambios de nombre («Primera División» y «Liga 1» en Perú) y uno sospechoso («FA Cup» y «Korea Cup»).
- La regla de siglas bajó los `name_mismatch` de equipos de 25 a 6. Sin ella, «VVOG», «HIK» o «QPR» iban todos a la cola.

**Homónimos.**

- Hay 14.184 nombres repetidos que agrupan a 40.804 jugadores. La ficha decía 13.456 y 37.959, pero aquella cifra comparaba el nombre en minúsculas y esta compara la clave sin tildes ni puntuación.
- De los jugadores con nombre repetido, 10.692 no tienen fecha de nacimiento y no pueden ir a la cola.
- 91 parejas se descartaron por ser gemelos o hermanos.
- **Ninguna id de API-Football apunta a dos entidades**, y ningún id de Reep aceptado está en dos entidades nuestras. Este es el criterio de cierre.

**Nombres.**

- La release aporta 1.058.670 alias a las entidades enlazadas:
  - 340.559 transliteraciones;
  - 261.417 nombres completos;
  - 202.414 cortos o con inicial;
  - 143.135 alternativos;
  - 109.842 localizados;
  - 1.303 oficiales.
- Por escritura: 700.761 latinas, 122.027 cirílicas, 103.896 árabes y 70.976 CJK, entre otras.
- Nuestros propios nombres son unas 357.000 filas más: el oficial de cada entidad y el completo de jugadores y entrenadores. A eso se suman los 9.936 de árbitros y los 119 de equipos de las tablas antiguas.
- El volumen total ronda 1,4 millones de filas. El disco no está medido: estimo 0,5–0,7 GB con índices, y quedan 128 GB libres.

## 5. Precisión sobre una muestra etiquetada

**Umbral preregistrado** (fijado antes de mirar los resultados): límite inferior de Wilson al 95 % ≥ 95 % sobre al menos 300 enlaces verificables.

**Cómo se eligió y se verificó la muestra.**

- 450 enlaces Reep aceptados de jugadores, al azar con semilla 71, de los 97.124.
- Cada uno se comparó con Wikidata en el servidor: P569 (fecha de nacimiento), P2446 (id de Transfermarkt) y etiquetas. Se usaron 4 consultas SPARQL, respetando el límite de 1 por minuto que pedía el servicio.

**Cuándo un enlace es correcto:** el apellido es compatible y además, o la fecha coincide (±5 días), o, si no hay fecha, coincide el id de Transfermarkt.

**Cuándo un enlace no se puede verificar:** cuando no tiene QID y ningún ítem de Wikidata tiene su id de Transfermarkt. Para verificarlo habría que abrir Transfermarkt, y eso está prohibido.

**Cuándo un enlace es dudoso:** los dudosos se revisaron a mano.

**Resultado.** De los 450 enlaces, 319 se pudieron verificar y 131 no (29,1 %): no tienen QID y ningún ítem de Wikidata tiene su id de Transfermarkt.

- **Correctos por la regla automática: 316.**
- **Dudosos: 3**, revisados a mano:
  - «P. Polycarpou» frente a «Paris Polykarpou»: transliteración del griego, con la misma fecha y el mismo id de Transfermarkt.
  - «M. Rahman Jony»: mismo nombre completo y mismo id de Transfermarkt. Su fecha difiere 152 días entre API-Football y Wikidata.
  - «S. Mensah»: mismo nombre y mismo id de Transfermarkt, con 39 días de diferencia en la fecha.

  Los tres son la misma persona. La diferencia está en el dato de nacimiento de una de las dos fuentes, no en el enlace.
- **Incorrectos: 0.**

**Precisión: 319 de 319, límite inferior de Wilson al 95 % = 98,8 %. Cumple el umbral.** El resultado aguanta incluso en el peor caso: si los tres dudosos contaran como errores, serían 316 de 319, con un límite inferior del 97,3 %, que también lo cumple. Las primeras 300 de la muestra son la muestra inicial: 215 verificables, 215 correctas, límite inferior del 98,2 %.

**Límites de esta comprobación:**

- Mide la identidad de los enlaces de **jugadores**, no la de equipos ni entrenadores.
- Los 131 no verificables son sobre todo jugadores jóvenes o de ligas menores sin ítem en Wikidata. Su precisión no se puede comprobar sin fuentes que no usamos.
- La comparación de fechas es con Wikidata, que a veces tiene varias fechas o una distinta de la del proveedor.

## 6. Qué no cambia

- El lector. Ninguna pantalla ni API lee estas tablas todavía.
- `core.players`, `core.teams` y el resto de tablas del proveedor. Lo externo nunca pisa datos del proveedor. La única escritura en una tabla existente es el paso opcional `player-keys --create-missing`, que crea una fila de identidad mínima (id, nombre y posición, lo mismo que ya escribe la ingesta desde una alineación) para los jugadores que están en una plantilla y nunca aparecieron en un partido. Eran 10.208 el 16-nov.
- El contenido de `ai.evidence`. El disparador solo escribe `player_id`, que la guarda de contenido no mira. Ninguna afirmación cambia (lo comprueba la prueba de la migración).
- `core.team_aliases` y `core.referee_aliases`. Siguen escribiéndose como hasta ahora. La tabla nueva los copia en cada `sync-core`, y `audit` comprueba que los recuentos son iguales.
- Modelos, motores, prompts, interruptores, picks, `decision-v1`, pagos y cuentas.

## 7. Cómo se activa (en el servidor, tras desplegar)

Ningún paso es automático. Todo lo que escribe es un ensayo mientras no se pase `--apply`. En el contenedor del worker:

```
python -m scripts.entity_identity fetch --dir /tmp/lab_h01/reep           # ~280 MB, comprueba los sha256
python -m scripts.entity_identity load --dir /tmp/lab_h01/reep            # ensayo: qué escribiría
python -m scripts.entity_identity load --dir /tmp/lab_h01/reep --apply    # ~1,3 GB de memoria, unos minutos
python -m scripts.entity_identity sync-core --apply                       # nombres propios, tablas antiguas, homónimos
python -m scripts.entity_identity player-keys                             # cuenta las filas sin player_id
python -m scripts.entity_identity player-keys --create-missing --apply    # rellena por lotes de 2.000, lock_timeout 3 s
python -m scripts.entity_identity audit                                   # criterios; sale con 1 si falla alguno
rm -rf /tmp/lab_h01/reep                                                  # la descarga no se guarda
```

Conviene lanzar `player-keys` fuera de la ventana de `fixtures_sync`: es la lección del bloqueo del worker (AD-A05). Cada lote confirma por separado y cede si encuentra un bloqueo.

**Revisar la cola:**

```
python -m scripts.entity_identity queue --limit 40
python -m scripts.entity_identity decide <id> accept|reject|same|different|keep_a|keep_b|dismiss --note "..." --apply
python -m scripts.entity_identity undo --queue <id> --apply
```

## 8. Cómo se apaga o se revierte

- **Una release mala:** `python -m scripts.entity_identity retire <carga> --note "..." --apply`. Oculta lo que añadió y devuelve lo que retiró. No se borra nada.
- **Una decisión equivocada:** `undo --decision <id>` o `undo --queue <id>`.
- **La clave de jugador:** los lectores siguen usando `provider_player_id`, que no se toca. La columna `player_id` se puede ignorar.
- **Volver a la base de antes:** la vuelta atrás de la migración (`alembic downgrade 0137`) borra lo añadido. Las decisiones de las personas sería lo único que se perdería, así que antes hay que hacer la copia habitual.

## 9. Lo que queda pendiente

- **Ningún lector pasa todavía a la clave propia.** AD-H09 pedía «los lectores pasan a la clave propia», pero esos lectores son de UX y de AD-H07, y el cambio necesita su prueba de paridad. Aquí solo queda la columna, con un 100 % de relleno una vez aplicado `player-keys --create-missing`.
- **El vocabulario único de posición** está listo (`position_group` y `core.position_group`), pero C-09 (AD-H07) aún no existe para usarlo.
- **Normalización de alias en SQL.** `alias_key` está en Python. AD-I01 instalará `unaccent` y su envoltorio SQL, y tendrá que dar la misma clave: hay pruebas que fijan la equivalencia para la escritura latina.
- **Estadios.** Reep casi no los cubre (20 puentes). Su identidad llegará con AD-H04 (Wikidata y coordenadas).
- **Refresco.** Cada release nueva de Reep es un cambio de código con sus huellas. No hay una tarea periódica.

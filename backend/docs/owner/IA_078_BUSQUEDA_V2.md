# IA-078 e IA-081 · Índice de búsqueda y búsqueda v2 (C-10)

*Plan maestro de la arquitectura definitiva 2026, piezas AD-I01 (índice, IA-078) y AD-I02 (búsqueda v2, contrato C-10,
IA-081). Medido el 16 y el 17-nov-2026.*

Esta pieza **no cambia nada de lo que ve el lector hoy**. El buscador actual (`GET /api/v1/search`, el que usa la lupa de la
barra superior y la paleta de la consola) queda exactamente igual. Lo nuevo es una ruta aparte, `GET /api/v1/search/v2`,
que nadie llama todavía, y su versión privada para el dueño. No toca modelos, probabilidades, picks, liquidaciones ni
pagos, y no hace ninguna llamada a API-Football ni a ningún modelo de IA.

## 1. Qué problema resuelve

El buscador de hoy son tres `ILIKE '%texto%'` sobre competiciones, equipos y partidos:

- **No encuentra** jugadores, selecciones como grupo propio, entrenadores, árbitros ni estadios.
- **No ignora tildes**: «atletico» no encuentra «Atlético Ottawa»; «munchen» no encuentra «Bayern München».
- **No tolera erratas**: «barcelna» o «liverpol» no encuentran nada.
- **No entiende palabras sueltas**: «jam rod» no encuentra a James Rodríguez.

## 2. Qué se añade

### La migración 0145 (`0145_search_index.py`, IA-078)

Encadenada sobre la **0141** de IA-071 (alias, PR #349, en revisión). Solo añade cosas:

| Pieza | Qué es |
| --- | --- |
| Extensiones `unaccent` 1.1 y `pg_trgm` 1.6 | Vienen con PostgreSQL y estaban disponibles sin instalar. Son extensiones «de confianza»: las puede crear el dueño de la base (el rol `fbi`, el de las migraciones) sin ser superusuario. Comprobado en producción el 16-nov. |
| `core.search_key(texto)` | La única forma de normalizar un nombre: minúsculas, sin tildes, sin signos. «Atlético-Madrid, F.C.» → «atletico madrid f c». Otros alfabetos conservan sus letras (el cirílico no se translitera). |
| `core.search_entries` | Una **vista materializada**: una fila por cada nombre de cada equipo, selección, jugador, competición, entrenador, árbitro y estadio. Reúne los nombres propios (nombre, nombre corto, nombre + apellidos), las tablas de alias antiguas (`core.team_aliases`, `core.referee_aliases`) y los alias en vigor de IA-071 (`core.entity_aliases_live`). Guarda también lo que se enseña (nombre y subtítulo: país, equipo actual, ciudad) y una popularidad (partidos en competiciones seguidas, 400 días atrás y 60 adelante). |
| Cuatro índices | La clave única, uno para «empieza por», uno de palabras sin lematizar y uno de trigramas (erratas). |

La migración **crea la vista vacía** (`WITH NO DATA`): no lee ninguna tabla grande ni construye nada. En la copia tardó 0,5 s.

### La búsqueda v2 (C-10, IA-081)

| Ruta | Quién | Qué devuelve |
| --- | --- | --- |
| `GET /api/v1/search/v2?q=` | lector (mismas puertas que `/search`) | La proyección pública de C-10 |
| `GET /api/v1/admin/search/v2?q=` | solo dueño (`require_admin`) | La privada: además, la puntuación de cada resultado y el estado del índice (para calibrar) |

Nueve grupos, en el orden del contrato de UX: **Equipos, Selecciones, Jugadores, Competiciones, Entrenadores, Árbitros,
Estadios, Partidos, Noticias**; hasta 8 por grupo. Tres pasadas:

1. **prefijo** — el nombre empieza por lo escrito («atletico» → «Atletico Madrid»).
2. **palabras** — cada palabra escrita empieza una palabra del nombre, en cualquier orden («jam rod» → «James Rodríguez»). Desde 3 letras o dos palabras.
3. **trigramas** — el nombre se parece (erratas: «barcelna» → «Barcelona»). Desde 4 letras, umbral 0,6.

Dentro de cada grupo se ordena por: la pasada y lo cerca que está, un extra si lo escrito es el nombre entero o una palabra
entera, el tipo de nombre (oficial antes que apodo) y la popularidad. Partidos: los de los equipos encontrados, el más
cercano a hoy primero. Si nada aparece, «¿Quisiste decir…?» (`did_you_mean`) propone hasta 3 nombres cercanos.

Un grupo vacío siempre dice por qué: `sin_resultados`; **Noticias** dice `no_entregado` (`AD-G01`) porque aún no existen
noticias propias (`news.items`) — y cuando existan, solo se buscará por titular y resumen propios, nunca por el texto de un
artículo ajeno. Mientras el índice no se haya llenado, todos los grupos dicen `no_entregado` (`AD-I01`) y
`freshness.stale = true` con `indice_sin_construir`: la ruta se puede desplegar antes de llenar el índice sin romper nada.

El contrato está registrado en el mecanismo de IA-057 (`fbi/api/contracts/intelligence/search.py`, versión **1.0.0**) con
tres ejemplos (`tests/fixtures/contracts/intelligence/C-10/`: `encontrado`, `sin_resultados`, `sin_indice`). Las pruebas
genéricas comprueban que la pública no filtra nada privado y que la privada responde 403 a un lector.

## 3. Qué se midió (copia de producción, 17-nov-2026)

**Cómo:** exporté en solo lectura las columnas de nombres de 13 tablas de producción (equipos 8.310, de ellos 459
selecciones; jugadores 196.446; entrenadores 18.498; competiciones 165; árbitros 6.111; estadios 7.159; partidos 247.424;
alias de equipo 119 y de árbitro 9.937) a una base local PostgreSQL 16 en otra máquina (2 CPU compartidas), apliqué la
0145 y llené el índice. La copia se borró al terminar. Script y banco: `docs/owner/lab/IA_078/medir_busqueda.py.txt`.

| Medida | Resultado |
| --- | --- |
| Filas del índice | 365.437 (jugadores 316.416, equipos 10.661, entrenadores 21.891, árbitros 8.420, estadios 7.159, selecciones 725, competiciones 165) |
| Disco | 100 MB (44 MB la vista + 18/11/12/15 MB los cuatro índices). La base ocupa 31 GB con 133 GB libres |
| Primer llenado | 7,7 s |
| Refresco posterior (CONCURRENTLY: los lectores siguen viendo las filas viejas) | 15,9 s y 16,7 s |
| Latencia v2 (53 consultas × 5 rondas, mediana por consulta) | mediana 5,9–11,6 ms, p90 17–24 ms, máx. 28–41 ms (dos tandas) |
| Latencia de `/search` de hoy, misma copia y máquina | mediana 6,5 ms, p90 8,8 ms, máx. 112 ms |
| Recuperación en los 8 primeros del grupo esperado | **44 de 53 (83 %)** |

Por tipo de consulta: tildes 16/16, exactas 14/14, palabras 5/5, una o dos letras 3/3, transliterada 1/1, erratas 5/7
(fallan «mesi» y «halland»: hay jugadores reales que se llaman «Mesić» o «Helland»), idioma 0/3 («españa», «brasil»,
«alemania»), apodos 0/3 («cr7», «la pulga», «liga betplay») y cirílico 0/1. **Los siete últimos dependen de alias**, que
llegan con IA-071 (Reep/Wikidata) y aún no están cargados: sin ellos, 44 de 46 (96 %).

**El umbral 0,6 se queda:** con 0,5 y 0,45 la recuperación fue la misma (44/53) y la latencia subió (mediana 14,7–15,3 ms).

**Propuesta de umbral preregistrado (decide el dueño):** recuperación en los 8 primeros ≥ 90 % en las consultas que no
dependen de alias, ≥ 80 % en el banco completo una vez cargados los alias de IA-071, y p90 ≤ 50 ms.

Los planes de consulta usan los tres índices y nunca recorren la vista entera (lo comprueba la prueba de integración).

## 4. Qué no cambia

- `GET /api/v1/search` y su contrato `SearchHit` (mismos tres tipos, mismos campos, mismas consultas).
- Nada de la web (`web/`), ningún interruptor, ningún modelo, prompt, pick o probabilidad.
- El selector de favoritos sigue con su búsqueda propia (`translate()`); pasarlo a este servicio es un paso posterior.
- Ninguna tabla existente gana o pierde una columna.

**Importante para UX:** en producción `FBI_SEARCH` está **encendido** (`FBI_SEARCH=1` en `predigol-api`, comprobado el
17-nov). La lupa que ven hoy los lectores lee `/search`, que esta pieza no toca. Para usar C-10, la web cambia a
`/search/v2` cuando lo decida UX.

## 5. Cómo se activa en el servidor (una vez desplegado)

1. La migración 0145 la aplica el despliegue como cualquier otra (rol `fbi`). Crea las extensiones y la vista vacía.
2. Llenar el índice, **fuera de `fixtures_sync` y nunca entre 03:50 y 05:00 UTC** (el script se niega solo):

   ```
   docker compose run --rm ops python -m scripts.search_index status
   docker compose run --rm ops python -m scripts.search_index refresh            # simulacro: dice qué haría
   docker compose run --rm ops python -m scripts.search_index refresh --apply    # lo hace
   ```

   Tiene que ser el contenedor `ops` (el dueño de la base): solo el dueño de una vista materializada puede refrescarla.
3. Refrescarlo cuando haga falta (tras cargar alias de IA-071, o una vez por semana). No hay trabajo programado: si el
   índice tiene más de 7 días, la respuesta lo dice (`indice_antiguo`).

## 6. Cómo se apaga o se revierte

- **Apagar:** no hay nada encendido. Ningún lector llama a `/search/v2` hasta que la web lo use.
- **Revertir la migración:** `alembic downgrade 0141` borra la vista y la función, y las extensiones solo si nada más las usa.
- **Revertir el código:** quitar las dos rutas no afecta a `/search`.

## 7. Pendiente

- Cargar los alias de IA-071 en producción y refrescar el índice: resolvería idioma, apodos y cirílico.
- Noticias (AD-G01): cuando exista `news.items`, añadir su grupo al índice (cambio aditivo: versión 1.1.0).
- Contexto del lector (sus favoritos) en el orden: no está; el plan lo pide para más adelante.
- El selector de favoritos y la paleta de la consola pasando a este servicio («un solo buscador en el código»).
- Que el dueño fije el umbral preregistrado del banco (propuesta en el punto 3).

## 8. C-10 1.1 (IA-161, 24-nov-2026): nombres en español e inglés y la selección absoluta primero

Lo pidió el plan de correcciones UX/UI (AP-B02, AP-B07, AP-E02; `claude/INTEGRACION_CONTRATOS_INTELLIGENCE_1_1_20261123.md`).
**Mismo contrato, sin campos nuevos**: sube a 1.1.0 porque cambia lo que encuentra y el orden, no la forma.

- **Los nombres.** `fbi/people/identity/localized.py`: el nombre en español e inglés de cada selección que el proveedor
  nombra (213 países y naciones, 227 nombres del proveedor; los de CLDR 48, revisados para el fútbol: «Costa de Marfil», «Palestina», «China Taipéi»…;
  las cuatro naciones del Reino Unido a mano) con su sub-17…sub-23 («Alemania Sub-21») y su femenina («México Femenina
  Sub-17»), y 69 competiciones («Mundial», «Copa del Mundo», «Liga de Campeones», «Eurocopa», «Copa de Alemania»,
  «Supercopa de España»…). Una selección se reconoce por su nombre del proveedor y `is_national`; una competición por su
  nombre y país. Lo que la tabla no conoce no recibe nada: no se adivina.
- **Por dónde entran.** Como alias `localized` con su idioma (`{es}` o `{en}`) y fuente `localized` (migración 0173: solo
  añade ese valor a la lista permitida), dentro de la carga de nuestros nombres (`sync-core`), y de ahí al índice.
- **El orden.** En Selecciones, una sub-NN o femenina va detrás de toda absoluta encontrada, salvo que la consulta la pida
  («sub 21», «u21», «femenina», «women»).

Para que se vea en producción, tras desplegar (fuera de 03:50–05:00 UTC y de `fixtures_sync`):

```
docker compose run --rm ops python -m scripts.entity_identity sync-core            # simulacro: cuenta lo que añadiría
docker compose run --rm ops python -m scripts.entity_identity sync-core --apply
docker compose run --rm ops python -m scripts.search_index refresh --apply
```

Vuelta atrás: `python -m scripts.entity_identity retire <load> --note "..." --apply` oculta la carga y trae la anterior
(después, `search_index refresh --apply`). Preguntas para el dueño: los **países** no son entidades del índice (no hay página
de país): «España» lleva a la selección, no a «el fútbol de España»; si se quiere un grupo de países, es un contrato nuevo.

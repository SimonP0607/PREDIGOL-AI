# IA-062 e IA-063 · Registro de fuentes v2, lista de exclusión y política de acceso por fuente

Piezas AD-C01 (IA-062) y AD-C02 (IA-063) del plan maestro de la arquitectura definitiva 2026. No cambia probabilidades, umbrales,
picks, `decision-v1`, prompts, motores ni la muestra de la sombra. Lo único que cambia desde el primer despliegue es **qué páginas se le
dan a leer al extractor** (investigación v1 y v2) y al analista. **Efecto indirecto en el lector:** las tarjetas de «Noticias» de un
partido salen de `ai.evidence`; desde el despliegue no se crean evidencias nuevas de webs de apuestas, de resultados sin redacción, de
`exa.ai` ni de medios con reserva de IA (en 14 días habrían sido 734 de 5.981 evidencias, el 12,3 %). Las ya guardadas siguen ahí.

## 1. Qué hay ahora

**El directorio v2 como datos versionados.** `backend/config/sources/directorio_v2_2026-11-16.json` (2.001 fuentes con sus 52 campos,
ordenadas por identificador, una por línea) y `backend/config/sources/exclusion_dominios_2026-11-16.csv` (559 dominios que Exa trajo en
60 días, con su clase). Los dos ficheros están **fijados por su huella** (sha256) en `fbi/ai/source_registry.py`: si alguien los edita a
mano, el cargador los rechaza. Un directorio nuevo es un fichero nuevo con su huella nueva, nunca una edición del anterior.

**Cinco tablas de solo añadido** (migración `0139`):

| Tabla | Qué guarda |
| --- | --- |
| `ai.source_registry_versions` | Cada fichero cargado: nombre, huella, filas y recuentos. La versión se llama como su contenido; la más reciente de cada tipo es la vigente |
| `ai.source_registry` | Una fila por fuente y versión: estado, familia, tipo, los cuatro permisos, la autoridad por tipo de afirmación, la fecha de la última revisión y el registro completo |
| `ai.domain_rules` | La lista de exclusión: dominio, clase y acción (`block` para las cuatro clases seguras, `review` para los dudosos, `none` para el resto) |
| `ai.source_signoffs` | Tus firmas: el paso de una fuente a autorizada, su revocación y la firma de la lista de exclusión |
| `ai.source_policy_log` | Cada página que la política apartó de un modelo, o que habría apartado (sombra): cuándo, en qué camino, qué fuente, por qué |

`ai.sources` (402 dominios, los niveles de `tiers-v1`) **no cambia**: el nivel de cada evidencia sigue saliendo de ahí.

**Un único punto de decisión en el código** (`fbi/ai/source_policy.py`): `can_fetch`, `can_extract`, `can_store` y
`can_publish(fuente, tipo_de_afirmación)`. La tabla que aplica es la del directorio v2 (sección 6):

| Estado | Lectura automática | Extracción por IA | Almacenamiento | Publicación |
| --- | --- | --- | --- | --- |
| Verificada y autorizada **y firmada por ti** | Sí (si robots lo permite) | Sí | Hechos con cita breve | Titular y resumen propios, con enlace |
| Verificada y autorizada sin tu firma | como pendiente | | | |
| Pendiente de derechos | No | No | Título, fecha y enlace | Solo enlace |
| Solo referencia (reserva de IA) | No | **Nunca** | Título, fecha y enlace | Solo enlace |
| No comprobada, bloqueada o fuera del directorio | No | No | Nada | Nada |
| Dominio excluido | No | No | Nada | Nada |

`can_publish` devuelve además la autoridad de la fuente para ese tipo de afirmación (`confirma`, `informa`, `solo_rumor`,
`sin_autoridad`, o `desconocida` si el directorio no lo dice): nadie la publica todavía; la usará AD-G04.

## 2. Las tres reglas, de la más dura a la más suave

1. **Reserva de IA: siempre, sin interruptor.** Una fuente cuyo robots o cuyos términos reservan el texto frente a la IA, cuyos términos
   prohíben la lectura automática, o que el directorio dejó en «solo referencia», **nunca llega a un modelo** y su texto no se guarda en
   la caché (sí su título, fecha y enlace). Son 77 fuentes del directorio v2 (ESPN, Sky Sports, El Tiempo, kicker, ANSA, el grupo
   National World…). En la UE esa reserva desactiva la excepción de minería de textos (Directiva 2019/790, art. 4.3). Si no se puede
   leer ningún registro, nada llega a un modelo (falla cerrado).
2. **Lista de exclusión: `FBI_SOURCE_EXCLUSION`, aplicada por defecto.** Los 117 dominios de las cuatro clases seguras (apuestas y
   pronósticos, resultados sin redacción, contenido generado, no fútbol; `exa.ai` incluido) se quitan de los resultados de Exa antes de
   que nadie los lea. Los 165 dudosos **no** se quitan: quedan en revisión (`review`), en tu cola.
3. **Solo fuentes autorizadas: `FBI_SOURCE_POLICY`, en sombra por defecto.** Aplicada hoy dejaría la investigación casi sin fuentes
   (ver la medición), así que por defecto **solo registra**, página a página, qué habría bloqueado y por qué. Cambiarla a `enforce` es
   decisión tuya, tras revisar los términos de las pendientes.

Los dos interruptores se leen del entorno del worker (y de la API para el analista); no están en el registro de interruptores de
Intelligence ni los lee ningún agente.

## 3. Qué se midió en producción (solo lectura, 16-nov-2026)

Ventana: 3-nov 05:05 a 16-nov 18:07 UTC (14 días). Cada página o evidencia se clasificó con la misma regla del código
(el dominio registrado más específico decide).

| | Total | Excluidas (lista) | Reserva de IA | Autorizadas | Resto (pendientes, bloqueadas, no comprobadas, desconocidas) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Páginas leídas por el extractor v1 | 3.094 | 435 (14,1 %) | 34 (1,1 %) | 1 | 2.624 |
| Resultados distintos de Exa | 4.665 | 677 (14,5 %) | 50 (1,1 %) | 1 | 3.937 |
| Evidencias web guardadas (v1 y v2) | 5.981 | 663 (11,1 %) | 71 (1,2 %) | 3 | 5.244 |
| … de ellas CONFIRMED o PROBABLE | 1.739 | 50 | 41 | 0 | 1.648 |

- **Lo que se aplica ya** (lista y reserva) habría quitado 469 de las 3.094 páginas leídas por v1 (15,2 %). Solo 1 de las 565 llamadas
  de extracción v1 tenía únicamente páginas excluidas: el ahorro está en las páginas, no en las llamadas; las plazas que dejan libres
  las ocupan otras páginas del mismo resultado.
- **La regla dura cuesta algo**: 41 evidencias CONFIRMED o PROBABLE de fuentes con reserva de IA en 14 días (ESPN 22 evidencias, The Star
  19, Noticias Caracol 6, Sky Sports 5…). Es el precio de no usar con un modelo lo que su dueño reservó.
- **El modo estricto en `enforce` dejaría 1 página de 3.094** (99,97 % bloqueada) y 3 evidencias de 5.981. Por eso queda en sombra.
- Las 3.006 páginas que leyó la investigación v2 no se pueden clasificar por dominio con lo guardado (su clave en la caché es un hash);
  sus evidencias sí están en la fila de evidencias.
- Coste: en esos 14 días las llamadas de extracción costaron 0,68 USD (v1, 629 llamadas) y 0,43 USD (v2, 560): el ahorro en dinero es
  pequeño; lo que se gana es no leer apuestas ni páginas del buscador, y cumplir las reservas.

Estas cifras salen de `ai.research_cache`, `ai.evidence` y `ai.usage` (consultas en la entrega de la pieza). «CONFIRMED o PROBABLE» no es
lo mismo que los «útiles» de la medición de 60 días del directorio: no se comparan entre sí.

## 4. Qué no cambia

- `ai.sources` y el nivel de las evidencias. El informe `tiers` compara el nivel que implicaría el directorio con `tiers-v1` en los 402
  dominios: 295 están en el directorio y coinciden 286; los 9 cambios (8 «agregador» que el directorio llama medio o proveedor de datos, y
  `dimayor.com.co`) quedan en una lista para que la firmes antes de que nada los lea.
- Exa: se le pide lo mismo y se le paga lo mismo (cobra por búsqueda). Las estadísticas por dominio (`ai.source_stats`) siguen contando
  todos los resultados.
- Nada del lector, de los agentes, de los prompts ni de la muestra de la sombra.

## 5. Después de desplegar (en el servidor)

1. `docker exec predigol-worker python -m scripts.ia_sources_load load` — carga el directorio y la lista (idempotente: repetirlo no
   escribe nada). Hasta que se ejecute, la política lee los mismos ficheros fijados de la imagen, así que no hay hueco.
2. `docker exec predigol-worker python -m scripts.ia_sources_load status` — versiones vigentes, recuentos por estado (deben ser 3 /
   1.289 / 71 / 153 / 485) y las tres autorizadas que esperan tu firma.
3. Cuando quieras ver qué hace la sombra: `... ia_sources_load shadow --days 14`.
4. Una página concreta: `... ia_sources_load check-url https://...`.

## 6. Lo que firmas tú

- **El paso de una fuente a autorizada** (hoy: Agência Brasil Esportes, El Nuevo Día de Ibagué y À Punt Esports):
  `... ia_sources_load sign --source bra-agencia-brasil-esportes --reason "términos leídos el ..." --confirm-owner`. Sin
  `--confirm-owner` se niega. `--revoke` lo retira; manda la firma más reciente.
- **La lista de exclusión**: `... ia_sources_load sign-exclusion --reason "..." --confirm-owner`. El filtro no espera a esta firma (el
  plan aprobado lo aplica ya); la firma deja constancia de que la revisaste.
- **`FBI_SOURCE_POLICY=enforce`**, cuando las pendientes tengan los términos revisados (AD-G05, con abogado).

## 7. El comprobador periódico (diseño; no está programado)

`python -m scripts.ia_sources_check --limit 20` (o `--source <id>`; `--dry-run` para ver a quién preguntaría). Por cada fuente hace
**una** petición propia a su `robots.txt` (sin Exa, sin modelo, sin reintentos, con pausa entre dominios y un User-Agent honesto). No
pregunta nunca a una fuente bloqueada (no se reintenta por otra vía), ni a una con reserva, ni a un dominio excluido. Solo propone
cambios hacia más estricto: reserva de IA en robots → «solo referencia»; robots ilegible o que rechaza → «bloqueada»; autorizada sin
revisar en 90 días → pendiente. **Nunca sube a nadie a autorizada.** No escribe en la base: imprime propuestas, que se convierten en una
versión nueva del directorio. Cuándo y cada cuánto programarlo lo decides tú.

## 8. Cómo se apaga o se revierte

- Lista de exclusión: `FBI_SOURCE_EXCLUSION=shadow` (solo registra) o `off` (ni quita ni registra) y reiniciar el worker (un minuto).
- Modo estricto: ya está en sombra; `FBI_SOURCE_POLICY=enforce` se deshace quitando la variable.
- La regla de reserva de IA **no se revierte** con un interruptor: por diseño.
- La migración se puede bajar (`alembic downgrade 0137`; se pierden las cinco tablas, el directorio sigue en el repositorio).

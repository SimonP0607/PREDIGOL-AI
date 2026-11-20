# PREDIGOL — PLAN MAESTRO DE INNOVACIÓN, COBERTURA MUNDIAL Y APROVECHAMIENTO INTEGRAL DE RECURSOS 2026–2027

*Versión del 19-nov-2026. Etapa de planificación: no implementa nada, no modifica el repositorio y no abre ningún PR. No es asesoría legal y no promete rentabilidad.*

> **Copia publicada en el repositorio** por PM-00-01 (DOC-004) el 19-nov-2026, el mismo día en que el dueño aprobó el plan completo y las decisiones DM-01 a DM-14 según su recomendación. El repositorio es público: frente al original se han quitado los detalles de los hallazgos de la auditoría de seguridad (quedan sus consecuencias) y el enlace al lienzo privado. Las reservas de zona por bloque están en el documento de coordinación de sesiones del proyecto. Los anexos ligeros E y G están en [`plan_maestro_pm_2026/`](plan_maestro_pm_2026/); el resto (A–D, F, H e I) son pesados o internos y se conservan en el proyecto del dueño.

## 1. Resumen ejecutivo

PrediGol puede pasar de 138 a 200 competiciones seguidas, y aprovechar lo que ya paga, sin cambiar de plan ni de servidor. El cupo sobra: de media usa el 24 % del límite del proveedor (17.845 de 75.000 peticiones al día) [D]. Lo que limita es la cobertura real del dato y la memoria del worker, al 93 % de 3 GiB.

Este documento es solo el plan. No implementa nada, no modifica el repositorio y no abre ningún PR. No es asesoría legal y no promete rentabilidad.

### Cómo leer las cifras

Cada cifra lleva su origen. Una hipótesis nunca se presenta como hecho.

| Marca | Significado |
|---|---|
| [M] | Medida en producción o en el proveedor el 19-nov-2026, salvo otra fecha indicada |
| [C] | Leída en el código o la configuración del repositorio (clon `4feb5d2`) |
| [P] | Afirmación del proveedor o de un tercero, leída en su página |
| [D] | Derivada con aritmética a partir de cifras medidas |
| [S] | Supuesto de este plan; se sustituye por una medición en la tarea indicada |

### Lo urgente

La suscripción de API-Football vence el 29-nov-2026 a las 21:45 UTC [M]. Es de prepago y no se renueva sola [P]. Si nadie paga, la cuenta baja a 100 peticiones al día [P]. PrediGol usa unas 17.800 [M]. Es la decisión DM-01 y va antes que todo lo demás.

### Las diez conclusiones

1. **Dos dimensiones separadas.** La prioridad editorial dice qué importa al dueño (P0 a P4). La cobertura técnica dice qué dato existe (A a D). Ninguna condiciona a la otra.
2. **Niveles medibles.** A exige 95 % con 30 partidos; B, 80 % con 10; C, 50 %; D, menos de 50 %. Se aplican por competición, temporada, dato y mercado. Son umbrales que ya usa el código [C].
3. **Hoy, por resumen:** 45 competiciones en A, 35 en B, 27 en C, 19 en D y 12 con muestra insuficiente [M]. El resumen solo sirve al directorio; cada pantalla decide por dato.
4. **Una matriz de disponibilidad** será la única fuente de verdad. Distingue siete estados, del «existe el dato» al «cumple las reglas del módulo». Reutiliza cinco piezas que ya existen.
5. **Altas: 62 competiciones en seis lotes.** Cuestan unas 1.400 peticiones al día de media [S] y unos 9,5 GB al año como máximo [S]. Once pedidas no existen en el proveedor [M].
6. **API-Football ya se pide entero.** Solo falta un parámetro con valor: `half=true`. El resto de lo desaprovechado ya está guardado y cuesta cero peticiones [C].
7. **Ningún proveedor de fútbol nuevo.** Lo que ofrece RapidAPI duplica lo contratado o procede de extracción sin permiso [P]. Las redes sociales son canales, no fuentes.
8. **Las 59 oportunidades tienen destino.** Se implementan 17, se completan 17 y se conserva 1. Tres se integran en otro plan y 13 van al LAB privado. Cuatro se aplazan y 4 se descartan.
9. **El plan son 108 tareas, 16 bloques y 7 olas.** Cada tarea lleva sus 20 campos en el anexo H.
10. **Escenario recomendado: B.** Usar más dentro del plan Ultra actual, con reserva. Media prevista de 18.300 peticiones al día [S], sobre un presupuesto interno de 60.000 [C].

### Qué necesita del dueño

Hay 14 decisiones en el registro (sección 14 y anexo I). Tres bloquean el arranque: renovar API-Football (DM-01), aprobar el plan y el escenario (DM-02) y fijar los umbrales (DM-04).

### Qué no hace este plan

- No rediseña Mi parlay. Solo cambia de dónde lee sus reglas, con igualdad exigida.
- No saca nada predictivo de sombra sin firma. `FBI_PICKS_SOURCE` sigue apagado.
- No deja que un modelo de lenguaje toque probabilidades.
- No borra historia, evaluaciones, copias ni dependencias necesarias.
- No sube los sobres de IA: 185, 55 y 35 USD al mes [C].

## 2. Estado actual y reconciliación con los planes existentes

De las 59 oportunidades, 1 ya está implementada, 20 están a medias, 3 las ejecuta otro plan y 35 no existen en el repositorio [C]. Siete planes siguen vivos y hoy no hay ninguna reserva de zona activa.

### Punto de partida

| Dato | Valor | Origen |
|---|---|---|
| HEAD de `main` | `4feb5d2`, 19-nov-2026 10:13 UTC | [C] |
| Última migración | `0167_stat_documents` | [C] |
| Competiciones seguidas | 138 (83 ligas y 55 copas); 27 más cargadas sin seguir | [M] |
| Con reglamento codificado | 11 | [C] |
| Base de datos | 36,33 GB; 304 tablas en 14 esquemas | [M] |
| Servidor | 6 vCPU, 11,68 GiB de RAM, 123 GB libres de 193 | [M] |
| Worker | 2,80 de 3 GiB (93,4 %); tocó el límite 4.160 veces en 10 horas | [M] |
| Consumo de API-Football | Media de 17.845 al día en 30 días; máximo normal de 23.430 | [M] |
| Siguientes códigos libres | CI-020, SEG-003, UX-173, BE-051, FE-004, OPS-007, DOC-004, IA-145 | [C] |

La API de GitHub no estaba disponible en la lectura. Los PR abiertos no se pudieron listar.

### Planes vigentes y sus zonas

| Plan | Estado el 19-nov-2026 | Zona reservada que este plan debe respetar |
|---|---|---|
| Arquitectura definitiva (AD) | Código desplegado; 23 interruptores en sombra | `fbi/ai`, `intel`, `chronicle`, `competitions`, `venues`, `people`, `config/rules`, `config/sources`, `config/expansion.yaml` |
| Estadísticas avanzadas (EA) | Desplegado y encendido; 8 piezas bloqueadas por datos | `fbi/stats`, `fbi/market/{in_force,eligibility,settle_coverage}.py`, C-13, C-14, carpetas `stats` de la web |
| Unificado UX e Intelligence | Olas 0 a 2 desplegadas; UX-159 a UX-171 sin empezar | Casi todo `web/**`; los números UX-159 a UX-171 están tomados |
| Intelligence 2026 | Protocolos E4 y E6 vivos hasta marzo de 2027 | `fbi/research/protocol.py`, `ai.feature_gates` |
| Cuotas | Cerrado y encendido | `fbi/odds`, `routers/odds_explorer.py` |
| Medición de picks | En curso; `decision-v2` en sombra | `fbi/picks` |
| Seguridad | Auditoría entregada; sin plan aprobado | Accesos, llaves, `grants.sql`, copias y despliegue |

Regla de coordinación: reservar por escrito antes de tocar una zona compartida. Primero el contrato y después el consumidor. La tarea PM-00-01 abre las reservas.

### Qué cambia respecto de la matriz original

| Oportunidad | La matriz decía | El repositorio dice | Efecto en este plan |
|---|---|---|---|
| OP-13, OP-16, parte de OP-12 | «No consta» | El Plan EA lo hizo el 18 y 19-nov | Se pide solo el resto |
| OP-29 | «En LAB sin registrar» | INT-A02 la rechazó el 11-nov | Solo un protocolo nuevo |
| OP-44 | «INP solo en laboratorio» | Se mide en el 3 % de las visitas reales | Leer antes de optimizar |
| OP-06 | «El proveedor no da córners por mitad» | `half=true` existe y no se pide | Se construye tras la sonda |
| OP-09, OP-01 | Piden desarrollo | Piden firmas y esperar muestra | Pasan a decisiones |

### Convenciones que obligan a cada tarea

- Un código `ÁREA-NNN` por cambio, con su fila en `REGISTRO_CODIGOS.md` en el mismo PR. `PM-…` es nombre de pieza, no código.
- Fusión por squash; `main` protegido; nunca rebase.
- Migraciones solo aditivas y solas en su PR. Toda tabla nueva lleva su entrada en `grants.sql`.
- Cadena de despliegue con copia y prueba de restauración. Tarda cerca de 1,5 horas.
- Todo lo nuevo y visible nace apagado.
- No se despliega entre las 03:50 y las 05:00 UTC ni durante una `fixtures_sync`. Tampoco a las 07:20 UTC ni los lunes a las 06:00 UTC.

### Lo que impone la auditoría de seguridad

| Hallazgo | Consecuencia para este plan |
|---|---|
| Política de copias (decisión D1 de la auditoría, pendiente) | Nada de archivo frío ni de mover datos antes de la decisión D1 |
| Fusionar equivale a ejecutar en producción | PR pequeños, interruptor apagado, ningún dato sensible en Actions |
| Accesos y llaves del servidor | Ninguna llave, acceso ni privilegio nuevo |
| Permisos en la base de datos | Cada tabla nueva con permisos explícitos |
| battery-v4 no pasa en `match` ni en `extract` | Nada con modelo de lenguaje sale de sombra |
| La calificación ignora la competición (H-EST-01) | Las ligas nuevas nacen sin probabilidad autorizada |
| Regla 2: no borrar | Las retiradas apagan o dejan de instalar; no borran |

### Contradicciones

La nota de reconciliación lista 16 contradicciones entre documentos y código. La nota de pendientes añade 5 nuevas. La sección 15 dice cuáles quedan abiertas. La tarea PM-00-03 corrige las documentales.

## 3. Cobertura mundial de competiciones

El proveedor lista 162 competiciones pedidas o relacionadas. De ellas, 90 ya se siguen, 61 se pueden dar de alta y 11 no tienen edición vigente [M]. Otras 11 pedidas no existen en el proveedor [M]. Con la Liga Femenina de Colombia, que este plan propone, las altas son 62. El proveedor lista 1.253 competiciones; PrediGol sigue 138 [M].

### Dos dimensiones que no se mezclan

La prioridad editorial es una decisión del dueño. La cobertura técnica es una medición. Una competición puede ser P0 y nivel D, como la Primera B de Colombia.

| Prioridad editorial | Qué incluye | Filas en el anexo A | Seguidas hoy | Altas propuestas |
|---|---|---|---|---|
| P0 Colombia | Primera A, Primera B, Copa, Superliga y Liga Femenina | 5 | 2 | 3 |
| P1 Internacionales | Clubes y selecciones listados por el dueño | 41 | 30 | 4 |
| P2 Países prioritarios | Primeras, segundas, copas y supercopas de 26 países | 120 | 58 | 47 |
| P3 Resto actual | Todo lo demás que ya se ingiere: se mantiene | 63 | 48 | 0 |
| P4 Pirámide inglesa 5 a 7 | Niveles 5, 6 y 7 y FA Trophy | 8 | 0 | 8 |
| Sin prioridad | El resto del catálogo del proveedor | 1.027 | 0 | 0 |

Las 138 seguidas hoy se mantienen todas. Las 15 cargadas y no seguidas que nadie pidió quedan como están.

### Qué existe y qué no

- **Existen todas las internacionales pedidas** [M]: Libertadores, Sudamericana, Recopa, Champions, Europa League, Conference, Mundial de Clubes, Intercontinental, CONCACAF, CAF, AFC y OFC; Mundial, eliminatorias de las seis confederaciones, Copa América, Eurocopa, Nations League, Copa Oro, Copa Africana y Copa Asiática.
- **Existe toda la pirámide inglesa hasta el nivel 7** [M], con sus copas.
- **No existen** [M]: segunda división, copa y supercopa de Panamá; supercopas de Dinamarca, Escocia, Austria, Estados Unidos, Corea del Sur y Australia; segunda división nacional de Australia; Durand Cup de la India.
- **Descontinuadas en el proveedor** [M]: Copa MX y Coupe de la Ligue (última temporada 2019), Copa de la Liga Profesional (2024).
- **Cíclicas sin edición abierta** [M]: OFC Nations Cup, clasificación de la Copa Asiática, de la Eurocopa y de la Copa Oro, y Supercopa de Japón. Se dan de alta cuando el proveedor liste la edición siguiente.

Las inexistentes quedan documentadas como limitación. La tarea PM-03-08 avisa si el proveedor las añade.

### Países pedidos: situación

| País | Seguidas | Altas | No existe |
|---|---|---|---|
| España, Italia, Alemania, Turquía | 4 cada uno | 0 | 0 |
| Francia | 4 | 0 | 0 (Coupe de la Ligue descontinuada) |
| Portugal | 4 | 1 | 0 |
| Inglaterra | 8 | 8 | 0 |
| Escocia | 2 | 3 | 1 |
| Bélgica | 2 | 2 | 0 |
| Dinamarca, Austria | 1 y 2 | 2 y 1 | 1 cada uno |
| Colombia | 2 | 3 | 0 |
| Brasil | 3 | 1 | 0 |
| Argentina | 1 | 5 | 0 |
| Chile, Uruguay | 1 y 0 | 3 y 4 | 0 |
| México | 1 | 2 | 0 (Copa MX descontinuada) |
| Estados Unidos | 2 | 1 | 1 |
| Panamá | 0 | 1 | 3 |
| Japón, Corea del Sur | 2 y 1 | 2 y 2 | 0 y 1 |
| India | 1 | 2 | 1 |
| Arabia Saudita, Catar, Emiratos | 2, 1 y 1 | 2, 4 y 4 | 0 |
| Egipto | 2 | 3 | 0 |
| Australia | 1 | 2 | 2 |

### Altas por lotes

Los lotes siguen el orden de prioridad y la regla «un lote solo tras medir un día el anterior». Los partidos por temporada son un supuesto por formato habitual. La sonda `probe_leagues` los sustituye.

| Lote | Contenido | Comp. | Partidos por temporada [S] | Peticiones al día, media [S] | Día de más carga [S] | GB al año [S] |
|---|---|---|---|---|---|---|
| 4 | Ya decidido por el Plan AD: Uruguay (268) y Copa Colombia (241) | 2 | 380 | 57 | 525 | 0,5 |
| 5 | Colombia e internacionales: 713, 712, 541, 27, 1132, 36 | 6 | 368 | 80 | 720 | 0,2 |
| 6 | América: 129, 130, 517, 810, 1178, 632, 266, 267, 527, 263, 857, 304, 257, 269, 842, 930 | 16 | 1.875 | 317 | 2.019 | 2,2 |
| 7 | Europa: 220, 147, 519, 120, 121, 550, 181, 182, 185 | 9 | 742 | 142 | 1.336 | 0,3 |
| 8 | Asia, África y Oceanía: 21 competiciones (ids en el anexo A) | 21 | 1.875 | 347 | 2.050 | 1,6 |
| 9 | Inglaterra 5 a 7: 43, 50, 51, 58, 59, 60, 931 y FA Trophy (47) | 8 | 3.669 | 478 | 3.465 | 4,7 |
| **Total 4 a 9** | | **62** | **8.909** | **1.421** | no coinciden el mismo día | **9,5** |

El coste por petición usa el modelo medido del 10 al 16-nov: 6,1 por liga y día más 42,7 por partido con la captura en vivo repartida (24,8 sin ella) [M]. El disco usa 1,18 MB de cuotas y 0,10 MB de resto por partido [D]. Es una cota superior: las ligas menores traen menos mercados y menos casas.

Otros costes de una sola vez:

- **Sondas:** 4 peticiones por competición, unas 240 para las 60 candidatas nuevas [S].
- **Primer llenado de referencia:** unas 1.800 con profundidad mínima, o unas 73.000 con profundidad completa [S]; de ellas, unas 69.000 corresponden a los lotes 5 a 9. La tarea PM-04-04 fija la profundidad por nivel.
- **Historia:** opcional. `scripts.migration plan` da la cifra sin gastar peticiones. El disco, unos 4,3 GB con cinco temporadas [S].

### Qué nivel esperar de las altas

De las 62 altas, 57 tienen techo C y 1 tiene techo D: el proveedor declara que no hay estadísticas de partido [M]. Esa bandera es fiable cuando dice «no». Solo 4 pueden llegar a A o B: Primera de Uruguay, Liga de Expansión MX, League Cup de Escocia y clasificación de la Copa Africana. Trece no declaran alineaciones.

Por eso la regla de admisión del lote 1 no sirve para estos lotes. Exige alineaciones en el 80 % y siete casas. Admitir competiciones de nivel C o D es la decisión DM-03. La matriz impide que se muestren con huecos.

### Procedimiento real de alta

1. Candidata en `backend/config/expansion.yaml`, por PR. Es zona del Plan AD: se reserva.
2. Sonda de solo lectura: `python -m scripts.probe_leagues --league <id>`.
3. Lote nuevo en `expansion.yaml` con lo medido.
4. Fusión y despliegue por la cadena normal.
5. Activación por el dueño: `python -m scripts.expand_leagues --batch N`, primero en ensayo y luego con `--apply`.
6. Un día UTC de medición con `python -m scripts.capture_odds status`. Criterio vigente: 1.000 peticiones añadidas como máximo.
7. Historia, opcional, con `scripts.migration`.
8. Reglamento, si se quiere «qué se juega», en `backend/config/rules/`.

La vuelta atrás es `expand_leagues --batch N --untrack --apply`. No borra nada.

El anexo A lleva 1.264 filas: las 1.253 del proveedor y las 11 que no existen. Incluye prioridad, acción, lote, niveles medidos y techo declarado.

## 4. Niveles de cobertura y matriz dinámica de disponibilidad

Los niveles se fijan por dato, con dos umbrales de porcentaje y dos de muestra que el código ya usa: 80 % y 50 %, 10 y 30 partidos [C]. Este plan añade un escalón superior, el 95 %, y no rebaja ninguno.

### La unidad correcta

La unidad es **competición × temporada × fase × dato**, y para precios, **× mercado**. Un nivel global por país o por liga sería injusto en los dos sentidos. La Premier no debe limitarse por la National League. La Champions no debe arrastrar sus rondas previas.

### Umbrales por dato

| Nivel | Nombre | Porcentaje de partidos terminados con el dato | Muestra mínima | Para mercados, además |
|---|---|---|---|---|
| A | Completa | 95 % o más | 30 partidos | Mediana de 5 casas o más |
| B | Intermedia | 80 % o más | 10 partidos | Mediana de 3 casas o más |
| C | Básica | 50 % o más | 10 partidos | Con menos de 3 casas, el techo es C |
| D | Limitada | Menos del 50 % | 10 partidos | — |
| MI | Muestra insuficiente | Cualquiera | Menos de 10 | — |

Por qué estos números:

- **80 %** es el umbral con que hoy se publica una estadística, se liquida un mercado y se da por cubierta una liga [C]: `fbi.stats.team.COVERAGE`, `settle_coverage.MIN_SHARE` y `coverage.COVERED_SHARE`.
- **50 %** es el suelo bajo el cual un mercado no se ofrece [C]: `market_status.NO_SETTLEMENT`.
- **10 y 30 partidos** son `settle_coverage.MIN_MATCHES` y `market_status.MIN_SETTLE_SAMPLE` [C].
- **3 casas** es `MIN_BOOKS` [C].
- **95 % con 30 partidos** es nuevo. Con esos valores, el extremo inferior del intervalo de Wilson es 0,81 [D]: sigue por encima de B.
- Con 80 % y 10 partidos, ese extremo es 0,49 [D]. Por eso B con menos de 30 partidos se marca «provisional».

Reglas de aplicación:

1. Un dato cuenta si está relleno para los dos equipos. Un valor vacío no es un cero.
2. Con menos de 10 partidos en la temporada, la celda hereda el nivel de la temporada anterior, marcado «provisional».
3. Las competiciones de un solo partido agregan sus cinco últimas ediciones. Hoy no está medido así.
4. Subir de nivel exige cumplir el umbral. Bajar exige incumplirlo en dos recálculos seguidos.
5. La bandera del proveedor solo se usa cuando dice «no». La bandera «sí» falló en 16 competiciones [M].

El anexo B aún no aplica la herencia ni la marca «provisional»: deja esas celdas en MI. Lo hará la tarea PM-02-01.

### Familias y resumen

Los datos se agrupan en siete familias. El nivel de la familia es el peor de sus datos.

| Familia | Datos que agrupa |
|---|---|
| Base | Eventos y alineaciones |
| Estadísticas de equipo | Córners, tarjetas amarillas y tiros |
| xG | xG del proveedor |
| Estadísticas de jugador | Línea de jugador por partido |
| Árbitro | Árbitro identificado |
| Cuotas principales | 1X2, más o menos y ambos marcan |
| Cuotas estadísticas | Córners y tarjetas |

El resumen por competición solo sirve al directorio (I08). Ninguna pantalla decide con él.

| Resumen | Regla | Competiciones hoy [M] |
|---|---|---|
| A | Base A, equipo A, jugador B o más, cuotas principales A y cuotas de córners B o más | 45 |
| B | Base, equipo y cuotas principales en B o más | 16, más 19 sin ventana de cuotas |
| C | Base B o más y cuotas principales C o más | 22, más 5 sin ventana de cuotas |
| D | El resto con muestra | 19 |
| MI | Menos de 10 partidos | 12 |

«Sin ventana» es 0 partidos con cuotas desde el 5-oct-2026, cuando empezó la captura a escala (30 competiciones); con 1 a 9 partidos es muestra insuficiente de cuotas (6). En la tabla, «sin ventana de cuotas» reúne los dos casos. El Mundial 2026 no tiene ninguno; la Libertadores tiene 4.

Cinco avisos sobre el resumen:

- **Champions, Europa League y Conference salen en C** porque la medición suma las rondas previas. La Champions tiene córners en el 72 % de la temporada [M]. La tarea PM-02-07 parte por fase.
- **Las copas en curso salen en D por sus rondas iniciales:** Coupe de France, Copa del Rey, Türkiye Kupası, FA Cup, CAF Champions y Copa Confederación [M]. La tarea PM-02-07, que parte la medición por fase, lo corrige.
- **Mundial, Libertadores, Sudamericana y los torneos de selecciones salen en B solo por falta de ventana de cuotas,** no por falta de datos [M]. AFC Champions League Two sale en D sin tener ninguna familia en D.
- **Las 12 en MI son supercopas y repescas.** No es un fallo de datos.
- **La Primera B de Colombia es D:** 0 % de córners y 10,7 % de cuotas [M].

### La matriz dinámica: qué responde

Para cada partido y cada mercado, la matriz responde siete preguntas distintas. Hoy cada módulo contesta algunas por su cuenta.

| N.º | Estado | Pregunta | Pieza existente que se reutiliza [C] |
|---|---|---|---|
| 1 | Existe el dato | ¿Llegó este dato para este partido o esta temporada? | Tablas `core.fixture_*`; `raw.league_coverage` |
| 2 | Cobertura suficiente | ¿La celda es B o más? | `scripts.stats_coverage`; `fbi.market.settle_coverage` |
| 3 | Cuota vigente | ¿Hay precio fresco de 3 casas o más? | `fbi.market.in_force`; `price_status`; `market.book_current` |
| 4 | Probabilidad calculada | ¿Hay pronóstico del modelo para este mercado? | `models.predictions`; pronósticos por familia |
| 5 | Calibrada y autorizada | ¿Hay calibrador validado y firma del dueño? | `intel.promotions`; estado `evaluable`; capacidad `autorizada` |
| 6 | Mercado liquidable | ¿Hay regla registrada y dato para liquidar? | `fbi.market.rules.rule_for`; `settle_coverage` |
| 7 | Cumple las reglas del módulo | ¿Lo admite Mi parlay, Picks o la consola? | `fbi.market.eligibility.verdict`; canal de decisión |

No se duplica nada. El catálogo de mercados sigue en `market_states.json` con sus cuatro estados. Los modelos siguen con ACTIVE y PLANNED, y los experimentos con RESEARCH y CANDIDATE. La matriz los lee y los combina.

### Diseño de datos

Tres tablas nuevas en el esquema `analytics`, solo aditivas, con su entrada en `grants.sql`.

| Tabla | Clave | Columnas principales | Para qué |
|---|---|---|---|
| `analytics.coverage_cells` | `competition_season_id`, `phase_key`, `datum` | `n_finished`, `n_with_data`, `share`, `level`, `provisional`, `declared_flag`, `rules_version`, `measured_at` | Estados 1 y 2 |
| `analytics.market_availability` | `competition_season_id`, `market_key` | `priced_share`, `median_books`, `settle_share`, `level`, `catalogue_state`, `window_days`, `measured_at` | Estados 2, 3 y 6, por competición |
| `analytics.coverage_changes` | `id` | celda, nivel anterior, nivel nuevo, motivo, fecha | Historia y avisos |

Los estados por partido no se guardan. Los calcula una función pura, `fbi/coverage/resolve.py`, con caché de 60 segundos.

### Cómo y cuándo se recalcula

| Qué | Cuándo | Cómo |
|---|---|---|
| Celdas de temporadas con partidos recientes | Cada noche, 08:00 UTC | Proceso por lotes fuera del worker, con tope de 512 MB [S] |
| Todas las celdas | Domingos | El mismo proceso, completo |
| Catálogo de mercados | Cuando cambie una regla o un calibrador | `scripts.ia_market_states`, por commit revisado, como hoy |
| Estados 3, 4 y 7 | En cada lectura | Resolutor, sobre precios y pronósticos vigentes |
| Tras un alta de competición | Al cerrar su día de medición | Ejecución manual del proceso |

Las 08:00 UTC evitan la copia diaria y la pasada de estadísticas de las 07:20.

### Contrato C-16 «Disponibilidad»

C-15 está reservado por el Plan EA. El número C-16 se confirma al reservar.

| Ruta | Devuelve |
|---|---|
| `GET /api/v1/availability/competitions` | Directorio: prioridad, resumen y familias por competición |
| `GET /api/v1/availability/competitions/{id}` | Celdas por temporada, fase y dato, con muestra y fecha |
| `GET /api/v1/matches/{id}/availability` | Bloques y mercados del partido con sus siete estados y el motivo |
| `GET /api/v1/admin/availability/matrix` | Matriz completa para la consola |
| `GET /api/v1/admin/availability/changes` | Cambios de nivel y discrepancias de sombra |

Con `FBI_AVAILABILITY` apagado, las rutas devuelven 404. Ejemplo abreviado del cuerpo por partido:

```json
{"fixture_id": 1557464, "rules_version": "coverage-levels-v1",
 "blocks": {"team_stats": {"exists": true, "level": "A", "n": 394},
            "half_stats": {"exists": false, "reason": "no_entregado"}},
 "markets": [{"key": "CORNERS_OU", "exists": true, "coverage_ok": true, "price_in_force": true,
              "prob_computed": true, "prob_authorised": false, "settleable": true,
              "modules": {"mi_parlay": {"ok": true}, "picks": {"ok": false, "reason": "MERCADO_NO_EVALUABLE"}}}]}
```

Los motivos usan el vocabulario que ya existe: `sin_cobertura`, `muestra_insuficiente`, `no_entregado`, `reglamento_no_codificado` [C].

### Cómo se adapta la interfaz

| Estado | Lo que hace la pantalla |
|---|---|
| El dato no existe y la celda es D | El bloque no se pinta. Ni tarjeta vacía ni pestaña |
| Celda C | Se pinta con la nota «cobertura parcial» y su porcentaje |
| Celda B o A | Se pinta completo |
| Muestra insuficiente | Nota única por pantalla, sin cifras derivadas |
| Sin cuota vigente | El mercado no aparece en Cuotas ni en Mi parlay |
| Probabilidad no autorizada | No se muestra probabilidad de PrediGol; sí la implícita del mercado |
| No liquidable | No se puede añadir a Mi parlay |

La adopción va en sombra primero. La tarea PM-02-06 compara 14 días lo que cada módulo enseña con lo que diría la matriz. Después se activa módulo a módulo.

## 5. Estadísticas y mercados por competición

Solo 152 de las 1.253 competiciones del proveedor declaran estadísticas de partido [M]. Ese es el techo de los mercados estadísticos, se añadan las ligas que se añadan. En la base, el dato real es menor.

### Cobertura por familia en las 138 competiciones seguidas

Niveles de la temporada más reciente con 10 partidos o más. Estadísticas medidas sobre los 234.517 partidos terminados [M]. Cuotas medidas sobre 4.659 partidos desde el 5-oct-2026: es una muestra [M].

| Familia o mercado | A | B | C | D | MI | Sin ventana |
|---|---|---|---|---|---|---|
| Base (eventos y alineaciones) | 101 | 8 | 11 | 6 | 12 | — |
| Estadísticas de equipo | 62 | 19 | 13 | 32 | 12 | — |
| Estadísticas de jugador | 70 | 12 | 9 | 35 | 12 | — |
| Árbitro | 87 | 15 | 5 | 19 | 12 | — |
| xG | 24 | 12 | 18 | 72 | 12 | — |
| Cuotas principales | 69 | 24 | 5 | 4 | 6 | 30 |
| Cuotas de córners | 58 | 26 | 10 | 8 | 6 | 30 |
| Cuotas de tarjetas | 0 | 18 | 18 | 66 | 6 | 30 |
| Cuotas de tiros | 0 | 5 | 20 | 77 | 6 | 30 |
| Mercados de jugador | 0 | 0 | 0 | 102 | 6 | 30 |

Lectura:

- **Ochenta y una competiciones** tienen estadísticas de equipo en A o B. Ahí caben embudo, balanza y mitades.
- **El xG es escaso:** 36 en A o B. La tabla esperada solo cabe ahí.
- **Las cuotas de tarjetas nunca llegan a A.** Su mediana de casas no pasa de 4 [M].
- **Los mercados de jugador están a cero.** El proveedor los da con una sola casa, y PrediGol no los extrae [C]. Siguen bloqueados.

### Competiciones de referencia

| Competición (2026) | n | Córners | Tarjetas | xG | Jugador | Cuotas córners | Resumen |
|---|---|---|---|---|---|---|---|
| Premier League | 100 | 100 | 98,0 | 98,0 | 100 | 100 | A |
| Primera A de Colombia | 394 | 99,2 | 97,7 | 79,9 | 99,7 | 96,0 | A |
| Libertadores | 153 | 100 | 98,0 | 94,8 | 100 | n = 4 | B, sin ventana |
| Champions League | 162 | 72,2 | 71,0 | 38,3 | 76,5 | 100 | C, por las previas |
| K League 1 | 210 | 55,7 | 55,7 | 4,8 | 55,7 | 100 | C |
| FA Cup | 366 | 19,1 | 19,4 | 0 | 0 | 92,0 | D |
| Primera B de Colombia | 286 | 0 | 0 | 0 | 0 | 10,7 | D |

Porcentajes medidos el 19-nov-2026. El anexo B trae las 272 filas con el nivel de cada dato.

### Mercados: catálogo, extracción y estado

| Dato | Valor | Origen |
|---|---|---|
| Mercados en el catálogo del proveedor | 338 | [M] `GET /odds/bets` |
| Mercados marcados para extraer | 55; en 14 días llegaron 42 con historia | [M] y nota de inventario |
| Mercados con clave de catálogo evaluable | 4: 1X2, más o menos, ambos marcan y hándicap | [C] foto del 17-nov-2026 |
| En calibración | 20 | [C] |
| Necesitan datos | 18 | [C] |
| No se ofrecen | 295 | [C] |

El catálogo propio suma 337 claves; el proveedor lista 338.

Ningún mercado tiene hoy ventaja demostrada. «Evaluable» no significa «con valor» [C].

### Las banderas del proveedor no bastan

- **Bandera `odds`:** falla en 21 competiciones. Hay 17 con «no» y cuotas en la base, como la Europa League. Hay 4 con «sí» y menos de la mitad [M].
- **Bandera de estadísticas:** fiable solo cuando dice «no». Con «sí», 16 competiciones tienen córners en menos de la mitad de sus partidos. Son sobre todo copas [M].
- **Un porcentaje bajo de cuotas no dice la causa.** Puede faltar el precio o faltar la petición. La tarea PM-01-04 lo separa.

### Estadísticas por mitad

La sonda de hoy dio datos por mitad en 5 de 8 competiciones [M]: Champions, Premier, Primera A, Segunda de España y Nations League. Dio vacío en Primera B y en los niveles 5 y 7 ingleses. Las faltas llegaron vacías en 2 de las 5. Ocho partidos no prueban la cobertura de una liga. La tarea PM-01-05 mide una semana.

### Qué se ofrecerá en cada nivel

| Bloque | A | B | C | D |
|---|---|---|---|---|
| Resultado, eventos y tabla | Sí | Sí | Sí | Sí, si hay eventos |
| Alineaciones con capas | Sí | Sí | Solo alineación | No |
| Embudo, balanza y mitades | Sí | Sí | Solo franja de estado | No |
| Perfil de jugador con datos nuevos | Sí | Sí | Básico | Mínimo |
| Cuotas principales | Sí | Sí | Con nota | Solo si hay precio vigente |
| Mercados de córners y tarjetas en Mi parlay | Sí | Sí | No | No |
| Probabilidad de PrediGol | Solo con estado 5 | Solo con estado 5 | No | No |

Cada módulo se muestra según el nivel de su propio dato en esa competición y temporada, no según un nivel global de la competición. Una liga con base A y estadísticas D enseña alineaciones y oculta el embudo. Las láminas I04 (B, C y D) son ejemplos ilustrativos de tres competiciones, no una regla por nivel global.

## 6. API-Football: auditoría, peticiones y escenarios

PrediGol ya pide los 38 endpoints de la versión 3.9.3 y usa de media el 24 % del cupo diario (17.845 de 75.000) [D]. Lo único con valor que no se pide es `half=true`. Lo demás desaprovechado ya está guardado.

### Urgencia: la suscripción vence el 29-nov-2026

| Hecho | Valor | Origen |
|---|---|---|
| Fin de la suscripción | 29-nov-2026 21:45:57 UTC | [M] `GET /status` |
| Renovación automática | No: «prepaid… no auto-renewal» | [P] página de precios |
| Al vencer | La cuenta pasa al plan gratuito: 100 peticiones al día | [P] |
| Precio de Ultra | 26 USD en la página viva; 29 USD en el documento interno | contradicción abierta |
| Antecedente | El 29-oct hubo 1.930 ejecuciones fallidas en 24 horas | documento interno |

El libro marcó 60.000 el 29-oct con 12.819 llamadas [M]. Encaja con un vencimiento mensual, pero la causa no está determinada. Recomendación: pagar antes del 25-nov y programar la alarma de la tarea PM-01-01. Antes de pagar varios meses, preguntar al proveedor por el cambio de plan a mitad de periodo. La página no lo describe.

### Qué se aprovecha y qué no

El anexo C tiene 1.049 campos de 39 endpoints, uno por fila.

| Acción propuesta en el anexo C | Campos | Qué son |
|---|---|---|
| Mantener | 362 | Lo que el producto, los modelos o la liquidación ya usan |
| Mostrar | 27 | Guardado y sin pintar: trayectoria de entrenadores, penaltis, fueras de juego, goles evitados |
| Pedir | 15 | Los tipos de `statistics_1h` y `statistics_2h` |
| Reprocesar RAW | 1 | Tiempo añadido |
| No merece la pena | 644 | Redundantes o derivables: logos repetidos, totales, agregados de `/players` |

### Recuperar primero desde RAW

El índice del RAW tiene 330.337 respuestas (619.351 archivos en disco) desde el 12-sep-2026, en 4,6 GB [M]. Antes de pedir, se reprocesa.

| Dato | ¿Sale del RAW? | Coste |
|---|---|---|
| Campos de jugador y portero no pintados | Ya normalizados | 0 peticiones |
| Tiempo añadido e inicio real de cada parte | Sí, de `/fixtures`; cobertura sin confirmar | 0 peticiones |
| Los 283 mercados no extraídos | Sí, desde el 25-sep-2026 | 0 peticiones; unos 9 GB al mes si se extrajeran todos, descartado |
| Trayectorias, fichajes, bajas y trofeos | Completos | 0 peticiones |
| Estadísticas por mitad | No | 1 por partido |
| Cuotas anteriores al 25-sep-2026 | No | No recuperable |

### Dónde se va el cupo hoy

| Trabajo | Peticiones en 31 días [M] | Parte |
|---|---|---|
| `reference_refresh` (plantillas, fichajes, trofeos, perfiles) | 287.511 | 57,8 % |
| `live_odds_capture` | 64.741 | 13,0 % |
| `live_match_capture` | 41.489 | 8,3 % |
| `historical_backfill` | 29.343 | 5,9 % |
| Cuotas previas, libro y cierre | 30.724 | 6,2 % |
| Calendario, contexto, alineaciones y resto | 43.739 | 8,8 % |

Más de la mitad del consumo no es de partidos. La suma por trabajos da 16.050 al día; el libro da 17.845 porque incluye el 29-oct. No existe contador por endpoint: la tarea PM-01-02 lo crea.

### Reparto del cupo en carriles

Propuesta de diseño sobre el presupuesto interno de 60.000. Los techos son un punto de partida y se ajustan con 14 días en modo medición.

| Prioridad | Carril | Trabajos | Techo diario | Uso medio hoy [D] |
|---|---|---|---|---|
| 1 | Directo | `live_match`, `live_odds` | 15.000 | 3.430 |
| 2 | Cuotas | `odds_capture`, `odds_book_refresh`, `final_prematch` | 10.000 | 990 |
| 3 | Alineaciones | `prematch_lineups`, `lineup_watch` | 1.500 | 180 |
| 4 | Resultados | `results_sync`, `results_repair`, detalle y mitades | 1.500 | menos de 200 |
| 5 | Calendario y prioritarias | `fixtures_sync`; P0 y P1 primero | 1.500 | 440 |
| 6 | Estadísticas y contexto | `context_refresh`, `context_due` | 2.000 | 700 |
| 7 | Jugadores y referencia | `reference_refresh` | 9.000 | 9.270 |
| 8 | Históricos | `historical_backfill`, relleno de mitades | 6.000 | 950 |
| 9 | Ampliación | Sondas y primer llenado de lotes | 5.000 | 0 |
| 10 | Reparación | Reprocesos y reintentos | 1.500 | menos de 100 |
| — | Reserva de emergencia | Nadie la consume en régimen | 7.000 | — |
| | **Total** | | **60.000** | **≈ 16.100** |

El techo del carril 7 (9.000) es inferior a su uso actual (9.270) a propósito: exige las tareas PM-04-03 y PM-04-04 antes de activarse.

Reglas del reparto:

- **Prioridad estricta.** Un carril inferior nunca retrasa a uno superior.
- **Límites dinámicos.** Al 60 % del presupuesto se pausan históricos y ampliación. Al 75 %, la referencia. Al 88 % solo quedan directo, cuotas, alineaciones y resultados.
- **Caché y deduplicación.** Una respuesta idéntica no genera fila nueva en RAW; eso ya ocurre [M]. `/predictions` pasa de tres lecturas a una. `/teams/statistics` y el barrido de `/players` se reducen.
- **Pausas.** Ningún relleno entre las 03:50 y las 05:00 UTC. Los picos del lunes (23.072 de media [M]) se reparten en la semana.
- **Reserva.** 7.000 dentro del presupuesto y 15.000 más hasta el límite del proveedor.
- **Límite por minuto.** Máximo medido de 202 sobre 450, en una muestra de 48 horas [M].

### Tres escenarios

| | A · Optimizar el plan actual | B · Usar más dentro del cupo | C · Plan superior (Mega) |
|---|---|---|---|
| Plan | Ultra, 75.000 al día | Ultra, 75.000 al día | Mega, 150.000 al día [P] |
| Peticiones al día, media | ≈ 17.000 [S] | ≈ 18.300 [S] | No estimable hoy |
| Pico de un día normal | ≈ 24.500 [S] | ≈ 28.400 [S] | — |
| Pico con rellenos nocturnos | ≈ 29.500 [S] | ≈ 38.400 [S] | — |
| Margen medio sobre 60.000 | 72 % [D] | 70 % [D] | — |
| Margen el peor día | 51 % [D] | 36 % [D] | — |
| Competiciones nuevas | 8 (lotes 4 y 5) | 62 (lotes 4 a 9) | Sin límite de cupo |
| Datos nuevos | Mitades, campos guardados, contexto, tablas colombianas | Lo mismo, más segundas, copas y pirámide inglesa | Lo mismo |
| Coste mensual | 26 o 29 USD | 26 o 29 USD | 36 o 39 USD [P] |
| PostgreSQL | +0,7 GB al año [S] | +9,5 GB al año como máximo [S] | Más de 7 GB al mes si se duplican las cuotas [S] |
| Servidor | Sin cambio | Sin cambio; todo por lotes | Exige más memoria: no cotizado |
| Beneficio | Orden y ahorro | Cumple el encargo editorial | Bajo hoy |

**Recomendación: escenario B, por pasos.** Se arranca en A durante las olas 0 a 2 y se pasa a B lote a lote.

**Cuándo pasar a C.** Solo con necesidad demostrada: p95 diario por encima de 45.000 durante 14 días, o p95 por minuto por encima de 300. Hoy el máximo normal es 23.430 [M]. El límite de 900 por minuto de Mega no figura en la página oficial.

El límite real no es el cupo. Es la cobertura del proveedor y la memoria del worker. Comprar más peticiones no resuelve ninguna de las dos.

## 7. APIs complementarias, RapidAPI y redes sociales

No se incorpora ningún proveedor de datos de fútbol: de 110 recursos de API catalogados, 54 quedan en «no usar» y solo 9 se aprovechan ya. Lo nuevo es infraestructura gratuita y, con condiciones, un canal de alerta temprana.

### RapidAPI: sirve para descubrir, no para contratar

RapidAPI no licencia datos ni garantiza su procedencia [P]. Sus términos dicen que el contrato es solo entre consumidor y proveedor. Renuncia a garantizar la no infracción y limita su responsabilidad a 100 USD. No hay reembolsos.

| Oferta en RapidAPI | Quién la publica | Decisión |
|---|---|---|
| «Sofascore» | «Api Dojo»; Sofascore declara que no ofrece API | No usar |
| «FlashScore», «LiveScore Football» | Cuenta genérica; editor «datascraper» | No usar |
| «Free Football API Data» y similares | Origen no declarado | No usar |
| API-Football | «api-sports», el titular | Legítima, pero duplica lo contratado |
| APIs no oficiales de X e Instagram | Extracción declarada | No usar |

Regla de alta de cualquier proveedor (tarea PM-00-04): quién es el editor, si tiene términos propios, si declara su fuente y si el precio es creíble para un dato licenciado. Las preguntas completas, la lista de exclusión y la disciplina de conocimiento están en [`DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md`](DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md).

### Lo que sí se incorpora

| N.º | Qué | Necesidad | Coste [P] | Condición |
|---|---|---|---|---|
| 1 | Healthchecks.io | Saber que una tarea no corrió | 0 USD, 20 tareas | Leer términos; DM-11 |
| 2 | UptimeRobot | Aviso externo de caída del servidor | 0 USD, 50 monitores | Confirmar uso comercial; DM-11 |
| 3 | Sitios y RSS oficiales en lista cerrada | Bajas, convocatorias y comunicados | 0 USD nuevos | Firma por dominio; DM-05 |
| 4 | MET Norway | Clima previsto | 0 USD | Una persona acepta los términos; DM-06 |
| 5 | GeoNames y Copernicus | Coordenadas y altitud | 0 USD | Atribución; Wikidata por confirmar; DM-09 |
| 6 | API oficial de X, en sombra | Adelantar bajas | 30 a 75 USD al mes [D] | DM-07, abogado y medición previa |

No se planifican mapas de estadio, correo nuevo ni traducción. Claude ya lee portugués e inglés. Los husos y festivos se resuelven en local.

### Redes sociales: canales, no fuentes

Lo que eleva una afirmación a confirmada es quién la emite, no la red por la que llega.

| Red | Vía autorizada | Qué permite | Decisión |
|---|---|---|---|
| X | API oficial de pago por uso: 0,005 USD por publicación [P] | Leer una lista cerrada de cuentas oficiales | Solo en sombra y si pasa DM-07 |
| Facebook e Instagram | Acceso con empresa verificada y revisión | Mostrar; el oEmbed prohíbe analizar | Aplazado |
| Telegram | Sus términos vetan usar sus datos con IA [P] | Solo como canal de salida propio | No leer |
| YouTube, Bluesky, Reddit | Ya catalogados | — | Sin cambio |

Dos dudas de X van al abogado: si el pago por uso ampara un producto comercial, y si pasar una publicación a Claude está permitido. Además, X obliga a borrar lo que se borre allí en 24 horas [P].

Falta el dato que decide: cuánto se adelanta X a la web oficial y a API-Football. La tarea PM-06-03 lo mide antes de gastar.

### Datos personales

Bajas y lesiones son datos de salud de personas identificadas. El plan trata solo lo que el club o el jugador hicieron público, con fuente y fecha, y sin detalle médico. La Ley 1581 de 2012 debe revisarla un abogado (DM-08).

El anexo D reúne las 110 filas: las 82 API del catálogo previo, 28 nuevas y 22 estados actualizados hoy. Cada fila nueva del anexo D se da de alta con las preguntas de [`DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md`](DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md).

## 8. Destino de las 59 oportunidades

Las 59 conservan su identificador y ninguna se pierde: 34 se construyen, 1 se conserva, 3 pasan a otro plan, 13 van al LAB, 4 se aplazan y 4 se descartan.

| Destino | Cuántas | Cuáles |
|---|---|---|
| Implementar | 17 | OP-02 a 06, 17, 22, 24, 25, 36, 37, 40, 43, 45, 46, 49, 50 |
| Completar (parcial) | 17 | OP-07, 08, 11 a 16, 20, 23, 33, 35, 38, 39, 44, 47, 51 |
| Ya resuelto: conservar | 1 | OP-09 |
| Integrar en otro plan | 3 | OP-01 (AD), OP-19 (AD y UX), OP-28 (Intelligence 2026) |
| LAB privado | 13 | OP-10, 18, 21, 26, 27, 29, 30, 31, 34, 41, 48, 53, 54 |
| Aplazar (nivel 4) | 4 | OP-32, 42, 52, 55 |
| Descartado | 4 | OP-56 a 59 |

Las 14 líneas de LAB de la investigación siguen separadas de lo destinado a lectores. Son las 13 de la tabla más OP-28, que sigue en LAB bajo los protocolos E4 y E6 del Plan Intelligence. Ninguna llega a un lector sin validación y firma.

El orden de ejecución prioriza lo que el dueño enumeró. Primero, datos y contexto (OP-06 a 09) y competición y temporada (OP-19 y 20). Después, visualizaciones (OP-22 a 25), Intelligence (OP-35 a 40) y calidad estadística (OP-16 y 17).

### Las 59, una a una

| ID | Funcionalidad | Estado en GitHub (19-nov) | Destino | Detalle | Tareas |
|---|---|---|---|---|---|
| OP-01 | Recortar el gasto de IA sin valor demostrado | en ejecución por otro plan | **integrar en otro plan** | Plan AD (AD-D11, AD-F05, AD-D10). Este plan solo lleva a firma `review-retire-v1` y ordena el calendario. | PM-13-01 |
| OP-02 | Higiene de base de datos | no existe | **implementar** | Dejar de duplicar hacia adelante, sin borrar historia. | PM-13-02, PM-13-03 |
| OP-03 | Adelgazar la imagen de producción del backend | no existe | **implementar** | Partir el extra `analytics`: numpy y scipy se quedan en la imagen. | PM-13-04 |
| OP-04 | LAB fuera del VPS: DuckDB + Parquet, manifiesto por ejecución, archivo… | no existe | **implementar** | Solo exportación de solo lectura y manifiesto. El archivo frío espera la decisión D1 de la auditoría. | PM-12-02 |
| OP-05 | Disciplina de conocimiento y de fuentes: ruta de estudio, lista de… | no existe | **implementar** | Documentación: lecturas, lista de auditoría, regla de origen y alta de proveedores. | PM-00-04 |
| OP-06 | Sonda y estadísticas por mitad con half=true | no existe | **implementar** | Sonda de una semana, tabla por mitad, relleno y regla nueva de córners por mitad. | PM-01-05, PM-05-01, PM-05-02, PM-05-03, PM-10-03 |
| OP-07 | Coordenadas y altitud de todos los estadios | parcial | **completar** | Confirmar la carga en producción y completar en cascada con procedencia por fila. | PM-07-01, PM-07-02 |
| OP-08 | Contexto del partido: clima previsto, altitud, viaje, descanso y… | parcial | **completar** | Cliente de MET Norway, viaje, descanso y bloque de contexto. Solo descripción. | PM-07-03, PM-07-04, PM-07-05 |
| OP-09 | Fuentes oficiales por lectura directa: firmar los RSS ya construidos | ya implementado | **ya resuelto: conservar** | Construido por el Plan AD (AD-C03). Falta la firma del dueño, no código. | PM-06-02 |
| OP-10 | Señales y contrastes para el LAB: clima histórico, radar de prensa… | no existe | **LAB privado** | Un experimento acotado por señal; se cierra la línea si sale nulo. | PM-12-04 |
| OP-11 | Árbitro designado en el partido y ficha de árbitro | parcial | **completar** | Medir antelación y publicar el bloque con n e intervalo. Sin cruces árbitro por equipo. | PM-08-01, PM-08-02 |
| OP-12 | Estadística descriptiva con datos ya guardados: eventos por minuto,… | parcial | **completar** | El resto tras el Plan EA: campos guardados, bajas, entrenador, movimientos y tiempo añadido. | PM-05-04, PM-05-05, PM-05-06, PM-05-08, PM-08-04, PM-14-03 |
| OP-13 | xG del proveedor en lo descriptivo: goles − xG, eficiencia de portero y… | parcial | **completar** | El resto tras el Plan EA: portero, goles evitados con sonda y tabla esperada. | PM-05-05, PM-08-06, PM-09-06 |
| OP-14 | Inteligencia de mercado con el libro propio: movimiento, margen y… | parcial | **completar** | Agregados diarios de margen y dispersión por liga. Sin tocar Mi parlay ni la ingesta. | PM-05-07 |
| OP-15 | Índices de fuerza con método publicado: clubes con dificultad de… | parcial | **completar** | Dificultad de calendario con fórmula. El ranking entre ligas queda en LAB. | PM-08-05, PM-14-03 |
| OP-16 | Evidencia y lectura en cada cifra: n, intervalo de Wilson, valor de… | parcial | **completar** | El resto tras el Plan EA: etiqueta E0 a E4, frase de lectura y revisión de accesibilidad. | PM-10-06 |
| OP-17 | Tabla de estabilización por estadística y liga, y contracción para… | no existe | **implementar** | Tabla de solo lectura calculada fuera del VPS. La contracción visible queda en LAB. | PM-10-08 |
| OP-18 | Fichas que exigen medir antes: entrenador, identidad abierta de… | no existe | **LAB privado** | Medir cobertura y estabilidad antes de construir. La trayectoria del entrenador ya va por OP-12. | PM-08-07 |
| OP-19 | «Qué se juega cada equipo»: estados demostrados matemáticamente | en ejecución por otro plan | **integrar en otro plan** | Plan AD (en sombra) y Plan unificado UX (UX-162 a UX-166). Este plan solo añade reglamentos colombianos. | PM-03-09 |
| OP-20 | Tablas colombianas completas (reclasificación, descenso por promedio,… | parcial | **completar** | Tablas por configuración de temporada y calculadora. La de 2026 ya es definitiva: el valor es 2027. | PM-09-01, PM-09-02, PM-09-03 |
| OP-21 | Probabilidades de temporada por simulación (título, clasificación,… | parcial | **LAB privado** | Validación sobre temporadas cerradas; privado hasta firma. | PM-09-07 |
| OP-22 | Embudo y zona de remate (dos zonas reales) — M01 | no existe | **implementar** | Lámina I01 (M01). | PM-10-01 |
| OP-23 | Cancha de alineación con capas de datos por jugador — M02 | parcial | **completar** | Capas sobre la cancha existente. Lámina I02 (M02). | PM-10-04 |
| OP-24 | Formación habitual y rotación de la plantilla — M03 | no existe | **implementar** | Agregado nocturno y sección de perfil. Lámina I05 (M03). | PM-08-03, PM-10-05, PM-14-03 |
| OP-25 | Balanza del partido y franja de estado del marcador — M04 | no existe | **implementar** | Lámina I01 (M04). | PM-10-02 |
| OP-26 | Ventaja de local por competición y variable en el tiempo | no existe | **LAB privado** | Protocolo y puerta antes de salir del LAB. | PM-12-03 |
| OP-27 | Fuerza de equipo derivada de cuotas («rating de mercado») | no existe | **LAB privado** | Protocolo con control de circularidad. | PM-12-03 |
| OP-28 | Información nueva ya planificada: tiros y xG (E4) y alineaciones con… | en ejecución por otro plan | **integrar en otro plan** | Plan Intelligence 2026 (INT-A08 y INT-A09). No se toca: sigue siendo LAB privado bajo sus protocolos. | PM-12-03 |
| OP-29 | Calibración multiclase coherente y abstención conforme | parcial | **LAB privado** | INT-A02 ya la rechazó el 11-nov-2026. Solo un protocolo nuevo; no se repite el anterior. | PM-12-03 |
| OP-30 | Retadores y contraste externo: penaltyblog, Poisson compuesta,… | no existe | **LAB privado** | Solo contraste en portátil. | PM-12-03 |
| OP-31 | Estudio de altitud y viaje para Colombia y CONMEBOL | no existe | **LAB privado** | Primer experimento del protocolo de patrones; depende de OP-07. | PM-12-04 |
| OP-32 | Probabilidad de victoria en vivo y ritmo por estadísticas acumuladas | no existe | **aplazar (nivel 4, fuera del alcance de producción)** | Exige modelo prepartido cerrado, sonda de cadencia y validación por minuto. | — |
| OP-33 | Tablero privado de evaluación: fiabilidad y resolución, conteos,… | parcial | **completar** | Informes internos que faltan. No toca ninguna puerta. | PM-12-01 |
| OP-34 | Protocolo de patrones v2: libro de pruebas, FDR, bóveda, escalera… | parcial | **LAB privado** | Versión nueva tras simular su tasa de falsas alarmas. | PM-12-04 |
| OP-35 | Hoja de hechos ampliada para la crónica y clases de valoración en el… | parcial | **completar** | Hoja de hechos ampliada, clases de valoración y lámina I10. En sombra hasta firma. | PM-11-01, PM-11-02, PM-11-09 |
| OP-36 | Analizador por reglas para listas de bajas y onces probables | no existe | **implementar** | Quinto brazo de la comparación AD-C05, en sombra. | PM-11-04 |
| OP-37 | Ajustes de coste cero en las salidas de Claude: enum sin distinguir… | no existe | **implementar** | Primero el recuento de solo lectura. Si es cero, no se toca nada. | PM-11-05 |
| OP-38 | Aislamiento completo del agente de Partido frente a texto externo | parcial | **completar** | Aislamiento estructural y battery-v4 medida y superada. | PM-11-06 |
| OP-39 | Texto por plantillas: respaldo de la crónica, ficha de partido y… | parcial | **completar** | Medir la tasa de vacías y dar respaldo por plantillas. | PM-11-03 |
| OP-40 | Propuesta automática de nivel de fuente por sitio oficial | no existe | **implementar** | Lista por dominio para firma en bloque. | PM-06-02 |
| OP-41 | LAB de Intelligence: NLI y embeddings en sombra, enlazado por… | no existe | **LAB privado** | En portátil contra los bancos etiquetados. | PM-12-05 |
| OP-42 | Asistente de preguntas sobre datos propios (patrón de dos pasos) | no existe | **aplazar (nivel 4, fuera del alcance de producción)** | Exige batería superada, coste por respuesta medido y presupuesto nuevo. | — |
| OP-43 | Calendario suscribible de tus equipos (iCalendar) | no existe | **implementar** | Enlace con testigo secreto y revocable. | PM-14-06 |
| OP-44 | Fiabilidad y rapidez en el móvil: avisos declarativos de WebKit, INP… | parcial | **completar** | Leer lo ya medido antes de optimizar. | PM-14-05 |
| OP-45 | Probabilidad que se ve y se prueba: matriz de iconos, simulador de… | no existe | **implementar** | Lámina I09 (M08). Solo con probabilidades autorizadas. | PM-10-07 |
| OP-46 | Modo «solo fútbol» y pausa voluntaria | no existe | **implementar** | Preferencia y prueba de que ningún precio se escapa. | PM-14-07 |
| OP-47 | Historial descargable y calibración con incertidumbre | parcial | **completar** | Descarga CSV en la apertura de Transparencia. | PM-14-08 |
| OP-48 | Participación y audio: voto de la comunidad «¿Quién gana?» y «escuchar… | no existe | **LAB privado** | Esperar base de usuarios; audio en cuatro o cinco dispositivos. | PM-12-05 |
| OP-49 | Tarjeta al compartir un partido (imagen propia) | no existe | **implementar** | Última ola, tras piloto de CPU y visto bueno legal. | PM-14-09 |
| OP-50 | llms.txt y política de citación para asistentes de IA | no existe | **implementar** | Última ola; utilidad limitada mientras el sitio sea privado. | PM-14-10 |
| OP-51 | Canal de Telegram con resumen diario automático | parcial | **completar** | Resumen informativo, sin picks ni cuotas. | PM-11-10 |
| OP-52 | Capa pública mínima con datos estructurados y resumen oficial incrustado | no existe | **aplazar (nivel 4, fuera del alcance de producción)** | Exige decisión de tener cara pública y respuesta del abogado. | — |
| OP-53 | LAB privado de analítica espacial y demostrador histórico con datos… | no existe | **LAB privado** | Privado y con atribución. La licencia de Wyscout sigue en contradicción. | PM-12-05 |
| OP-54 | Vías con dictamen legal previo: muestra de BSD (xG por tiro) y… | no existe | **LAB privado** | No empieza sin dictamen legal. | PM-12-05 |
| OP-55 | Datos con coordenadas de pago: proveedor empresarial para la Liga… | no existe | **aplazar (nivel 4, fuera del alcance de producción)** | Láminas F01 a F04 de «13 · Evolución futura». Exige contrato, licencia de exhibición y sobre nuevo. | — |
| OP-56 | Complejidad sin beneficio en modelos: LLM como pronosticador, redes… | no existe | **descartado** | Complejidad sin beneficio medido en modelos. | — |
| OP-57 | Fuentes sin permiso y vías inventadas: extractores web, APIs internas,… | no existe | **descartado** | Fuentes sin permiso o con origen no declarado. | — |
| OP-58 | Lo que satura el servidor o no compensa: 95 mercados a la historia, LLM… | no existe | **descartado** | Satura el servidor o no compensa su coste. | — |
| OP-59 | Promesas y patrones espurios: ROI público, rachas como señal, «efecto… | no existe | **descartado** | Promesas y patrones espurios; queda como regla del protocolo. | — |

El anexo E añade el área, el nivel original, las olas y la decisión de la que depende cada una.

## 9. Plan de implementación por bloques y olas

El plan tiene 108 tareas en 16 bloques y 7 olas. Se ejecuta de corrido tras la aprobación, una ola detrás de otra. Dentro de cada ola, las tareas sin dependencia mutua van en paralelo.

Los bloques 0 a 15 son los que propuso el dueño. Se ajustaron tres cosas. La vigilancia externa sube a la ola 1. La higiene de base va antes de añadir datos. La adopción de la matriz por la web va después de 14 días de sombra.

### Orden de olas

| Ola | Nombre | Tareas | Qué entrega | Puerta para pasar a la siguiente |
|---|---|---|---|---|
| 0 | Urgente y sin código | 4 | Renovación, reservas, foto de producción y firma de retiradas | Suscripción renovada y plan aprobado |
| 1 | Medir y reconciliar | 12 | Contadores, sondas, reglas de nivel y memoria por trabajo | Sonda de mitades leída y umbrales firmados |
| 2 | Cimientos | 17 | Matriz, contrato C-16 en sombra, carriles de cupo e higiene | Siete noches de matriz; carriles en modo medición |
| 3 | Datos nuevos y primeros lotes | 21 | Mitades, estadios, clima, tablas colombianas y lotes 5 y 6 | Lotes medidos; datos visibles en la consola |
| 4 | Producto para lectores | 22 | Match Center adaptativo, perfiles, competición, directorio y lotes 7 y 8 | Catorce días de sombra sin discrepancias sin explicar |
| 5 | Intelligence, evaluación y últimos lotes | 18 | Hoja de hechos, plantillas, evaluación por competición y lote 9 | Muestras de sombra alcanzadas |
| 6 | LAB, condicionadas y cierre | 14 | LAB, piezas con dictamen, encendidos y cierre medido | Informe de cierre |

Reparto por área prevista: BE 35, IA 21, UX 18, OPS 16, DOC 8, FE 8 y CI 2. Por prioridad: 29 críticas, 46 altas, 24 medias y 9 bajas.

### Reglas que valen para todas las tareas

- Cada cambio entra por un PR con CI en verde y pasa la cadena de copia y restauración.
- El código `ÁREA-NNN` se asigna al abrir el PR. Otras sesiones consumen números.
- Las migraciones son aditivas, van solas y llevan su entrada en `grants.sql`.
- Los interruptores nacen apagados. Nada predictivo sale de sombra sin firma.
- `FBI_PICKS_SOURCE` sigue apagado. Nada sale de sombra sin battery-v4 medida y superada.
- Ningún modelo de lenguaje toca probabilidades.
- Nada pesado corre dentro del worker. Va por lotes nocturnos o en el LAB.
- Cada zona ajena se reserva por escrito antes de tocarla.

Las 20 fichas completas de cada tarea están en el anexo H (`anexo_fichas_tareas.md`) y en `plan_tareas.csv`, que se conservan en el proyecto del dueño (no se suben al repositorio por tamaño).

### Bloque 0 · Inventario y reconciliación

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-00-01 | nueva | Publicar este plan, sus anexos y las reservas de zona antes de tocar código | DOC | P0 | 0 | DM-02 | 0 | Nulo |
| PM-00-02 | nueva | Leer en producción la lista real de competiciones seguidas y el estado de los interruptores | OPS | P0 | 0 | PM-00-01 | 0 | Nulo (consultas de segundos, solo lectura) |
| PM-00-03 | nueva | Corregir los documentos y comentarios que contradicen al código o a lo medido | DOC | P1 | 1 | PM-00-02, PM-01-05 | 0 | Nulo |
| PM-00-04 | OP-05 | Dejar escrita la disciplina de conocimiento y la regla de alta de proveedores | DOC | P2 | 1 | PM-00-01 | 0 | Nulo |

### Bloque 1 · Auditoría de API-Football

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-01-01 | nueva | Renovar la suscripción de API-Football antes del 29-nov-2026 y vigilar su vencimiento | OPS | P0 | 0 | DM-01 | 0 (`/status` no consume cuota) | Nulo |
| PM-01-02 | nueva | Contar las peticiones por endpoint y por carril, y guardar la historia de picos y de tamaño de la base | BE | P0 | 1 | PM-00-01 | 0 | Una fila por endpoint y día: menos de 20.000 filas al año |
| PM-01-03 | nueva | Explicar el 29-oct y la diferencia entre archivos RAW e índice | OPS | P1 | 1 | — | 0 | Lecturas con `statement_timeout` |
| PM-01-04 | nueva | Sondear `/odds` en las competiciones donde la bandera del proveedor y la base discrepan | BE | P1 | 1 | — | ≈ 65 una vez | Nulo |
| PM-01-05 | OP-06 | Medir una semana de `half=true` por competición antes de construir nada | BE | P0 | 1 | PM-01-01 | ≈ 600 a 900 en 7 días | Nulo |

### Bloque 2 · Matriz de cobertura y disponibilidad

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-02-01 | nueva | Codificar las reglas `coverage-levels-v1` como módulo puro con pruebas | BE | P0 | 1 | DM-04 | 0 | Nulo |
| PM-02-02 | nueva | Crear las tablas de la matriz de disponibilidad | BE | P0 | 2 | PM-02-01 | 0 | Menos de 60.000 filas para 200 competiciones |
| PM-02-03 | nueva | Recalcular la matriz cada noche por lotes, sin cargar el worker | BE | P0 | 2 | PM-02-02 | 0 | Proceso aparte con tope de memoria de 512 MB |
| PM-02-04 | nueva | Resolver por partido los siete estados de disponibilidad con una sola función | BE | P0 | 2 | PM-02-03 | 0 | Lecturas indexadas por partido |
| PM-02-05 | nueva | Publicar el contrato C-16 «Disponibilidad» tras un interruptor apagado | BE | P0 | 2 | PM-02-04 | 0 | Respuestas de pocos KB |
| PM-02-06 | nueva | Comparar en sombra lo que cada módulo enseña con lo que diría la matriz | BE | P1 | 2 | PM-02-05 | 0 | Muestra de 500 partidos al día, de noche |
| PM-02-07 | nueva | Partir las celdas por fase en las copas | BE | P1 | 3 | PM-02-03 | 0 | Triplica las filas de las copas: irrelevante |
| PM-02-08 | nueva | Dar al dueño la consola de la matriz de disponibilidad (I11) | UX | P1 | 3 | PM-02-05 | 0 | Nulo |

### Bloque 3 · Ampliación de competiciones

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-03-01 | nueva | Inscribir las candidatas y sondearlas con el procedimiento real | BE | P0 | 2 | DM-03 | ≈ 240 una vez (4 por competición) | Nulo |
| PM-03-02 | nueva | Dar de alta el lote 5: Colombia e internacionales que faltan | OPS | P0 | 3 | PM-03-01, PM-04-01, DM-03 | ≈ 80 al día de media | ≈ 0,2 GB al año |
| PM-03-03 | nueva | Dar de alta el lote 6: segundas, copas y supercopas de América | OPS | P1 | 3 | Lote 5 medido un día | ≈ 320 al día de media | ≈ 2,2 GB al año, sobre todo cuotas |
| PM-03-04 | nueva | Dar de alta el lote 7: segundas, copas y supercopas de Europa | OPS | P1 | 4 | Lote 6 medido un día | ≈ 140 al día de media | ≈ 0,3 GB al año |
| PM-03-05 | nueva | Dar de alta el lote 8: Asia, África y Oceanía | OPS | P1 | 4 | Lote 7 medido un día | ≈ 350 al día de media | ≈ 1,6 GB al año |
| PM-03-06 | nueva | Dar de alta el lote 9: pirámide inglesa de los niveles 5 a 7 y FA Trophy | OPS | P2 | 5 | PM-04-04 | ≈ 480 al día de media | ≈ 4,7 GB al año si se capturan todas las cuotas |
| PM-03-07 | nueva | Cargar la historia de las competiciones nuevas con el planificador de migración | OPS | P2 | 5 | DM-03 | La cifra la da `migration plan` (0 peticiones) | ≈ 0,1 MB por partido histórico sin cuotas |
| PM-03-08 | nueva | Registrar las competiciones pedidas que no existen o están descontinuadas, y vigilar su aparición | DOC | P2 | 3 | PM-03-01 | 0 | Nulo |
| PM-03-09 | OP-19 | Codificar los reglamentos de las competiciones colombianas nuevas y revisar la Copa | IA | P1 | 4 | PM-09-02 | 0 | Nulo |

### Bloque 4 · Peticiones e ingesta

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-04-01 | nueva | Repartir el cupo en carriles con techo y prioridad | BE | P0 | 2 | PM-01-02 | 0 (no añade; ordena) | Nulo |
| PM-04-02 | nueva | Añadir límites dinámicos, pausas automáticas y reserva de emergencia | BE | P0 | 2 | PM-04-01 | 0 | Nulo |
| PM-04-03 | nueva | Recortar los barridos que nadie lee | BE | P1 | 2 | PM-01-02 | Ahorro estimado de 800 a 1.500 al día (no medido por endpoint) | Menos escritura en `core` y en RAW |
| PM-04-04 | nueva | Ajustar la profundidad de la referencia al nivel de cobertura y a la prioridad | BE | P1 | 2 | PM-02-03 | Evita ≈ 69.000 peticiones del primer llenado de los lotes 5 a 9 (supuesto de 120 por equipo) | Menos filas en `core.player_transfers`, hoy 1,64 GB |
| PM-04-05 | nueva | Mostrar en la consola el consumo por carril, endpoint y competición | UX | P2 | 3 | PM-01-02, PM-04-01 | 0 | Nulo |

### Bloque 5 · Datos pagados y desaprovechados

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-05-01 | OP-06 | Guardar las estadísticas por mitad donde el proveedor las da | BE | P0 | 3 | PM-01-05, PM-02-03, DM-13 | 110 a 200 al día (afirmación de la nota 03; se medirá) | 4 filas por partido: menos de 100 MB al año |
| PM-05-02 | OP-06 | Rellenar las mitades de 2024 a 2026 por lotes nocturnos | OPS | P1 | 3 | PM-05-01, PM-04-01, DM-13 | ≈ 53.500 una sola vez (afirmación de la nota 03; la cifra exacta no se calculó) | Once noches a 5.000 |
| PM-05-03 | OP-06 | Hacer liquidables los córners por mitad con una regla nueva | BE | P1 | 4 | PM-05-02 | 0 | Nulo |
| PM-05-04 | OP-12 | Recuperar del RAW el tiempo añadido y el inicio real de cada parte | BE | P2 | 3 | Comprobar antes si `status.extra` está en los RAW finales (no confirmado) | 0 | Lectura de 1,86 GB de RAW por lotes, de noche y fuera del worker |
| PM-05-05 | OP-12, OP-13 | Exponer los campos ya guardados que la web no pinta | BE | P1 | 3 | PM-02-03 | 0 | Documentos algo mayores en `analytics.stat_documents` |
| PM-05-06 | OP-12 | Llevar el historial de bajas a «Bajas del partido» y a Intelligence, sin detalle médico | IA | P2 | 4 | DM-08 | 0 | Nulo |
| PM-05-07 | OP-14 | Calcular cada día el margen y la dispersión del mercado por liga | BE | P2 | 4 | PM-02-03 | 0 | Una fila por liga, mercado y día |
| PM-05-08 | OP-12 | Convertir rondas, fase y tabla de local y visitante en hechos de «importancia del partido» | BE | P2 | 4 | — | 0 | Nulo |

### Bloque 6 · APIs complementarias y redes

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-06-01 | nueva | Vigilar desde fuera que el servidor responde y que las tareas corren | OPS | P1 | 1 | DM-11 | 0 | Una petición saliente por ejecución de tarea |
| PM-06-02 | OP-09, OP-40 | Proponer el nivel de cada sitio oficial para que el dueño firme en bloque | IA | P1 | 3 | DM-05, DM-08 | 0 | Nulo |
| PM-06-03 | nueva | Medir cuánto tarda una baja en llegar por cada vía | IA | P2 | 4 | PM-06-02 | 0 | Nulo |
| PM-06-04 | nueva | Probar en sombra la API oficial de X sobre una lista cerrada, solo si el dueño lo aprueba | IA | P3 | 6 | DM-07, DM-08, PM-06-03 | 0 de API-Football | Nulo |

### Bloque 7 · Clima, estadios, altitud y contexto

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-07-01 | OP-07 | Confirmar que las coordenadas y la altitud de estadios están cargadas en producción | OPS | P0 | 1 | — | 0 | Nulo |
| PM-07-02 | OP-07 | Completar coordenadas en cascada, con procedencia y precisión por fila | BE | P1 | 3 | PM-07-01, DM-09 | 0 | Carga única de unos cientos de filas |
| PM-07-03 | OP-08 | Traer la previsión de MET Norway cumpliendo sus condiciones | BE | P1 | 3 | DM-06, PM-07-02 | 0 de API-Football | Unas cientos de peticiones salientes al día, repartidas con minutos aleatorios |
| PM-07-04 | OP-08 | Calcular viaje, descanso y congestión de cada equipo | BE | P1 | 3 | PM-07-02 | 0 | Cálculo por partido próximo |
| PM-07-05 | OP-08 | Mostrar el bloque «Contexto del partido» con clima, altitud, viaje y descanso (I03) | UX | P1 | 4 | PM-07-03, PM-07-04, PM-14-01 | 0 | Nulo |

### Bloque 8 · Equipos, jugadores, entrenadores y árbitros

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-08-01 | OP-11 | Medir la cobertura del árbitro y con cuánta antelación llega | BE | P1 | 1 | — | 0 | Nulo |
| PM-08-02 | OP-11 | Publicar el bloque «Árbitro designado» con tasas, muestra e intervalo | BE | P1 | 4 | PM-08-01, DM-08 | 0 | Agregado nocturno pequeño |
| PM-08-03 | OP-24 | Calcular cada noche la formación habitual y la rotación de cada equipo | BE | P1 | 3 | Reserva con EA | 0 | Alarga la pasada de las 07:20 UTC |
| PM-08-04 | OP-12 | Aprovechar la trayectoria del entrenador y los movimientos de plantilla | BE | P2 | 3 | — | 0 | Nulo |
| PM-08-05 | OP-15 | Publicar la dificultad de calendario con fórmula e incertidumbre | BE | P2 | 4 | Firma de publicación DM-14 | 0 | Nulo |
| PM-08-06 | OP-13 | Dar al portero y al jugador de campo su perfil con los datos nuevos (I06) | UX | P1 | 4 | PM-05-05, PM-14-01 | 0 | Nulo |
| PM-08-07 | OP-18 | Medir en LAB las fichas que exigen prueba antes de construir | IA | P3 | 6 | PM-12-02 | 0 | Nulo en el VPS |

### Bloque 9 · Competiciones, clasificaciones y escenarios

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-09-01 | OP-20 | Calcular las tablas colombianas completas a partir de una configuración por temporada | BE | P0 | 3 | PM-09-02 | 0 | Nulo |
| PM-09-02 | OP-20 | Cotejar a mano los artículos del reglamento antes de publicar una tabla | DOC | P0 | 2 | — | 0 | Nulo |
| PM-09-03 | OP-20 | Ofrecer la calculadora «¿Qué pasa si…?» en el navegador (I07) | UX | P1 | 4 | PM-09-01, PM-09-04, DM-14 | 0 | Nulo: se calcula en el navegador |
| PM-09-04 | nueva | Crear la página de competición con tablas, líderes, calendario y nivel de cobertura | UX | P1 | 4 | PM-02-05, PM-14-01 | 0 | Nulo |
| PM-09-05 | nueva | Publicar el directorio mundial de competiciones con nivel y prioridad (I08) | UX | P1 | 4 | PM-02-05 | 0 | Nulo |
| PM-09-06 | OP-13 | Calcular la tabla esperada con xG donde la cobertura de xG sea suficiente | BE | P3 | 5 | PM-02-03 | 0 | Nulo |
| PM-09-07 | OP-21 | Validar en LAB las probabilidades de temporada por simulación | IA | P3 | 6 | PM-12-02 | 0 | Nulo en el VPS |

### Bloque 10 · Estadísticas y visualizaciones

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-10-01 | OP-22 | Mostrar el embudo de remate y las dos zonas reales de tiro (M01) | FE | P0 | 4 | PM-02-05, PM-14-01 | 0 | Nulo |
| PM-10-02 | OP-25 | Mostrar la balanza del partido y la franja de estado del marcador (M04) | FE | P0 | 4 | PM-02-05, PM-14-01 | 0 | Nulo |
| PM-10-03 | OP-06 | Mostrar las estadísticas por mitad en el Match Center | FE | P1 | 4 | PM-05-01 | 0 | Nulo |
| PM-10-04 | OP-23 | Añadir capas de datos a la cancha de alineación (M02) | UX | P1 | 4 | PM-02-05, PM-14-01 | 0 | Nulo |
| PM-10-05 | OP-24 | Mostrar formación habitual y rotación en el perfil de equipo (M03) | FE | P1 | 4 | PM-08-03 | 0 | Nulo |
| PM-10-06 | OP-16 | Exigir etiqueta de evidencia, frase de lectura y revisión de accesibilidad en cada gráfica nueva | FE | P1 | 3 | Reserva con EA | 0 | Nulo |
| PM-10-07 | OP-45 | Explicar la probabilidad con una matriz de iconos y piezas educativas (M08) | UX | P2 | 5 | PM-02-05 | 0 | Nulo |
| PM-10-08 | OP-17 | Calcular fuera del servidor cuántos partidos necesita cada estadística para ser estable | IA | P2 | 5 | PM-12-02 | 0 | Nulo en el VPS |

### Bloque 11 · IA, noticias y crónicas

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-11-01 | OP-35 | Ampliar la hoja de hechos de la crónica con cifras calculadas por código | IA | P0 | 5 | PM-07-04, PM-05-01, PM-11-07 | 0 | Más cálculo en el trabajo `chronicle_v4`, por partido |
| PM-11-02 | OP-35 | Añadir clases de valoración al verificador de la crónica | IA | P1 | 5 | PM-11-01 | 0 | Nulo |
| PM-11-03 | OP-39 | Dar a la crónica un respaldo por plantillas con cada frase enlazada a su cifra | IA | P1 | 5 | PM-11-01 | 0 | Nulo |
| PM-11-04 | OP-36 | Extraer bajas y onces probables con reglas antes que con un modelo | IA | P2 | 5 | Etiquetas humanas del dueño (pendiente del Plan AD) | 0 | Nulo |
| PM-11-05 | OP-37 | Contar las salidas inválidas de Claude por causa antes de cambiar nada | IA | P1 | 1 | — | 0 | Nulo |
| PM-11-06 | OP-38 | Aislar por completo el agente de Partido del texto externo y repetir battery-v4 | IA | P0 | 3 | Reserva con Intelligence | 0 | Nulo |
| PM-11-07 | nueva | Garantizar que crónica, perfiles y estadísticas enseñan la misma cifra | IA | P0 | 5 | Reserva con EA e Intelligence | 0 | Nulo |
| PM-11-08 | nueva | Ordenar la biblioteca científica por método y lugar de aplicación | DOC | P2 | 2 | PM-00-04 | 0 | Nulo |
| PM-11-09 | OP-35 | Mostrar la crónica enriquecida con su hoja de hechos (I10) | UX | P2 | 5 | PM-11-01, PM-11-03, DM-14 | 0 | Nulo |
| PM-11-10 | OP-51 | Enviar un resumen diario informativo por el canal oficial de Telegram | IA | P3 | 6 | DM-08 | 0 | Un envío al día |

### Bloque 12 · Evaluación científica y LAB

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-12-01 | OP-33 | Completar el tablero privado de evaluación | IA | P1 | 5 | Reserva con Intelligence y con medición de picks | 0 | Cálculo semanal por lotes |
| PM-12-02 | OP-04 | Sacar el LAB del servidor con una exportación de solo lectura y un manifiesto | OPS | P1 | 2 | Autorización del dueño | 0 | Exportación nocturna fuera de las ventanas de copia |
| PM-12-03 | OP-26, OP-27, OP-28, OP-29, OP-30 | Ejecutar la cartera de modelos del LAB con protocolos preregistrados | IA | P2 | 6 | PM-12-02 | 0 | Nulo en el VPS |
| PM-12-04 | OP-34, OP-31, OP-10 | Adoptar el protocolo de patrones v2 y probar altitud, viaje y señales externas | IA | P2 | 6 | PM-12-02, PM-07-02 | 0 | Nulo en el VPS |
| PM-12-05 | OP-41, OP-48, OP-53, OP-54 | Mantener el LAB de Intelligence, participación y analítica espacial dentro de sus condiciones | IA | P3 | 6 | DM-08 | 0 | Nulo en el VPS |
| PM-12-06 | nueva | Evaluar los modelos por competición y por nivel de cobertura | IA | P1 | 5 | PM-02-03 | 0 | Cálculo semanal |

### Bloque 13 · Optimización, limpieza y costes

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-13-01 | OP-01 | Llevar a firma el protocolo de retirada de `review-v2` y ordenar el calendario de retiradas | DOC | P0 | 0 | DM-10 | 0 | Menos trabajos de IA en el worker cuando se ejecuten las retiradas |
| PM-13-02 | OP-02 | Dejar de duplicar rasgos hacia adelante sin borrar historia | BE | P1 | 2 | Reserva con Intelligence | 0 | Menos escritura |
| PM-13-03 | OP-02 | Guardar una versión de paquete de partido solo cuando cambia | BE | P1 | 2 | Reserva con Intelligence | 0 | Menos escritura y menos CPU de PostgreSQL |
| PM-13-04 | OP-03 | Sacar de la imagen de producción las bibliotecas que nadie importa | BE | P1 | 2 | Confirmar que ningún guion del servidor las usa | 0 | Imagen más pequeña y construcción más corta |
| PM-13-05 | nueva | Medir la memoria del worker por trabajo y decidir qué sale a procesos por lotes | OPS | P0 | 1 | — | 0 | Instrumentación ligera |
| PM-13-06 | nueva | Fijar la política de volcados locales y de caché de compilación, con la sesión de seguridad | OPS | P2 | 3 | Decisión D1 de la auditoría (política de copias) | 0 | Libera disco cuando se apruebe |
| PM-13-07 | nueva | Retirar `/odds/best` y la página antigua de cuotas, ya sustituidas | UX | P2 | 2 | DM-10 | 0 | Nulo |

### Bloque 14 · Unificación UX/UI

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-14-01 | nueva | Construir los estados «información no disponible» como componentes compartidos (I12) | UX | P0 | 3 | PM-02-05 | 0 | Nulo |
| PM-14-02 | nueva | Adaptar el Match Center a los niveles A, B, C y D leyendo la matriz (I01 e I04) | UX | P0 | 4 | PM-02-06, PM-14-01, PM-10-01, PM-10-02 | 0 | Una lectura más por partido, con caché |
| PM-14-03 | OP-15, OP-24, OP-12 | Integrar en el perfil de equipo formación, calendario, bajas e historial de entrenador (I05) | UX | P1 | 4 | PM-10-05, PM-08-04, PM-08-05 | 0 | Nulo |
| PM-14-04 | nueva | Hacer que Cuotas, Picks, Noticias y Mi parlay lean la matriz sin rediseñarse | UX | P1 | 5 | PM-02-06 | 0 | Nulo |
| PM-14-05 | OP-44 | Mejorar la rapidez en móvil solo donde la medición real lo pida | FE | P2 | 5 | — | 0 | La precarga añade lecturas a la API |
| PM-14-06 | OP-43 | Ofrecer un calendario suscribible de los equipos seguidos | BE | P2 | 5 | Revisión de seguridad del testigo (H de API y web) | 0 | Lecturas periódicas de clientes de calendario |
| PM-14-07 | OP-46 | Añadir el modo «solo fútbol» y la pausa voluntaria | UX | P2 | 5 | PM-14-04 | 0 | Nulo |
| PM-14-08 | OP-47 | Permitir descargar el historial de picks publicados, con calibración e incertidumbre | UX | P3 | 6 | Apertura de Transparencia por el dueño | 0 | Nulo |
| PM-14-09 | OP-49 | Generar una tarjeta propia al compartir un partido, tras piloto y visto bueno legal | FE | P3 | 6 | DM-08, DM-12 | 0 | CPU por imagen |
| PM-14-10 | OP-50 | Publicar `llms.txt` y dejar coherentes `robots.txt` y `noindex` | FE | P3 | 6 | DM-12 | 0 | Nulo |
| PM-14-11 | nueva | Verificar la trazabilidad entre cada lámina del lienzo y su pantalla real | UX | P1 | 6 | Pantallas de las olas 4 y 5 | 0 | Nulo |

### Bloque 15 · Integración, pruebas y cierre

| Id | OP | Objetivo | Área | Prioridad | Ola | Dependencias | Peticiones | Impacto en el servidor |
|---|---|---|---|---|---|---|---|---|
| PM-15-01 | nueva | Probar la matriz de extremo a extremo con una competición real por nivel | CI | P0 | 5 | PM-14-02 | 0 | Nulo |
| PM-15-02 | nueva | Pasar WebKit, regresión visual y Lighthouse móvil a las pantallas nuevas | CI | P1 | 6 | PM-14-11 | 0 | Nulo |
| PM-15-03 | nueva | Encender los interruptores en orden, con kits auditados | OPS | P0 | 6 | Aceptación de cada pieza | 0 | Recreación de contenedores con `predigolctl up` |
| PM-15-04 | nueva | Cerrar el plan con mediciones a 30 días y documentos de estado al día | DOC | P1 | 6 | PM-15-03 | ≈ 15 (las mismas sondas) | Nulo |

## 10. Intelligence, crónicas y biblioteca científica

La crónica gana doce hechos nuevos calculados por código y ninguna llamada más a Claude. Todo lo de este apartado nace en sombra, en zona de la sesión de Intelligence, y sale solo con firma.

### Más hechos, mismas cifras

Regla: un hecho de la crónica se lee de la misma fuente que la pantalla de estadísticas y el perfil. La tarea PM-11-07 lo prueba partido a partido.

| Hecho nuevo de la hoja | Fuente única | Tarea que lo crea |
|---|---|---|
| Descanso, congestión y viaje | Calendario y estadios | PM-07-04 |
| Altitud y clima previsto | `core.venue_geo`, MET Norway | PM-07-02, PM-07-03 |
| Árbitro: tasas con muestra | Agregado de árbitros | PM-08-02 |
| Estadísticas por mitad | `core.fixture_team_stats_period` | PM-05-01 |
| Embudo de remate y franja de estado | C-13 y eventos | PM-10-01, PM-10-02 |
| Puntos rescatados y tramos de goles | Eventos | PM-11-01 |
| Tiempo añadido | RAW reprocesado | PM-05-04 |
| Importancia del partido | Rondas y tablas | PM-05-08 |
| Formación habitual y rotación | C-13 | PM-08-03 |

Cada hecho lleva su nivel de cobertura. Si la celda es C o D, el hecho no entra en la hoja. Así la crónica de una liga D es corta, no inventada.

### Qué cambia en la cadena

| Pieza | Cambio | Estado tras el cambio |
|---|---|---|
| Hoja de hechos | Versión nueva con huella | Sombra |
| Verificador | Una regla por clase de valoración («dominó», «remontó») | Sombra |
| Respaldo por plantillas | Texto sin modelo cuando el redactor falla | Sombra |
| Bajas y onces | Reglas antes que modelo, como quinto brazo | Sombra |
| Agente de Partido | Solo recibe texto tipado y en cuarentena | battery-v4 medida y superada |
| Salidas inválidas | Primero se cuentan | Solo lectura |

Lo que no cambia: los modelos dan los números, el modelo de lenguaje explica y la decisión es código.

El coste por crónica se vigila. La hoja más larga añade tokens de entrada. El criterio de aceptación es no superar el 110 % del coste actual.

### Biblioteca científica: método, evidencia y datos

Son tres cosas distintas y no se mezclan.

| Clase | Qué es | Dónde vive | Regla |
|---|---|---|---|
| Método | Una técnica publicada | En el código y en su documento | Se cita; no se copia texto |
| Evidencia de partido | Hechos de un partido concreto | Hoja de hechos, con fuente y fecha | Es lo único que entra en un prompt |
| Datos de entrenamiento | Series para ajustar modelos | Base propia y LAB | Solo con licencia que lo permita |

Ningún libro ni artículo entra en un prompt. Reglas completas en [`DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md`](DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md).

| Método | Referencia | Dónde se aplica | Estado de la referencia |
|---|---|---|---|
| Intervalo de Wilson | Brown, Cai y DasGupta (2001) | Estadísticas, árbitro y niveles de cobertura | Comprobada hoy |
| Poisson, Dixon-Coles y Elo | Base de los modelos | `fbi/models`, `fbi/features/elo.py` | Sin cambio |
| Plus-minus de jugadores | Holmes y McHale (2024) | Protocolo E6 del Plan Intelligence | Comprobada hoy |
| Fiabilidad y resolución | Murphy (1973) | Tablero de evaluación (PM-12-01) | No reabierta |
| Capacidad predictiva superior | Hansen (2005) | Contraste de retadores en LAB | No reabierta |
| Control de falsos descubrimientos | Protocolo de patrones v2 | LAB (PM-12-04) | Pendiente de simular |
| Frecuencias naturales | Gigerenzer et al. (2005) | Probabilidad en iconos (I09) | Comprobada hoy |
| Paleta para daltonismo | Wong (2011) | Sistema «Noche de partido» | Comprobada hoy |
| Ventaja de local y público | Ponzo y Scoppa (2018) | LAB de ventaja de local | Comprobada hoy |
| Patrones contra inyección | arXiv 2506.08837 | Aislamiento del agente (PM-11-06) | Parcial: licencia no vista |

La tarea PM-11-08 publica el índice completo. Las referencias se comprobaron en registros bibliográficos, no leyendo los artículos.

### Fuentes de noticias

Solo 3 de 2.001 fuentes están firmadas [C] (anexo E de la nota de reconciliación, OP-09; directorio `config/sources/directorio_v2_2026-11-16.json`). La tarea PM-06-02 propone el nivel de cada sitio oficial para firma en bloque. De un RSS se guarda título, fecha y enlace, nunca el cuerpo. UEFA y FIFA quedan fuera: sus términos no cubren un uso comercial [P].

## 11. Optimización, limpieza y reducción de costes

Ninguna retirada de OP-01 se puede ejecutar hoy. Lo accionable es una firma, tres cambios de higiene y una medición de memoria. Nada de este apartado borra datos.

### Qué sigue activo y qué exige su retirada

| Candidato | Estado el 19-nov-2026 [C] | Protocolo o comparación | Qué falta |
|---|---|---|---|
| `review-v2` y Opus en la revisión | Activo (`on`) | `review-retire-v1`: IC95 inferior de −0,005 o mejor, 300 selecciones y 14 días | La firma; sin ella no corre la ventana de 4 semanas |
| Crónica `user-narrative-v3` | Activa | `retire-compare-v1`, firmado | Muestra de 100 partidos de `chronicle-v4` |
| `brief-v8` y `match-analysis-v1` | Activos, sin interruptor propio | La misma comparación | Una pieza aparte, con la sesión UX |
| Brazo Haiku del Council | En sombra | Decisión del dueño | El banco C02 no pasa |
| Council completo | Activo | AD-D10 y AD-K03, firmados | Muestra |
| Extractores v1 a v3 | v1 en producción | AD-A01 y AD-C09 | Etiquetas humanas del dueño |
| Revisiones congeladas | Congeladas, solo lectura | — | Nada; no se borran |
| `/odds/best` y página antigua | En `main` | Siete días sin uso y visto bueno | Leer el recuento |

Retiradas seguras hoy, sin comparación: sacar bibliotecas sin uso de la imagen (OP-03) y archivar `competitions.yaml` con una nota. Las dos son reversibles con un `revert`.

### Protocolo común de retirada

1. La comparación se preregistra y se firma antes de medir.
2. Se cumple su muestra mínima y su plazo.
3. Se apaga por pasos con su interruptor: completo, sin Opus, muestra del 20 %, apagado.
4. Las tablas quedan en solo lectura. No se borra ninguna fila.
5. El resultado se anota, pase o no pase.

### Higiene de base, sin tocar la historia

| Objetivo | Dato medido [M] | Cambio | Tarea |
|---|---|---|---|
| `features.fixture_features` | 4,57 GB, 43,3 millones de filas | Escribir un conjunto solo si cambia | PM-13-02 |
| `ai.match_packets` | 2,89 GB; 29,5 versiones por partido | Guardar versión solo si cambia | PM-13-03 |
| Tres consultas calientes | Sin medir de nuevo | Revisar planes y autovacuum | PM-13-03 |
| Cuotas | 0,12 GB al día; freno a los 25 GB [C] | Sin cambio: el archivo frío espera a D1 | — |

El precedente es BE-050, que ya conserva documentos solo cuando cambian.

### Memoria del worker: el límite real

El worker usa 2,80 de 3 GiB y tocó el techo 4.160 veces en 10 horas, sin muertes por memoria [M]. La suma de límites de los contenedores es 11,63 de 11,68 GiB: no hay de dónde subir.

Por eso el plan impone tres reglas. Ningún trabajo nuevo corre dentro del worker. Todo cálculo pesado va de noche, en proceso aparte y con tope. La tarea PM-13-05 mide la memoria por trabajo antes de la ola 2.

### Coordinación con seguridad

| Asunto | Regla |
|---|---|
| Volcados locales (16 GB) y caché de compilación (4,7 GB) | No se borra nada hasta aprobar el inventario |
| Política de copias | Decisión D1 de la auditoría; condiciona OP-04 |
| Exportación para el LAB | Lista cerrada de tablas; nunca `auth` ni `customer` |
| Tablas nuevas | Permisos explícitos en `grants.sql` |
| Accesos y llaves | Ninguno nuevo |

### Ahorro esperado

| Partida | Ahorro | Tipo |
|---|---|---|
| Retiradas de IA | Unos 85 USD al mes | Estimación del Plan AD, no medición |
| Barridos sin lector | 800 a 1.500 peticiones al día | Estimación; se medirá por endpoint |
| Rasgos repetidos | 21,6 % de rasgos repetidos medidos en `features.feature_sets` (nota 01) | El ahorro en crecimiento no está medido |
| Imagen de producción | Unos 103 MB de ruedas | Afirmación de la investigación |

El gasto de IA de la primera quincena de noviembre tiene dos cifras de Exa, 12,90 y 81,22 USD. No se resolvió.

## 12. UX/UI unificado

Todo el diseño nuevo está publicado en el lienzo principal, «PrediGol — Mockups Noche de partido» (lienzo privado del dueño): cuatro páginas nuevas con 54 artboards, revisados visualmente a tamaño real. Este plan fija la trazabilidad.

| Página del lienzo | Artboards | Contenido |
|---|---|---|
| «12 · Innovación 2026–27» | 22 | Láminas I01 a I12: el alcance |
| «13 · Evolución futura» | 4 | Láminas F01 a F04: fuera del alcance |
| «14 · Estadísticas avanzadas (V2)» | 10 | Trasladados y unificados |
| «15 · Intelligence» | 18 | Pantallas de Intelligence |

Pendiente declarado: las versiones de tableta y escritorio de 16 pantallas de Intelligence, la versión móvil de dos pantallas de consola y los estados interactivos de seis V2, que quedaron estáticos. En el visor, los iconos y el escudo no se pudieron comprobar con la sesión del dueño. El detalle está en `H_revision_visual.md` y `H2_revision_visual.md`.

Niveles en pantalla: cada módulo se muestra según el nivel de su propio dato en esa competición y temporada (sección 5). Las láminas I04 (B, C y D) son ejemplos ilustrativos de tres competiciones, no una regla por nivel global. La nota de niveles del lienzo se alinea con la sección 4 antes de DM-04.

### Página «12 · Innovación 2026–27»

| Lámina | Contenido | Tareas | Pantalla real |
|---|---|---|---|
| I01 | Match Center con cobertura A: embudo y zona de remate (M01), balanza y franja (M04), mitades | PM-10-01, 10-02, 10-03, 14-02 | `web/src/product/match/StatsTab.tsx`, `SummaryTab.tsx` |
| I02 | Alineaciones con capas (M02) | PM-10-04 | `LineupsTab.tsx` |
| I03 | Contexto: árbitro (M06) y clima, altitud, viaje y descanso (M07) | PM-08-02, 07-05 | `ContextBlocks.tsx`, `SummaryTab.tsx` |
| I04 | Match Center con cobertura B, C y D: tres competiciones de ejemplo | PM-14-02 | `useMatchTab.ts`, `MatchPage.tsx` |
| I05 | Perfil de equipo: formación y rotación (M03), calendario, bajas, entrenador | PM-10-05, 08-05, 05-06, 08-04, 14-03 | `teams/TeamPage.tsx`, `teams/stats/TeamStatsHub.tsx` |
| I06 | Perfil de jugador con datos nuevos, incluido portero | PM-05-05, 08-06 | `teams/PlayerPage.tsx`, `teams/stats/PlayerStatsHub.tsx` |
| I07 | Competición: tablas colombianas, «qué se juega», calculadora (M05) | PM-09-01, 09-03, 09-04 | Ruta nueva: hoy no existe |
| I08 | Directorio mundial con nivel y prioridad | PM-09-05 | Ruta nueva |
| I09 | Probabilidad en iconos (M08) | PM-10-07 | `explain/ExplainSheet.tsx` |
| I10 | Crónica enriquecida con hoja de hechos | PM-11-09 | `PostmatchTab.tsx`, `AnalysisBlock.tsx` |
| I11 | Consola: matriz de disponibilidad | PM-02-08, 04-05 | `routes/admin.competitions.tsx` |
| I12 | Estados «información no disponible» | PM-14-01 | `product/shared/` |

### Página «13 · Evolución futura»

F01 a F04 son los antiguos M09 a M12: mapa de calor, disparos con xG, red de pases y análisis territorial. Exigen coordenadas que el proveedor no da. Quedan fuera del alcance (OP-55) y no tienen tarea.

### Reglas de diseño que el plan respeta

- **Anchos del lienzo:** móvil 390, tableta 820 y escritorio 1440, con la hoja `pg.css`.
- **Sin tarjetas vacías.** Un bloque sin dato no se pinta. Un bloque parcial lo dice.
- **Cada estado dice qué pasa, qué sigue valiendo y qué se puede hacer.** Es la regla de la lámina S5.
- **Cada cifra con su muestra, su intervalo y su origen.** La tarea PM-10-06 lo exige como criterio de aceptación.
- **Rótulos honestos:** «2 zonas», «posición nominal», «dominio aproximado», «xG de API-Football», «formación declarada».
- **Mi parlay no se rediseña.** Conserva interfaz y reglas. Solo lee la matriz, con igualdad total exigida en 1.000 selecciones.
- **Cuotas, Picks y Noticias** conservan sus láminas vigentes (C01 a C06, K01 a K08, N01 a N04).

### Coordinación con la sesión UX

Casi todo `web/**` es zona del plan unificado UX. Los números UX-159 a UX-171 están tomados. La página de competición (I07) roza UX-162 a UX-166: se coordina y no se duplica. Las piezas en carpetas `stats` son zona del Plan EA.

Tres pendientes heredados entran en el cierre: WebKit, regresión visual y Lighthouse móvil (PM-15-02).

El anexo G relaciona 26 funcionalidades con su tarea, su lámina, su ruta y su componente real.

## 13. Presupuesto operativo

El escenario recomendado, B, no añade coste mensual: sigue en 26 o 29 USD de API-Football, según cuál sea el precio real. Los sobres de IA no cambian.

| Partida | Hoy | Escenario A | Escenario B | Escenario C |
|---|---|---|---|---|
| Peticiones al día, media | 17.845 [M] | ≈ 17.000 [S] | ≈ 18.300 [S] | No estimable |
| Pico diario con rellenos | 23.430 [M], sin rellenos | ≈ 29.500 [S] | ≈ 38.400 [S] | — |
| Presupuesto interno | 60.000 [C] | 60.000 | 60.000 | A definir |
| Competiciones seguidas | 138 [M] | 146 | 200 | Más de 200 |
| Almacenamiento añadido al año | — | 0,7 GB [S] | 9,5 GB como máximo [S] | Proporcional |
| Crecimiento actual de cuotas | 0,12 GB al día [M] | Igual | Hasta 0,15 GB al día [S] | Mayor |
| CPU | 15,5 % de media [M] | Sin cambio apreciable | Sin cambio apreciable | Sin medir |
| Memoria del worker | 93,4 % de 3 GiB [M] | No aumenta | No aumenta | Exige ampliar |
| IA (topes) | 185, 55 y 35 USD al mes [C] | Igual | Igual | Igual |
| API-Football | 26 o 29 USD al mes | Igual | Igual | 36 o 39 USD [P] |
| Servicios nuevos | — | 0 USD | 0 USD | 0 USD |
| X en sombra, solo si se aprueba | — | — | 30 a 75 USD al mes [D] | — |

Con 123 GB libres [M] y unos 4,5 GB al mes entre cuotas y lotes [D], el disco aguanta más de un año solo por cuotas y lotes [S]. Es un supuesto: no incluye el crecimiento del resto de tablas, que no tiene histórico (PM-01-02), ni los volcados locales, que hoy ocupan 16 GB y oscilan.

Tres avisos:

- **Los precios de API-Football tienen dos versiones.** La página viva dice 26 y 36 USD; un archivo interno dice 29 y 39. El panel del dueño dirá cuál se cobra.
- **El ahorro de IA no está medido.** Los 85 USD al mes son estimación.
- **Las cifras [S] dependen de los partidos por temporada supuestos.** La sonda de cada lote las corrige.

El anexo F detalla 65 partidas con su tipo de cifra y su fuente.

## 14. Registro de decisiones

El dueño tiene 14 decisiones; tres bloquean el arranque y una tiene fecha: el 29-nov-2026. El anexo I da opciones, recomendación y efecto de cada una.

| Id | Decisión | Recomendación | Qué bloquea |
|---|---|---|---|
| DM-01 | Renovar API-Football y elegir plan y duración | Renovar Ultra antes del 25-nov; duración corta hasta conocer el cambio de plan | Toda la ingesta |
| DM-02 | Aprobar el plan y el escenario | Escenario B, por pasos | Todas las olas |
| DM-03 | Altas por lotes, regla de admisión e historia | Aprobar los lotes 5 a 9; admitir niveles C y D; decidir temporadas de historia | Bloque 3 |
| DM-04 | Umbrales de niveles | 95, 80 y 50 %; 30 y 10 partidos; 5 y 3 casas | Bloque 2 |
| DM-05 | Firma de fuentes oficiales | Firmar en bloque por dominio | Noticias con fuente primaria |
| DM-06 | MET Norway | Que una persona acepte los términos del 5-nov-2026 | Clima (I03) |
| DM-07 | X de pago en sombra | No, hasta medir el adelanto y oír al abogado | PM-06-04 |
| DM-08 | Consultas al abogado | Enviar la lista de siete asuntos | Árbitro, bajas, X, tarjeta, canal, LAB espacial |
| DM-09 | Comprobaciones manuales | Captura de la licencia de Wikidata; panel de API-Football | Estadios; precio real |
| DM-10 | Retiradas de OP-01 | Firmar `review-retire-v1`; visto bueno a `/odds/best` | Ahorro de IA |
| DM-11 | Vigilancia externa | Crear las dos cuentas gratuitas | PM-06-01 |
| DM-12 | Capa pública | Mantener cerrado; `llms.txt` y tarjeta al final | OP-49, 50 y 52 |
| DM-13 | Estadísticas por mitad | Construir si la sonda da 80 % o más; autorizar el relleno | Mitades y córners por mitad |
| DM-14 | Firmas de publicación | Publicar primero lo demostrado, no lo predictivo | «Qué se juega», tablas, crónica |

Quedan fuera las decisiones de otros planes: D1 a D12 de la auditoría de seguridad y D-05 del plan UX. Este plan depende de D1 y de D-05, y no las reabre.

## 15. Verificaciones, límites y anexos

Este plan se apoya en mediciones del 19-nov-2026 y deja 12 cosas sin medir y 9 contradicciones abiertas. Ninguna cifra supuesta se usa para una decisión irreversible.

### Lo que no se midió

| N.º | Qué | Por qué importa | Tarea |
|---|---|---|---|
| 1 | Consumo por endpoint | Decide los recortes | PM-01-02 |
| 2 | Picos por minuto más allá de 48 horas | Decide el paso a un plan superior | PM-01-02 |
| 3 | Histórico de tamaño de la base | Proyección de disco | PM-01-02 |
| 4 | Causa del 29-oct | Riesgo de corte | PM-01-03 |
| 5 | Si el proveedor publica cuotas donde faltan | Nivel de cuotas real | PM-01-04 |
| 6 | Cobertura de `half=true` por liga | Decide las mitades | PM-01-05 |
| 7 | Carga de `core.venue_geo` en producción | Bloquea clima y viaje | PM-07-01 |
| 8 | Antelación del árbitro | Viabilidad del bloque | PM-08-01 |
| 9 | Estado real de los interruptores | Qué ve hoy el lector | PM-00-02 |
| 10 | Memoria del worker por trabajo | Qué se saca del worker | PM-13-05 |
| 11 | Partidos por temporada de las altas | Coste de cada lote | PM-03-01 |
| 12 | Tiempo y memoria del recálculo de la matriz | Horario nocturno | PM-02-03 |

Tampoco se pudieron listar los PR abiertos. No se accedió al panel de la cuenta de API-Football.

### Contradicciones abiertas

| Asunto | Versiones | Tratamiento |
|---|---|---|
| Precio de Ultra | 26 USD en la página viva; 29 en el documento interno | El dueño lo mira en su panel (DM-09) |
| Renovación | «No auto-renewal» en el texto literal; «Automatic Renewal» en un resumen automático | Se trata como sin renovación automática |
| Mercados extraídos | 55 marcados para extraer; 42 con historia en 14 días | Se dan las dos cifras |
| Gasto de Exa en noviembre | 12,90 y 81,22 USD | Sin resolver |
| Dataset de Wyscout | CC BY 4.0 en figshare; «non-commercial» en D4Science | Solo LAB; abogado |
| Licencia de Wikidata | CC0 según lectura interna; no verificable hoy | Captura manual del dueño |
| Versión de `@vercel/og` | 1.0.3 en el registro; 0.6.2 en la web de npm | Manda el registro; fijar versión |
| Horas de `fixtures_sync` | Dos series en los documentos | Se leen antes de cada despliegue |
| Horas de copia | 03:30, 04:15 y 05:30 UTC en el repositorio; 04:30, 05:15 y 06:31 en `list-timers` | Probable hora local del servidor; confirmar en PM-00-02 |

Resueltas con fuente: `half=true` existe; el reglamento vigente de la Liga es el V0 del 14-ene-2026; la Copa cambió a partido único el 25-ago-2026.

### Supuestos de este plan

- Partidos por temporada de las 62 altas, por formato habitual.
- 120 peticiones por equipo en un primer llenado completo y 3 en uno mínimo.
- 0,10 MB por partido sin cuotas y 1,18 MB de cuotas, por proporción.
- Ahorro de 800 a 1.500 peticiones al día por recortes.
- Tope de 512 MB y menos de 5 minutos para el recálculo nocturno.
- Coste de mitades: 110 a 200 al día y unas 53.500 una vez, según la nota de inventario.
- Número C-16 del contrato y nombres de tablas: propuestas a confirmar al reservar.

### Límites

- No es asesoría legal. Las preguntas al abogado están en DM-08.
- No promete rentabilidad. Ningún mercado tiene hoy ventaja demostrada.
- Los niveles miden disponibilidad de datos, no calidad deportiva.
- La cobertura de cuotas es una muestra de 46 días.
- El lienzo está publicado y revisado a tamaño real: 54 artboards en cuatro páginas nuevas (sección 12), y los códigos I01 a I12 y F01 a F04 se comprobaron contra él. Quedan pendientes las versiones de tableta y escritorio de 16 pantallas de Intelligence, la versión móvil de dos pantallas de consola y los estados interactivos de seis V2. En el visor, los iconos y el escudo no se pudieron comprobar con la sesión del dueño. Detalle en `H_revision_visual.md` y `H2_revision_visual.md`.

### Anexos

| Anexo | Archivo | Contenido |
|---|---|---|
| A | `A_matriz_mundial_competiciones.csv` | 1.264 filas: prioridad, acción, lote y niveles |
| B | `B_matriz_estadisticas_mercados.csv` | 272 filas: nivel por dato, mercado y familia |
| C | `C_inventario_api_football.csv` | 1.049 campos de 39 endpoints |
| D | `D_catalogo_apis_actualizado.csv` | 110 recursos de API con su decisión; regla de alta en [`DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md`](DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md) |
| E | `E_destino_59_oportunidades.csv` | Destino, tareas y condición de cada oportunidad |
| F | `F_presupuesto_operativo.csv` | 65 partidas de los tres escenarios |
| G | `G_trazabilidad_visual.csv` | 26 funcionalidades con lámina y componente |
| H | `anexo_fichas_tareas.md` y `plan_tareas.csv` | 108 tareas con sus 20 campos |
| I | `I_registro_decisiones.md` | 14 decisiones con opciones |

Los anexos A, B, D, E, F y G se generan con los guiones de la carpeta `scripts/` del trabajo de planificación (no está en el repositorio). Son reproducibles a partir de las mediciones. En el repositorio solo están E y G, en [`plan_maestro_pm_2026/`](plan_maestro_pm_2026/).

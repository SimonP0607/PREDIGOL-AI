# A12 · Transparencia: «Cómo le va a PrediGol»

Plan maestro UX, sección 31 y ficha A12. Rama `ux/a12`. **Sin migración.** La página responde con datos a «¿funciona?»: lo que
PrediGol publicó y cómo fue, los días sin picks y por qué, y lo que sigue en evaluación, **siempre con su muestra**. Solo lee datos
que ya existen: no cambia picks, modelos, reglas ni nada de PrediGol Intelligence. La ven los clientes con sesión **cuando tú la
abras** (`FBI_TRANSPARENCY`, tras tu revisión: P9); hasta entonces solo la ves tú. **Ampliada en UX-010** (plan de cierre, 1.5):
lista de picks uno a uno, parlays, «Qué es un pick», «Cómo leer probabilidades y cuotas», historial de cambios y el aviso de «cero
picks» — ver la sección 13.

## 1. Qué ve el cliente

Página `/transparency` (ES y EN), en tarjetas apiladas en el móvil, la cifra y su n juntas:

| Bloque | Qué dice | Regla |
| --- | --- | --- |
| Picks publicados | Publicados, ganados, perdidos, medio ganados, medio perdidos, devueltos, anulados y pendientes en **7 días, 30 días y todo el histórico** (periodos fijos, cortados en la zona horaria del lector como en Mis picks) | Con menos de **25 liquidados**, solo conteos («la muestra es demasiado pequeña…»); desde 25, unidades y rentabilidad **± su margen**; por debajo de **100**, «la muestra todavía no permite concluir» |
| Días sin picks | Cuántos de los últimos 30 días de producto (nunca antes del 4-oct-2026, cuando empezó la regla) no tuvieron picks, y por qué | El motivo de cada día y, rotulado como reconstrucción, lo que PrediGol Intelligence midió esos días |
| Por tipo de apuesta | Todo el histórico por mercado | Los tipos con menos de 25 liquidados, juntos en «Otros» |
| Valor de línea | La cuota publicada frente a la probabilidad sin margen del consenso en la última captura antes del inicio | Definición `clv-v1` rotulada con su fecha (22-oct-2026); media y % positivo solo desde 25 picks |
| Pronóstico | 1X2, más/menos de 2,5 y ambos marcan: calibrado o «sin calibrar»; cuando está calibrado y hay 300 partidos, lo dicho frente a lo ocurrido por tramos de 10 puntos | Sin cifras para un mercado sin calibrar |
| En evaluación | Cuántos tipos de apuesta se miden frente al mercado y cuántos lo superaron; cuántos pronósticos de modelos calificados hubo | Solo recuentos: nunca una selección, una cuota o un resultado de evaluación |
| Cómo se decide | Qué tiene que pasar para que haya un pick, en palabras, y la distinción pronóstico ≠ valor ≠ pick | Sin cifras internas que cambien con el tiempo |

Al pie, **las definiciones vigentes con su fecha** («si una cambia, lo decimos aquí y recalculamos el histórico»). Nunca: elegir el
periodo que mejor queda, rachas, «el pick estrella», proyecciones, comparaciones con otros, ni mezclar evaluación con lo publicado
(una prueba busca esas palabras en ES y EN).

**Enlaces:** desde el menú de la cuenta («Cómo le va a PrediGol») y desde un día sin picks ya decidido (Picks e Inicio), **solo
cuando la página está abierta a los lectores** (el campo `transparency` de `/auth/me`) — nunca un enlace a una página que diría «no
publicada». Tú lo ves siempre, con el aviso «Vista previa: los lectores todavía no ven esta página». El onboarding (A13) y «Más»
(A15) enlazarán aquí cuando existan.

## 2. De dónde sale cada cifra (solo lectura)

- **Un pick publicado** es un ítem del set `qualified` del día (`picks.daily_set_items`): el único que ve un cliente. **El set
  `evaluation` no se nombra en ninguna consulta** (una prueba lo comprueba sobre el código del servicio y del contraste).
- La fórmula es **la de Mis picks** (`fbi.userdata.records`): una unidad por pick liquidado; un anulado devuelve la apuesta y no
  cuenta; un devuelto cuenta sin ganancia. Una prueba de integración pasa los mismos datos por las dos y exige el mismo resultado.
- **Margen:** un error estándar, `1/√n` → ±20 puntos con 25, ±14 con 50, ±10 con 100, ±5 con 400 (los números del plan).
- **Días sin picks:** un día de producto (Bogotá, como los sets) sin ítems en el set `qualified`. Motivo:
  `no_matches` (ningún partido de las competiciones seguidas), `no_qualified_candidates` (ningún pronóstico de un modelo que haya
  superado al mercado en su prueba — `picks.picks.qualification` — así que nada podía publicarse) o `not_chosen` (los hubo y
  ninguno cumplió el resto de la regla). **Lo que midió Intelligence** se reconstruye con sus decisiones guardadas
  (`intel.decisions`, la última de cada selección antes del inicio): cuántas selecciones y el primer filtro que más las paró — de
  los candidatos calificados cuando los hubo —, rotulado «reconstruido con las decisiones guardadas».
- **Valor de línea:** `fbi.market.closing_value.clv` (una sola definición en todo el sistema) sobre la cuota del ítem y el
  consenso Shin de la última captura antes del inicio.
- **Pronóstico:** el último `models.match_forecasts` (`forecast-v1`) antes del inicio de cada partido terminado de los últimos 90
  días, frente a su resultado en tiempo reglamentario. Estado del mercado: el de la mayoría de sus pronósticos de las últimas dos
  semanas de la ventana. Tramos de menos de 30 casos no se muestran (se cuentan como omitidos).
- **En evaluación:** el rol más nuevo de cada combinación mercado × modelo en `intel.promotions` (`market_edge`, `edge-gate-v1`) y
  los pronósticos calificados de la ventana de los días sin picks.

## 3. Línea base de producción (26-oct-2026, 07:10 UTC, solo lectura)

- **Ningún set `qualified` ni pick calificado nunca**: solo sets de evaluación (23, del 4 al 26-oct). Todas las versiones de
  modelo son «experimental»; todas las comparaciones guardadas frente al mercado dicen «worse» (1X2 contra 7 referencias, 27
  veces; más/menos de 2,5 contra 3, 8 veces); las versiones de los últimos 14 días no tienen prueba completada.
- Intelligence mide **11 combinaciones mercado × modelo de 5 tipos de apuesta (1X2, AH, BTTS, DC, OU): ninguna validada**.
  Calibrador campeón solo en más/menos (OU).
- 585 partidos terminados con pronóstico antes del inicio desde el 23-oct (OU calibrado en 569).
- `intel.decisions` desde el 13-oct: nunca APROBADO; primer filtro que más para: calibración (18.030), mercado (12.879), datos
  (2.704), valor (2.535).
- El consenso de cierre llega de mediana **176 minutos** antes del inicio: es «unas 3 horas antes» que dice el plan.

**Lo que la página diría hoy:** ningún pick publicado; 22 de 22 días sin picks porque ningún modelo había superado al mercado en
su prueba; lo medido en evaluación con su parada más común (calibración); sin valor de línea; más/menos de 2,5 calibrado con su
tabla, 1X2 y ambos marcan «sin calibrar»; «De 5 tipos de apuesta que medimos… 0 lo han superado… por eso hoy publicamos poco».

## 4. Control en cada despliegue

`python -m scripts.transparency_check [--tz America/Bogota]` (solo lectura: `default_transaction_read_only`, 60 s por consulta):
calcula **cada cifra con su propia consulta**, escrita aparte de la del servicio (agregados y `FILTER` donde el servicio cuenta en
Python, contención JSON donde el servicio convierte, funciones de ventana donde usa `DISTINCT ON`, los periodos cortados en SQL),
y la compara con la página. Sale 0 si todo cuadra, 1 con la lista de diferencias y 2 si no alcanza la base. Lo que no re-deriva a
propósito: la fórmula del valor de línea (una sola definición del sistema, aplicada a un cierre buscado aparte) y las reglas del
plan (25 para la rentabilidad, «Otros» por debajo de 25). Corre en la verificación del despliegue y en las pruebas de integración
(dos zonas horarias), y una prueba comprueba que ve una cifra falseada.

## 5. Interruptor, vista previa y vuelta atrás

| `FBI_TRANSPARENCY` | Lectores | Tú (cuenta de dueño) |
| --- | --- | --- |
| ausente, `0` o algo que no se entiende | `not_available`; ningún enlace | `/transparency` con «Vista previa» |
| `1` | la página y sus enlaces | igual, sin el aviso |

La API la lee al arrancar (recrear la API para cambiarla). Vuelta atrás sin desplegar: `FBI_TRANSPARENCY=0`; completa: la imagen
anterior (no hay migración).

## 6. Rendimiento

Caché de 10 minutos: los bloques comunes (días, valor de línea, pronóstico, evaluación) **una vez para todos** los lectores; los
picks publicados por zona horaria. Medido en producción con `EXPLAIN ANALYZE` (26-oct, en frío): días sin picks 1,8 s, decisiones
1,5 s, pronóstico 0,4 s, el resto milisegundos — dentro del límite de 10 s por consulta de la API.

## 7. Aislamiento y privacidad

Solo lee: ni una escritura (prueba sobre el texto del servicio y del contraste), ninguna tabla de clientes (`auth`, `customer`,
picks de clientes), ningún dato de popularidad. Nombrar `models.match_forecasts` exige estar en la lista de lectores permitidos
(`test_forecast_isolation.py`, con su motivo). El rol de la API ya lee todos los esquemas: **no cambia `grants.sql`**.

## 8. Decisiones que tomé (desviaciones deliberadas, escritas)

1. **El porqué de un día sin picks** sale primero de lo guardado por la publicación (partidos del día y pronósticos calificados);
   lo de Intelligence (`intel.decisions`, la capa en sombra, como ya decidí en A9) va como **reconstrucción rotulada**, en
   recuento, y para un día con candidatos calificados se cuenta solo sobre ellos.
2. **Valor de línea:** la definición canónica `clv-v1` (último consenso antes del inicio) en vez de «unas 3 horas antes»: en
   producción esa captura llega de mediana a 176 minutos, y la página dice cuántos minutos antes fue. Si la decisión 16 del plan de
   Intelligence cambia la referencia, la página cambia la versión y la fecha.
3. **«Liquidados»** = los que cuentan para la rentabilidad (ganados, perdidos, medios y devueltos); los anulados se cuentan aparte.
4. **Días contados:** los 30 anteriores a hoy (hoy está en Inicio), nunca antes del 4-oct-2026.
5. **Calibración visible** solo para un mercado calibrado y desde 300 partidos (el plan: «cuando la muestra lo permite»); un mercado
   sin calibrar dice «sin calibrar» sin cifras (la auditoría: «la calibración solo cuando sea sólida»).
6. **En evaluación** usa la prueba de Intelligence frente al mercado (`edge-gate-v1`, el «0 de 11» del plan de usuario) y añade el
   recuento de pronósticos calificados (la puerta que decide publicar); «por eso hoy publicamos poco» solo si no hay ni lo uno ni lo
   otro.

## 9. Pruebas

| Prueba | Qué demuestra |
| --- | --- |
| `tests/unit/test_transparency.py` (30) | El recuento como Mis picks; unidades, rentabilidad y margen solo desde 25 y «concluyente» desde 100; los márgenes del plan; «Otros»; la parada más común y su empate; la ventana; qué ocurrió en cada mercado; los tramos de calibración; el interruptor; que el servicio y el contraste solo leen, no nombran clientes ni el set de evaluación |
| `tests/integration/test_transparency.py` (12) | Cada bloque sobre un mundo construido a mano (periodos, días con sus tres motivos y su reconstrucción, mercados, valor de línea sin la captura de después del inicio, calibración con tramos omitidos, evaluación); el set de evaluación nunca cuenta; la misma fórmula que Mis picks; **cada cifra igual a su consulta independiente** en dos zonas horarias y el contraste ve una cifra falseada; una historia vacía; el interruptor, la vista previa (403 para un lector) y el campo de `/auth/me` |
| `test_forecast_isolation.py`, `test_user_layer_isolation.py` | Los lectores nuevos de la tabla de pronósticos, listados con su motivo; la ruta nueva entre las de cliente |
| Web: `transparency.test.tsx` (8), `noPick.test.tsx` | La página como sería hoy en producción y con historia (ES y EN), los textos de la muestra, las palabras que nunca dice, las fechas que no mueve la zona horaria; el enlace en un día vacío decidido y no mientras se revisa |
| e2e `user.spec.ts` (ES y EN) y `responsive.spec.ts` | Los bloques con las cifras de la API, el menú y el día sin picks llevan a la página; sin enlace cuando está cerrada; a 320–430 px tarjetas apiladas, nada de lado y 44 px |

## 10. Puertas

| Puerta | Árbol | Resultado |
| --- | --- | --- |
| Backend: ruff, mypy estricto y del árbol entero, pytest | backend `c07764af` | Limpio; mypy 493 y 1.172 ficheros; **5.827 pruebas** (4 omitidas), 10 min. Una primera vuelta encontró tres avisos de tipos en el árbol entero (fuera de los paquetes estrictos): corregidos en `1f94125e` |
| Web: lint, tipos (también los del e2e), pruebas, build de producción | web `3cdab390` | Lint 0 errores (los 26 avisos de antes); **840 pruebas**; build correcto |
| e2e completo con la página abierta a los lectores y la narrativa encendida (QA `fbi_qa_a12`, copia de `fbi_qa_a11` en la `0100`; `seed_a12.py`: la línea base de producción del 26-oct contada con nombres de QA) | web `3cdab390`, backend `c07764af` | **140 / 3 / 12** (29,1 min). Los tres fallos no eran del código: esperas del esqueleto de más de 20 s en tres páginas a ancho de teléfono mientras el servidor de desarrollo de QA crecía hacia el límite de memoria de la máquina de pruebas. Repetidos con un solo proceso y el servidor reiniciado: **3 / 3** |
| e2e completo «como arranca producción» (los dos interruptores ausentes: apagados) | web `3cdab390`, backend `c07764af` | **137 / 6 / 12** (29,7 min): sin enlace a la página y su dirección dice que no está publicada. Los seis fallos, otra vez del límite de memoria (dos «page crashed» y cuatro esperas de carga); repetidos con un solo proceso y el servidor reiniciado: **6 / 6** |
| Accesibilidad (axe) | | `/transparency` a 1440 y 390 px: 0 reglas incumplidas |
| Gitleaks del rango de la rama (`ux/a11..ux/a12`) | | 0 hallazgos (registro en la hoja de puertas) |

## 11. Despliegue

- Sin migración. **Copia previa al despliegue** (ficha A12) y su prueba de restauración, como siempre.
- Despliega **cerrada** (`FBI_TRANSPARENCY` ausente): los lectores no ven nada nuevo; en la verificación corre
  `scripts.transparency_check` (0 diferencias) contra la base real.
- Después tú revisas `/transparency` con tu cuenta (P9) y, si te parece bien, la línea `FBI_TRANSPARENCY=1` en `/etc/predigol/app.env`
  (fichero del plan de seguridad: copia fechada, candado, ventana propia) y se recrea la API.

## 12. Acción manual

**P9**: revisar la página antes de publicarla (con tu cuenta, en producción tras el despliegue, o con las capturas de QA de esta
fase). Por la regla 13 de la coordinación no te lo pido mientras otra tarea tuya del plan esté abierta (hoy P4).

## 13. Ampliación UX-010: la transparencia completa (plan de cierre, 1.5)

**Sin migración y sin tocar la inteligencia.** Se añade lo que faltaba para que un lector vea el historial entero y sepa leerlo.
La regla UX-002 sigue: el lector solo ve picks publicados en verde («Recomendado»); lo de evaluación nunca aparece.

| Bloque nuevo | Qué dice | De dónde sale |
| --- | --- | --- |
| Picks, uno a uno | Cada pick publicado con partido, competición, tipo de apuesta, selección, **la cuota y la probabilidad con las que se congeló**, la del mercado y cómo terminó (ganado, perdido, medios, devuelto, anulado o pendiente; unidades y marcador cuando los hay). Del más reciente al más antiguo, de 20 en 20 con «Ver más» | `GET /transparency/picks` (`fbi.api.services.transparency_picks`): los ítems del set `qualified`; un pick se queda como se publicó y se le añade el resultado |
| Parlays | Combinadas del día y de varios días: creadas, ganadas, perdidas, anuladas y pendientes (y cuántas ganaron con una pierna anulada), con el mismo criterio de muestra que los picks | `picks.parlays` con `source = 'qualified'`, sin las que están armándose ni las sin piernas; contadas como en Mis picks (`PARTIAL_VOID` cuenta como ganada) |
| Qué es un pick | En palabras: qué es, que no es una predicción segura, que se congela al publicarse y que hay filtros | Solo texto |
| Cómo leer probabilidades y cuotas | Cuota, lo que dijo PrediGol, lo que dice el mercado, valor, unidades y resultados, con un ejemplo | Solo texto |
| Historial de cambios | Las novedades de la página «Novedades» y el día en que entró cada definición vigente, la más nueva primero; las 6 últimas a la vista, el resto bajo «Ver todo el historial» | `UPDATES` (novedades) y las definiciones que dice el servidor con su fecha: no se inventa ninguna línea |
| Aviso de cero picks | Mientras no se haya publicado ninguno, la página lo dice tal cual, con los días sin picks y su motivo más común y lo que sí se mide (el pronóstico), y enlaza a esos bloques; nunca una cifra que no existe | Lo que ya traen los bloques de días y de pronóstico |

- **La lista y las cifras son lo mismo:** el total de la lista es el «publicados» de todo el histórico; una prueba de integración y el
  contraste lo exigen. El corte es el de las cifras (partidos que empiezan antes del final de «hoy» del lector), y el cursor es el de
  Mis picks, así que una página no repite ni se salta un pick.
- **Contrato:** `GET /transparency/picks?limit=1..50&cursor=` con la misma puerta y la misma vista previa que `/transparency`;
  cerrada para los lectores devuelve `not_available`; un cursor que no es de esta lista, 422 `invalid_cursor`. `Transparency`
  gana `parlays` (por tipo `daily` / `multiday`). El cliente web consume los dos lados en el mismo cambio.
- **Control en cada despliegue:** `scripts.transparency_check` calcula también, con consultas aparte, el total y el orden de la
  lista (sin repetidos), el resultado y las unidades de cada pick, y los parlays por tipo (con los de pierna anulada).
- **Qué no dice:** ningún umbral, prompt, estado interno ni nada del panel del dueño; ninguna cifra que no tenga detrás un pick o un
  parlay publicado. Las palabras que nunca dice (rachas, «pick estrella», garantías…) siguen vigiladas en ES y EN.

**Pruebas nuevas:** unitarias del recuento de parlays y de que el servicio, el contraste y la lista solo leen y nunca nombran el
set de evaluación (`test_transparency.py`, 35); de integración, un mundo con parlays (diario ganado, perdido, con pierna anulada,
activo, armándose sin piernas; varios días anulado y uno que aún no ha empezado) y la lista con la puerta, la paginación con reloj
congelado y el total igual a las cifras (`test_transparency.py`, 18); web (`transparency.test.tsx`: el cero picks, la lista con sus
resultados, parlays, lectura, historial en ES y EN) y e2e (`user.spec.ts`: la lista de la API frente a la de pantalla con «Ver
más»; `responsive.spec.ts`: tarjetas apiladas y 44 px a 320–430 px). El e2e se comprueba con tipos aquí y corre completo en CI.

**Estado:** hecho en código; **no desplegado**. Al desplegar, la página sigue cerrada para los lectores hasta que abras
`FBI_TRANSPARENCY` (P9, con esta ampliación incluida en tu revisión).

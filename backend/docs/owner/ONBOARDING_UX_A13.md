# A13 · Bienvenida y favoritos

Plan Maestro UX, secciones 20 (Onboarding) y 38 (Personalización), ficha A13. Rama `ux/a13`. **Migración `0101`.** De la
activación al primer valor en menos de 90 segundos, con favoritos: una bienvenida corta, una sola vez, y un Inicio que empieza
por las ligas y los equipos del lector. Se personaliza la **experiencia**, nunca la inteligencia: picks, probabilidades, estados
y cuotas son los mismos para todos (lo comprueba una prueba con dos lectores de favoritos distintos).

## 1. Qué ve el cliente

| Momento | Qué ve | Regla |
| --- | --- | --- |
| Bienvenida (`/welcome`) | Justo después de los consentimientos, **una vez**: «Tu fútbol» y, si la cuenta es nueva, «Qué es PrediGol»; luego Inicio (o la página que abrió con un enlace) | Cada paso se puede saltar; hecha o saltada, no vuelve. Una cuenta de **antes de A13** (más de 14 días) ve **una sola pantalla**, la de favoritos. Nunca para tus cuentas de administrador |
| «Tu fútbol» | Su selección arriba (chips que se quitan con un toque y «3 de 10 ligas · 1 de 20 equipos»), **una búsqueda** de liga o equipo (sin acentos ni mayúsculas: «atletico» encuentra «Atlético») y, sin buscar, **las ligas por país**, cada país plegado bajo una fila de 44 px que dice cuántas tiene y cuántas eligió (Colombia abierta; las internacionales al final) | **Hasta 10 ligas y 20 equipos** (constantes de `fbi/customer/favorites.py`, se amplían sin migración). **Ya vienen marcadas las sugeridas para Colombia**: Primera A (Liga BetPlay), Libertadores, Champions, Premier, LaLiga, Serie A, Bundesliga, Ligue 1 y la Selección. «Guardar» las hace suyas; «Saltar» deja las sugeridas, rotuladas como sugeridas. Al límite no se añade nada y lo dice antes |
| «Qué es PrediGol» | Tres frases: el análisis de sus partidos cada día; picks solo cuando medimos ventaja frente al precio (si ningún partido la tiene, ese día no publicamos); te contamos cómo nos va, también cuando perdemos — con «Cómo le va a PrediGol» **solo cuando la abras** (A12) — y el botón opcional del recorrido | — |
| Inicio, «Hoy en tus ligas» | Los partidos de hoy de sus ligas y equipos, en vivo primero, **cada uno con su porqué**: «Sigues a Nacional», «Tu liga» o «Sugerida» (un toque dice la frase entera: «Te mostramos este partido porque sigues a Atlético Nacional»); sus ligas y equipos nombrados con «Cambiar» (o «Elegir mis ligas» mientras son las sugeridas) | Si hoy no juegan: «Hoy no juegan tus ligas.» y **el próximo partido de cada favorito** (hasta 120 días). «Qué se juega» y «Resultados» también son de los suyos; «Partidos relevantes», los demás partidos del día con análisis. Las **noticias** de Inicio siguen siendo de las ligas sugeridas (rotuladas) hasta B2 |
| Pistas de primera visita | Una tarjeta corta la primera vez que abre **Picks, un partido, Parlays y Mis picks** | Se descarta con un toque y **no vuelve** (ni tras recargar ni en otro dispositivo: queda en su cuenta). Nunca un modal |
| Recorrido opcional | **4 pasos**: Inicio, un partido, Picks y Mis picks, con una tarjeta al pie que no tapa la barra ni el botón del parlay | Solo si el lector lo pide: desde la ayuda (hoy el glosario, hasta que llegue `/help` en A14) o desde «Qué es PrediGol» |
| Cabecera del partido | Una **estrella** junto a cada equipo: seguirlo o dejar de seguirlo con un toque | Si el lector aún no eligió, guarda las sugeridas que ya veía más ese equipo (no le quita nada). Al límite de 20 lo dice |
| Perfil | «Tu fútbol»: sus ligas y equipos (o «Sugeridas para Colombia: aún no eliges las tuyas») y el mismo selector para cambiarlos | B1 reunirá el perfil en sus bloques |

## 2. Lo que nunca cambia

- **Iguales para todos:** el tablero de Inicio (`GET /today`) se calcula **una vez por minuto para todos los lectores**; los
  favoritos se aplican encima: marcan por qué un partido es del lector, dejan el contexto solo en los suyos, quitan los
  resultados que no son suyos y añaden el próximo partido de cada favorito. Ningún pronóstico, línea de lectura, pick, estado
  ni cuota cambia: una prueba de integración pide `/today`, `/today/no-pick`, `/home`, `/picks`, `/daily` y el pronóstico y la
  lectura de un partido con un pick publicado para **dos lectores con favoritos distintos** y exige respuestas idénticas
  (fuera de lo que es de cada uno).
- **Sin perfil de apostador:** solo ligas y equipos. La API rechaza cualquier otro campo (un importe, por ejemplo).
- **Siempre explicable:** cada partido de los suyos dice por qué está ahí; los sugeridos, que son sugeridos.

## 3. Datos

- **`customer.favorites`** (migración `0101`): lector, tipo (`league` o `team`), la liga o el equipo con su propia clave a
  `core.competitions` / `core.teams` (si una liga o un equipo desaparece, su favorito se va con él), una fila por favorito y la
  fecha en que lo eligió (que da el orden del lector). Una cuenta no se puede borrar por debajo (se anonimiza, A7). **La bajada se
  niega** mientras haya favoritos: el código vuelve, la tabla se queda.
- **La bienvenida y las pistas** viven en `customer.preferences` (`onboarded_at`, `hints_seen`), columnas que la `0096` ya dejó
  preparadas: la `0101` no las toca.
- **`grants.sql`** (fichero de seguridad): el rol de la API puede **añadir y quitar** favoritos (nunca editarlos); el worker de
  PrediGol Intelligence **no lee nada** de `customer`. Viaja con la `0101`.
- La **exportación** del lector incluye sus favoritos (con el nombre de cada liga o equipo), su bienvenida y sus pistas; la
  **anonimización** de la cuenta los borra.

## 4. Línea base de producción (26-oct-2026, 10:15 UTC, solo lectura)

| Medida | Valor |
| --- | --- |
| Revisión | `0094` (el esquema `customer` llega con A4) |
| Cuentas | 1 de administrador activa y 1 desactivada; 6 de lector, **todas desactivadas**: hoy ningún lector activo verá la bienvenida al desplegar; la verán las primeras cuentas invitadas |
| Competiciones seguidas | **133** (31 internacionales; 9 de Inglaterra, 6 de Alemania…): por eso el selector pliega los países y busca |
| Ligas sugeridas | Las 8 existen y están seguidas; la Selección Colombia existe |
| Equipos que se pueden seguir | **5.774** (con partido en una competición seguida en los últimos 400 días) de 8.245 |
| Tablero de Inicio | **607 partidos** en la ventana (48 h atrás, 36 h adelante; 128 por jugar) |
| Consultas nuevas (EXPLAIN ANALYZE) | Próximo partido de cada favorito sugerido: **35 ms**; búsqueda de un equipo por nombre: **29 ms** |

**Dos defectos latentes de A9 encontrados aquí (A9 no está desplegada):**

1. **El tope de 300 partidos.** El tablero se leía en orden de hora con un tope de 300; con 603 en la ventana, el partido número
   300 era del día anterior a las 11:00 UTC (medido a las 10:48 UTC): el tablero **cortaba todos los partidos de hoy**. A13 sube
   el tope a 2.000 (solo contra un desbordamiento) y la respuesta de cada lector deja fuera los resultados que no son suyos, para
   que siga siendo ligera. Una prueba pone 400 resultados de ayer delante del partido de hoy (con el tope viejo, falla).
2. **La «mirada» de la lectura de cada partido** recorría **todos** los paquetes de los partidos de la ventana (se guardan cada
   vez que se reconstruyen: unos 50 por partido, **29.713 paquetes y 299 MB** para 600 partidos) y pasaba de 20 s, más que los
   10 s que permite la API: Inicio no habría cargado. A13 lee el paquete más reciente de cada partido por su índice: **0,7–0,8 s**
   para los mismos 600 (6,7 MB). Una prueba fija que la mirada es la del paquete más reciente conocido, nunca uno posterior.

Al empaquetar A9 se le llevan los dos arreglos con su prueba y se repite su puerta (anotado en el estado).

## 5. Interruptores y vuelta atrás

- `FBI_ONBOARDING` — **encendido** si falta la línea; `=0` manda a todas las cuentas directo a Inicio (sin bienvenida; los
  favoritos se quedan).
- `FBI_PERSONALIZATION` — **encendido** si falta la línea; `=0` da a todos el Inicio común (las sugeridas para Colombia), sigan lo
  que sigan.
- Las dos se cambian en `/etc/predigol/app.env` (fichero del plan de seguridad: copia fechada, candado, sin desplegar) y se
  recrea la API. Volver al código anterior no exige bajar la `0101`.

## 6. Rendimiento

En producción (26-oct, 10:48–10:53 UTC, EXPLAIN ANALYZE de solo lectura, 600 partidos en la ventana):

| Parte | Coste | Cuándo |
| --- | --- | --- |
| Los partidos de la ventana | 108 ms | Una vez por minuto para todos (el tablero común) |
| El pronóstico más reciente de cada uno | 331 ms | Ídem |
| La mirada de la lectura de cada uno (corregida) | 0,7–0,8 s (antes, más de 20 s) | Ídem |
| Lo del lector: sus favoritos | 1 consulta por clave primaria | En cada petición |
| Sus ligas y equipos con el próximo partido de cada favorito | 35 ms (las sugeridas) | Cinco minutos por conjunto de favoritos (todos los que siguen lo mismo lo comparten) |
| La búsqueda de un equipo por nombre | 29 ms | Al escribir (dos letras o más, con pausa de 300 ms) |

La respuesta de cada lector lleva los partidos por jugar y en juego de todos y los resultados solo de los suyos (unos 130–200
partidos en un fin de semana en vez de 600).

## 7. Aislamiento y privacidad

- Solo la API importa `fbi.customer`; el servicio de Inicio (`fbi.api.services.today`) **no lee datos de clientes**: recibe los
  favoritos como identificadores desde la ruta (`Follows`), y el analista de la consola no puede alcanzar nada de eso (pruebas
  estáticas de importaciones y de tablas nombradas).
- Cada lector ve y cambia **solo lo suyo**: ninguna ruta lleva un identificador de cuenta; anónimo, 401; desde otro sitio, 403.
- Los eventos de analítica (A6) cuentan el inicio de la bienvenida, los pasos saltados, el final y cada favorito añadido o
  quitado (solo su tipo y su identificador), con el consentimiento de siempre.

## 8. Decisiones que tomé (desviaciones deliberadas, escritas)

1. **Rutas propias** en `routers/favorites.py` (la ficha decía `routers/customer.py`): mismas garantías —nivel de la app, misma
   procedencia, fuera de las puertas de consentimiento y de membresía, como las preferencias de notificación—, en su fichero.
2. **«Cuenta de antes»** = creada hace más de **14 días** (la duración de la prueba, A8): ve solo la pantalla de favoritos.
3. **Saltar no guarda**: las sugeridas siguen siendo sugeridas (rotuladas); «Guardar» las hace del lector. Quitarlas todas
   vuelve a las sugeridas.
4. **La estrella** de un lector sin elección propia guarda las sugeridas que ya veía más el equipo.
5. **Noticias y filtros de Partidos y Picks por favoritos, en B2** (la ficha de A13 no los incluye; la sección 20 los pone en B2).
6. **El recorrido sale del glosario** hasta que exista `/help` (A14).
7. **El tablero de Inicio** sin el tope de 300, sin los resultados ajenos en la respuesta de cada lector y con la mirada de la
   lectura por el índice de los paquetes (sección 4): dos defectos latentes de A9 que la línea base de A13 encontró.
8. **El orden del lector** se guarda en la fecha de cada favorito (los de un mismo guardado, un microsegundo aparte), sin columna
   de posición.

## 9. Pruebas

| Prueba | Qué demuestra |
| --- | --- |
| `tests/unit/test_customer_favorites.py` (18) | Límites que rechazan sin recortar; solo ligas seguidas y equipos que juegan en ellas; búsqueda sin acentos; una pista inexistente rechazada; los interruptores; la bienvenida solo para lectores, una vez; cuenta nueva y de antes; el porqué de un partido (equipo antes que liga) |
| `tests/integration/test_customer_favorites.py` (10) | Por HTTP con sesión real: sugeridas rotuladas, exactamente lo elegido y en su orden, límites y lo que no se puede seguir, cada lector lo suyo, las opciones y la búsqueda; la bienvenida una vez, nunca para el administrador ni con `FBI_ONBOARDING=0`; una pista descartada no vuelve; Inicio con el porqué y el próximo de cada favorito; exportación y anonimización; **dos lectores, mismas respuestas** |
| `test_migration_0101_customer_favorites.py`, `test_db_roles.py`, `test_customer_privacy_api.py`, `test_today_api.py` | La `0101` arriba y abajo sin tocar otra tabla; los permisos de la API y que el worker no lee; las columnas del esquema; el tablero no se corta con 400 resultados delante y la mirada es la del paquete más reciente conocido |
| Web: `favorites.test.tsx`, `TodayBlocks.test.tsx`, `today.test.ts` | Las reglas del selector, los bloques de Inicio con lo del lector, las pistas que no vuelven, el recorrido y los porqués (ES y EN) |
| e2e `onboarding.spec.ts` | Bienvenida cronometrada de la primera entrada a «Hoy en tus ligas»; cuenta de antes con una pantalla; el selector a 320 px con teclado y axe; pistas; recorrido; estrella |

## 10. Puertas

| Puerta | Árbol | Resultado |
| --- | --- | --- |
| Backend: ruff, mypy estricto y del árbol entero, pytest | backend `9c472f2b` | Limpio; mypy 497 y 1.180 ficheros; **5.864 pruebas** (4 omitidas), 10 min. Antes del arreglo de la mirada, `58b73f14`: 5.863. Una vuelta con la web compilando a la vez falló una prueba de cuotas de presupuesto que depende de la carga (sola: 14 / 14) |
| Web: lint, tipos (también los del e2e), pruebas, build de producción | web `ce3a68e9` | Lint 0 errores (los 26 avisos de antes); **862 pruebas**; build correcto. La primera vuelta encontró un tipo en una prueba nueva (corregido) |
| e2e completo con la transparencia y la narrativa encendidas (QA `fbi_qa_a13`, la `0101`; `seed_a13.py`) | web `f794410a`, backend `9c472f2b` | **142 / 6 / 13** (30,9 min). Dos fallos eran de las propias pruebas de A13 (`legal.spec` registraba la bienvenida antes de terminar el inicio de sesión: 401; la de las pistas, cuatro páginas con recarga, pasó de sus 150 s con la carga de la corrida completa): corregidas en `7110f827`. Cuatro eran del límite de memoria de la máquina de pruebas (el núcleo cerraba el navegador); la de «Análisis y Postpartido» se caía así en cada corrida y dos veces sola, y ahora abre una pestaña por ancho (`29166a62`). Repetidos: el proyecto de bienvenida entero 6 / 6, los seis anchos de teléfono, Noticias y la consola en tableta; sobre el árbol final, la puerta de consentimiento y «Análisis y Postpartido» 2 / 2 |
| e2e completo «como arranca producción» (transparencia y narrativa apagadas) | web `f794410a`, backend `9c472f2b` | **144 / 4 / 13** (30,0 min): el mismo 401 y tres de memoria. Repetidos sobre el árbol final: **9 / 9** |
| e2e con el autoservicio y el messenger de QA (proyectos de cuenta, bienvenida y anónimo) | árbol final | **27 / 1 / 1** (3,7 min): la invitación se activa y pasa por la bienvenida; el fallo, una espera de red en `auth.spec` bajo carga, pasa solo 1 / 1 (el mismo grupo en `f794410a`: 28 / 0 / 1) |
| **Bienvenida cronometrada (G8)** | | **7,0 s** desde el inicio de sesión y **17,6 s** desde el enlace de la invitación (activación, consentimientos, «Tu fútbol», «Qué es PrediGol» e Inicio con «Hoy en tus ligas»); el límite es 90 s |
| Accesibilidad (axe) | | La bienvenida a 320 px: 0 reglas incumplidas; el selector, solo con teclado |
| Gitleaks del rango de la rama (`ux/a12..ux/a13`) | | 0 hallazgos (11 commits de código) |

## 11. Despliegue

- **BACKUP → RESTORE TEST antes de la `0101`** (ficha A13); después la migración, `grants.sql` (lo hace `predigolctl`) y la
  verificación: `/auth/me` con sus campos nuevos, `/today` con lo del lector, la huella de los picks igual antes y después.
- Despliega **encendido** (los dos interruptores ausentes): con 0 lectores activos hoy, nadie ve nada hasta la primera invitación.

## 12. Acción manual

Ninguna.

# IA-075 · Entrenador actual fiable y saneamiento de las carreras abiertas

*Plan maestro de la arquitectura definitiva 2026, pieza AD-H03. Medido en producción (solo lectura) el 16 y 17-nov-2026.*

Esta pieza no cambia nada de lo que ve el lector. No toca modelos, probabilidades, picks, liquidaciones ni interruptores, y no hace ninguna llamada a API-Football. Deja preparado el «entrenador actual» que usarán los perfiles de club (AD-H07, bajo `FBI_PROFILES`, que sigue apagado).

## 1. Qué problema resuelve

El proveedor guarda la trayectoria de cada entrenador (`core.coach_careers`), pero solo cierra una etapa cuando él mismo la reescribe, y muchas no las reescribe nunca. Por eso un club aparece con varios entrenadores «actuales» a la vez.

En la foto más reciente de cada entrenador, el 16-nov-2026:

| Equipos con alguna etapa abierta | 4.531 |
| --- | ---: |
| Con exactamente un entrenador | 1.404 |
| Con dos | 1.208 |
| Con tres | 945 |
| Con cuatro o más | 974 |

Es decir, el **69 %** tiene dos o más (3.127). La ficha decía 72 % sobre 4.581 equipos; la diferencia es del día de la medida.

La hoja de alineación sí es un hecho con fecha: `core.fixture_lineups.provider_coach_id` dice quién estaba en el banquillo ese día. Y el perfil del proveedor (`/coachs`, en `core.coach_profiles_latest`) tampoco sirve como respuesta: 3.544 de 4.586 equipos (77 %) aparecen como equipo actual en el perfil de más de un entrenador.

## 2. La regla (`coach-current-v1`)

Está en `fbi/people/current_coach.py`. Es pura y determinista: no lee ni escribe nada.

- **Entrenador actual = el de la hoja de alineación más reciente que nombra a alguno.** Junto a la respuesta van el partido, su fecha (día UTC), la fuente (`lineup`), cuántos partidos seguidos lleva (`streak`) y desde cuándo (`since`).
- **Una hoja sin entrenador se salta y se cuenta** (`sheets_without_coach`). En los últimos 90 días, el 14,6 % de las hojas no traía entrenador: 2.479 de 16.960.
- **Un interino es el actual mientras esté en el banquillo.** La regla no sabe de cargos; solo sabe quién se sentó. `career_known` dice si el proveedor le tiene una etapa abierta en ese club.
- **Sin hojas en la ventana** (400 días), se usa la carrera del proveedor solo si queda **una** etapa abierta (fuente `provider_career`). Si quedan varias, no hay respuesta y se dice por qué (`several_open_careers`).
- **Anunciados.** Si una etapa abierta empieza después del último partido, se avisa (`announced`): es un entrenador nombrado tras ese partido. El actual sigue siendo el de la hoja hasta que una hoja diga otra cosa.
- **Contraste con el proveedor.** `profile_team_agrees` dice si el perfil `/coachs` del entrenador nombra a ese club. Es solo un contraste, nunca la respuesta.
- **Fresco.** `fresh` vale sí cuando la hoja tiene 90 días o menos.

### Dos ids para una misma persona

Al revisar la primera pasada vi que el proveedor da a veces **dos ids al mismo entrenador**: «Mariusz Jop» y «M. Jop», «Tencati Claudio» y «Cláudio Tencati», «Hassan Al-Abdooli» y «Hassan Al Abdooli». Sin tenerlo en cuenta, la regla habría cerrado la etapa del entrenador actual bajo su otro id.

Ahora dos ids se tratan como posible misma persona cuando:

- sus nombres no se contradicen (apellido compartido, inicial con apellido o las mismas palabras en otro orden; se usa la función de nombres de IA-071),
- y, si las dos fechas de nacimiento son conocidas, coinciden.

En ese caso:

- las hojas de los dos ids cuentan en la misma racha;
- una etapa del otro id **nunca se cierra**;
- el otro id se informa en `same_person_ids`.

Esto solo sirve para **no** cerrar algo. Nunca fusiona entrenadores. En producción hay **1.184 equipos** con un entrenador actual que tiene otro id: es trabajo para la cola de identidad (AD-H01).

### Cuándo se corrige una etapa abierta

Una etapa abierta de otro entrenador X en el club se cierra solo si se cumplen las dos condiciones:

1. **La evidencia es fuerte.** El actual lleva al menos **2 hojas seguidas**, o el propio proveedor le tiene una etapa abierta en el club.
2. **La etapa de X empezó antes** de que arrancara la racha del actual.

Fecha de fin que se apunta:

- el último partido de X en ese banquillo, si las hojas lo muestran (`last_lineup`);
- si no, el día antes de que empezara la racha del sucesor, como cota máxima (`before_successor`).

Una etapa nunca termina antes de empezar.

**No se infiere un cese sin hoja.** Un club sin hojas no recibe ninguna corrección. Una sola hoja de otro entrenador (un titular sancionado, un ayudante un día) no basta, salvo que el proveedor esté de acuerdo.

## 3. Qué se añade (migración 0144, compartida con IA-076)

| Pieza | Qué es |
| --- | --- |
| `core.coach_career_corrections` | Una corrección de **una fila** de `core.coach_careers`, que no se toca nunca. `close` lleva la fecha y su base; `retract` retira una corrección anterior. Es de **solo añadido**: un disparador rechaza UPDATE y DELETE. |
| `core.coach_careers_audited` | Vista: la foto más reciente de cada entrenador, con tres fechas de fin (la del proveedor, la corregida y la vigente: `effective_end_date`) y de dónde sale (`end_date_source`). |
| `fbi/people/current_coach_store.py` | El lector `current_coach(conn, team_ids)`, que es lo que llamará AD-H07; `audit`, `close`, `retract` y `team_open_counts`. |
| `scripts/coach_current.py` | La consola: `show`, `audit`, `counts`, `close [--apply]`, `retract ID --note ... [--apply]`. |

Una corrección vale para la fila exacta que nombra. Si el proveedor manda una foto nueva de ese entrenador, esa foto es otra fila y se vuelve a juzgar.

## 4. Lo que se midió (producción, solo lectura, 17-nov-2026 ~03:30 UTC)

**Método.** Se exportaron cinco ficheros:

- las hojas de los últimos 400 días: 70.742 filas de equipo y partido;
- las etapas abiertas de la foto más reciente: 11.213;
- los perfiles: 15.632;
- los equipos;
- los equipos de liga doméstica seguida con partido en 90 días.

La regla real se ejecutó en la imagen del backend, sin red ni base de datos. El script está en `docs/owner/lab/IA_075/lab_coach_analysis.py.txt`.

**Clubes de liga doméstica seguida con partido terminado en los últimos 90 días** (1.309):

| | Equipos | % |
| --- | ---: | ---: |
| Entrenador actual por hoja | 1.297 | 99,1 % |
| … de una hoja de 90 días o menos | 1.285 | 98,2 % |
| Por la carrera del proveedor (una sola abierta) | 2 | 0,2 % |
| Con más de un entrenador abierto, antes | 1.204 | 92,0 % |
| **Con más de un entrenador abierto, después de las correcciones** | **38** | **2,9 %** |

**Todos los equipos con hoja o etapa abierta** (4.672):

- 3.921 tienen respuesta por hoja (2.023 frescas), 365 por la carrera del proveedor y 386 no tienen respuesta.
- Correcciones propuestas: **4.967**. De ellas, 1.376 llevan el último partido de X (`last_lineup`) y 3.591 la cota del sucesor (`before_successor`).
- Equipos con más de un entrenador abierto: 3.125 antes y **570** después.
- 256 etapas contradichas no se cierran porque la evidencia no es fuerte: el actual tiene una sola hoja y el proveedor no lo respalda.
- En el lector, el número de equipos con dos entrenadores «actuales» es **0**: la respuesta es una por equipo por construcción.

**Muestra revisada a mano.** Revisé 30 clubes al azar (semilla 75) de los que tienen correcciones, con 79 cierres.

- En ningún caso el cierre cae sobre el actual ni sobre otro id suyo. Los dobles ids que aparecen (Carille / «Carille Fabio», Abukasis / «Yossi Abukasis», Berg / «H. Berg», Dudamel / «R. Dudamel»…) quedan en `same_person_ids` y no se cierran.
- Los cierres coinciden con la secuencia de las hojas. Un ejemplo: Colonia, Rene Wagner desde el 24-ago-2026, cierra las etapas interinas abiertas de Funkel, Pawlak y Ruthenbeck.

Esta revisión comprueba que el cierre es coherente con las hojas. No contrasta con una fuente externa.

**Lo que queda.**

- Los 38 clubes con más de un entrenador abierto son casos sin evidencia fuerte: una sola hoja del nuevo, o etapas que empiezan dentro de la racha.
- Los 386 equipos sin respuesta no tienen ni hojas ni una etapa única.

## 5. Qué no cambia

- `core.coach_careers`, `core.fixture_lineups`, `core.coach_profiles` y `core.coach_spells` siguen como estaban. Las correcciones van en una tabla aparte.
- No hay tarea del worker ni interruptor. Nada lee esto todavía: llegará al lector solo con C-09 / AD-H07, bajo `FBI_PROFILES` (`off`).
- `decision-v1`, los modelos, los picks y la sombra no se tocan.

## 6. Cómo se activa tras desplegar (manual, en el servidor)

```
python -m scripts.coach_current audit            # cifras y correcciones que propondría (solo lee)
python -m scripts.coach_current close            # ensayo: cuántas escribiría
python -m scripts.coach_current close --apply    # escribirlas (una por fila y versión; repetirlo no escribe nada)
python -m scripts.coach_current counts           # equipos con >1 abierta: proveedor y neto de correcciones
python -m scripts.coach_current show 541 529     # el entrenador actual de unos equipos, con fuente y fecha
```

`close --apply` escribe unas 5.000 filas en una tabla nueva, en una transacción, sin bloquear tablas calientes. Puede repetirse cuando entren hojas nuevas.

## 7. Vuelta atrás

- **Una corrección:** `python -m scripts.coach_current retract ID --note "motivo" --apply`. La etapa vuelve a estar abierta en la vista.
- **Todo:** dejar de leer la vista. Las filas del proveedor nunca se tocaron.
- **La migración:** su `downgrade` borra las tablas nuevas; se perderían las correcciones y las retiradas. Haz antes la copia de seguridad habitual.

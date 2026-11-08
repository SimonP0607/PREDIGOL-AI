# El recorrido de bienvenida y las guías de cada pantalla (UX-032, UX-051 a UX-054 y UX-070)

Plan: `PLAN_BIENVENIDA_RECORRIDO_PREDIGOL` (en el Project). Este archivo cuenta lo que el dueño puede tocar y dónde queda guardado lo que cada lector ha visto.

## Qué es

Un solo motor de guías en la página, que sustituye al recorrido y a las pistas de primera visita anteriores:

- **Recorrido general** (opcional): una tarjeta de bienvenida y 5 pasos sobre la navegación real.
- **Guía de cada pantalla** (opcional): la primera vez que se entra a Inicio, Partidos, En vivo, Partido, Picks, Parlays, Cuotas y Mis picks; se puede repetir con el botón «?» de su cabecera (arriba a la derecha, también en Inicio y en el partido) y desde Ayuda > Guías.
- **Guía de Perfil** (obligatoria, una vez): recorre solo ajustes que existen de verdad. Escape o «Atrás» la pausan; no se puede saltar hasta terminarla.

Nada de esto cambia picks, modelos, IA, mercados ni la lógica deportiva.

## Lo que esta entrega (UX-032) deja hecho

Solo la memoria de lo visto; no hay pantalla nueva todavía (la traen UX-051 a UX-054).

- **Tabla `customer.guide_progress`** (migración 0126): una fila por lector y guía, con la versión del contenido que vio, el estado (`pending`, `in_progress`, `completed`, `skipped`), el último paso y cuándo se visitó, empezó, completó o saltó.
- **`customer.preferences.guides_auto`**: el interruptor personal del lector «mostrar guías al entrar a cada pantalla» (encendido por defecto).
- **API**: `GET /auth/me` añade `guides`, `guides_on` y `guides_auto`; `PUT /me/guides/{guide}` guarda `{version, status, step}`; `PATCH /auth/me/preferences` acepta `guides_auto`. `POST /me/hints` se mantiene (una PWA abierta con una versión anterior puede seguir llamándolo).
- **Reglas del servidor**: lista cerrada de guías, versiones (1 a 99), estados y pasos (422 si no); dentro de una versión el estado no retrocede (`completed` no se borra por una repetición saltada); una versión menor que la guardada no cambia nada; la guía de `profile` no acepta `skipped` mientras no esté completada (409 `guide_mandatory`); cada lector solo toca lo suyo.
- **Cuatro eventos** en el catálogo cerrado (de 36 a 40): `guide_started`, `guide_completed`, `guide_skipped`, `guide_paused`. Solo se registran con consentimiento (`FBI_PRODUCT_EVENTS=consent`) y con propiedades cerradas.

## Qué ves como dueño (UX-054)

En Admin > Producto, bajo «Qué miran los lectores», la tarjeta **Qué pasa con las guías (30 días)** lista cada guía y versión con cuántos lectores la empezaron, la terminaron, la saltaron y la pausaron, y el paso donde más la saltaron.

- Solo aparece una línea si al menos `FBI_PRODUCT_MIN_SUBJECTS` lectores (20 por defecto) la empezaron, y siempre en grupos, nunca un lector.
- Sale de los cuatro eventos de guías, así que solo cuentan los lectores que aceptaron la medición.
- **«Revisar»** marca una guía con al menos 30 lectores que empezaron, cuando más de la mitad la salta en la primera tarjeta o un solo paso de los siguientes pierde a más de un cuarto (la primera tarjeta solo cuenta con su mitad). Es una señal descriptiva de quienes eligieron verla: no hay grupo de control y no prueba que la guía cause nada.
- Cuando cambie el texto de una guía se sube su versión y aparece como línea nueva; la anterior se compara a simple vista.

## Lo que corrigió UX-070 (revisión del 8-nov-2026)

- **Perfil por «Más».** La guía obligatoria de Perfil —y las de Parlays y Cuotas— no salía al entrar desde «Más», que es el camino normal en el móvil: la hoja de «Más» seguía en la página mientras se cerraba y contaba como otra capa abierta. Ahora una capa que se está cerrando no cuenta, y si una guía esperaba solo a que se cerrara una capa, sale en cuanto se cierra.
- **Un navegador compartido.** Lo que queda sin enviar por falta de conexión se guarda aparte para cada cuenta. Antes, si un lector saltaba una guía sin conexión y otro entraba después en el mismo navegador, el salto se grababa en la cuenta del segundo.
- **Sin conexión, la guía no vuelve.** Mientras un salto o un final espera en la cola, o su respuesta aún no ha llegado, la guía no se repite al recargar.
- **«?» en Inicio y en el partido**, e Inicio en Ayuda > Guías; Cuotas y Picks tienen sus pasos en el móvil, la tableta y el escritorio (en «Filtros» por debajo de 1024 px, y el aviso de que hoy no hay picks cuando no los hay).
- La cuenta del dueño ya no guarda visitas en las guías.

### Cómo comprobarlo tras desplegar

Con una cuenta de **lector** (la del dueño no ve guías): en el móvil, Inicio → «Más» → Perfil muestra su guía; Escape la pausa y vuelve en la siguiente entrada. Cada pantalla con guía tiene su «?» arriba a la derecha.

## Interruptor

| Variable | Valor si falta | Qué controla |
| --- | --- | --- |
| `FBI_GUIDES` | encendido | `=0` hace que la página no muestre ninguna guía (ni el recorrido, ni las de pantalla, ni la de Perfil) y que la bienvenida no ofrezca «Hacer el recorrido». Lo ya guardado se conserva. Se aplica recreando la API, sin desplegar |

## Privacidad

Es estado funcional, necesario para mostrar cada guía una sola vez; se guarda para todos los lectores. Sale en «Copia de tus datos» (`guides`) y se borra al anonimizar la cuenta. Nunca se usa para analítica.

## Volver atrás

Apaga `FBI_GUIDES=0` y recrea la API. La migración baja sola solo si ningún lector tiene filas ni apagó las guías; si no, el código vuelve atrás y la tabla se queda (nada la lee).

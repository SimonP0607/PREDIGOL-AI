# El recorrido de bienvenida y las guías de cada pantalla (UX-032 a UX-031)

Plan: `PLAN_BIENVENIDA_RECORRIDO_PREDIGOL` (en el Project). Este archivo cuenta lo que el dueño puede tocar y dónde queda guardado lo que cada lector ha visto.

## Qué es

Un solo motor de guías en la página, que sustituye al recorrido y a las pistas de primera visita anteriores:

- **Recorrido general** (opcional): una tarjeta de bienvenida y 5 pasos sobre la navegación real.
- **Guía de cada pantalla** (opcional): la primera vez que se entra a Inicio, Partidos, En vivo, Partido, Picks, Parlays, Cuotas y Mis picks; se puede repetir con el botón «?» y desde Ayuda.
- **Guía de Perfil** (obligatoria, una vez): recorre solo ajustes que existen de verdad. Escape o «Atrás» la pausan; no se puede saltar hasta terminarla.

Nada de esto cambia picks, modelos, IA, mercados ni la lógica deportiva.

## Lo que esta entrega (UX-032) deja hecho

Solo la memoria de lo visto; no hay pantalla nueva todavía (la traen UX-033 a UX-035).

- **Tabla `customer.guide_progress`** (migración 0126): una fila por lector y guía, con la versión del contenido que vio, el estado (`pending`, `in_progress`, `completed`, `skipped`), el último paso y cuándo se visitó, empezó, completó o saltó.
- **`customer.preferences.guides_auto`**: el interruptor personal del lector «mostrar guías al entrar a cada pantalla» (encendido por defecto).
- **API**: `GET /auth/me` añade `guides`, `guides_on` y `guides_auto`; `PUT /me/guides/{guide}` guarda `{version, status, step}`; `PATCH /auth/me/preferences` acepta `guides_auto`. `POST /me/hints` se mantiene (una PWA abierta con una versión anterior puede seguir llamándolo).
- **Reglas del servidor**: lista cerrada de guías, versiones (1 a 99), estados y pasos (422 si no); dentro de una versión el estado no retrocede (`completed` no se borra por una repetición saltada); una versión menor que la guardada no cambia nada; la guía de `profile` no acepta `skipped` mientras no esté completada (409 `guide_mandatory`); cada lector solo toca lo suyo.
- **Cuatro eventos** en el catálogo cerrado (de 36 a 40): `guide_started`, `guide_completed`, `guide_skipped`, `guide_paused`. Solo se registran con consentimiento (`FBI_PRODUCT_EVENTS=consent`) y con propiedades cerradas.

## Interruptor

| Variable | Valor si falta | Qué controla |
| --- | --- | --- |
| `FBI_GUIDES` | encendido | `=0` hace que la página no muestre ninguna guía (ni el recorrido, ni las de pantalla, ni la de Perfil). Lo ya guardado se conserva. Se aplica recreando la API, sin desplegar |

## Privacidad

Es estado funcional, necesario para mostrar cada guía una sola vez; se guarda para todos los lectores. Sale en «Copia de tus datos» (`guides`) y se borra al anonimizar la cuenta. Nunca se usa para analítica.

## Volver atrás

Apaga `FBI_GUIDES=0` y recrea la API. La migración baja sola solo si ningún lector tiene filas ni apagó las guías; si no, el código vuelve atrás y la tabla se queda (nada la lee).

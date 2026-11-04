# B11 · Ciclo de vida del cliente: en qué punto está cada lector y por qué

Sin estados, nadie se entera a tiempo de quién se está enfriando. B11 guarda, **una vez al día y para cada lector**, dónde está
(invitado, activado, habitual, en riesgo, por vencer, renovó, vencido) y **por qué**, en frases que se leen («sin actividad en 7
días», «la última encuesta fue de 2 o menos»). No toca PrediGol Intelligence (el worker no tiene acceso a `customer`) y **nunca
se usa para campañas**: los únicos mensajes automáticos a un lector siguen siendo los cuatro de la membresía y los de seguridad.

## 1. Los siete estados y su precedencia

Gana el primero que se cumple: **vencido > por vencer > renovó > en riesgo > habitual > activado > invitado.**

| Estado | Cuándo |
| --- | --- |
| Vencido | La membresía y su gracia terminaron (la misma cuenta que usa la página del lector). |
| Por vencer | Le quedan 7 días o menos (3 en la prueba), o está en sus 3 días de gracia. |
| Renovó | Un periodo pagado que sigue a otro pagado, registrado hace menos de 7 días. |
| En riesgo | Sin actividad en 7 días (solo cuentas de más de 7 días), o la última encuesta de los últimos 30 días fue de 2 o menos, o una solicitud espera hace más de 72 horas. Puede tener varios motivos a la vez. |
| Habitual | Usó PrediGol 3 de los últimos 7 días. |
| Activado | Activó la cuenta pero aún no tiene hábito (con algo de uso, o todavía sin usarlo). |
| Invitado | Se le invitó y nunca activó la cuenta. |

Tu cuenta, la cuenta sintética, las suspendidas y las desactivadas **no tienen estado** (no se guarda nada de ellas).

## 2. Qué ves

| Dónde | Qué |
| --- | --- |
| **Clientes** | Una columna **Estado** con su motivo y dos vistas nuevas con su conteo: **En riesgo** e **Invitados sin activar**. |
| **Ficha del cliente** | Una sección **Ciclo de vida**: su estado de hoy y la lista de los días en que cambió (un renglón por cambio). |
| **Soporte** | La solicitud de un lector en riesgo va **primero dentro de su prioridad** y lleva la etiqueta «Lector en riesgo». No salta por encima de lo urgente. |
| **Aviso de la mañana** | Desde las 7:00 (Bogotá), un aviso en tu bandeja: cuántos clientes están en riesgo, por vencer y sin activar, con el enlace a Clientes. **Números y un enlace, nunca nombres.** Uno por día. |
| **Producto → Ciclo de vida** | Los siete conteos del último día calculado, la **renovación** (membresías que terminaron en 30 días y tienen un periodo posterior), la **activación en 7 días**, y quienes **vuelven** en su 2.ª semana (días 7 a 13) y en su 2.º mes (días 30 a 36). Un porcentaje solo se muestra desde **30 lectores** en la cohorte; antes dice «Datos insuficientes: n de 30». |

Las cifras son para vigilar, no para optimizar: ningún mensaje ni empujón sale por ellas.

## 3. Lo que nunca cambia

- **PrediGol Intelligence no se toca.** Todo es capa de usuario; el worker no lee `customer` y esta tabla tampoco entra en ningún modelo.
- **Nada personal en los motivos:** cada motivo es un código de una lista cerrada (la base lo exige con un patrón); nunca una palabra que el lector escribió, una cifra de dinero o una dirección.
- **Sin borrar historia:** la tabla es de solo añadir (el propio disparador rechaza editar y borrar). Se borra en dos casos documentados: cuando se **anonimiza** la cuenta (A7) y, pasados **24 meses**, solo con el mismo interruptor `FBI_EVENTS_PURGE` de la analítica (apagado no borra; `dry` cuenta; `on` borra).

## 4. Lo nuevo por dentro

- **Migración `0106`** (`customer.lifecycle_snapshots`: lector, día de Bogotá, estado, motivos; llave `(user_id, day)`; el tipo de aviso `lifecycle_daily` entra en `audit.notifications`). Bajar la migración solo se permite con la tabla vacía; con historia, vuelve el código (`FBI_LIFECYCLE=0`) y la tabla se queda.
- **`fbi/customer/lifecycle.py`**: `judge` (función pura, probada con historias sintéticas), `compute_day`, `latest_states`, `history`, `counts`, `purge`, `forget`, `metrics`.
- **El mensajero** calcula el día al comienzo de un ciclo (cada 5 minutos; el segundo cálculo del mismo día no añade nada) y escribe el aviso de la mañana. Un fallo se anota y el ciclo sigue.
- **API** (solo SUPER_ADMIN): `/admin/customers` gana `view=at_risk|invited`, el estado y los motivos de cada fila y el historial en la ficha; `/admin/support` marca `at_risk`; `/admin/product` añade `lifecycle`.
- **`FBI_LIFECYCLE`**: encendido mientras falte; `=0` detiene el cálculo diario (la tabla y su historia se quedan).
- **Web:** insignia de estado, vistas, sección de la ficha, etiqueta en soporte y tarjeta de Producto, en español e inglés.

## 5. Pruebas

- Backend: unitarias (precedencia y motivos con historias sintéticas, lista cerrada de motivos, umbral de 30, interruptor), integración con base real (un día escrito una sola vez, sin tu cuenta ni las desactivadas, historial de solo añadir, retención `off/dry/on`, vistas y ficha, cola de soporte, aviso sin nombres, métricas sin porcentajes pequeños, anonimización, ciclo del mensajero con fallo y con el interruptor apagado), la migración `0106` (esquema intacto, restricciones, bajada solo vacía) y la matriz de permisos (el worker no lee la tabla).
- Web: textos de cada estado, motivo y vista en los dos idiomas, que la lista de motivos de la web sea la del backend, un código desconocido se omite, y que una cohorte de menos de 30 nunca muestre porcentaje.

## 6. Puertas

Puertas sobre el árbol integrado del PR #21 (`feat/UX-001`, 4-nov-2026), el que se desplegará:

- Backend: `ruff check .` limpio; `mypy` estricto (597 ficheros) y `mypy .` (1.492 ficheros) sin errores; pruebas unitarias **7.904 pasan, 16 omitidas**;
  migraciones 0095 a 0106 con una sola cabeza (0106, colgada de la 0119).
- Web: lint 0 errores (26 avisos que ya existían), tipos de la web y del e2e, **1.456 pruebas pasan, 0 fallan**, build.
- Seguridad: autoprueba de Gitleaks 41 de 41; escaneo de todo el historial limpio.
- CI del PR #21: Convenciones del PR, web, `ruff + mypy`, `scan` y secretos en verde; `pytest` con PostgreSQL 16 y la corrida de integración
  completa se anotan en el PR al terminar. El e2e de esta fase se repite sobre el árbol integrado antes del despliegue.

## 7. Despliegue

Backend y web juntos (el contrato cruza los dos), **con migración**: copia de seguridad y prueba de restauración antes, como en las
demás. **Vuelta atrás:** `FBI_LIFECYCLE=0` en `app.env` (con su copia fechada y, al final, `predigolctl config-baseline`); la web anterior
funciona con este backend (la API es aditiva).

## 8. Acción manual

Ninguna.

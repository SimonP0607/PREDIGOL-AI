# B10 · La ficha de cliente: lo necesario para atender y renovar a cada lector, y nada más

Una página nueva en la consola, **Clientes** (`/admin/customers`), y una ficha por lector. Es solo tuya (SUPER_ADMIN; un lector
recibe 403 en cada ruta) y **no cambia nada de PrediGol Intelligence**: solo lee lo que la capa de usuario ya guarda.

## 1. Qué ves

| Dónde | Qué |
| --- | --- |
| Lista | Todos los lectores (nunca tu cuenta), los más nuevos primero, con búsqueda por correo o alias y cuatro vistas con su conteo: **vencen en 7 días** (o ya vencidos y dentro de la gracia), **inactivos 14 días**, **con tickets abiertos** y **con errores en 24 h**. 50 por página. |
| Ficha | Identidad (correo, alias, idioma y zona, alta, último acceso, 2FA, sesiones abiertas), membresía (estado, fecha, motivo de suspensión, «no renovará»), uso (días activos en 7 y 30, partidos vistos, picks abiertos, picks y parlays guardados, errores en 24 h), notificaciones (entregabilidad del correo, lo que apagó, dispositivos con avisos sin sus claves, correos de 30 días), consentimientos (versión y fecha), tickets, opiniones (última encuesta, «¿Te sirvió?») y notas. |
| Consola de usuarios | Las tarjetas del móvil muestran la fecha de alta; cada usuario abre sus **sesiones**; el rastro de auditoría ofrece **todos** los tipos de evento que tiene y se carga de 100 en 100 hasta el principio. |

## 2. Lo que puedes hacer desde la ficha, y qué queda registrado

Todo queda en el rastro de auditoría (`auth.audit_events`) con tu cuenta y la del lector sobre quien es.

| Acto | Cómo | Evento |
| --- | --- | --- |
| Renovar o extender | «Renovar o extender» abre la membresía del lector (pago, cortesía, prueba, suspensión) | `membership.*` (ya existían) |
| Activar o suspender la cuenta | Botón con confirmación | `user.status_changed` |
| Reenviar la invitación | Solo si sigue invitado | `user.invitation_resent` |
| Nota interna | Texto de 3 a 500 caracteres; el lector nunca la ve | `customer.note` |
| Consultar el consentimiento | «Ver la prueba de cada decisión» (documento, versión, huella del texto, origen) | `customer.consents_viewed` |
| Revisar un ticket | «Revisar» muestra la conversación | `customer.ticket_reviewed` |
| Exportar sus datos | Pide **tu contraseña** (y tu código 2FA si lo tienes); diez al día; el mismo archivo que él descargaría | `customer.export` + `customer.exported` |

El borrado sigue donde estaba: la anonimización de la consola de usuarios, con el correo escrito otra vez.

## 3. Lo que la ficha nunca muestra

Sin IP, sin tokens ni claves de dispositivos, sin hash ni secretos, sin clics sueltos (el uso son **conteos de días**), sin textos de
los tickets en la lista. PrediGol no guarda teléfono de nadie, así que no hay uno que mostrar. Si el lector no aceptó la analítica
o falta la clave, la ficha dice «no se mide su uso»: los ceros no significan que no use PrediGol. Las notas son para el trato, no para
datos sensibles (salud, documentos, pagos): la ficha lo recuerda.

## 4. Lo nuevo por dentro

- **Sin migración.** Todo es lectura salvo los eventos de auditoría.
- **`routers/admin_customers.py`**: `GET /admin/customers?view=&q=&limit=&offset=`, `GET /admin/customers/{id}`, `POST …/notes`,
  `GET …/consents`, `GET …/tickets/{ticket}`, `POST …/export`, y `GET /admin/audit/actions` para el filtro del rastro.
- **`services/customers.py`**: las vistas son una función pura (`in_view`) de unos pocos números, probada con lectores sintéticos; la
  lista se calcula con consultas por lote (membresía, tickets, errores y días activos de todos a la vez).
- **Web:** `src/admin/CustomersPage.tsx`, `CustomerCard.tsx`, `CustomerParts.tsx`; `AuditPage.tsx` (tipos y páginas) y `UsersPage.tsx`
  (fecha de alta y sesiones); `admin.json` en los dos idiomas.

## 5. Pruebas

- Backend: unitarias de las vistas (límites exactos de 7 y 14 días, la gracia, invitados y desactivados); integración con base real
  (403 y 401, cada vista con quien debe, la ficha sin campos prohibidos, cada acto deja su evento, un ticket de otro lector es 404, la
  copia exige la contraseña) y las guardas de la capa de usuario.
- Web: que cada texto exista en los dos idiomas, las vistas, y que el rastro tenga la etiqueta de cada acto nuevo.
- e2e (`customers.spec.ts`, proyecto `admin`): el recorrido del propietario (lista, vistas, búsqueda, ficha, nota, rastro) y el móvil
  de 320 px (lista, ficha, tarjetas de usuarios con fecha y sesiones), con axe.

## 6. Puertas

Puertas sobre el árbol integrado del PR #21 (`feat/UX-001`, 4-nov-2026), el que se desplegará:

- Backend: `ruff check .` limpio; `mypy` estricto (597 ficheros) y `mypy .` (1.492 ficheros) sin errores; pruebas unitarias **7.904 pasan, 16 omitidas**;
  migraciones 0095 a 0106 con una sola cabeza (0106, colgada de la 0119).
- Web: lint 0 errores (26 avisos que ya existían), tipos de la web y del e2e, **1.456 pruebas pasan, 0 fallan**, build.
- Seguridad: autoprueba de Gitleaks 41 de 41; escaneo de todo el historial limpio.
- CI del PR #21: Convenciones del PR, web, `ruff + mypy`, `scan` y secretos en verde; `pytest` con PostgreSQL 16 y la corrida de integración
  completa se anotan en el PR al terminar. El e2e de esta fase se repite sobre el árbol integrado antes del despliegue.

## 7. Despliegue

Backend y web juntos (el contrato cruza los dos), sin migración. **Vuelta atrás:** volver al commit anterior; las rutas son solo de
administrador y no hay interruptor porque un lector no puede alcanzarlas.

## 8. Acción manual

Ninguna.

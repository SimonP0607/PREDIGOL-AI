# A16 · Prueba real: los 16 pasos (P10)

Plan Maestro UX, sección 45, y línea G15 del gate. **Para qué:** comprobar en producción, con una cuenta que no es de
administrador, que un cliente nuevo puede hacer todo el recorrido. **La haces tú**, porque yo no inicio sesión con
contraseña en producción; yo compruebo por lecturas, sin ver datos personales, lo que cada paso deja escrito.

Antes que tú, el mismo recorrido ya pasó en QA (la copia de pruebas) con el motor de Android y con el del iPhone
(`web/e2e/journey.spec.ts`): esta prueba confirma en producción lo que QA ya vio.

## Cuándo

Al final del bloque A, con A2…A15 desplegadas y encendidos el correo (después de P2 y P3), el autoservicio (invitación y
recuperación), la puerta de consentimiento (después de P5) y la membresía (después de P6 y P7). Te lo pediré cuando todo eso
esté listo y no tengas otra tarea abierta. Repite en B12, al cerrar el primer mes.

## Qué necesitas

- **Un correo tuyo que no sea el de tu cuenta de administrador** (por ejemplo, un Gmail que uses poco).
- **Tu teléfono** (iPhone con Safari o Android con Chrome) y, para el paso 1, el computador con la consola.
- **Unos 40 minutos**, mejor un día con partidos.

**Antes de empezar** me escribes «empiezo la prueba real»: anoto la hora y miro, solo leyendo, que todo esté encendido.
**Si un paso falla**, para ahí y dímelo: lo arreglo y seguimos desde ese paso. Escribe ✓ o ✗ en cada paso y una nota si
algo te extrañó; las capturas, sin datos personales.

## Los 16 pasos

| Paso | Qué haces | Qué debes ver | ✓ / ✗ y nota |
| --- | --- | --- | --- |
| 1. Invitación | En el computador: Consola → Usuarios → «Invitar». Escribe el correo de prueba, deja Español y la zona de Bogotá y pulsa «Enviar invitación» | En unos minutos llega un correo de PrediGol (mira también «Correo no deseado»). En Gmail, «Mostrar original» dice **SPF, DKIM y DMARC: PASS** (captura solo de esa parte) | |
| 2. Activación | En el teléfono, abre el enlace del correo y crea la contraseña (al menos 15 caracteres, sin tu nombre ni tu correo) | La página «Activa tu cuenta» ya trae tu correo, el idioma y la zona. Al terminar pasas a los textos legales. Después del paso 4, abre otra vez el mismo enlace: **debe decir que ya no sirve** | |
| 3. Consentimiento | Lee las cuatro casillas | Están separadas y **sin marcar**; sin las cuatro no se puede seguir | |
| 4. Bienvenida | «Tu fútbol»: elige una liga o un equipo. Luego «Qué es PrediGol». **Cronometra** desde que abriste el enlace (paso 2) hasta ver Inicio | **Menos de 90 segundos** | |
| 5. Inicio | Mira «Hoy en tus ligas» | Partidos de hoy de lo que elegiste, cada uno con el porqué. Si no hay picks, la frase que explica por qué | |
| 6. Partido | Abre un partido y pasa por sus secciones: Resumen, Análisis, Estadísticas, Mercados, Alineaciones y Noticias (y Postpartido en uno terminado) | Cada sección muestra datos o dice con claridad que no los hay; en Noticias, tarjetas o la frase de que no hay noticias verificadas | |
| 7. Pick | Abre Picks | Un pick publicado con su estado real, o el día sin picks bien explicado. **Nunca un pick inventado** | |
| 8. Parlay | En Mercados, toca dos cuotas de dos partidos distintos y abre «Mi parlay»; quita una, pulsa «Deshacer», mira la dependencia; ponle nombre y guarda | La selección vuelve al deshacer, la dependencia se ve y el parlay se guarda | |
| 9. Mis picks | Guarda una cuota con «Guardar» (el marcador junto a la cuota); abre Mis picks y bórrala | Ves lo guardado y tu parlay, el resumen con sus cifras y, **al borrar, te pregunta antes** | |
| 10. Perfil | «Más» → Perfil. Mira el idioma y la zona, «Descargar mis datos» (pide tu contraseña), Seguridad (tus sesiones) y Membresía | El archivo descargado **solo tiene tus datos** (tu correo y nada de otras personas). Membresía: «En prueba hasta el …» | |
| 11. Soporte | «Más» → Ayuda → «Reportar un problema». Escribe «Prueba real, ignorar» y envía | Te da un número de mensaje. Yo respondo desde la consola y te llega un correo **con el número y el enlace, no con las palabras**; al abrirlo ves mi respuesta | |
| 12. Salir | «Más» → «Cerrar sesión». Luego el botón Atrás del teléfono | Vuelves a «Inicia sesión»; Atrás **no muestra tus datos** | |
| 13. Entrar | Escribe mal la contraseña una vez; luego bien | El error dice que el correo o la contraseña no son correctos, sin entrar; con la buena entras sin que te pidan otra vez los consentimientos ni la bienvenida. (Con 5 errores seguidos la cuenta espera 15 minutos: no hace falta probarlo) | |
| 14. Recuperación | Antes, abre PrediGol en el computador con esta cuenta. Luego, en el teléfono: «Cerrar sesión» → «¿Olvidaste tu contraseña?» → tu correo. Abre el enlace del correo y elige una contraseña nueva | Llega el correo (el enlace vale 30 minutos y una sola vez). Con la contraseña nueva, **la sesión del computador se cierra sola** (recarga allí: te pide entrar) | |
| 15. Móvil | Todo lo anterior lo hiciste en el teléfono | Nada se corta ni hace falta zoom; la barra de abajo y «Más» se usan bien con el pulgar | |
| 16. App instalada | «Más» → «Instalar PrediGol» y sigue los pasos; abre PrediGol desde el icono; pon el modo avión y abre otra página; tras el siguiente despliegue, acepta «Actualizar ahora» | Se abre a pantalla completa; sin conexión dice «Sin conexión» (nunca datos viejos); la actualización recarga una sola vez | |

**Al terminar:** me mandas la hoja (o las marcas por el chat) y las capturas. Si quieres, borro la cuenta de prueba, siempre
con tu confirmación: el borrado anonimiza la cuenta y no se deshace.

## Lo que compruebo yo (solo lectura, sin datos personales)

Con la cuenta de prueba identificada por su número (lo saco de la invitación en el registro de auditoría), leo en
producción **solo recuentos, estados y horas**: nunca el correo, la IP, el navegador, el texto de un mensaje ni una
contraseña. Las consultas no escriben nada.

| Paso | Lo que debe haber quedado escrito |
| --- | --- |
| 1 | La invitación en la cola de correo (`customer.messages_outbox`: plantilla `invitation`, estado `sent`) y `user.invited` en el registro de auditoría |
| 2 | `user.activated` en el registro; el enlace de la invitación usado una vez (`auth.account_tokens`: `used_at`) |
| 3 | Cuatro consentimientos (`customer.consents`) con su versión, su sha256 y el origen «activación» |
| 4 | La hora de la bienvenida terminada (`customer.preferences.onboarded_at`) y su distancia a la activación |
| 8–9 | El parlay guardado (`picks.user_parlays`); la cuota guardada y quitada no deja fila, como está diseñado |
| 10 | `privacy.export` en el registro; el periodo de prueba de la cuenta (`customer.membership_periods`) |
| 11 | El mensaje con su categoría y su contexto (`customer.support_tickets`), la respuesta (`customer.ticket_messages`, solo el autor y la hora) y los dos correos en la cola (`support_ticket_received` y `support_ticket_answered`, enviados) |
| 12 | La sesión cerrada en el servidor (`auth.sessions.revoked_at`) y `logout` en el registro |
| 13 | Un `login.failed` y después `login.succeeded` |
| 14 | `password.reset_requested` y `password.reset`; el correo `password_reset` enviado; todas las sesiones de antes cerradas a la hora del cambio |
| Todos | Ningún error nuevo en Sentry durante la prueba; picks y decisiones de Intelligence sin cambios |

Las consultas exactas están en el anexo; las corro por SSH en transacciones de solo lectura
(`default_transaction_read_only`) y la salida se queda en el informe de la prueba.

## Anexo: consultas de solo lectura

`:uid` es el número de la cuenta de prueba (`SELECT target_user_id FROM auth.audit_events WHERE action = 'user.invited'
ORDER BY at DESC LIMIT 1`, comprobado contra la hora que me digas). Ninguna consulta devuelve el correo, la IP, el
navegador, un texto escrito por la persona ni un hash.

```sql
-- 1, 11, 14: los correos de la cuenta, por plantilla y estado (la cola no guarda la dirección ni el cuerpo)
SELECT template, status, count(*), min(created_at), max(sent_at)
FROM customer.messages_outbox WHERE user_id = :uid GROUP BY 1, 2 ORDER BY 4;

-- 1, 2, 10, 12, 13, 14: el registro de auditoría de la cuenta, solo acciones y horas
SELECT action, count(*), min(at), max(at)
FROM auth.audit_events WHERE target_user_id = :uid OR actor_user_id = :uid GROUP BY 1 ORDER BY 3;

-- 2: el enlace de la invitación, usado una vez; 14: el de la recuperación
SELECT purpose, created_at, used_at, revoked_at, revoked_reason
FROM auth.account_tokens WHERE user_id = :uid ORDER BY created_at;

-- 3: los consentimientos, con versión y huella
SELECT kind, granted, document, version, left(sha256, 12) AS sha256, source, at
FROM customer.consents WHERE user_id = :uid ORDER BY at;

-- 4: la bienvenida terminada
SELECT onboarded_at FROM customer.preferences WHERE user_id = :uid;

-- 8: el parlay guardado (su nombre lo escribió la persona: no se lee)
SELECT count(*), min(created_at), max(status) FROM picks.user_parlays WHERE user_id = :uid;

-- 10: el periodo de prueba
SELECT kind, starts_at, ends_at FROM customer.membership_periods WHERE user_id = :uid ORDER BY starts_at;

-- 11: el mensaje y su respuesta, sin los textos
SELECT t.id, t.category, t.status, t.context ->> 'route' AS route, t.context ->> 'device' AS device,
       (t.context ->> 'pwa')::bool AS pwa, t.opened_at, t.closed_at,
       (SELECT count(*) FROM customer.ticket_messages m WHERE m.ticket_id = t.id AND m.author = 'owner') AS answers
FROM customer.support_tickets t WHERE t.user_id = :uid ORDER BY t.opened_at;

-- 12, 14: las sesiones, solo sus horas
SELECT created_at, last_seen_at, revoked_at, revoked_reason
FROM auth.sessions WHERE user_id = :uid ORDER BY created_at;
```

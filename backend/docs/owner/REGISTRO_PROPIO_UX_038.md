# Registro propio y verificación del correo (UX-038)

Primer paso visible del tramo 1 del flujo del usuario: una persona crea su cuenta sola y confirma su correo. **Nace apagado** (`FBI_SIGNUP`) y, aun encendido, **no da acceso a nada**: crear la cuenta y confirmar el correo no son pedir el acceso, ni pagar, ni tener la membresía activa.

## Qué pasa, paso a paso

1. En `/register` la persona escribe nombre, apellido, correo, celular, apodo y contraseña, y marca las cuatro casillas (términos, datos personales, mayor de 18 y aviso de riesgo), cada una con su frase exacta y un enlace al texto. Las casillas opcionales (estadísticas, resumen semanal) no se piden aquí: están en el perfil.
2. El servidor responde siempre lo mismo (202, «revisa tu correo»), sea el correo nuevo, uno que espera su enlace o uno que ya tiene cuenta. A un correo nuevo le llega el enlace de confirmación; a uno pendiente, un enlace nuevo; a uno que ya tiene cuenta, un aviso de que ya la tiene. Solo se rechaza lo que la persona puede arreglar: un apodo ya usado (409), un campo mal escrito (422) o la pausa del día (503).
3. La cuenta queda `pending`: no entra, no tiene membresía ni prueba. Los consentimientos se escriben en la misma transacción que la cuenta (origen `signup`, con versión, sha256 y frase) o no se escribe nada.
4. El enlace del correo (24 horas, un solo uso, viaja en el fragmento) más la contraseña elegida confirman el correo: la cuenta pasa a `active` y abre sesión. Entrar con una cuenta sin confirmar responde `email_not_verified` y la pantalla ofrece reenviar el enlace. Quien ya no recuerda la contraseña que eligió pulsa «Elegir otra» en esa misma página: el enlace prueba el correo y la contraseña nueva reemplaza la guardada (UX-084); sin ese camino habría que esperar a que la cuenta se cerrara a los siete días.
5. Lo que sigue (pedir el acceso y pagar por Nequi) es el siguiente paso del plan; hasta entonces la cuenta recién confirmada se ve como cualquier cuenta sin membresía.

## Candados del interruptor

`FBI_SIGNUP=on` solo abre si además: el correo está encendido (`FBI_SELF_SERVICE`), la puerta de consentimientos está en `on` sin textos en borrador y la membresía está exigida. Si falta uno, las rutas responden 404, `GET /auth/options` dice `signup: false` y el acceso no ofrece «Crear cuenta». El orden de encendido está en `claude/PLAN_FLUJO_USUARIO_TRAMO1.md` (proyecto).

## Límites

- Cinco intentos de registro por hora y por cliente (cuenta cada intento, sea cual sea el correo).
- Un tope diario de cuentas nuevas, `FBI_SIGNUP_DAILY_CAP` (100 si falta). Al llegar, el registro se pausa solo (503 `signup_paused`) y queda en el historial; no hace falta estar despierto.
- Tres enlaces por hora por cuenta, como en las invitaciones.

## Cuentas que nunca confirman

A los siete días, el mensajero cuenta (`FBI_SIGNUP_PURGE=dry`, el valor de nacimiento) o cierra (`on`) las cuentas pendientes: la fila se queda (los consentimientos apuntan a ella), pero el correo se enmascara, el nombre, el apellido y el celular se borran, el apodo queda libre y la contraseña ya no sirve. El mensajero lo anota en su resumen.

## Lo que guarda y para qué

El celular es solo para el registro del dueño; **no se usa para enviar nada**. Nombre y apellido, los de la persona, para el registro del dueño. El apodo es único (sin distinguir mayúsculas) y no puede ser un nombre reservado (admin, soporte, predigol…). La anonimización borra todos estos datos.

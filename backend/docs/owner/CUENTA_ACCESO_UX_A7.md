# A7 · Cuenta y acceso

Plan Maestro UX, fase A7 (migración **0098**; el plan la numeró 0097, que tomó A6). Todo nace **apagado**
(`FBI_SELF_SERVICE`): hasta que lo enciendas, las cuentas se crean como hoy, con una contraseña temporal, y no sale
ningún correo nuevo. Se enciende después del correo de A5 (`FBI_EMAIL_SEND=1` con su prueba real).

## 1. Qué cambia para tus clientes

- **Invitación en lugar de contraseña compartida.** Desde la consola escribes el email, un alias, el idioma y la zona
  horaria; al cliente le llega un correo con un enlace que sirve **una sola vez y caduca en 7 días**. En `/activate` crea
  su contraseña (con un medidor que le dice al momento lo que el servidor va a decir), revisa idioma y zona, acepta los
  textos legales (se registran como dados en la activación) y entra. Nadie más conoce su contraseña.
- **Recuperar la contraseña sin ti.** «¿Olvidaste tu contraseña?» en la pantalla de acceso → un enlace de **30 minutos y
  un solo uso**. La respuesta es siempre la misma, exista o no la cuenta (no se puede averiguar quién es cliente). Al
  cambiarla se cierran **todas** sus sesiones; si usa verificación en dos pasos, además del enlace pide un código de su
  app (o uno de recuperación) — cinco códigos malos anulan el enlace. La verificación en dos pasos sigue igual.
- **Desbloquear la cuenta sin ti.** Tras cinco fallos la cuenta espera 15 minutos; desde la misma pantalla puede pedir un
  enlace (1 hora, un uso) que la desbloquea. Abrir el enlace no hace nada: solo actúa el toque del cliente (un
  antivirus que sigue enlaces no desbloquea nada).
- **Avisos de seguridad por correo:** inicio de sesión desde un navegador nuevo (dice navegador, sistema y hora en su
  zona; **nunca la IP**), y cambios de contraseña, de verificación en dos pasos o de códigos de recuperación, incluidos
  los que hagas tú desde la consola. No se pueden desactivar (categoría «seguridad»).
- **Cerrar otras sesiones pide la contraseña o un código.** Una sesión robada sola no puede echar al dueño de la cuenta.
- **Contraseñas (regla compartida con el plan de seguridad, R11):** mínimo 15 caracteres, o 12 con verificación en dos
  pasos; sin reglas de mayúsculas o símbolos; no puede ser el email, ni contener «predigol», el email o el nombre, ni ser
  una repetición o secuencia, ni estar entre 1.179 contraseñas comunes. Pegar desde un gestor de contraseñas funciona.

## 2. Qué cambia para ti (Consola → Usuarios)

- **«Invitar»** es el botón principal mientras el autoservicio está encendido; **«Con contraseña temporal»** queda como
  respaldo (por si el correo no llega). Si el envío de correo está apagado, la consola te avisa de que la invitación
  espera en la cola.
- Estados nuevos: **Invitada** (con «Reenviar invitación» —el enlace anterior deja de valer— y «Retirar invitación») y
  **Borrada**. Las borradas se ocultan por defecto («Mostrar las borradas»).
- **Borrar una cuenta = anonimizarla**, con el email tecleado de nuevo (no se puede deshacer). Se borra: preferencias,
  picks y combinadas guardados, sesiones, verificación en dos pasos y códigos, enlaces abiertos y los correos aún en cola;
  el email queda enmascarado en la cuenta y en el registro de accesos. Se conserva, enlazado: los consentimientos (prueba
  de lo aceptado) y las solicitudes de privacidad con su hilo. Una cuenta SUPER_ADMIN, o la tuya, no se borra.
- **Solicitudes de borrado (privacidad):** responde primero y comprueba en Mensajes que la respuesta salió; después el
  botón de borrado de la solicitud hace la anonimización (después ya no hay dirección a la que escribir).
- El registro de auditoría nombra las acciones nuevas (invitación enviada, reenviada, renovada, cuenta activada,
  recuperación pedida, contraseña restablecida, desbloqueo, cuenta borrada, enlaces agotados).

## 3. Seguridad y privacidad

- Del enlace solo se guarda su huella (sha256): quien lea la base no puede usarlo. El enlace se fabrica al enviar el
  correo y viaja en la parte de la dirección que el navegador nunca manda al servidor (no queda en registros ni en
  referencias); la página lo lee una vez y lo quita de la barra de direcciones.
- Límites: 3 enlaces por hora y cuenta; 10 peticiones por hora y por cliente (un hash de la IP de vida corta, nunca la
  IP); 20 enlaces fallidos por cliente en 15 minutos.
- Tablas: `auth.account_tokens`. Los enlaces usados o caducados se borran a los 30 días, pero la purga nace **en
  ensayo** (`FBI_TOKENS_PURGE=dry`: solo cuenta). El recorrido sintético comprueba cada pocos minutos que la página de
  activación responde.

## 4. Cómo se enciende (cuando decidas)

1. Antes: A5 desplegada y el correo encendido con su prueba real (P2 y P3; `FBI_EMAIL_SEND=1`).
2. Una línea en `/etc/predigol/app.env` (fichero de seguridad: copia fechada, candado de despliegue, ventana propia):
   `FBI_SELF_SERVICE=1`; se recrean la API y el messenger.
3. Comprobación: en la consola aparece «Invitar»; te invitas a una dirección tuya de prueba, activas desde el correo y
   pruebas «¿Olvidaste tu contraseña?». Cuando lleve un tiempo sin incidencias te pediré el visto bueno para
   `FBI_TOKENS_PURGE=on`.

## 5. Vuelta atrás

`FBI_SELF_SERVICE=0` y recrear la API y el messenger: vuelve el alta con contraseña temporal, los enlaces ya enviados dejan
de funcionar y no salen avisos nuevos. Las cuentas invitadas o borradas se quedan como están; por eso, mientras existan,
la marcha atrás es el interruptor y no el código (la migración 0098 se niega a bajar).

## 6. Pendiente de tu abogado (P5)

Al anonimizar se conserva el texto que el cliente escribió en sus solicitudes y tickets, como prueba de que se le
respondió. Si el abogado dice que también debe borrarse, se adapta.

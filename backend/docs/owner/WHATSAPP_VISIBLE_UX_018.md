# UX-018 · WhatsApp visible y sin invadir

Plan de cierre de la UX, tarea 4.2. **Sin migración, sin interruptor nuevo, sin IA y sin servicios externos.** El número de WhatsApp
ya existía (P7); esta tarea lo hace fácil de encontrar y hace que quien lo recibe sepa dónde estaba el lector, sin pedirle datos.

## 1. Qué ve el cliente

- **Dónde está «Escríbenos»:** Ayuda (el bloque de contacto), «Más» (una fila «Escríbenos por WhatsApp»), Perfil → Ayuda, renovar la
  membresía, «¿No puedes entrar?» bajo el acceso y, **bajo cada error**, «¿Sigue fallando? Escríbenos».
- **Sin burbuja flotante:** la que ya hay es la de «Mi parlay»; no se añade otra.
- **Mensaje prellenado:** una primera línea (según el sitio) y, debajo, «Código de consulta: v1.4.2 · /matches/812 · ref a1b2c3» con la
  versión de la web, la pantalla (solo la ruta, sin consulta ni fragmento) y, en un error, su `request_id`. **Ni nombre, ni correo, ni
  cuenta, ni pick.** Es el mismo contexto que lleva un ticket, construido por la misma función.
- **Horario de atención:** si el dueño lo publica, Ayuda dice «Atención: …».
- En un error, el enlace solo aparece si el lector ya puede escribir a PrediGol (el mismo interruptor que «Reportar un problema») y si
  el dueño dio el número.

## 2. Qué configura el dueño (solo en el servidor)

| Variable | Qué hace |
|---|---|
| `FBI_SUPPORT_WHATSAPP` | El número (P7). **Solo en el servidor**; el navegador lo recibe únicamente dentro del enlace. |
| `FBI_SUPPORT_CHANNELS` | Orden de los canales en Ayuda: `whatsapp,tickets,email` (por defecto). Para pasar a Telegram o a tickets basta cambiar esta lista, sin tocar código. Un nombre desconocido se ignora; vacío vuelve al orden por defecto; un canal sin configurar no se ofrece. |
| `FBI_SUPPORT_HOURS` | Texto del horario (hasta 80 caracteres, sin saltos de línea ni `<` `>`). Vacío: no se muestra. |

`GET /v1/support/contact` suma `channels` y `hours` (compatible: los campos viejos no cambian).

## 3. Qué no cambia

Ni un pick, una probabilidad, un estado ni una cuota: la capa de usuario consume la inteligencia, no la altera.

## 4. Tareas del dueño

- **P7:** dar el número de WhatsApp Business en el servidor (`FBI_SUPPORT_WHATSAPP`), y, si quiere, `FBI_SUPPORT_HOURS`.

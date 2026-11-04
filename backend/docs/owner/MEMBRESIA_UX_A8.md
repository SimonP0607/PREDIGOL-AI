# A8 · Membresía

Plan Maestro UX, fase A8 (migración **0099**; el plan la numeró 0098, que tomó A7). La puerta nace **apagada**
(`FBI_MEMBERSHIP_ENFORCE`): hasta que la enciendas, una membresía terminada no limita nada; los estados se calculan y se
muestran tal como son.

## 1. Qué es

Un solo plan completo, **prueba de 14 días** y siete estados calculados por fecha (nunca guardados):

| Estado | Cuándo | Acceso |
| --- | --- | --- |
| En prueba | La prueba corre y le quedan más de 3 días | Completo |
| Activa | Un periodo pagado o una cortesía, más de 7 días por delante | Completo |
| Próxima a vencer | 7 días o menos (3 en la prueba) | Completo, con un aviso discreto |
| En gracia | Terminó hace menos de 3 días | Completo, con un aviso fijo |
| Vencida | Terminó la gracia | Limitado: perfil, Mis picks en lectura, ayuda, textos legales y descarga de sus datos |
| Renovada | Un pago que sigue a otro pago, durante 7 días | Completo |
| Suspendida | Tú la suspendes con un motivo | Limitado, como vencida (la sesión sigue: no es desactivar) |

El primer pago después de la prueba deja la cuenta **Activa** llegue cuando llegue. Vencer nunca borra nada. Tus
cuentas SUPER_ADMIN y la cuenta sintética no tienen membresía. Una cuenta sin ningún periodo (las de antes de A8)
sale en la consola como «sin periodo» y conserva el acceso completo.

## 2. Cuándo empieza la prueba

- **Invitación (A7):** al activar la cuenta. Al invitar eliges los días de prueba (7 a 14); si no, `FBI_TRIAL_DAYS` (14).
- **Cuenta creada con contraseña temporal (respaldo):** al crearla.
- **Cuentas de antes:** desde la consola, «Membresía» → «Empezar prueba» (una sola prueba por cuenta).

## 3. Renovar en menos de un minuto (Consola → Usuarios → Membresía)

1. El cliente paga por el medio acordado (P6).
2. Pulsas **Membresía** en su fila → «Registrar pago y extender»: importe, moneda, medio, una referencia en texto
   («Nequi, 25 oct» o los 4 últimos dígitos) y los meses. **Nunca números de cuenta o tarjeta:** la referencia rechaza
   cualquier serie de 10 dígitos o más.
3. El periodo nuevo empieza al final del vigente, o hoy si ya terminó. Un doble clic registra un solo pago (clave de
   idempotencia).

También desde ahí: **cortesía** (días y motivo), **suspender** y **levantar** (con motivo) y **«no renovará»** (con su
motivo; detiene los correos de vencimiento, nunca los avisos de la app). Todo queda en el registro de auditoría
(`membership.*`) y en la historia de la cuenta. La lista de Usuarios tiene el filtro **Vencimientos** (próximas a
vencer, en gracia y vencidas).

## 4. Qué recibe el cliente

- **App:** desde 7 días antes (3 en la prueba) un aviso discreto arriba («Tu membresía termina el…»), la víspera
  «Mañana termina…», durante la gracia un aviso fijo, y con acceso limitado una página que dice qué puede hacer y cómo
  renovar. En el perfil, el bloque Membresía con el estado, la fecha, los días que quedan, cómo renovar y los periodos.
- **Correo (con A5 encendido):** 7 días antes (3 en la prueba) y el día que termina («tienes 3 días de gracia con
  todo»), una sola vez cada uno por periodo; cómo renovar por WhatsApp (P7, `FBI_SUPPORT_WHATSAPP`) o respondiendo al
  correo (`FBI_EMAIL_REPLY_TO`). El cliente puede apagar los correos de membresía en su perfil; «no renovará» también
  los detiene.
- Sin cuentas atrás, ofertas ni colores de alarma: son avisos del servicio contratado.

## 5. Qué recibes tú

Cada mañana (desde las 07:00 de Bogotá), si hay algo que decir, un aviso por tu canal con **cuántas** membresías
terminan hoy, cuántas están en gracia, cuántas pasaron a acceso limitado y cuántas dijeron que no renovarán — solo
números; los nombres, en la consola (`/admin/users?membership=due`).

## 6. Privacidad y seguridad

Solo un SUPER_ADMIN registra pagos y cambios. Nunca se guardan números de tarjeta o de cuenta: importe, moneda, medio
y una referencia en texto. Las tablas (`customer.payments`, `customer.membership_periods`,
`customer.membership_events`) solo admiten filas nuevas; el worker de PrediGol Intelligence no puede leerlas. Los pagos
y periodos quedan enlazados a la cuenta aunque se borre (anonimización de A7), por obligación tributaria. El cliente
los ve en su exportación.

## 7. Cómo se enciende (cuando decidas)

1. Antes: cada cliente vivo tiene su periodo (la columna Membresía no muestra «sin periodo» en cuentas de clientes).
2. P6 (precio, moneda y medios) y P7 (WhatsApp Business): `FBI_MEMBERSHIP_CURRENCY` y `FBI_SUPPORT_WHATSAPP`.
3. Una línea en `/etc/predigol/app.env` (fichero de seguridad: copia fechada, candado de despliegue, ventana propia):
   `FBI_MEMBERSHIP_ENFORCE=1`, y se recrea la API.

## 8. Vuelta atrás

`FBI_MEMBERSHIP_ENFORCE=0` y recrear la API: acceso completo para todos al momento; periodos y pagos se quedan. La
migración 0099 solo se deshace con las tablas vacías.

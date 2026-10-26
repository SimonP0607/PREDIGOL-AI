# A16 · Hoja del gate «Listo para el primer cliente de pago»

Plan Maestro UX, fase A16 (secciones 45 y 49). PrediGol está listo para cobrar al primer cliente cuando **las 15 líneas**
de esta hoja están en verde, cada una con su prueba. Aquí está, línea por línea, qué tiene que ser verdad, dónde está la
prueba y qué falta. Al final la firmas tú.

**Hoy, 26-oct-2026: 1 de 15 líneas en verde. LISTO PARA COBRAR = NO.**

## Cómo leer el estado

- **Verde:** probado en producción, con su prueba.
- **Listo en código:** construido y probado en QA (la copia de pruebas, sin datos de clientes); falta desplegarlo o
  encenderlo.
- **Espera:** depende de alguien de fuera: el abogado, el plan de seguridad o tú.

Desplegar no significa que el cliente lo vea: cada fase llega con su interruptor apagado y se enciende después de
comprobarla en producción.

## Las 15 líneas

| # | Línea | Qué tiene que ser verdad | Dónde está la prueba | Hoy | Qué falta |
| --- | --- | --- | --- | --- | --- |
| G1 | Estabilidad | PrediGol Intelligence, los picks, la liquidación, las cuotas y los modelos siguen iguales | La huella de los modelos `mc9a7bec97ca` y los picks y decisiones del día idénticos antes y después de cada despliegue (A0 y A1: todas las líneas bien; en A1, 10.035 picks y 2.333 decisiones idénticos); las pruebas de separación de cada fase | **Verde** | Repetir la comprobación en cada despliegue de A2 a A15 |
| G2 | Seguridad | El gate del plan de seguridad («SECURITY READY FOR PAID USERS») en SÍ: sus 23 puntos | El acta del gate S7 del plan de seguridad y las pruebas de seguridad de cada fase | Espera: el plan de seguridad tiene 2 de 23 | Lo cierra el plan de seguridad, con tus tareas P13 (copias fuera del servidor) y P15 (acceso de administración separado) |
| G3 | Legal | Términos, tratamiento de datos, juego responsable, +18 y consentimientos con versión, con el visto bueno escrito del abogado | Los textos con su versión y su huella sha256 y las pruebas de la puerta de consentimiento (A4) | Listo en código; espera al abogado | P5 (el abogado revisa los textos), desplegar A4 y encender la puerta |
| G4 | Datos | Los datos de clientes fuera del alcance del worker de Intelligence; roles comprobados; ninguna tabla con datos prohibidos; la IP y el correo justificados, con su plazo | `test_db_roles.py` en QA (de A4 a A14) y el inventario de datos de la guía de A4 | Listo en código | Desplegar A4 (con su `grants.sql`) y comprobar los permisos en producción con consultas de solo lectura |
| G5 | Acceso | Invitación con enlace de un uso, activación con correo autenticado (SPF, DKIM y DMARC) y una sesión que se renueva con el uso | Las pruebas de la invitación (A7) y del recorrido (A16); la sesión de A1, ya en producción | Listo en código | Desplegar A5 y A7; P2 y P3 (dominio de correo y cuenta de Resend); encender el correo y el autoservicio |
| G6 | Recuperación | Recuperar la contraseña y desbloquear la cuenta sin pedírtelo a ti | Las pruebas de recuperación y desbloqueo (A7, y el paso 14 del recorrido), con un enlace reutilizado rechazado | Listo en código | Lo mismo que G5 |
| G7 | Membresía | Prueba gratis, estados, avisos, gracia, acceso limitado y renovación en menos de 1 minuto | Las pruebas con fechas movidas en QA y una renovación cronometrada (A8) | Listo en código | Desplegar A8; P6 (precio, moneda y medios de pago) y P7 (WhatsApp) para encender la puerta |
| G8 | Bienvenida | De la activación al primer valor en menos de 90 segundos, con favoritos | La bienvenida cronometrada: 17,6 s desde el enlace de la invitación (A13) y el paso 4 del recorrido (A16) | Listo en código | Desplegar A13 y los tiempos del ensayo con una persona nueva (P11) |
| G9 | Valor diario | Pronóstico, lectura, contexto, noticias y el motivo honesto cuando no hay picks; lenguaje claro; transparencia publicada; ningún estado visible sin su equivalente real | Las pruebas de A3, A9, A10 y A12, la de palabras vetadas y la página de transparencia | Listo en código | Desplegar A3, A9, A10 y A12; una semana de capturas con y sin picks; tu visto bueno a la transparencia (P9) |
| G10 | Soporte | Centro de ayuda, mensaje con contexto, WhatsApp y respuesta en plazo | Las pruebas de A14: un mensaje respondido y cerrado; el paso 11 del recorrido | Listo en código | Desplegar A14; P7 (WhatsApp) y P14 (canal de avisos) para el aviso de un mensaje urgente |
| G11 | Móvil | Cinco destinos, objetivos de 44 px, nada cortado entre 320 y 430 px y la app instalada | Las pruebas en todos los anchos, con el motor de Android y el del iPhone (A1 y A15) | Listo en código | Desplegar A15 y tu prueba en un iPhone y un Android reales |
| G12 | Observabilidad | Los errores de la web y de la API llegan con un usuario seudónimo y su referencia, el recorrido sintético 24 h en verde y los avisos activos | Las pruebas de A2 con un Sentry de pruebas | Empaquetado (A2) | Desplegar A2 (ventana del 27-oct); P1 (Sentry); el error de prueba intencional y 24 h del sintético |
| G13 | Copia de seguridad | Una copia cifrada fuera del servidor y una restauración probada desde ella | La restauración desde Cloudflare R2 con sus conteos | Espera: plan de seguridad | P13 (R2 y la clave que cifra las copias) y el simulacro del plan de seguridad |
| G14 | Privacidad | Exportación, solicitud de borrado con plazo, retención definida y Sentry sin datos personales | Las pruebas de exportación y solicitud (A4 y A7, y el paso 10 del recorrido), la de `before_send` (A2) y las purgas en seco | Listo en código | Desplegar A2, A4 y A7 |
| G15 | Prueba real | El recorrido de 16 pasos con una cuenta que no es de administrador y el ensayo con una persona nueva, superados | La hoja de la prueba real (`PRUEBA_REAL_A16.md`), el informe del ensayo (`ENSAYO_PERSONA_NUEVA_A16.md`) y el recorrido entero en QA (`journey.spec.ts`) | Probado en QA; espera a producción | P10 y P11, con todo lo anterior en producción |

## El camino hasta el verde

1. **Desplegar A2…A15**, una fase por noche entre las 19:55 y las 23:00 UTC, sin pisar las ventanas de los otros planes. Cada
   despliegue repite la comprobación de G1.
2. **Tus tareas, de una en una:** P4 (abierta), P5 (el abogado), P1 (Sentry), P2 y P3 (correo), P14 (avisos), P6 y P7
   (membresía y WhatsApp), P9 (transparencia) y P8 (presupuesto de la IA de lectores, que no bloquea el gate). Te las pido
   cuando no tengas otra abierta y cuando sirvan (por ejemplo, P2 y P3 después de desplegar A5).
3. **El gate del plan de seguridad en SÍ**, con P13 y P15.
4. **La prueba real (P10) y el ensayo (P11)**, con todo encendido.
5. **Tu firma**, abajo.

Si una sola línea sigue en rojo no se cobra: se corrige y se vuelve a pasar esa línea. El gate se repite en B12, al cerrar el
primer mes.

## Lo que esta fase ya hizo en QA

- **El recorrido de 16 pasos en QA** (`web/e2e/journey.spec.ts`): una cuenta invitada desde la consola recorre la
  activación, los consentimientos, la bienvenida cronometrada, Inicio, un partido, Picks, un parlay, Mis picks, el perfil con
  la copia de sus datos, un mensaje de soporte respondido, la salida, la entrada, la recuperación de la contraseña y el borrado
  final, en un teléfono de 390 px, con el motor de Android y con el del iPhone. Resultado en la guía de A16.
- **Las hojas** de la prueba real y del ensayo, listas para cuando toque.

## Firma

Revisé las 15 líneas y su prueba. PrediGol está listo para el primer cliente de pago: SÍ / NO.

Nombre: ______________________ Fecha: ______________

# A4 · Guía del dueño: textos legales, datos y la puerta de consentimientos

Plan de cierre de la UX, tarea 1.3 (código `UX-009`, solo documentación). Esta guía es para que **leas** qué dice hoy
PrediGol de sí mismo y de tus datos, **llevarla a tu abogado** (P4 y P5) y saber **cómo se publica un texto y se enciende
la puerta de consentimientos**. No es asesoramiento legal: los textos los valida el abogado. Lo que aquí figura como
«hecho» está comprobado en el código y en las migraciones; lo que no se pudo comprobar está marcado como pregunta.

## 1. En qué estado está

| Cosa | Hoy |
| --- | --- |
| Términos del servicio | versión `2026-11-05-draft3`, **borrador** (cambio material) |
| Política de tratamiento de datos | versión `2026-11-05-draft4`, **borrador** (no material) |
| Juego responsable | versión `2026-10-25-draft1`, **borrador** (sin cambios) |
| Datos del responsable (P4) | pendientes: `backend/src/fbi/customer/texts/controller.json` trae marcadores `[P4 · …]` |
| Puerta de consentimientos | **apagada** (`FBI_CONSENT_GATE`): el servicio funciona sin pedir nada |
| Analítica de uso | **apagada** (`FBI_PRODUCT_EVENTS`): no se guarda ningún evento |

La puerta tiene tres posiciones: sin valor o `0`, apagada; `drafts`, encendida **solo para pruebas en QA** (nunca
producción); `1`, encendida **solo cuando ninguno de los tres textos sea ya un borrador**. Con borradores, poner `1` no
hace nada: es una cerradura contra encenderla por error. Quedan fuera de la puerta tu cuenta (SUPER_ADMIN) y la del
robot de monitoreo.

## 2. Lo que PrediGol dice de sí mismo

Una sola frase, igual en todas partes (tarea 1.1): *plataforma de análisis deportivo y detección de valor; no garantiza
resultados ni beneficios; no es una casa de apuestas ni recibe dinero de apuestas; solo para mayores de 18 años*. Está en
el resumen y las secciones 1 y 2 de los términos, en la sección 1 de la política, en el aviso del pie de cada pantalla,
en la descripción de la app (la del navegador y la de la app instalada), en la bienvenida y en el bloque «El plan» de la
membresía. El único dinero que PrediGol recibe es el de **su propia membresía**, y los términos lo dicen.

## 3. Inventario de datos

Lo que guarda la base de datos sobre un lector, para qué, cuánto y si la política ya lo nombra.

| Dato | Para qué | Cuánto | ¿Lo dice la política? |
| --- | --- | --- | --- |
| Cuenta: correo, alias, idioma, zona horaria y la contraseña como huella (argon2id) | Prestar el servicio | Mientras exista la cuenta | Sí |
| Sesiones (fecha, navegador y dirección IP) e historial de accesos; verificación en dos pasos si la activa | Seguridad de la cuenta | Sesiones, 90 días después de vencer; accesos, 12 meses | Sí |
| Consentimientos: qué aceptó, versión, huella del texto, frase de la casilla, origen y fecha | Prueba de la autorización | Mientras exista la relación | Sí |
| Membresía: periodos (prueba, pago, cortesía), pagos registrados a mano (monto, moneda, medio y una referencia en palabras; la base rechaza referencias con diez cifras seguidas) y avisos de vencimiento | Prestar y cobrar la membresía | No se borran (los registros solo se añaden) | Sí, desde `draft3`. **Pregunta:** el plazo de conservación |
| Picks y parlays que guarda, con la cuota que anote (no pide importe ni operador) | «Mis picks» | Mientras exista la cuenta | Sí, desde `draft3` |
| Favoritos (ligas y equipos) y alertas de partido («avísame N minutos antes») | Ordenar Inicio y avisar | Mientras exista la cuenta; se borran al anonimizar | En general («preferencias»); **las alertas no se nombran** |
| Correos: cada mensaje y su suerte, **sin cuerpo, sin nombre y sin dirección** (se leen al enviar); qué categorías apagó y si su dirección rebota | Enviar, no repetir, respetar bajas | 12 meses (la purga es un trabajo documentado que se hace con tu visto bueno) | Parcial (habla de correos necesarios) |
| Soporte: tickets y mensajes, y el contexto técnico que adjunta la web (ruta, versión, `request_id`, dispositivo) | Atender | 24 meses después de cerrarse | Sí |
| Encuesta mensual y «¿Te sirvió?» (nota de 1 a 5 y comentario opcional) | Mejorar el producto | 24 meses; se borra al anonimizar | **No se nombra** |
| Avisos en el teléfono (cuando se enciendan): la dirección del servicio de notificaciones del navegador y las claves que cifran el aviso | Avisar | Hasta que lo revoque; se borra al anonimizar; la cola de avisos, 90 días | **No se nombra** |
| Estado diario del cliente (invitado, activado, habitual, en riesgo, por vencer, renovado, vencido) con códigos de motivo, nunca palabras del lector | Soporte, el dueño y métricas; nunca campañas | 24 meses; se borra al anonimizar | **No se nombra** |
| Analítica de uso, **solo si marca la casilla**: un seudónimo (derivado de su cuenta con una clave propia) y eventos de una lista cerrada de 35; nunca correo, IP ni texto libre | Mejorar el producto | 90 días en bruto y 13 meses agregada. La purga nace en ensayo: hay que pasarla a `on` | Sí, desde `draft4` |
| Errores (Sentry): un seudónimo, la referencia del error, la versión y el navegador; nunca correo, IP, contraseñas, tokens, cookies ni parámetros de URL | Corregir fallos | 30 días, por el plan de Sentry | Sí |

**Lo que no se guarda:** documentos de identidad, números de tarjeta o de cuenta, datos sensibles, importes apostados ni el
operador con el que apuesta el lector.

## 4. Quién más recibe datos

| Proveedor | Para qué | Qué recibe | Dónde | Estado |
| --- | --- | --- | --- | --- |
| Contabo | Alojar el servidor | Todo lo que guarda la base | EE. UU. (el panel de Contabo muestra la región exacta; los documentos del proyecto dicen St. Louis en uno y Nueva Jersey en otro) | Activo |
| Cloudflare | Copias de seguridad cifradas (R2), DNS y, cuando se active, el proxy | Las copias van cifradas; el proxy vería la IP y las peticiones | EE. UU. (sede) | R2 contratado; DNS y proxy, según la sesión de seguridad |
| Resend | Correos de activación, recuperación y avisos | Correo, idioma y contenido del aviso | EE. UU. (sede) | Cuando se active (P2 y P3) |
| Sentry | Registro de errores | Lo de la tabla anterior, sin correo ni IP | A elegir al crear la cuenta: EE. UU. o UE (decisión de P1) | Cuando se active (P1) |
| WhatsApp de Meta | Soporte por el número de PrediGol | Su número y lo que escriba | Meta | Cuando se active (P7) |
| Anthropic | Los modelos de IA | Solo datos de fútbol: la narrativa se escribe desde la lectura del partido, no desde datos de lectores. «Explícame» no llama a ninguna IA | EE. UU. | Narrativa apagada hasta P8 |
| Servicios de notificaciones de Google, Mozilla y Apple | Entregar avisos al teléfono | La dirección del servicio y el aviso cifrado | EE. UU. | Cuando se enciendan los avisos (P12) |

## 5. Lo que la política todavía no dice

Antes de enviarla al abogado, esto debería entrar en la próxima versión o decidirse que no hace falta:

1. **Cloudflare** como encargado (copias cifradas, DNS y proxy). Hoy la política no lo nombra.
2. **Las encuestas, las alertas de partido, los avisos en el teléfono y el estado diario del cliente**, con su plazo.
3. **Los servicios de notificaciones de los navegadores** (Google, Mozilla, Apple) si se encienden los avisos.
4. **El plazo de conservación de los pagos y de la membresía.**
5. **La región de Sentry** (una vez elegida) y el país de cada envío al exterior.

## 6. Preguntas para el abogado (P4 y P5)

1. **Transferencias al exterior.** Contabo, Cloudflare, Resend, Meta, Sentry y Anthropic están fuera de Colombia. ¿Cada una
   es una transmisión con contrato de encargo o una transferencia? ¿Qué garantías pide la ley y qué debe decir la política?
2. **Registro Nacional de Bases de Datos.** ¿Está PrediGol obligado a inscribir su base de datos? ¿Cuándo?
3. **Retracto y reembolsos.** Los términos citan un derecho de retracto de 5 días hábiles con sus excepciones. ¿Aplica a una
   suscripción mensual con 20 días de prueba gratis? ¿Cómo se redactan las excepciones y los reembolsos?
4. **IVA y facturación.** ¿El precio incluye IVA? ¿Hay que facturar cada pago registrado a mano (factura electrónica)? Esto es
   para el abogado o el contador.
5. **Edad.** Hoy el lector declara que tiene 18 años o más y PrediGol no pide documentos. ¿Basta esa declaración?
6. **Analítica de uso.** Ahora es una casilla aparte, sin marcar y retirable. ¿Es suficiente como base legal? ¿Debe haber también
   un aviso al entrar, o puede registrarse a todos (`FBI_PRODUCT_EVENTS=on`) con un texto de información?
7. **Qué es PrediGol.** ¿La frase «plataforma de análisis deportivo y detección de valor» y la ausencia de enlaces a operadores
   bastan para quedar fuera de la regulación de juegos de suerte y azar y de su publicidad (Coljuegos)? ¿Cambia algo si algún
   día hay enlaces a casas de apuestas?
8. **Cookies.** Hoy solo hay la cookie de sesión y, si Cloudflare activa un desafío, su cookie de seguridad. ¿Hace falta aviso o
   política de cookies aparte?
9. **Plazos de respuesta.** Los textos prometen 10 días hábiles para consultas y 15 para reclamos, ampliables. ¿Son los correctos
   y de dónde se cuentan?
10. **Menores.** Si se detecta la cuenta de un menor se cierra y se suprimen sus datos. ¿Es suficiente?

Con las respuestas, el abogado devuelve los textos revisados y tus datos de responsable (P4: nombre o razón social, domicilio,
correo de privacidad y teléfono).

## 7. Cómo se publica una versión de un texto

Lo hace la sesión de código con tu aprobación; esto es lo que pasa, para que lo sepas:

1. Se editan los textos en `backend/src/fbi/customer/texts/es/` y `en/` (siempre los dos idiomas, con las mismas secciones).
2. Se calcula la huella: `python -m scripts.legal_texts hashes --version <fecha-y-nombre>`.
3. Se añade una entrada en `texts/versions.json` con la fecha, si sigue siendo borrador, si el cambio es **material** (obliga
   a todos a aceptar de nuevo), qué cambió en los dos idiomas y la huella. Un texto nunca cambia sin una versión nueva: una
   prueba del repositorio recalcula todas las huellas y falla si no coinciden.
4. `python -m scripts.legal_texts check`, las pruebas y un PR, como cualquier cambio.
5. Cuando el abogado dé el visto bueno por escrito, la versión definitiva se publica con `draft` en `false` y los datos del
   responsable ya rellenados en `controller.json`.

## 8. Cómo se enciende la puerta

Condiciones, en este orden:

1. Los tres textos, en su versión definitiva (`draft: false`), con tus datos de responsable (P4).
2. El correo funcionando (P2 y P3), porque la invitación y la recuperación de contraseña piden aceptar los textos.
3. Una prueba en QA con `FBI_CONSENT_GATE=drafts` y una cuenta nueva: se ven las cuatro casillas obligatorias, la de
   analítica (opcional, sin marcar), y el producto se abre al aceptar las cuatro.
4. Una línea en `/etc/predigol/app.env` (fichero de seguridad: copia fechada, candado de despliegue y ventana propia):
   `FBI_CONSENT_GATE=1`, y se recrea la API. Nunca pegues claves en el chat.

**Qué verá cada lector:** al entrar, los textos nuevos y las casillas; como la versión definitiva será material, todos
deberán aceptar de nuevo. La analítica es opcional y la puerta no la espera.

**Vuelta atrás:** `FBI_CONSENT_GATE=0` y recrear la API. Lo que ya aceptaron queda guardado con su versión y su huella.

## 9. Lo que tú puedes ir haciendo

- Leer esta guía y las tres páginas legales en la app (`/legal/terms`, `/legal/privacy` y `/legal/responsible-gaming`).
- Llevar la sección 6 al abogado y pedirle tus datos de responsable.
- Decidir, con tu abogado, qué entra en la política antes de la versión definitiva (sección 5).

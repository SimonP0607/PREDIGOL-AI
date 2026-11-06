# UX-022 · Comunicados del dueño

Plan de cierre de la UX, tarea 4.3. **Una migración (0124), una plantilla de correo nueva y ningún cambio en la inteligencia.** Es
la consola donde tú escribes avisos a los lectores. Son tus palabras: nada aquí se calcula con modelos, picks ni datos de un lector.

> Estado de esta entrega: **hecho en código; no desplegado.** Hasta que se despliegue (migración 0124 y `grants.sql`), la consola
> no existe en producción. Telegram y el correo crítico necesitan además lo que dice la sección 4.

## 1. Qué puedes hacer

En la consola, **Comunicados**. Cuatro tipos cerrados: **mantenimiento**, **incidencia**, **actualización** y **comunicado general**.
No existe «promoción». Cada comunicado se escribe en español y en inglés (título de 3 a 80 caracteres, texto de 3 a 600) y tiene
fechas de inicio y fin (90 días como máximo).

Destinos, a tu elección:

| Destino | Qué hace | Condición |
| --- | --- | --- |
| **Banner** en la app | Aparece bajo el encabezado, entre las dos fechas, también en la pantalla de entrada (un mantenimiento tiene que llegar a quien no puede entrar). Cada lector puede cerrarlo; el siguiente comunicado vuelve a salir. | Ninguna |
| **Novedades** | Entra como una entrada más, la primera de la lista. | Solo el tipo *actualización* |
| **Canal de Telegram** | Un mensaje con el título y el texto en español y en inglés. | Solo si Telegram está configurado (sección 4) |
| **Correo** | Una plantilla «aviso importante» a cada lector activo cuyo correo funciona, aunque haya apagado los avisos del servicio. Un correo por lector y comunicado, nunca dos. | Solo si es **crítico** (mantenimiento o incidencia), con textos de 200 caracteres como máximo |

Todo sirve sin Telegram: si no está configurado, el banner, Novedades y el correo funcionan igual y la consola te lo dice.

## 2. Cómo se publica (doble confirmación)

1. **Borrador.** Guardas el comunicado; no lo ve nadie.
2. **Vista previa.** La consola te muestra, destino por destino, lo que saldrá (fechas del banner, el título en Novedades, el texto de
   Telegram, a cuántos lectores llegaría el correo) y te da un **código que vale 10 minutos**. Editar el borrador anula el código.
3. **Publicar.** Escribes la palabra **PUBLICAR**; el código va con ella. Sin código vigente o con otra palabra, no se publica.

**Tope diario:** 3 comunicados publicados por día (`FBI_ANNOUNCE_DAILY_CAP`). Al llegar, la consola avisa y no deja publicar más hasta el día siguiente (UTC).

**Retirar, no borrar.** Un comunicado publicado se retira (el banner y la entrada de Novedades desaparecen). Nada se borra: la base
de datos lo impide, y cada paso (creado, editado, vista previa, publicado, retirado, Telegram, correos) queda en un **registro que solo se
puede ampliar**. Si te equivocas en el texto de uno publicado: lo retiras y escribes otro.

Si Telegram falla al publicar, la publicación **no se deshace**: el banner, Novedades y el correo salen, y el registro anota que
Telegram no salió y por qué (sin el token).

## 3. Qué no hace

No toca picks, modelos, probabilidades, calibraciones, liquidación ni el histórico. No publica nada por su cuenta: toda publicación
la dispara una persona con el código y la palabra. El bot de Telegram **no conversa**: al pulsar /start saluda y da los enlaces; cualquier otra
cosa la ignora y no guarda nada de lo que le escriben.

## 4. Lo que tienes que hacer tú (no bloquea el resto)

Solo si quieres el canal de Telegram; sin esto todo lo demás funciona.

1. Crea el canal público y el bot (con @BotFather) y haz al bot **administrador** del canal.
2. En el servidor, en el archivo de entorno de la API, rellena `FBI_TELEGRAM_BOT_TOKEN` (ya existe para tus avisos), `FBI_TELEGRAM_CHANNEL_ID`
   (por ejemplo `@nombre_del_canal`) y `FBI_TELEGRAM_WEBHOOK_SECRET` (24 caracteres aleatorios o más). **Nunca los pegues en el chat.**
3. Para la bienvenida, registra el webhook del bot apuntando a `https://<tu dominio>/api/v1/telegram/webhook/<el secreto>`.
   Sin este paso el canal publica igual; solo faltaría el saludo al pulsar /start.

## 5. Para revisar después de desplegar

- Crea un borrador de tipo *general* con banner solamente, pide la vista previa, publica con la palabra y mira el banner en la app y en la pantalla de entrada; ciérralo como lector y recarga; retira el comunicado desde la consola y comprueba que desaparece y que el registro conserva los pasos.
- Un borrador de tipo *actualización* con Novedades: la entrada aparece la primera en Novedades en español y en inglés.
- Con el correo de pruebas de la cola (UX-017) puedes ver «aviso importante» antes de encender el envío real; con `FBI_EMAIL_SEND` apagado un comunicado crítico solo llena la cola.
- A 320 px el banner no debe desbordar la pantalla.

## 6. Detalles técnicos

- Migración `0124_announcements`: tablas `customer.announcements` (tipos y reglas como `CHECK`, sin borrado) y `customer.announcement_log` (solo inserción). `grants.sql` da a la API `INSERT, UPDATE` en la primera e `INSERT` en la segunda.
- Plantilla `critical_notice` (categoría servicio, crítica: no depende del interruptor del lector), con la prioridad y el tope de servicio de UX-017.
- Rutas: consola `/api/v1/admin/announcements` (borrador, edición, vista previa, publicar, retirar, registro); pública y de solo lectura `GET /api/v1/announcements/active`; el webhook del bot `POST /api/v1/telegram/webhook/{secreto}`.
- Pruebas: unitarias (reglas, código, frase, tope, Telegram falso, bot), de integración con Postgres (flujo completo, correo solo crítico y una vez por lector, direcciones rebotadas fuera, registro inmutable) y de web (banner, formulario, Novedades); e2e del banner con la respuesta de la API fijada.

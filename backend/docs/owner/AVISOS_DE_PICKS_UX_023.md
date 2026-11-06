# UX-023 · Interruptor de los avisos de picks (P14)

Plan de cierre de la UX, tarea 4.4. **Sin migración y sin tocar la inteligencia.** Es un interruptor del notificador de la app: decide
a quién se avisa, nada más.

> Estado de esta entrega: **hecho en código; no desplegado.** Hasta que se despliegue y tú lo pongas en `off`, todo sigue como hoy.

## Para qué

Los avisos de la app a tu Telegram (tickets, vencimientos de membresía, presupuesto de IA, trabajos que fallan, la cola de correos) están
bloqueados desde S3 (P14): el mismo notificador apunta **un aviso por cada pick en sombra y otro por cada liquidación**, y en un mes son
cientos de miles. Con el token puesto, tu chat se inundaría.

## Qué hace

`FBI_NOTIFY_PICKS=off` en el entorno del worker:

- No apunta los avisos de picks en sombra ni de liquidación (tampoco consulta los picks para eso).
- No envía lo que ya esté apuntado y en cola sobre picks. **No lo borra ni lo cambia**: queda en cola tal cual.
- Los demás avisos (tickets, vencimientos, presupuesto, trabajos que fallan, trabajador silencioso, cola de correos, conteo de la mañana) siguen igual.

Por defecto está `on`: hasta que tú lo cambies, nada se comporta distinto.

No lo lee ningún pick, modelo, probabilidad, estado, liquidación ni histórico. Los picks se siguen creando y liquidando igual y la app los muestra igual.

## Lo que tienes que hacer tú (P14)

En este orden, en el servidor y sin pegar nada en el chat:

1. Poner `FBI_NOTIFY_PICKS=off` en el entorno del worker y reiniciarlo.
2. Después, rellenar `FBI_TELEGRAM_BOT_TOKEN` y `FBI_TELEGRAM_CHAT_ID`.

Volver a `on` más adelante enviaría a tu chat lo que haya quedado en cola de picks y volvería a apuntar los de los últimos 7 días: no lo hagas con el token puesto
salvo que quieras ese volumen.

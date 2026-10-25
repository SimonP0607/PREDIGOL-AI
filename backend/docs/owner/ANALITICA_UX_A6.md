# A6 · Analítica de producto

Plan Maestro UX, fase A6 (migración **0097**; el plan la numeró 0096, que tomó A5). La medición nace **apagada**
(`FBI_PRODUCT_EVENTS`): hasta que tú decidas, no se guarda ningún evento.

## 1. Qué se mide y qué no

- **35 eventos de un catálogo cerrado** (sección 39 del plan), cada uno atado a una decisión de producto: entrada,
  uso, picks, parlays, noticias, avisos y PWA, soporte y opinión, membresía y otros. El catálogo está en
  `backend/src/fbi/customer/events_catalog.json` y es el mismo en la web (`web/src/lib/track.ts`); una prueba comprueba
  que coinciden. Cada evento se empieza a enviar cuando existe su pantalla: hoy, el inicio de sesión (clase de
  dispositivo, ancho, PWA o navegador, idioma), el partido abierto (y desde dónde), sus secciones, el término del
  glosario explicado, el pick guardado o quitado, la pierna añadida al parlay, el parlay creado, el constructor, los
  errores mostrados (código y estado) y los avisos por correo encendidos o apagados. Los de activación, membresía y
  tickets los registrará el servidor en A7, A8 y A14.
- **Lo que nunca se guarda:** IP, correo, nombre, el contenido de un formulario, texto libre, la sesión grabada. Una
  propiedad solo puede ser una opción de una lista, un número acotado, un sí o no, un identificador corto o un id de
  partido o pick; cualquier otra cosa rechaza el envío entero.
- **Quién:** un seudónimo (una huella HMAC del id de la cuenta con su propia clave, distinta de la de Sentry); la tabla
  no se puede unir a las cuentas sin la clave. **Tú (SUPER_ADMIN) y la cuenta sintética nunca se miden.**
- **Dónde:** en PostgreSQL, sin terceros. El worker de PrediGol Intelligence no puede leer estas tablas, y ningún evento
  entra en un modelo, en la capa de decisión ni en el paquete de la IA.

## 2. Qué ves

**Consola → Producto** (`/admin/product`): si la medición está encendida y en qué modo, el estado de la purga, y con
**20 lectores activos en 30 días o más** (antes, solo cuántos hay): activos hoy, en 7 y en 30 días, días activos por
semana, errores por lector activo, el embudo de activación (cuenta activada, bienvenida empezada y completada, primer
valor), sesiones por dispositivo (alimenta el trigger C5 de tabletas) y el uso de cada evento en 7 y 30 días. DAU/MAU
aparece desde 100 lectores. No se optimizan el tiempo en la app, los picks guardados por lector ni los avisos enviados.

## 3. Conservación y purga

- Crudos: **90 días**; agregados diarios por lector seudónimo (`customer.activity_daily`): **13 meses**. El messenger
  recalcula cada 5 minutos el agregado de hoy y de ayer (siempre cuadra con los crudos).
- La purga nace **en ensayo** (`FBI_EVENTS_PURGE=dry`): cada ciclo cuenta lo que pasaría de su plazo y lo deja en el
  registro de trabajos, sin borrar nada. **Borrar es decisión tuya:** cuando las primeras filas cumplan 90 días (a
  finales de enero de 2027 si se enciende ahora) te pediré el visto bueno para `FBI_EVENTS_PURGE=on`.

## 4. Cómo se enciende (cuando decidas)

1. Base legal: la finalidad «analítica de producto» está declarada en la política de tratamiento (borrador de A4). Si el
   abogado (P5) pide una casilla aparte, el modo es `FBI_PRODUCT_EVENTS=consent` (solo quien la marque); si no, `on`.
2. Una línea en `/etc/predigol/app.env` (fichero de seguridad: copia fechada, candado de despliegue, ventana propia) y se
   recrea la API.
3. Comprobación: la página Producto pasa de «Medición apagada» a «encendida»; con menos de 20 lectores dice cuántos hay.

## 5. Vuelta atrás

`FBI_PRODUCT_EVENTS=0` y recrear la API: no se guarda nada más (lo guardado se queda hasta que tú decidas borrarlo). La
migración 0097 solo se deshace con las tablas vacías.

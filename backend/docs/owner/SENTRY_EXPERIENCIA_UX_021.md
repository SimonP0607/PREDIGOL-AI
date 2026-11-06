# UX-021 · Sentry de experiencia

Plan de cierre de la UX, tarea 5.3. **Sin migración, sin interruptor nuevo, sin IA.** Sigue encendiéndose solo con el proyecto web de Sentry que ya existe (P1) y por el mismo túnel: el navegador nunca habla con Sentry, y todo evento pasa por el filtro del servidor.

## Qué se mide ahora

- **Tiempos de carga (LCP, INP y CLS):** en una muestra del 3 % de las visitas, una sola lectura por visita al cerrar o ocultar la página. Lleva los tres números, la ruta (sin consulta), la peor de las calificaciones («buena», «mejorable», «mala» con las líneas de las métricas web), el ancho de pantalla y si es la app instalada. Nada de la persona: el servidor la reconstruye solo con esos campos y descarta el resto (usuario, rastro, extras).
- **Tope propio:** las lecturas tienen su cuota en el túnel, aparte de la de errores y más pequeña: `FBI_MONITORING_VITALS_HOURLY_CAP` (2 por hora y proceso) y `FBI_MONITORING_VITALS_DAILY_CAP` (6 por día y proceso). Pasada la cuota se descartan sin error y **nunca tocan el presupuesto de errores** (el plan gratuito son 5.000 al mes).
- **Módulos que ya no existen tras un despliegue** («Failed to fetch dynamically imported module»): se reporta y la página se recarga sola una vez; si la recarga no lo arregla, aparece un aviso «Hay una versión nueva de PrediGol. Recarga para seguir.» con el botón. La pantalla de error de la página también ofrece «Recargar la página» en vez de «Reintentar» cuando es este caso.
- **Errores de API que el lector ve:** al mostrarse un error con su referencia (`request_id`) se reporta una vez por referencia (los de servidor 5xx ya se reportaban al llegar; 401, 403 y 404 son respuestas esperadas y no se reportan). Con esa referencia se busca la línea del servidor.
- **Service worker:** fallos al registrarlo, al instalar una versión nueva (queda «redundant») y al comprobar actualizaciones: solo se dice el paso, no el texto del worker.

## Qué no cambia

Nunca datos personales (ni correo, ni picks, ni lo que se teclea o se pulsa). Sin Sentry encendido, nada de esto se envía ni se descarga.

## Tareas del dueño

- **P1:** el proyecto web de Sentry (ya configurado si recibes los errores de la web); no hace falta nada más para los tiempos de carga. Si quieres más o menos lecturas, las dos variables de arriba.

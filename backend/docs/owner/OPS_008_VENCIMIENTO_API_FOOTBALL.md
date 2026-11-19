# OPS-008 · Aviso de vencimiento de la suscripción de API-Football

Fecha: 19 nov 2026. Tarea PM-01-01 del Plan Maestro PM (decisión DM-01). Sin migración, sin cambios en la web y sin efecto en el lector.

## Por qué

El plan de API-Football es de **prepago y no se renueva solo**. Cuando vence, la cuenta baja al plan gratuito (100 peticiones al día) y la
ingesta se para, como el 29-oct-2026. El 19-nov-2026 a las 22:08 UTC, `GET /status` decía: plan Ultra, activo, **fin el
2026-11-29 a las 21:45:57 UTC**. Nada avisaba de esa fecha.

## Qué hace

La comprobación de salud del servidor (`bin/healthcheck.sh`, cada 5 minutos) mira cuándo vence la suscripción y avisa por el **mismo
canal de siempre** (el bot de avisos de Telegram, con su número de incidente `INC-AAAA-NNN` en el registro de incidentes):

| Situación | Aviso | Cuántos mensajes |
| --- | --- | --- |
| Quedan **menos de 10 días** | `provider.subscription` SEV2: «la suscripción de API-Football vence en N días y H h (fin … UTC): renueva el plan en el panel del proveedor» | **Uno** al abrirse. Los días bajan en el texto sin mensajes nuevos |
| La suscripción **no está activa**, es el plan gratuito o la fecha de fin **ya pasó** | `provider.subscription` SEV1: «… no está activa o ya venció …: la ingesta cae a 100 peticiones al día» | Uno al pasar a SEV1 y un recordatorio cada hora mientras dure (como todo SEV1) |
| La fecha de fin se aleja a más de 10 días (renovado) | El aviso se cierra | Un «recuperado» |

Cómo lo sabe: el worker pregunta `GET /status` (no gasta cuota del proveedor; es 1 petición de nuestro presupuesto diario) **como mucho
cada 6 horas** (`scripts/provider_subscription.py`). Guarda una línea en `/srv/predigol/state/provider-subscription.json` con el plan, si
está activa, la fecha de fin y los segundos que faltan; **nunca** el nombre ni el correo de la cuenta, ni la clave. La respuesta tampoco se
escribe en el almacén RAW. Cada pasada de 5 minutos juzga esa línea con el reloj, sin preguntar otra vez.

Si el worker no responde (un despliegue, el proveedor caído), se sigue juzgando la última lectura. Si no hay ninguna, o tiene más de 2 días,
el aviso abierto se queda como está (no se cierra solo) y el veredicto de salud muestra un `warning`.

**Hoy, con el fin el 29-nov, el aviso SEV2 debe abrirse en la primera pasada tras el despliegue.** Es lo esperado.

## Qué te toca

1. Renovar el plan en el panel de API-Football (DM-01).
2. Nada más: en un máximo de 6 horas el servidor lee la fecha nueva y cierra el aviso con un «recuperado». Si quieres que la lea ya:
   `rm /srv/predigol/state/provider-subscription.json` en el servidor; la siguiente pasada (5 minutos) pregunta de nuevo.

Si renovaste y la fecha de `/status` **no cambia**, puede que el prepago nuevo empiece cuando acabe el periodo actual: el aviso seguirá
abierto (sin repetir mensajes) hasta que el proveedor muestre la fecha nueva. Si al 29-nov a las 21:45 UTC no la muestra, el aviso pasa a
SEV1: escribe al proveedor.

## Ver el estado

* La línea guardada: `jq . /srv/predigol/state/provider-subscription.json`
* El aviso abierto: `predigolctl incident list`
* El mismo dato a mano, desde el worker: `docker exec predigol-worker python -m scripts.capture_odds status` (línea «subscription active»)

## Interruptor y vuelta atrás

* **Apagar el aviso:** `PREDIGOL_PROVIDER_SUB_ALERT=0` en `/etc/predigol/predigol.env` y después `predigolctl config-baseline` (cambiar ese
  archivo es un cambio de configuración). En la pasada siguiente el aviso abierto se cierra con un «recuperado»: es el apagado, no la
  renovación. Sin la variable, o con cualquier otro valor, está encendido.
* **Margen:** `PROVIDER_SUB_WARN_DAYS` (10 por defecto) en el mismo archivo.
* **Revertir el código:** PR de `revert`. No hay datos que deshacer: el archivo de estado se puede borrar.

## Simulacro

`provider.subscription` está en la tabla del simulacro de avisos (`docs/owner/SIMULACROS_AVISOS.md`, Tabla A, sin número del catálogo):
`predigolctl alert-drill provider.subscription SEV2 --dry-run` muestra el mensaje sin enviarlo.

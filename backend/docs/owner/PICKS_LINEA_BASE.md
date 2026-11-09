# PICKS: línea base y liquidación recalculada (plan PICKS, F1 y F6)

Dos lecturas de solo lectura para medir el punto de partida del módulo PICKS y comprobar lo ya liquidado. Ninguna escribe en la base: la conexión la abre el servidor en modo `READ ONLY` y cualquier `INSERT` o `UPDATE` falla. No llaman al proveedor.

Las cifras de este documento se rellenan **con la corrida en producción**. Hasta entonces, las secciones de resultados dicen «pendiente» y no se adelanta ningún número.

## Cómo se corren

En el servidor, dentro del contenedor del worker, como las demás herramientas de las guías. Usa la conexión del worker, pero cada herramienta la abre en solo lectura:

```
docker exec -w /app predigol-worker python -m scripts.audit_picks_module --hours 24                  # línea base (F1)
docker exec -w /app predigol-worker python -m scripts.audit_picks_module --hours 24 --json > picks_f1.json
docker exec -w /app predigol-worker python -m scripts.audit_settlement --days 30                     # liquidación recalculada (F6)
docker exec -w /app predigol-worker python -m scripts.audit_settlement --days 30 --json > picks_f6.json
```

El `> archivo.json` guarda el resultado en la carpeta del servidor desde la que se lanza, fuera del contenedor. Las herramientas existen en el servidor desde el despliegue que incluye BE-007.

`audit_settlement` termina con código 1 si encuentra un cambio sin explicar o un día cuyo resumen no cuadra, y con 0 si todo cuadra.

## Llave de solo lectura para las auditorías

Para que Claude (u otra persona) lance estas herramientas sin tener la llave de root, hay una llave aparte que solo puede hacer eso. Su orden forzada, `predigol-audits` (en el repositorio: `backend/deploy/release/templates/gate/predigol-audits`), acepta solo:

```
audit_picks_module [--hours N] [--json]              N de 1 a 168
audit_settlement [--days N] [--no-timing] [--json]   N de 1 a 90
research_picks_calibration [--days N] [--json]       N de 1 a 400
help
```

Cualquier otra cosa se rechaza: una consola, otro script, `;`, `|`, `$( )`, una ruta o una opción que la herramienta no tiene. Cada llamada, permitida o rechazada, queda en `/var/log/predigol-audits.log` con la dirección del cliente. `restrict` quita además la terminal, los reenvíos y el agente.

**Instalarla (una vez, como root en el servidor):**

1. Copiar la orden forzada: `install -m 755 -o root -g root predigol-audits /usr/local/sbin/predigol-audits`.
2. Añadir a `/root/.ssh/authorized_keys` una línea con la llave **pública** nueva (nunca la privada):
   `command="/usr/local/sbin/predigol-audits",restrict ssh-ed25519 AAAA… predigol-audits`
3. Probar desde el equipo que tiene la llave: `ssh predigol-audits help` debe listar las tres herramientas, y `ssh predigol-audits id` debe responder `refused`.

**Quitarla:** borrar esa línea de `authorized_keys`. La llave de root y la del despliegue no se tocan.

## Qué mide `audit_picks_module` (F1)

Llama a los mismos servicios que responde la API en la vista previa del dueño (`picks_board`, `started_board` y `daily_board`), así que cuenta lo mismo que se ve en pantalla:

| Hallazgo | Qué cuenta |
| --- | --- |
| Motor | Precios evaluados, picks en sombra, calificados, publicados (deben ser 0) y liquidados |
| S1 | Tarjetas que hoy no pasan la regla de valor, y por qué (precio viejo, partido no programado, pocas casas, VE no positivo) |
| S2 | Tarjetas que repiten la misma idea en otra línea (mismo partido, mercado y lado); tarjetas por partido: mediana y máximo |
| S3 | Tarjetas con cuota por encima de 3,00 |
| C4 | En goles, «menos de» frente a «más de»; en ambos marcan, «no» frente a «sí» |
| C5 | Edad del precio de cada tarjeta: menos de 1 h, de 1 a 3 h, más de 3 h, sin precio; y la del más nuevo |
| L2 | «Ya empezaron hoy»: candidatos, partidos y el máximo en un partido |
| D1 | Los dos «picks del día»: el de la página (con su regla y sus estados) e Intelligence (último estado de cada selección del día de Bogotá y su set) |

## Qué mide `audit_settlement` (F6)

Para cada registro liquidado sobre un marcador de los partidos de los últimos N días (picks en sombra, picks del día, patas de las combinadas de PrediGol, picks y combinadas de los lectores), lo vuelve a liquidar con las mismas reglas (`settle-v4`) y la misma lectura que la reliquidación, y lo compara con lo guardado:

| Resultado | Significado |
| --- | --- |
| Igual | Lo guardado es lo que dan hoy las reglas |
| Retenido | Una diferencia que las reglas dejan a una persona: un nulo por regla, o un partido que ya no se liquida |
| Cambio con corrección registrada | El resultado del partido se corrigió después de liquidarse el registro y la reliquidación aún no lo aplicó. Una corrección anterior a la liquidación no explica nada: ya debía estar en lo guardado |
| **Sin explicar** | El criterio del plan es **cero** |

Después comprueba en los datos que el resumen de cada día cuadra (ganados + perdidos + nulos o devueltos + por jugar = tamaño del set) y mide cuánto tardan las dos consultas de la consola de rendimiento (R1). La base ya impide un estado fuera de esa lista, así que hoy esa suma no puede fallar: queda como guarda por si algún día se añade un estado. Lo que sí puede fallar es la liquidación de cada pick del día, y esa se comprueba arriba, registro a registro.

Si aparece algo sin explicar, **no se corrige desde aquí**: se usa la reliquidación (`docker exec -w /app predigol-worker python -m scripts.resettle`), que deja rastro, con tu visto bueno.

## Resultados

| Lectura | Fecha | Resultado |
| --- | --- | --- |
| Línea base (F1) | pendiente | pendiente de la corrida en producción |
| Liquidación, 30 días (F6) | pendiente | pendiente de la corrida en producción |
| Consola de rendimiento (R1) | pendiente | pendiente de la corrida en producción |

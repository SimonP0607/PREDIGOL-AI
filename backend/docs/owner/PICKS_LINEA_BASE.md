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

Corrida del 9-nov-2026, 00:50 UTC (19:50 del 8-nov en Bogotá), con la llave de solo lectura (SEG-002).

### Línea base (F1), ventana de 24 h

| Hallazgo | Cifra |
| --- | --- |
| Motor | 2.330.675 precios evaluados · 337.227 picks en sombra · 0 calificados · 0 publicados · 335.103 liquidados |
| Tablero | 155 tarjetas de 15 partidos (de noche: menos partidos que en la lectura del 7-nov) |
| S1 fuera de la regla ahora | 91 (59 %): 82 por precio viejo y 9 por VE no positivo |
| S2 misma idea en otra línea | 107 (69 %); por partido, mediana 10 y máximo 24 |
| S3 por encima de 3,00 | 55 (35 %) |
| C4 dirección | goles: 42 «menos de» frente a 9 «más de» (82 %); ambos marcan: 6 «no» frente a 0 «sí» |
| C5 edad del precio | menos de 1 h: 20 · de 1 a 3 h: 53 · más de 3 h: 82 (53 %) · el más nuevo, hace 17 min |
| L2 «Ya empezaron» | 2.701 candidatos de 206 partidos; hasta 22 en uno |
| D1 picks del día de la página | `daily-set-v5`: 5 picks del 8-nov, los 5 perdidos |
| D1 Intelligence (día de Bogotá) | 2.722 selecciones: 0 aprobadas, 40 en cautela, 6 en investigación, 2.676 rechazadas; su set del día, vacío |

### Liquidación recalculada (F6), 30 días

3.804 partidos (28 con correcciones registradas del resultado).

| Registro | Examinados | Iguales | Retenidos | Con corrección | **Sin explicar** |
| --- | --- | --- | --- | --- | --- |
| Picks en sombra | 313.714 | 312.612 | 946 (nulos por regla que se mantienen) | 0 | **156** |
| Picks del día | 146 | 145 | 0 | 0 | **1** |
| Patas de combinadas | 243 | 243 | 0 | 0 | 0 |
| Picks de lectores | 0 | 0 | 0 | 0 | 0 |
| Patas de combinadas de lectores | 52 | 52 | 0 | 0 | 0 |

Los 30 sets del día cuadran.

**El criterio (0 sin explicar) no se cumple.** 157 registros están liquidados con un marcador distinto del que hoy tiene su partido, y ninguna corrección registrada lo explica:

- 101 son de partidos del 10 al 12 de octubre. Los 20 que muestra la herramienta son todos de Gwangju FC 4–3 Ulsan Hyundai (K League 1, 11-oct, partido 21562): están liquidados como si hubiera acabado en empate con dos goles o menos («empate» ganado, «menos de 2,5» ganado, «local» perdido). También es de ese partido el pick del día n.º 2 del set 8, guardado como perdido cuando hoy sería ganado.
- 55 son de partidos de los últimos 27 días; entre ellos, los partidos 21497 y 21389.

**Causa (9-nov, solo lectura).** Todos son de partidos anteriores al 24-oct, es decir, de antes de que existiera el rastro de correcciones (migración 0080, 23-oct): hasta entonces el resultado se sobrescribía en el sitio y la liquidación corría con la primera lectura de «final», sin dejar nada en `core.fixture_result_revisions`. La misma auditoría con `--days 16` da **0 sin explicar** sobre 181.164 picks, 76 picks del día y 122 patas de combinadas (2.198 partidos, 22 con correcciones registradas), y los sets del día cuadran. No es un defecto nuevo ni sigue creciendo.

Lo que queda es reliquidar esos 157 con `scripts.resettle --all`, que deja rastro, con el visto bueno del dueño (primero el simulacro, sin `--apply`, y luego `--apply --by <nombre>`).

### Consola de rendimiento (R1)

Totales: 3,3 s · porciones: 7,0 s, corriendo a la vez que las otras dos auditorías. La consola responde desde BE-006, y el navegador la midió en 11,2 s el 8-nov.

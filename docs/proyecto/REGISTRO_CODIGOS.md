# Registro de códigos

*Fuente de verdad de los códigos `ÁREA-NNN` (ver `CONVENCIONES_GITHUB.md`). **Se añade la fila en el mismo PR que usa el código.** El siguiente número libre de cada área está al pie.*

Estados: `abierto` · `en curso` · `hecho` · `desplegado` · `descartado`.

## CI — integración y despliegue continuos

| Código | Qué es | Estado | PR | Fase o nombre anterior |
| --- | --- | --- | --- | --- |
| CI-001 | CI en GitHub Actions: backend, web, seguridad (gitleaks) y Dependabot | hecho | #1 (cerrado), #2 | C1 |
| CI-002 | Kit de lanzamiento unificado (`backend/deploy/release/`) y su corrección de partes | desplegado | #2, #11 | C3 |
| CI-003 | Unión de las cuatro líneas (producción, F11, CI) en `main` y su despliegue | desplegado | #2 | unif (2-nov-2026) |
| CI-004 | Despliegue desde GitHub: puerta del servidor, llave restringida y doble aprobación | hecho (falta ver un despliegue completo con éxito desde GitHub) | #12, #13, #14 | C4 |
| CI-005 | Convenciones de GitHub: códigos, plantillas, validador y etiquetas | hecho (3-nov-2026) | #16 | — |
| CI-006 | Las pruebas de copia usan el cliente de PostgreSQL 16 en el CI (la imagen de GitHub trajo un `pg_dump` más nuevo) | hecho (3-nov-2026) | #17 | — |
| CI-007 | Despliegue continuo: cada fusión en `main` con el CI verde se despliega sola (interruptor `AUTO_DEPLOY`, entorno `production-auto`, comprobación de linaje) | en curso | #24 | — |
| CI-008 | El kit de lanzamiento toma la cabeza de migraciones de la cadena (`down_revision`), no el número más alto: la verificación de `ux-001` marcó «NOT OK» por comparar con 0119 cuando la cabeza real era 0106 | en curso | este PR | — |
| CI-009 | El CI vuelve a pasar con ruff 0.17.4: se junta un `if` anidado del revisor posterior en una sola condición (misma lógica, ahora con prueba) | en curso | este PR | — |

## IA — capa de inteligencia artificial

| Código | Qué es | Estado | PR | Fase o nombre anterior |
| --- | --- | --- | --- | --- |
| IA-001 a IA-004 | Fases 1 a 4 del plan de IA | desplegado | (fuera de `main` hasta la unión) | ia-p01 a ia-p04 |
| IA-005 | El sondeo de lotes no abandona lo que un ciclo en marcha aún va a enviar | desplegado el 3-nov-2026 (en `main` por #15) | #15 | ia-p05 |
| IA-006 | Fases 3 y 3b de IA (agentes, orquestador, brazos en sombra, migración 0119) incorporadas a `main` tal como corren en producción | desplegado el 3-nov-2026 (en `main` por este PR) | #20 | ia-p3, ia-p3b (y los interruptores ia-switch-v2/v3) |
| IA-007 | Agente de Estadísticas en sombra para córners y tarjetas (interruptor apagado por defecto, sin migración) | en curso | este PR | ia-p4 (fase 4 del plan de IA) |
| IA-008 | Revisor posterior (`pmr-v1`) y Analista de aprendizaje (`la-v1`) en sombra, con la atribución mecánica `attr-v1` y la migración 0120 (interruptores apagados por defecto) | en curso | este PR | ia-p5 (fase 5 del plan de IA) |

## UX — experiencia de usuario y diseño de la web

| Código | Qué es | Estado | PR | Fase o nombre anterior |
| --- | --- | --- | --- | --- |
| UX-001 | Plan maestro de UX completo, de A3 a B11: Inicio, Análisis y Postpartido, Mis picks, avisos y dispositivos, membresía, ficha del cliente y ciclo de vida (migraciones 0095 a 0106, que cuelgan de la 0119). A1 y A2 ya corrían en producción | desplegado el 4-nov-2026 (release `ux-001`, backend `0306f006e631`, web `32dce8b44177`, base en 0106) | #21 | A3 a B11 |
| UX-002 | «Solo verde + pronóstico aparte» (decisión del dueño): los lectores solo ven picks en «Recomendado»; «Con cautela» y «No recomendado» se ocultan en listas, Top 5, partido, análisis, picks del día y parlays (la vista previa del dueño no cambia; el pronóstico sigue visible). Sin migración | en curso | este PR | B3 (estado visible de un pick) |

## BE — backend

| Código | Qué es | Estado | PR | Fase o nombre anterior |
| --- | --- | --- | --- | --- |
| BE-001 | La prueba del seudónimo de Sentry ya no falla al azar (una vez de cada catorce) | en curso | este PR | — |

## Otras áreas

Todavía sin códigos asignados en el resto. Lo anterior al 3-nov-2026 se identifica por su fase: F11 (familias), S1 a S4 (seguridad), UX A1 y siguientes.

## Siguiente número libre

CI-010 · SEG-001 · IA-009 · UX-003 · BE-002 · FE-001 · OPS-001 · DOC-001

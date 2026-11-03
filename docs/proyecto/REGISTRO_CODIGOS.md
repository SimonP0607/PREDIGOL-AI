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

## IA — capa de inteligencia artificial

| Código | Qué es | Estado | PR | Fase o nombre anterior |
| --- | --- | --- | --- | --- |
| IA-001 a IA-004 | Fases 1 a 4 del plan de IA | desplegado | (fuera de `main` hasta la unión) | ia-p01 a ia-p04 |
| IA-005 | El sondeo de lotes no abandona lo que un ciclo en marcha aún va a enviar | desplegado el 3-nov-2026 (en `main` por #15) | #15 | ia-p05 |

## BE — backend

| Código | Qué es | Estado | PR | Fase o nombre anterior |
| --- | --- | --- | --- | --- |
| BE-001 | La prueba del seudónimo de Sentry ya no falla al azar (una vez de cada catorce) | en curso | este PR | — |

## Otras áreas

Todavía sin códigos asignados en el resto. Lo anterior al 3-nov-2026 se identifica por su fase: F11 (familias), S1 a S4 (seguridad), UX A1 y siguientes.

## Siguiente número libre

CI-007 · SEG-001 · IA-006 · UX-001 · BE-002 · FE-001 · OPS-001 · DOC-001

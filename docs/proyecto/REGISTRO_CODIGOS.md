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
| CI-010 | El despliegue automático (CI-007) no llegaba al servidor: GitHub no podía leer la llave SSH del entorno `production-auto` («error in libcrypto»). `ci_ssh_setup.sh` ahora endereza la llave (BOM, CRLF, un solo renglón, tabuladores, sangrías) y, si aun así no carga, se detiene ahí diciendo qué le pasa (cabecera, pie, renglones) sin imprimirla; con pruebas sobre una llave real. No toca la inteligencia ni el servidor | en curso | este PR | — |

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
| UX-003 | Fase 0 del plan de cierre de la UX: el mapa de interruptores de la capa de usuario con su prueba (plantilla del servidor, mapa del dueño y código dicen lo mismo), el inventario de secretos al día (DSN de la web y contraseña del recorrido sintético), la novedad de «Explícame» y la limpieza de dos componentes y dos dependencias sin uso | en curso | este PR | plan de cierre UX, fase 0 |
| UX-004 | Membresía con el precio y la prueba que decidió el dueño (5-nov-2026): 150.000 COP o 50 USD al mes (a elección del lector, configurables con `FBI_MEMBERSHIP_PRICE_COP` y `FBI_MEMBERSHIP_PRICE_USD`; `0` esconde una moneda), prueba de 20 días por defecto (de 7 a 20, también al invitar) y el bloque «El plan» en Perfil → Membresía. Sin migración; no toca la inteligencia ni la puerta `FBI_MEMBERSHIP_ENFORCE` | en curso | este PR | — |
| UX-005 | Cupones y descuento por fidelidad de la membresía (decisión del dueño del 5-nov-2026): el dueño crea cupones cuando quiera (código, porcentaje, nota, último día y cupos; los apaga, nunca los borra), el lector guarda uno con su código en la sección Membresía del perfil, y quien lleva más de dos meses pagados tiene 20% en cada renovación. No se suman: se aplica el mayor. Sin cobro automático: el descuento lo registra el dueño con el pago. Migración 0121 (`customer.coupons`, `customer.coupon_redemptions` y tres columnas de `customer.payments`); no toca la inteligencia | en curso | este PR | — |
| UX-006 | «Cómo funciona PrediGol» (plan de cierre UX, 1.6): la página `/help/how-it-works` con 11 tarjetas (Inicio, Partidos, Picks, Parlays, Cuotas, Mis picks, Favoritos, Análisis de un partido, Probabilidades, Mercados y Estados de los picks), cada una con qué es, cómo se lee, un ejemplo y «Verlo en la app»; el glosario suma los cinco mercados y los estados de un pick; el recorrido pasa a 5 pasos (con los parlays) y su paso de picks dice lo que el lector ve de verdad; enlaces desde Ayuda, Perfil, la bienvenida y el último paso del recorrido. Solo web: no toca la inteligencia ni el backend | en curso | este PR | — |
| UX-007 | Textos legales `2026-11-05-draft3` (plan de cierre UX, 1.1): términos y política dicen igual qué es PrediGol (plataforma de análisis deportivo y detección de valor; no garantiza resultados ni beneficios; no es una casa de apuestas ni recibe dinero de apuestas; solo +18), la membresía deja de ser un hueco (prueba sin tarjeta, precio visible en el perfil, pago a mano, cupones y descuentos con sus condiciones) y la política nombra los datos de membresía y la cuota que el lector anota; el aviso del pie, la descripción de la app, la bienvenida y el bloque «El plan» dicen la misma frase. Siguen en borrador pendiente del abogado (P5): la puerta de consentimientos sigue apagada. No toca la inteligencia | en curso | este PR | — |
| UX-010 | Transparencia completa (plan de cierre 1.5): la lista de picks publicados uno a uno con la cuota y la probabilidad con que se congelaron y su resultado (`GET /transparency/picks`, de 20 en 20), el bloque de parlays, «Qué es un pick», «Cómo leer probabilidades y cuotas», el historial de cambios (Novedades y definiciones con su fecha) y el aviso de cero picks con los días sin picks; `transparency_check` ampliado. Sin migración; no toca la inteligencia ni la regla de «solo verde» | en curso | este PR | plan de cierre UX, 1.5 |
| UX-011 | Puntos clave, «Por qué hay valor» y factores en la lectura de un partido (plan de cierre UX, 2.1): tres apartados nuevos de la lectura estructurada, escritos con lo que ya está guardado, sin IA y sin migración. «Por qué hay valor» solo existe si PrediGol publicó un pick visible para el lector (probabilidad de PrediGol frente a la del mercado, cuota frente a la cuota justa y a la cuota según PrediGol); el Resumen del partido los muestra y Análisis sigue con sus seis apartados. No cambia picks, probabilidades ni umbrales; la narrativa de A11 no los lee (`backend/docs/owner/LECTURA_VALOR_UX_011.md`) | en curso | este PR | — |

## BE — backend

| Código | Qué es | Estado | PR | Fase o nombre anterior |
| --- | --- | --- | --- | --- |
| BE-001 | La prueba del seudónimo de Sentry ya no falla al azar (una vez de cada catorce) | en curso | este PR | — |

## Otras áreas

Todavía sin códigos asignados en el resto. Lo anterior al 3-nov-2026 se identifica por su fase: F11 (familias), S1 a S4 (seguridad), UX A1 y siguientes.

## Siguiente número libre

CI-011 · SEG-001 · IA-009 · UX-012 · BE-002 · FE-001 · OPS-001 · DOC-001

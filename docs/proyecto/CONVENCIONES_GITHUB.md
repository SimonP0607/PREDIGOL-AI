# Convenciones de GitHub de PrediGol

*Vigentes desde el 3-nov-2026 (código CI-005). Todo en español, salvo el tipo técnico (`feat`, `fix`…), que es el estándar internacional.*

La idea es una sola: **cada cosa que entra en el proyecto tiene un código, y ese código aparece en el mismo sitio siempre** (rama, título del PR, commits, etiquetas, lanzamiento y registro). Así, dado un código, se encuentra todo lo demás, y dado un cambio, se sabe de qué trata sin abrirlo.

## 1. El código: ÁREA-NNN

| Área | Qué cubre |
| --- | --- |
| `CI` | Integración y despliegue continuos: GitHub Actions, kit de lanzamiento, convenciones de GitHub |
| `SEG` | Seguridad: accesos, secretos, copias, alertas, respuesta a incidentes |
| `IA` | La capa de inteligencia artificial (lotes, ciclos, presupuestos, agentes) |
| `UX` | Experiencia de usuario y diseño de la web |
| `BE` | Backend: API, datos, modelos, migraciones, trabajos programados |
| `FE` | Web (frontend) que no es diseño: rutas, componentes, rendimiento |
| `OPS` | El servidor y su operación: disco, contenedores, monitoreo, temporizadores |
| `DOC` | Documentación y planes sin cambio de código |

- Tres dígitos, desde `001` en cada área, sin saltos ni reutilización: `IA-005`, `CI-012`.
- **Se pide el siguiente número en `docs/proyecto/REGISTRO_CODIGOS.md`** (se añade la fila en el mismo PR). Un código identifica **un cambio con un propósito**; si aparece trabajo distinto, es otro código.
- Las fases de los planes siguen existiendo (F11, C4, S2, `ia-p05`…); el registro dice con qué código se corresponden. Lo anterior al 3-nov-2026 se identifica por su fase.

## 2. Rama

`<tipo>/<CÓDIGO>-<resumen-en-minúsculas-con-guiones>`

Ejemplos: `fix/IA-005-sondeo-lotes-sin-abandonar`, `feat/CI-004-despliegue-desde-github`, `docs/DOC-003-guia-incidentes`.

Entre 3 y 50 caracteres de resumen. Las ramas de Dependabot (`dependabot/…`) quedan exentas. La rama se borra sola al fusionar.

## 3. Título del PR (y del commit que entra en `main`)

`<tipo>(<CÓDIGO>): <resumen en español, sin punto final>`

- **Tipos:** `feat` (algo nuevo), `fix` (corrige un fallo), `docs`, `test`, `refactor`, `perf`, `ci` (los flujos de GitHub), `build`, `chore` (mantenimiento), `revert`.
- El resumen dice **qué cambia para quien lo lea**, no cómo: «el sondeo de lotes no abandona lo que un ciclo aún va a enviar», no «cambia batch.py».
- Entre 15 y 100 caracteres en total. Un solo código por título. El tipo va en minúscula.
- Los PR de Dependabot usan `chore(deps): …` y quedan exentos.
- Un cambio que **no lleva despliegue** lo dice en la sección «Despliegue» de la descripción.

Ejemplos buenos:

- `feat(CI-004): botón de despliegue desde GitHub con llave restringida y doble aprobación`
- `fix(IA-005): el sondeo de lotes no abandona lo que un ciclo en marcha aún va a enviar`
- `docs(DOC-003): guía de respuesta a incidentes de la base de datos`

El validador rechaza, por ejemplo: `Update stuff`, `C4: arreglo`, `fix: cosas` (sin código), `fix(IA-5): …` (código mal formado), `Feat(CI-001): …` (el tipo va en minúscula) y un título que termina en punto.

## 4. Descripción del PR

La plantilla (`.github/pull_request_template.md`) trae las secciones **Resumen**, **Qué cambia**, **Por qué**, **Cómo se probó**, **Riesgo y vuelta atrás**, **Despliegue** y **Códigos**. Se rellenan todas; lo que no aplique se escribe «No aplica». El validador exige al menos «Resumen» y «Despliegue».

## 5. Commits

Dentro de una rama, el mensaje sigue el mismo formato que el título: `tipo(CÓDIGO): resumen`, con el detalle en el cuerpo. El PR se **fusiona con squash**: en `main` queda **un commit por PR**, con el título y la descripción del PR, de modo que el historial de `main` se lee como una lista de códigos.

## 6. Etiquetas

Las de `area:` y `tipo:` se ponen solas a partir del título; el resto, a mano.

- `area:CI`, `area:SEG`, `area:IA`, `area:UX`, `area:BE`, `area:FE`, `area:OPS`, `area:DOC`
- `tipo:feat`, `tipo:fix`, `tipo:docs`, `tipo:test`, `tipo:refactor`, `tipo:perf`, `tipo:ci`, `tipo:build`, `tipo:chore`, `tipo:revert`
- `estado:en-revision`, `estado:bloqueado`, `estado:listo-para-desplegar`, `estado:desplegado`
- `prioridad:alta`, `prioridad:media`, `prioridad:baja`
- `requiere-despliegue` (toca producción) y `requiere-decision-del-dueno` (espera una decisión de Simon)
- Las de Dependabot (`dependencies`, `python`, `javascript`, `github_actions`) se mantienen.

La definición completa vive en `.github/labels.json`.

## 7. Issues e hitos

Hay tres formularios: **Cambio** (algo nuevo o a mejorar), **Error** y **Decisión del dueño**. El título del issue es `CÓDIGO: resumen` (por ejemplo `SEG-014: rotar la contraseña del worker`) y el código es el mismo que llevará su PR. Los hitos (*milestones*) son los planes: Plan CI/CD, Plan de Seguridad, Plan de UX, Plan de IA, Plan de Usuario y Mantenimiento.

## 8. Lanzamientos (despliegues)

- El **nombre del lanzamiento** (el `--rel` del kit) es el código en minúscula: `ia-005`, `ci-004`. Si un lanzamiento reúne varios cambios, `rel-AAAAMMDD-N` y la lista de códigos en la descripción.
- La carpeta del servidor sigue siendo `AAAAMMDDTHHMMZ-<nombre>`, y el flujo `Deploy` de GitHub usa ese mismo nombre.
- **Quien lanza desde `main` debe comprobar antes que `main` contiene todo lo que producción ya ejecuta** (la carpeta `/root/releases/` del servidor lo dice): desplegar desde un `main` desactualizado pisaría el trabajo de otras sesiones.
- Cada lanzamiento se anota en el registro con su código, la fecha y el commit de `main`.

## 9. Qué hace cumplir esto

- El flujo **«Título, rama y descripción del PR»** rechaza un PR cuyo título o rama no sigan el formato, cuyo código en la rama no coincida con el del título, o cuya descripción no traiga las secciones mínimas. Además pone las etiquetas `area:` y `tipo:`.
- `main` está protegido: solo se entra por PR, sin forzar ni borrar, y ese flujo es una comprobación obligatoria.
- Solo se permite fusionar con squash; la rama se borra al fusionar.
- Las pruebas de `backend/tests/unit/test_github_conventions.py` fijan el formato, para que nadie lo debilite sin que el CI lo note.

## 10. Lo que NO se hace

- No se reescribe la historia anterior (cambiaría todos los hashes y rompería kits y documentos que los citan).
- No se usan títulos sin código, ni un código para dos cosas, ni dos códigos para una.

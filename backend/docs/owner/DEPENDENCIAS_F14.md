# Librerías fijadas de la imagen del backend (F14.2) — PrediGol

*Escrito el 24 de octubre de 2026. Es solo la forma de construir la imagen del backend: no cambia ningún modelo, pronóstico, precio ni pick,
no necesita migración, no toca la base de datos, no hace peticiones al proveedor y no usa IA. Sale con el próximo despliegue; hasta entonces
producción sigue exactamente como está.*

## 1. Qué se encontró

La imagen del backend se construía con `pip install -e ".[analytics]"`. Ese comando solo pide **cotas inferiores** (`fastapi>=0.115`,
`numpy>=2.1`, …): cada vez que Docker tiene que rehacer esa capa (958 MB), instala lo más nuevo que haya ese día. Y la rehace siempre que
cambia `pyproject.toml`: entre el 22 y el 23 de octubre lo tocaron cinco commits (F2, F3.2, F5, F7 y F10.1, cada vez que creció la lista de
paquetes que revisa `mypy`), y cada despliegue que los incluyó rehízo la capa con lo más nuevo de ese día.

El resultado, medido el 24 de octubre sobre la imagen que corre (`predigol-backend:7a7d010653a5`, Python 3.12.15): **seis librerías de
producción eran más nuevas que las del entorno donde pasan las puertas** (`fastapi` 0.162.0 contra 0.159.1, `pandas` 3.1.0 contra 3.0.6,
`sentry-sdk` 2.73.0 contra 2.72.0, `certifi`, `pycparser` y `tzlocal`). Las otras 54 coincidían. Nadie lo eligió, nada lo anotó, y la huella del
código de los modelos (`mc9a7bec97ca`) solo mira nuestro código, no las librerías: una versión nueva de una librería numérica no la mueve.

## 2. Qué cambia

* **`backend/constraints.txt`** (nuevo): **60 bibliotecas** con su versión exacta (`nombre==versión`, una por línea, en el orden de `pip freeze`), tomadas de
  `pip freeze` dentro de la imagen que corre, sin el propio proyecto. Un archivo de restricciones no instala nada por sí mismo: solo dice qué
  versión usar de lo que ya se pide.
* **`backend/Dockerfile`**: copia `constraints.txt` junto a `pyproject.toml` antes de la capa de `pip` (el `README.md` ya no se copia ahí: no hace falta para instalar, y
  editarlo reconstruía sin motivo esa capa de 958 MB), y la instala con
  `pip install -c constraints.txt -e ".[analytics]"`. Si cambia cualquiera de los dos archivos, la capa se rehace; si no, se reutiliza.
* **`backend/README.md`**: la instalación local pasa a `pip install -c constraints.txt -e ".[dev,analytics]"`.
* **`backend/tests/unit/test_dependency_pins.py`** (nuevo, 6 pruebas, sin red): el archivo es una lista ordenada de versiones exactas sin
  repetidos; nombra todas las librerías que `pyproject.toml` pide a la imagen (las de siempre y las del extra `analytics`) y ninguna otra;
  **el entorno donde corre la prueba tiene esas mismas versiones** (así la puerta se pasa siempre sobre lo que corre en producción, y una
  librería actualizada sin tocar el archivo, o el archivo cambiado sin instalarlo, falla con la línea a corregir); el Dockerfile copia el
  archivo antes de `pip` y lo usa con `-c`; `.dockerignore` lo deja entrar; y esta guía dice cuántas bibliotecas hay y qué imágenes base siguen
  sin fijar.

## 3. Cómo se comprobó

1. **La resolución a seco** (`pip install --dry-run --ignore-installed --report …` con el mismo comando de la imagen y el archivo nuevo, sin
   instalar nada): instala **60 de 60** bibliotecas con exactamente las versiones de producción, más el propio proyecto; ninguna de más, ninguna
   de menos, ninguna con otra versión.
2. **La puerta completa sobre esas versiones** (el entorno de pruebas se alineó con producción el 24-oct a las 05:08 UTC y la puerta corrió de
   05:12 a 05:23 UTC): `ruff` limpio, `mypy` estricto sin errores (447 archivos), `mypy` de todo el árbol sin errores (1.035 archivos) y
   `pytest` con **4.746 pasando, 4 omitidas (las de siempre) y 0 fallando**, en 9 min 30 s. Con las versiones de antes eran 4.738 + 4: la diferencia son
   las 8 pruebas de la lista de cierre por fase. El único aviso de `pytest` (Starlette recomienda `httpx2` para su cliente de pruebas) ya
   salía antes y no afecta a producción.
3. **La prueba nueva** (sección 2), que se repite en cada pasada de la puerta.

Lo que **no** se ha podido hacer es construir la imagen de verdad: eso ocurre en el servidor, en el próximo despliegue (sección 4).

## 4. Qué pasará en el próximo despliegue

* La primera construcción con este Dockerfile **rehace la capa de `pip` una vez** (el archivo nuevo cambia su huella de caché): tardará más que
  un despliegue normal y bajará las librerías de PyPI. Instalará las mismas versiones que corren hoy; no se espera ningún cambio de resultados.
* Tras desplegar se comprueba, solo en lectura, que la imagen es la del archivo:
  `diff <(docker exec predigol-worker pip freeze --exclude-editable) <(grep -v '^#' backend/constraints.txt | grep .)` no debe devolver nada.
* Los despliegues siguientes reutilizan la capa mientras no cambien `pyproject.toml` ni `constraints.txt`.

## 5. Cómo se sube la versión de una librería

1. Cambiar su línea en `constraints.txt` (y `pyproject.toml` solo si cambia la cota inferior).
2. Instalar el archivo en el entorno de pruebas: `pip install -c constraints.txt -e ".[dev,analytics]"`.
3. Pasar la puerta completa (`ruff`, `mypy`, `mypy .`, `pytest`). La prueba `test_dependency_pins.py` falla si algo del paso 1 o 2 no coincide.
4. Si la librería puede mover un número (`numpy`, `scipy`, `statsmodels`, `pandas`, `polars`, `duckdb`, `pyarrow`), **medir los modelos antes y
   después** con el mismo conjunto de partidos: el registro de promociones (F12) no la ve, porque la huella no se mueve con una librería.
5. Salir como cualquier otro cambio, con el aviso al dueño y la nota en el lanzamiento.

## 6. Lo que sigue sin fijar (y por qué)

* **Las imágenes base** `python:3.12-slim` (backend), `oven/bun:1.3.13-alpine` y `node:22-alpine` (web): `bun` ya está en una versión exacta; las otras dos
  se refrescan dentro de su rama (Python 3.12.x sobre Debian; Node 22.x sobre Alpine) cada vez que Docker las vuelve a bajar. Traen los
  parches de seguridad del sistema y cambian poco, pero no son reproducibles al byte. Es la decisión 24, más abajo.
* **`hatchling`**, que empaqueta el proyecto durante la construcción: `pip` no le aplica el archivo de restricciones. No entra en la imagen
  que corre.
* **Las herramientas de desarrollo** del entorno de pruebas (`pytest`, `ruff`, `mypy`, …) y los extras `ml` y `dev`: no están en la imagen y
  no afectan a producción.
* **La web** ya estaba fijada: `bun.lock` y `bun install --frozen-lockfile`.

## 7. Decisión 24 (tuya): ¿fijar también las imágenes base?

* **a) Dejarlas como están (lo que recomiendo).** Reciben los parches de seguridad sin que nadie haga nada y los saltos de versión
  (Python 3.13, Node 24) no se producen solos.
* **b) Fijarlas por huella (`python:3.12-slim@sha256:…`).** Construcciones idénticas al byte, pero los parches de seguridad dejan de llegar
  hasta que alguien actualice la huella; habría que ponerlo en el calendario (una vez al mes).

Mientras no digas nada, se queda (a).

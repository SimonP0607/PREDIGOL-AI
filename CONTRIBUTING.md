# Cómo contribuir a PrediGol

Todo cambio entra por Pull Request a `main` y lleva un **código `ÁREA-NNN`**.

1. Pide el siguiente número libre en [`docs/proyecto/REGISTRO_CODIGOS.md`](docs/proyecto/REGISTRO_CODIGOS.md) y añade tu fila en el mismo PR.
2. Crea la rama `tipo/CÓDIGO-resumen` (por ejemplo `fix/IA-005-sondeo-lotes-sin-abandonar`).
3. Abre el PR con el título `tipo(CÓDIGO): resumen en español` y rellena la plantilla.
4. El flujo «Título, rama y descripción del PR» lo valida y pone las etiquetas `area:` y `tipo:`.
5. Se fusiona con **squash**; la rama se borra sola.

Las reglas completas (áreas, tipos, etiquetas, lanzamientos) están en [`docs/proyecto/CONVENCIONES_GITHUB.md`](docs/proyecto/CONVENCIONES_GITHUB.md).

Nada llega a producción sin la palabra del dueño: el despliegue es el flujo `Deploy` y exige su aprobación en GitHub.

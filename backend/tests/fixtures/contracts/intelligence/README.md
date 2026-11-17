# Ejemplos de los contratos de Intelligence

Un fichero por caso y proyección: `<contrato>/<caso>.private.json` y, si el contrato tiene proyección pública,
`<contrato>/<caso>.public.json`. Cada fichero es el `data` de la respuesta (el sobre `status`/`data`/`reason`/`meta` de
siempre no se repite aquí).

- El privado valida contra el modelo privado y vuelve idéntico al serializarlo.
- El público es **exactamente** lo que el servidor construye a partir del privado (`to_public`), y la prueba de no fuga lo
  recorre: ningún campo privado, ninguna clave desconocida, ningún estado distinto de `publicada`, `en_juego` o `liquidada`.
- Equipos y personas ficticios, enlaces y direcciones en `.invalid`. **Nunca** datos de producción, y la web no los usa como
  datos: solo en pruebas de componente y de regresión visual.

Esta carpeta es propia porque `tests/fixtures/contracts/` guarda respuestas grabadas de API-Football (`teams.json`,
`standings.json`…).

Las reglas: `backend/docs/owner/IA_057_CONTRATO_INTELLIGENCE.md`. Las pruebas: `tests/unit/test_intelligence_contract_*.py`.

| Contrato | Caso | Qué enseña |
| --- | --- | --- |
| C-00 (muestra, sin ruta) | `publicada` | Una selección autorizada sale en la pública como `publicada`; la que sigue `en_evaluacion` solo en la privada. 59 % `calibrada` en las dos; 78,5 % `sin_calibrar` solo en la privada |
| C-00 | `sin_publicar` | Nada autorizado: la pública trae `{"items": [], "missing_reason": "sin_publicados"}` |

Al añadir un contrato: su carpeta con al menos un caso, una fila aquí y su línea en la coordinación entre sesiones.

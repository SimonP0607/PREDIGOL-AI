# IA-119 · Retirada segura de los textos duplicados (`retire-compare-v1`)

Pieza **AD-F05**. **No apaga nada.** Prepara la comparación preregistrada de la crónica única (`chronicle-v4`) con los tres textos que
reemplazaría y documenta, texto por texto, con qué interruptor **existente** se retira y cómo se vuelve atrás. Cada retirada es un acto del
dueño, con su firma; ninguna está firmada. **No se borra ninguna fila**: la tabla del texto retirado queda tal cual, de solo lectura.

## La comparación (escrita antes de correrla)

Sobre **los mismos partidos**: los que Intelligence analizó en la ventana y para los que se intentó la crónica única.

| Métrica | Qué es | Mejor |
| --- | --- | --- |
| Apoyo | de los intentos respondidos, los que dejaron un texto mostrable (v4: ok/partial; v3: ok; brief: ok por el modelo con narrativa) | más alto; **v4 debe ser mejor** |
| Cobertura | partidos con al menos un texto aceptado antes del saque | más alto |
| Sin autorización | textos con una frase de clase de alto riesgo que el plan del partido no autoriza («nada en juego» con un objetivo abierto…) | más bajo |
| Coletillas | frases de la lista cerrada de IA-117 | más bajo |
| Coste | US$ por texto aceptado (sin intervalo: es un cociente de sumas) | más bajo |

**No peor** (propuesto, sin firmar): una tasa, si el intervalo del 95 % (Wilson) de v4 alcanza la del otro texto con un margen de 5 puntos;
el coste, si no supera al otro en más de un 10 %. **Mínimo 100 partidos**; si no, INSUFICIENTE. Las tarjetas de análisis
(`match-analysis-v1`) se hacen por reglas, sin modelo ni texto: solo se compara su cobertura.

```
python -m scripts.ia_chronicle_eval compare --days 14      # solo lectura: el informe en JSON
```

## Los pasos, uno por texto

| Orden | Texto | Tabla | Interruptor que lo retira | Vuelta atrás |
| --- | --- | --- | --- | --- |
| 1 | `user-narrative-v3` (crónica de lectores) | `ai.user_narratives` | `FBI_USER_NARRATIVE=off` (apaga el trabajo y lo que ven los lectores) | volver a la palabra de antes (`on` o `shadow`) |
| 2 | `brief-v8` (su narrativa) | `ai.match_briefs` | **no existe**: el brief va dentro del pase del día y además decide la escalada; `FBI_AI_MODE=off` apagaría toda la revisión de la IA | — |
| 3 | `match-analysis-v1` (tarjetas) | `ai.match_analyses` | **no existe**: las construye el ciclo del día por reglas y las sirve la ruta del análisis | — |

Para los pasos 2 y 3 hace falta **una pieza aparte** con su propio interruptor (y, para lo que ve el lector, la sesión UX). Aquí no se
crea ninguno.

**Ninguna pantalla se queda sin texto**: la regla `retire.shown` dice qué mostraría el hueco de la crónica de C-01 — la crónica única si
tiene texto; si no, la crónica de lectores mientras no esté retirada; si no, la abstención con su código (`SIN_PLAN`, `SIN_DATOS`,
`VERIFICACION_VACIA`). Llevarla a C-01 es la entrega 2 de AD-J02 (otra pieza).

## Qué tiene que hacer el dueño

1. Firmar (o cambiar) los márgenes de la comparación.
2. Cuando el informe diga `lista_para_firma` para `user-narrative-v3`, decidir y firmar su retirada, y cambiar él mismo el interruptor.
3. Decidir si se hace la pieza que daría interruptor propio a la narrativa del brief y a las tarjetas.

## Estado al entregar (17-nov-2026)

Sin datos: la crónica única nace apagada y aún no tiene filas en producción, así que la comparación daría INSUFICIENTE. El ahorro de
hasta unos US$ 27/mes de la ficha es una proyección del 1 al 15-nov sin verificar a 30 días.

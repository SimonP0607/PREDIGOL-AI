# IA-024 · Cifras de la crónica: español e inglés se comparan por lo que dicen

**Qué se midió.** Lectura de solo lectura de `ai.user_narratives` (9-nov): de las crónicas `user-narrative-v3` con respuesta, 297 pasaron y 364 se rechazaron tras el segundo intento. La razón más frecuente, con diferencia, fue «el inglés dice otras cifras que el español»: **143 de las 364** (39 %). Las siguientes: más de 4 referencias en una frase (94), un rumor fuera de «riesgos» (57 + 35), una noticia probable contada como hecho (34), una sección que el relato no tiene (29) y una sección vacía (25).

**Por qué ocurría.** La comprobación comparaba las cifras de cada frase en los dos idiomas, pero no las leía de la misma manera: el inglés contaba «eleven», «three»… como cifras, el español no contaba «once» (por la plantilla titular) ni «dos»/«two», y un «2 empates» en un idioma frente a «two draws» en el otro se leía como dos cifras distintas. Los ejemplos rechazados (`eleven months ago`, `two draws`, `15th`…) son frases correctas.

**Qué cambia.** Solo la comparación entre idiomas (`fbi.narrative.job._numbers_key`): una cantidad de dos a veinte vale lo mismo escrita en cifras o en palabras, en español o en inglés; el cero y el uno enteros no se comparan («una victoria» frente a «a win», «0-0» frente a «goalless»); los decimales se siguen comparando («1,8» frente a «1.9» se rechaza). **No cambia** la comprobación de cada idioma contra los hechos y las noticias que la frase cita (`check_sentence` y `SPELLED`): toda cifra sigue necesitando su referencia, y una cantidad distinta o un marcador distinto entre idiomas se sigue rechazando.

**Qué no cambia.** Prompt `user-narrative-v3`, referencias, validaciones de rumores, causas y certezas, presupuesto, modos (`FBI_USER_NARRATIVE`), tablas. No toca Intelligence, ni modelos, ni umbrales, ni picks.

**Cómo se mide el efecto.** La proporción de crónicas rechazadas por esa razón, por versión y día (consulta de solo lectura sobre `ai.user_narratives.rejected`). Las que ya están rechazadas no se reescriben: el nuevo `input_hash` solo vuelve a pagarse cuando cambia la historia del partido.

**Lo que queda para la crónica v4 (etapa C del flujo único).** Las otras razones son de prompt: frases con más de cuatro referencias, rumores contados fuera de «riesgos», secciones vacías o que el relato no tiene. Se atacan en `user-narrative-v4` con batería de calidad y en sombra al lado de v3, no aquí.

**Vuelta atrás.** Revertir el cambio; no hay migración ni interruptor.

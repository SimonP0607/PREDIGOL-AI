# IA-147 · Nivel propuesto de cada sitio oficial, para firmar en bloque (DM-05)

Plan Maestro PM, tarea **PM-06-02** (OP-09, OP-40). 20-nov-2026. **Propuesta: no enciende, no firma ni cambia nada.** La firma es del
dueño (DM-05) y tres filas dependen además de la consulta al abogado (DM-08), que **no está hecha**. `FBI_SOURCE_POLICY` sigue en
`shadow`; nada pasa a `enforce`.

Tabla completa: [`IA_147_NIVEL_FUENTES_OFICIALES.csv`](IA_147_NIVEL_FUENTES_OFICIALES.csv) (separador `;`, una fila por dominio, 668
dominios de los 671 sitios oficiales —familia E— del directorio v2; la columna `firma_dueno` está vacía para que la rellenes).

## 1. De dónde sale cada columna

| Columna | Fuente |
| --- | --- |
| `fuentes`, `nombre`, `pais`, `prioridad`, `cubre_predigol`, `estado_actual`, `rss`, `rss_verificado`, `terminos_leidos`, `terminos` | directorio v2 (`config/sources/directorio_v2_2026-11-16.json`, revisado el 16-nov-2026); `terminos` es el resumen del directorio, no el texto de los términos |
| `robots_20nov` | `robots.txt` de cada dominio leído el 20-nov-2026 entre las 14:50 y las 15:24 UTC con las reglas de `scripts.ia_sources_check` (una petición por dominio, pausa de 2 s, sin reintento, sin Exa ni modelos; los 72 `bloqueada` no se vuelven a pedir) |
| `nivel_propuesto`, `motivo` | las reglas del §2 |

Lecturas desde la nube de esta sesión: un 403, 429 o fallo de conexión puede ser del intermediario de salida y no del sitio, así que
no se toma como prueba de bloqueo (`ia_sources_check` los propondría como `bloqueada`): esas 68 filas quedan «no concluyente» y se
repiten desde el servidor.

## 2. Los niveles

| Nivel | Qué significa si lo firmas | Regla | Filas |
| --- | --- | --- | --- |
| **N1-DM08** | Pasa a `verificada_autorizada` con tu firma: se lee su RSS (título, fecha, enlace, autor; nunca el cuerpo, `feeds-v1`), se guarda el hecho con enlace y se enseña titular propio con enlace. **Solo con la respuesta del abogado** | oficial, `robots.txt` lo permite, sin términos que lo prohíban y sin términos publicados (DM-08: «¿basta título y enlace?») | 3: `dimayor.com.co`, `fcf.com.co` (los dos con RSS verificado), `rfef.es` (aviso legal mudo sobre extracción) |
| **N2-pendiente** | No cambia: sigue en `verificada_pendiente_derechos` (solo enlace) hasta leer sus términos | `robots.txt` lo permite o no se pudo leer, y los términos no están leídos | 533 (173 de prioridad alta) |
| **N3-no-firmar** | Rechazo: no se firma. Para las que reservan a la IA, `ia_sources_check` propone `solo_referencia` | bloqueada en el directorio (71), `robots.txt` reserva a la IA o lo cierra a todos (43), o sus términos limitan el uso a lo personal o no comercial o prohíben la reproducción (10: CAF, CBF, Concacaf, FFF, LaLiga, Leagues Cup, Ligue 1, Premier League, The FA, IFAB) | 124 |
| **EXCLUIDA** | Fuera, por regla del plan: UEFA y FIFA | dominios de `fifa.com` y `uefa.com` (8) | 8 |

Ningún sitio llega hoy a un «N1» sin condiciones: de los 15 con términos leídos por el directorio, 12 los restringen (la AFC,
además, reserva ahora su `robots.txt` a la IA; FIFA queda excluida) y los otros 3 son las N1-DM08. Por eso la firma en bloque hoy son **3 filas condicionadas a DM-08 y 124 rechazos**; el grueso (533) espera a que se
lean sus términos.

Colombia (P0): `dimayor.com.co` y `fcf.com.co` en N1-DM08. De los clubes, `independientesantafe.com` y `realcartagena.com.co` reservan su
sitio a la IA en `robots.txt` (N3); nueve están bloqueados en el directorio (N3); el resto, N2 (términos sin leer), con
`aguilasdoradas.com.co`, `americadecali.com` e `interbogota.com` sin `robots.txt` legible desde la nube.

## 3. Cómo firmas en bloque

1. Rellena `firma_dueno` con `firmo`, `rechazo` o `espero` (las N2 pueden quedarse vacías: equivale a `espero`). Para las tres N1-DM08,
   `firmo` solo cuando el abogado haya respondido a DM-08; mientras, `espero`.
2. Devuelve la tabla (o la lista de dominios con `firmo`) en un comentario del PR o en el chat, con la fecha.
3. Lo aplica después una sesión con `python -m scripts.ia_sources_load sign --source <id> --reason "IA-147, firma en bloque del <fecha>"
   --confirm-owner` por cada `firmo` (registro de solo añadir `ai.source_signoffs`; `--revoke` la retira). Los rechazos que reservan a la
   IA entran como nueva versión del directorio (las propuestas de `ia_sources_check`), no como firma.

## 4. Lo que queda

* **Dueño:** DM-05 (la firma de la tabla) y **DM-08** (enviar al abogado el asunto «Fuentes sin términos: DIMAYOR, FCF; ¿basta título y
  enlace?»; añadir `rfef.es`). No se da por hecha.
* **Siguiente paso (otra sesión):** leer los términos de las 173 N2 de prioridad alta, empezando por Colombia y las competiciones P1, y
  repetir `robots.txt` de las 68 «no concluyente» desde el servidor; cada lectura mueve una fila a N1 o a N3 en una versión nueva de esta
  tabla.
* PM-06-03 (medir cuándo llega una baja por cada vía) necesita al menos las N1 firmadas.

## 5. Reversión

Es un documento. Una firma aplicada se retira con `ia_sources_load sign ... --revoke --confirm-owner` (manda la más reciente).

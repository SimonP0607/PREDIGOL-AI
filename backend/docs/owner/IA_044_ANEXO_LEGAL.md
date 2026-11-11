# IA-044 — Anexo legal: datos de terceros, citas y conservación

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-B08, ola 1. 11-nov-2026.*

Este anexo acompaña a `PAQUETE_ABOGADO_TRAMO1_20261110.md`, que trata el registro, el pago manual y la membresía, y no repite nada de él. Cubre los cinco temas de la decisión 6 y de M6:

- (a) API-Football;
- (b) Exa;
- (c) la política de citas;
- (d) la conservación y el borrado;
- (e) Transfermarkt.

**No es asesoría legal.** Son hechos verificados, cada uno con su fuente, y preguntas para el abogado.

**Cómo se verificó.**

- Páginas web: leídas el 11-nov-2026, entre las 04:25 y las 04:50 UTC.
- Código: `main` en `77518df0`, en solo lectura.
- Producción: consultas de solo lectura del 11-nov a las 04:38 UTC.

**Política prudente mientras el abogado no responda (la del plan).**

- Cita breve con enlace y fuente.
- Ningún artículo completo.
- No usar Transfermarkt.
- No guardar textos más allá de esta política.

## 0. Lo esencial

1. **API-Football.** Deja construir aplicaciones y webs con sus datos, pero prohíbe revenderlos y no da licencia para publicarlos. Sus términos no dicen nada sobre guardar datos, conservar históricos ni mostrar cuotas.
2. **Exa.** Prohíbe copiar, mostrar o publicar lo que se obtiene con su servicio, salvo que lo permitan sus términos o un permiso escrito (cláusula 4.2 a). Su documentación no autoriza expresamente guardar ni mostrar resultados.
3. **Cita en Colombia.** Se puede citar indicando el autor y el título (Ley 23, art. 31), o la fuente y el autor (Decisión 351, art. 22 a), en la medida justificada. Los hechos y las ideas no están protegidos. Hoy PrediGol muestra al lector un resumen propio con enlace, nunca el texto ni el título del artículo.
4. **Conservación.** PrediGol guarda sin plazo extractos y citas de textos de terceros:
   - extractos de hasta 2.000 caracteres en una caché cuya purga no corre;
   - citas de hasta 300 caracteres en una evidencia que no se borra;
   - y copias de la base bloqueadas hasta 12 meses.

   X y Meta obligan a borrar. X da 24 horas y exige borrar también las copias.
5. **Transfermarkt.** Prohíbe acceder o copiar de forma automatizada, prohíbe usar sus contenidos para IA y se reserva la minería de textos, así que hace falta permiso escrito. PrediGol no lo usa como fuente, pero la caché ya guarda 18 resultados suyos que devolvió Exa.

## 1. Qué hace hoy PrediGol con contenidos de terceros

| Hecho | Cifra o detalle | Origen |
| --- | --- | --- |
| Acceso al proveedor | API-Football por su acceso directo, `v3.football.api-sports.io`, con su propia clave. No usa RapidAPI | `core/config/providers.py`, `providers/api_football/client.py` |
| Conservación de datos del proveedor | Partidos, resultados y cuotas prepartido se guardan «para siempre» en la base. Los ficheros crudos del proveedor también, bloqueados en R2 | `api/services/storage.py` (`RETENTION`) |
| Copias de la base | Diarias durante 14 días, semanales durante 8 semanas y mensuales durante 12 meses, bloqueadas en R2 | `api/services/storage.py` (`RETENTION`) |
| Qué ve el usuario del proveedor | Cuotas por casa (explorador de Cuotas y pestaña Mercados), estadísticas y alineaciones. La web muestra escudos servidos por `media.api-sports.io`, que la PWA guarda en caché | rutas `/odds`; `web/src/lib/pwa.test.ts` |
| Búsqueda web | Exa `/search` devuelve 8 resultados con hasta 2.000 caracteres de texto de cada página. No hay filtro de dominios | `analyst/search.py` |
| Caché de búsquedas | 11.336 resultados guardados. Extracto medio de 724 caracteres y máximo de 2.000. La caché vale 24 h, o 4 h en las 12 horas antes del partido | producción, `ai.research_cache`; `ai/cache.py` |
| Purga de la caché | La función `purge_expired` existe, pero nada la llama. Siguen guardadas 740 respuestas de búsqueda que caducaron hace más de 14 días | `ai/cache.py`; producción |
| Evidencia | 18.083 filas del 7-oct al 10-nov: 11.500 del proveedor, 5.684 de la web con Research v1 (resumen propio, 109 caracteres de media) y 899 de Research v2 (cita literal de la página, hasta 300 caracteres) | producción, `ai.evidence`; `ai/contracts/claim.py`, `ai/extract_v2.py` |
| Borrado de la evidencia | Un disparador impide borrar filas, salvo en modo de mantenimiento, y cambiar su contenido | migración `0072_ai_decision_layer.py` |
| Qué ve el lector de una noticia | Un resumen propio de una frase en español, la fuente, su nivel, la hora y el enlace. Nunca el texto, el título ni la imagen del artículo | `api/contracts/news.py`, `api/services/news.py` |
| Research v2 | Está en sombra y sus citas no se muestran. Si se enciende sin cambios, una cita literal en español se mostraría como si fuera el resumen propio, sin comillas ni autor | `api/services/news.py` (`own_summary`, `typed_visible`) |
| Redes sociales | 0 ítems en la evidencia y 1 resultado de una red en la caché | producción |
| Transfermarkt | 0 ítems en la evidencia y 18 resultados en la caché de búsquedas | producción |

**Consultas.** `B08/q1.sh` y `B08/q2.sh`: agregados de solo lectura, sin leer contenido. Una tercera consulta, `B08/q3.sh`, buscaba las fechas de los 18 resultados de Transfermarkt y no terminó porque el equipo remoto no respondió.

## 2. (a) API-Football / API-Sports

**Fuentes, consultadas el 11-nov-2026.**

- Términos: https://www.api-football.com/terms y https://api-sports.io/terms. El texto es idéntico en las dos y dice «Last updated: Mai 21, 2025».
- Documentación: https://www.api-football.com/documentation-v3, sección Odds.

| Tema | Qué dicen (cita literal) | Lectura |
| --- | --- | --- |
| Uso y reventa | «it is prohibited to resell this data to third parties […] you cannot directly sell the data we provide. We provide data for you to create different projects such as applications, websites, fantasy soccer games etc.» | Permite aplicaciones y webs. Prohíbe vender los datos directamente |
| Licencia de publicación | «We do not provide a "license" for the use and publication of the data […] Any license or permission to publish the data must be requested by the user from the competent authorities.» | No dan licencia para publicar |
| Derechos de terceros | «may be subject to intellectual property rights or commercial restrictions imposed by third parties, including leagues, federations, or event organizers». También: «The use of our data for betting platforms, television broadcasting, fantasy sports platforms, or any mass media distribution may require additional licenses from the relevant rights holders.» | La responsabilidad es del usuario |
| Quejas de titulares | Ante «a formal complaint or legal notice from a recognized rights holder», pueden suspender el acceso «immediately […] without refund» | Riesgo de corte sin aviso |
| Logos | «provided solely for identification and descriptive purposes». Su uso «may require additional authorization or licensing from the respective rights holders» | Los escudos tienen derechos de terceros |
| Fin del plan | «Once the defined period has expired, your access to the API will be switched to the free plan.» | No dicen nada de borrar lo guardado |
| Cuotas | La documentación dice «We provide pre-match odds between 1 and 14 days before the fixture. We keep a 7-days history». No hay cláusula de licencia sobre cuotas | El histórico que muestra PrediGol es propio, hecho con sus capturas |
| Guardar en local | Ninguna cláusula | Los términos no lo tratan |
| Ley y tribunales | «governed by French law […] the French courts shall have exclusive jurisdiction» | — |
| Dudas | «If you have any doubts about how you would like to use it, you can contact us directly by email.» | Hay una vía para confirmar por escrito |

**Preguntas para el abogado**

1. Una membresía de pago que muestra cuotas por casa, estadísticas y alineaciones del proveedor, ¿es «crear una aplicación o una web», que está permitido, o «vender directamente los datos», que está prohibido? ¿Conviene pedir confirmación escrita al proveedor antes de abrir el cobro?
2. El plan Ultra se renueva antes del 29-nov-2026. Si vence o no se renueva, ¿puede PrediGol conservar sin plazo, y seguir mostrando, los históricos que construyó: resultados, cuotas y su movimiento?
3. Los términos dicen que las «betting platforms» pueden necesitar licencias adicionales. ¿Un sitio de análisis y picks de pago entra en esa categoría? ¿Qué licencias de ligas o federaciones habría que revisar?
4. Pregunta de derecho colombiano, fuera de los términos del proveedor. Según el análisis de la línea Cuotas del 4-oct-2026 (`docs/research/ODDS_PROVIDER_GAP_ANALYSIS_2026.md`), de los 14 operadores con licencia de Coljuegos solo la marca Betano está entre las casas del proveedor. ¿Mostrar a usuarios en Colombia cuotas y marcas de casas sin licencia local puede tomarse como publicidad o promoción de juego no autorizado?
5. ¿Se pueden mostrar escudos de clubes en un producto de pago, o conviene usar el escudo provisional con sigla y color que ya prevé el diseño (lámina S4)?
6. ¿Qué implica, en la práctica, para un titular en Colombia que rijan la ley y los tribunales franceses?

## 3. (b) Exa (exa.ai)

**Fuentes, consultadas el 11-nov-2026.**

- Términos: https://exa.ai/assets/Exa_Labs_Terms_of_Service.pdf, enlazado como «Terms» desde https://exa.ai/privacy-policy. El PDF tiene 8 páginas y no muestra la fecha «Last Revised», aunque su cláusula 10.2 la menciona. Según sus metadatos, se creó y se modificó por última vez el 4-mar-2025.
- Política de privacidad: «Last updated: June 29, 2026».
- Política de contenidos (https://exa.ai/docs/reference/content-policy.md) y preguntas frecuentes (https://exa.ai/docs/admin/faqs.md): no tratan guardar resultados, mostrarlos ni los derechos de autor.

| Cláusula | Qué dice (cita literal) |
| --- | --- |
| 1.1 Licencia | «non-exclusive, non-transferable, non-sublicensable, worldwide, revocable right and license to use our APIs for the limited purposes set forth in the documentation» |
| 4.1 Mostrar | Licencia para «access and display such software, content and materials provided to you as part of the Services […] for the sole purpose of enabling you to use the Services as permitted by these Terms». Añade: «it is your responsibility to review the Documentation to ensure that your use of the Services does not infringe […] the intellectual property […] of any third person» |
| 4.2 a) Restricción | Prohíbe «download, modify, copy, distribute, transmit, display, perform, reproduce, duplicate, publish, license, create derivative works from, or offer for sale any information contained on, or obtained from or through, the Services, except for temporary files that are automatically cached by your web browser for display purposes, or as otherwise expressly permitted in these Terms or by us in writing». Rige «unless applicable laws or regulations prohibit these restrictions or you have our written permission» |
| 4.2 e) y f) | No revender el servicio sin consentimiento. No usar el servicio, «including Output», para desarrollar un producto competidor |
| 1.2 c) | Exa recibe una licencia «perpetual and irrevocable» sobre las consultas y los resultados para prestar y mejorar sus servicios. La política de privacidad añade: «Query Data is used to improve our products and technology.» |
| 7.1.2 | «The Company shall have no responsibility or liability to you for the infringement of the rights of any third party in your use of any Output.» |
| Acuerdos adicionales | Si existe un «Master Subscription Agreement» u otro acuerdo, ese prevalece |
| 5.4 | En el PDF publicado, el enlace al acuerdo de tratamiento de datos aparece como «[LINK]», sin rellenar |
| 10.8 y 8 | Rige la ley de California. Las disputas van a arbitraje JAMS, con renuncia a acciones colectivas y opción de salida en 30 días |

**Preguntas para el abogado**

1. A la luz de las cláusulas 1.1, 4.1 y 4.2 a), ¿puede PrediGol hacer lo siguiente, o necesita un permiso escrito de Exa?
   - Guardar resultados en caché. La caché vale de 4 a 24 h, pero hoy no se purga.
   - Guardar sin plazo los hechos extraídos, con citas de hasta 300 caracteres.
   - Mostrar a usuarios de pago un resumen propio con enlace al original.
2. Si hace falta permiso, ¿qué hay que pedir por escrito a Exa (el contacto de sus términos es hello@exa.ai)? Por ejemplo: el plazo de caché, la conservación de los hechos extraídos y las citas breves con enlace.
3. ¿La cuenta de PrediGol está solo bajo estos términos o bajo un acuerdo adicional? Lo confirma el dueño.
4. Exa no responde por infracciones de derechos de terceros en el uso de sus resultados (7.1.2). Si PrediGol muestra un extracto, ¿quién responde ante el medio original y cómo se cubre en los términos de PrediGol?

## 4. (c) Política de citas de PrediGol y derecho de cita en Colombia

**Fuentes oficiales, consultadas el 11-nov-2026.**

- **Ley 23 de 1982** (Diario Oficial 35.949, 19-feb-1982), copia del SISJUR de la Alcaldía de Bogotá: https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=3431.
  - Los artículos 31 a 36 no tienen nota de modificación. En otros artículos la página sí anota modificaciones de las Leyes 44 de 1993, 1450 de 2011, 1915 de 2018, 1955 de 2019 y 2294 de 2023.
  - El artículo 6 se cotejó en el Gestor Normativo de Función Pública: https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=3431. De esa página la herramienta no devolvió los artículos 31 a 36.
  - La página de la Secretaría del Senado no se pudo leer: dio un error 404 y una conexión cortada.
- **Decisión Andina 351 de 1993** (Lima, 17-dic-1993), copia del Tribunal de Justicia de la Comunidad Andina: https://www.tribunalandino.org.ec/decisiones/normativa/DEC351.pdf.
- **Ley 1915 de 2018** (Diario Oficial 50.652, 12-jul-2018), artículo 16, en el normograma de la DIAN: https://normograma.dian.gov.co/dian/compilacion/docs/ley_1915_2018.htm. Añade excepciones (copias transitorias, bibliotecas, parodia y caricatura, enseñanza), pero ninguna sobre cita o noticias. Ojo: se leyó en un resumen de la herramienta, no en el texto literal.

| Norma | Texto (cita literal) |
| --- | --- |
| Ley 23, art. 31 | «Es permitido citar a un autor transcribiendo los pasajes necesarios, siempre que éstos no sean tantos y seguidos que razonadamente puedan considerarse como una reproducción simulada y sustancial, que redunde en perjuicio del autor de la obra de donde se toman. En cada cita deberá mencionarse el nombre del autor de la obra citada y el título de dicha obra.» |
| Ley 23, art. 33 | «Pueden ser reconocidas cualquier título, fotografía ilustración y comentario relativo a acontecimiento de actualidad, publicados por la prensa o difundidos por la radio o la televisión, si ello no hubiere sido expresamente prohibido.» El SISJUR dice «reconocidas»: conviene cotejarlo con el Diario Oficial |
| Ley 23, art. 34 | «Será licita la reproducción, distribución y comunicación al público de noticias u otras informaciones relativas a hechos o sucesos que hayan sido públicamente difundidos por la prensa o por la radiodifusión.» |
| Ley 23, art. 6 | «Las ideas o contenido conceptual de las obras literarias, artísticas y científicas no son objeto de apropiación. Esta Ley protege exclusivamente la forma literaria, plástica o sonora […]» |
| Decisión 351, art. 22 a) | «Citar en una obra, otras obras publicadas, siempre que se indique la fuente y el nombre del autor, a condición que tales citas se hagan conforme a los usos honrados y en la medida justificada por el fin que se persiga» |
| Decisión 351, art. 22 e) | Permite «Reproducir y distribuir por la prensa o emitir por radiodifusión» artículos de actualidad «en los casos en que la reproducción, la radiodifusión o la transmisión pública no se hayan reservado expresamente» |
| Decisión 351, art. 21 | Las excepciones «se circunscribirán a aquellos casos que no atenten contra la normal explotación de las obras o no causen perjuicio injustificado a los legítimos intereses del titular o titulares de los derechos» |
| Decisión 351, art. 7 | «No son objeto de protección las ideas contenidas en las obras literarias y artísticas, o el contenido ideológico o técnico de las obras científicas, ni su aprovechamiento industrial o comercial.» |
| Decisión 351, arts. 4 ll) y 28 | Las bases de datos se protegen si su selección o disposición es una creación intelectual, y «La protección concedida no se hará extensiva a los datos o información compilados» |

**Política para validar con el abogado.** No es una decisión nueva: es la política prudente del plan, en concreto.

- PrediGol cuenta con sus palabras los hechos de una noticia, con la fuente, la hora y el enlace.
- Si cita, la cita es breve, va entre comillas y lleva el medio y el autor.
- Nunca reproduce un artículo completo, nunca usa el título como reclamo y nunca muestra imágenes ajenas.

**Preguntas para el abogado**

1. ¿Una tarjeta de noticia o la crónica de PrediGol cuentan como «una obra» en la que se puede citar, según el art. 22 a)? ¿Qué extensión es «la medida justificada» en una tarjeta? Como referencia, Research v2 guarda citas de hasta 300 caracteres.
2. El art. 31 pide el nombre del autor y el título; el 22 a), la fuente y el nombre del autor. Muchas notas no llevan firma.
   - ¿Basta con el medio, la fecha y el enlace?
   - ¿Hay que mostrar el título del artículo, que hoy PrediGol no muestra a propósito?
3. ¿Un resumen propio de un hecho («X no jugará por lesión», con enlace) queda amparado por los arts. 6 y 34 de la Ley 23 y el art. 7 de la Decisión 351? PrediGol no es prensa y cobra una membresía.
4. Los arts. 33 de la Ley 23 y 22 e) de la Decisión 351 exceptúan lo «expresamente prohibido» o «reservado». ¿Una cláusula general en los términos de uso de un medio cuenta como esa prohibición?
5. Si un modelo de IA resume en español un artículo publicado en otro idioma, ¿el resumen es una obra derivada o solo un uso de los hechos?

## 5. (d) Conservación de textos de terceros y borrado de contenido de redes

Hoy PrediGol no usa contenido de redes (0 ítems, sección 1). Esta sección es para el día en que lo use, algo que el plan condiciona a G-EVENTOS, a G-REDES y a una decisión de gasto del dueño.

**Fuentes, consultadas el 11-nov-2026.**

- X Developer Agreement: https://docs.x.com/developer-terms/agreement.md («Last Updated: April 27, 2026»).
- X Developer Policy: https://docs.x.com/developer-terms/policy.md (sin fecha visible).
- Meta Platform Terms: https://developers.facebook.com/terms/dfc_platform_terms/ («Last updated February 3, 2026»).
- Búsqueda por palabras clave de Threads: https://developers.facebook.com/documentation/threads/keyword-search.

| Fuente | Qué exige (cita literal) |
| --- | --- |
| X Agreement, B. Removals | Borrar o modificar el contenido borrado o retirado en X «as soon as possible, and in any case within twenty four (24) hours after a written request to do so by X or by an X user» |
| X Agreement, I. Termination | Al terminar el acuerdo: «you shall permanently delete all Licensed Material in all forms and types of media, and copies thereof». Si X lo pide, hay que probarlo «within ten (10) business days». «Licensed Material» es «the X API and X Content». Rige la ley de Texas |
| X Policy, contenido guardado | «If you store X Content offline, you must keep it up to date with the current state of that content on X. Specifically, you must delete or modify any content you have if it is deleted or modified on X.» Plazo: «as soon as reasonably possible, or within 24 hours after receiving a request» |
| X Policy, uso comercial | «Pay-Per-Use access […] is designed for hobbyists, commercial prototyping, early-stage X product integrations, and supporting applications with limited end-users. If you use the X API and X Content beyond this scope, then you must apply (or already subscribe to) an Enterprise plan» |
| Meta, «Retention, Deletion, and Accessibility of Platform Data» | Actualizar o borrar los datos «promptly» si lo piden Meta o el usuario. Borrar todo «as soon as reasonably possible» cuando conservarlo «is no longer necessary for a legitimate business purpose», cuando se deja de operar el servicio, cuando Meta o el usuario lo piden o cuando lo exige la ley |
| Meta, «Prohibited Practices» | «Selling, licensing, or purchasing Platform Data» |
| Threads | Requiere el permiso `threads_keyword_search`. Sin aprobación, «the search will be performed only on posts owned by the authenticated user». Límite: «2,200 queries within a rolling 24-hour period». La página no menciona reglas de almacenamiento |

**Choque a revisar.** La evidencia de PrediGol no se puede borrar y las copias mensuales quedan bloqueadas 12 meses. Con contenido de X o de Meta, eso impediría borrar en 24 horas y borrar «copies thereof».

**Preguntas para el abogado**

1. ¿Cuánto tiempo puede guardar PrediGol los textos de terceros que no vienen de redes, y con qué justificación por finalidad (revisión posterior, auditoría de picks)? Hoy:
   - los extractos de la caché no tienen plazo efectivo;
   - los hechos extraídos, con citas de hasta 300 caracteres, se guardan para siempre;
   - las copias de la base quedan bloqueadas hasta 12 meses.
2. Si se usan redes, ¿basta con guardar su contenido fuera de la evidencia inmutable y fuera de las copias bloqueadas? ¿O la obligación de X alcanza también a lo derivado, como resúmenes o hechos extraídos?
3. ¿Una comunidad pequeña de pago cabe en el acceso «Pay-Per-Use […] with limited end-users» de X, o exigiría el plan Enterprise?
4. En Meta, ¿qué cuenta como «legitimate business purpose» para conservar una publicación de Threads después del partido?
5. Las publicaciones de personas naturales (jugadores, periodistas) se guardarían con su cuenta. ¿Qué obligaciones de la Ley 1581 de 2012 aplicarían (finalidad, aviso, supresión)? Enlaza con las preguntas 2 y 3 del paquete del tramo 1.

## 6. (e) Transfermarkt

**Fuentes, consultadas el 11-nov-2026.** Ninguna página muestra fecha. La investigación del 10-nov no había podido leerlas; hoy sí se leyeron.

- Condiciones de uso en inglés: https://www.transfermarkt.com/intern/anb.
- Condiciones de uso en alemán: https://www.transfermarkt.de/intern/anb.
- Aviso legal: https://www.transfermarkt.com/intern/impressum.

| Cláusula | Qué dice (cita literal) |
| --- | --- |
| 3.2 Derechos | «All rights to programs, services, processes, software, technology, trademarks, inventions, databases, and all material related to Transfermarkt reside exclusively with Transfermarkt. All programs and their contained contents, material, and trademarks are only allowed to be used for the purposes stated in their license agreements. Reproducing programs, services, processes, software, etc. for any purpose is illegal.» La versión alemana limita el uso «ausschließlich zu den in diesen Nutzungsbedingungen genannten Zwecken» |
| 11.1 Extracción automatizada e IA | «The User is not permitted to access or copy the Digital Content using bots, spiders, screen scraping or other automated processes. The user is also prohibited from using the digital content for the training or development of artificial intelligence (AI) […]. Uses for text and data mining (Section 44b UrhG) are expressly reserved.» |
| Uso comercial | No hay una cláusula que lo nombre así, pero la 3.2 limita el uso a los fines de las condiciones |
| 10.1 y 10.2 | Rige el derecho alemán. Para quien no reside en Alemania, son competentes los tribunales de Hamburgo |
| Contacto | Transfermarkt GmbH & Co. KG, Wandsbeker Zollstraße 5a, 22041 Hamburg; info@transfermarkt.de |

**Hechos para el abogado.**

- Las condiciones prohíben justo lo que PrediGol necesitaría: lectura automatizada y uso con IA. Por eso hace falta permiso escrito.
- PrediGol no usa Transfermarkt como fuente. El plan lo descarta salvo permiso escrito (anexo B, valores de mercado de las plantillas).
- Aun así, Exa busca sin filtro de dominios y devolvió 18 páginas de Transfermarkt que hoy están en la caché. Ninguna llegó a la evidencia.

**Preguntas para el abogado**

1. El rastreo lo hace Exa, no PrediGol. Aun así, ¿recibir por Exa extractos de Transfermarkt, guardarlos en caché y leerlos con un modelo para extraer hechos choca con la cláusula 11.1 («copy […] automated processes», «development of AI»)? ¿Conviene excluir sus dominios y borrar esos 18 resultados mientras no haya permiso?
2. ¿Qué alcance pedir en el permiso? Por ejemplo:
   - valores de mercado por plantilla para los modelos internos;
   - cifras agregadas, con atribución, visibles para usuarios de pago;
   - entrega por un medio con licencia (fichero o feed), nunca por extracción.
3. ¿Qué efecto tiene para un usuario en Colombia la reserva de minería de textos (§ 44b UrhG)?

### Borrador del correo de solicitud (no enviado)

Va en inglés porque Transfermarkt publica sus condiciones en alemán y en inglés. Los datos entre corchetes los completa el dueño cuando el abogado apruebe el texto.

> **To:** info@transfermarkt.de
> **Subject:** Request for written permission / data licence – PrediGol (football analysis platform, Colombia)
>
> Dear Transfermarkt team,
>
> We run PrediGol, a football analysis platform operated from Colombia with a small paid membership. We are not a betting operator and we do not take bets.
>
> We have read your Terms of Use, in particular clauses 3.2 and 11.1, and we do not access or copy your content by automated means. We would like to request written permission, or a licence, to use squad market values (team-level totals and, if possible, player values) for two purposes: as an input to our internal statistical models, and as figures shown to our members with clear attribution and a link to Transfermarkt.
>
> Could you tell us whether this is possible, through which channel (a data file, a feed or an API), and on what conditions and at what price? We would also welcome your guidance on how to handle Transfermarkt pages that third-party search providers return to us.
>
> Kind regards,
> [NAME], [ROLE], PrediGol
> [E-MAIL] · [WEBSITE]

## 7. Hallazgos para el dueño

No he tocado ninguno: los resuelven otras piezas o tus decisiones.

| # | Hallazgo | Pieza |
| --- | --- | --- |
| 1 | La purga de la caché no corre: 740 búsquedas caducadas hace más de 14 días siguen guardando extractos de hasta 2.000 caracteres | `INT-B07`, `INT-B06` |
| 2 | Hay 18 resultados de Transfermarkt en la caché, contra la decisión 6 («no usar Transfermarkt antes de la respuesta»). Exa se llama sin excluir dominios | `INT-B01`, `INT-B02` |
| 3 | En `ai/evidence.py`, `transfermarkt.de` figura como «media», mientras `.com` y `.es` están como agregadores | `INT-B01` |
| 4 | Si se enciende Research v2 sin cambios, sus citas literales de hasta 300 caracteres se mostrarían como resumen propio, sin comillas ni autor | `INT-B06`, antes de encender Research v2 |
| 5 | Una evidencia que no se borra y unas copias bloqueadas 12 meses no permiten borrar contenido de redes en 24 horas | Diseño de `INT-B06` e `INT-B11` |

## 8. Método y limitaciones

- **Términos.** Se leyeron en su fuente oficial con herramientas de lectura web; los PDF de Exa y de la Decisión 351, con su lector de PDF. Las citas son literales. Las columnas de lectura son mías y no son interpretación jurídica.
- **Páginas que no se pudieron leer.** La Ley 23 en la Secretaría del Senado y sus artículos 31 a 36 en Función Pública. En su lugar se usó la copia del SISJUR. El artículo 16 de la Ley 1915 se leyó resumido, no literal.
- **Fechas.** Las condiciones cambian, por eso cada fuente lleva su fecha. La política de desarrolladores de X, las condiciones de Transfermarkt y el texto del PDF de Exa no muestran ninguna.
- **Producción.** Dos consultas agregadas de solo lectura, a las 04:38 UTC; la tercera no terminó. No se leyó ni se copió contenido de terceros.
- **Lo que este anexo no cubre.** Las condiciones particulares que pudieran tener las cuentas de Exa o de API-Football, y los términos de cada medio concreto.

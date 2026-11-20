# Disciplina de conocimiento y regla de alta de proveedores

*PM-00-04 del Plan Maestro PM (OP-05) · código DOC-007 · escrito el 20-nov-2026 · próxima revisión: 20-feb-2027 y
después cada trimestre.*

Este documento fija cuatro cosas que cada sesión volvía a comprobar por su cuenta: **qué conocimiento puede entrar en
PrediGol y por dónde**, **qué hay que contestar antes de dar de alta una API o una fuente nueva**, **qué no se da de alta
nunca** y **qué se comprueba antes de dar por bueno un experimento**. Incluye la página interna de lecturas (sección 6).
Vale para el código, para los prompts, para el LAB y para cualquier plan nuevo. Lo que aquí se prohíbe no se activa con un
interruptor: hace falta cambiar este documento por PR, con la firma del dueño.

Fuentes: plan maestro PM, secciones 7 («RapidAPI: sirve para descubrir, no para contratar») y 10 («Biblioteca científica»)
en [`PLAN_MAESTRO_INNOVACION_COBERTURA_2026.md`](PLAN_MAESTRO_INNOVACION_COBERTURA_2026.md); la investigación de recursos
gratuitos del 18-nov-2026 (secciones 4, 5, 6, 8 y 12) y su catálogo de 628 recursos, que viven en el trabajo de
planificación y no en el repositorio (los identificadores `R-NNNN` de abajo son filas de ese catálogo); el anexo D del plan
(110 recursos de API); y la clasificación de dominios
[`backend/config/sources/exclusion_dominios_2026-11-16.csv`](../../backend/config/sources/exclusion_dominios_2026-11-16.csv)
(de la sesión de Intelligence; aquí solo se lee).

## 1. Tres clases de conocimiento que no se mezclan

| Clase | Qué es | Dónde vive | Regla |
| --- | --- | --- | --- |
| **Método** | Una técnica publicada (un intervalo, un modelo, un contraste) | En el código que la aplica y en su documento | Se cita (autor, año, DOI o enlace). No se copia su texto |
| **Evidencia de partido** | Hechos de un partido concreto: alineaciones, bajas confirmadas, cuotas, estadísticas | Hoja de hechos del partido, cada hecho con su fuente y su fecha | **Es lo único que entra en un prompt** |
| **Datos de entrenamiento** | Series para ajustar o evaluar modelos | Base propia y LAB | Solo con una licencia que permita ese uso, anotada en el catálogo |

Consecuencias prácticas:

1. **Ningún libro ni artículo entra en un prompt**, ni entero ni a trozos, ni como «contexto experto». Si un método
   sirve, se programa y se prueba; el modelo de lenguaje no lo «aplica» leyéndolo.
2. **Ningún modelo de lenguaje toca probabilidades.** Los modelos dan los números, el modelo de lenguaje explica y la
   decisión es código. Un método nuevo cambia una cifra solo a través del código, con su protocolo y su firma.
3. **Un método se cita donde se aplica.** El docstring o el documento de la pieza nombra la referencia y la fecha en que se
   comprobó. Si la referencia no se pudo abrir, se dice («no reabierta»), no se da por buena.
4. **Un dato de entrenamiento sin licencia leída no se usa**, aunque sea descargable. «Público» no es «reutilizable».
5. **La evidencia de partido lleva su origen.** Un hecho sin fuente ni fecha no entra en la hoja de hechos, y por tanto
   tampoco en el prompt.
6. **Ningún texto protegido se copia** al repositorio, a la base de conocimiento, a la web ni a un documento del
   proyecto. Se enlaza, se resume con palabras propias y se cita la idea. Aplicar un método publicado no requiere licencia;
   reproducir su texto, sí.

## 2. Origen antes que etiqueta

Lo que hace fiable un dato es **quién lo produce**, no el nombre con que se anuncia, la licencia que le pone quien lo
recopila ni la red por la que llega.

- Una oferta llamada «Sofascore», «FlashScore» o «Free Football API» no es de esas marcas si la publica otra cuenta: se
  mira el editor, no el título.
- **Una licencia abierta solo vale lo que valgan los derechos de quien la otorga.** Un dataset con etiqueta CC0 o MIT
  recopilado de un sitio que prohíbe reutilizar sus datos sigue teniendo el origen restringido; la etiqueta no lo «limpia»
  (ejemplos en la sección 4.4).
- Una baja publicada por el club en su web, en su cuenta oficial o en una nota de prensa es la misma afirmación: lo que la
  eleva a confirmada es que la emite el club. Una red social es un **canal**, no una fuente.
- Un agregador que repite a otros hereda su origen; si no lo declara, se trata como «origen no declarado».
- Las clases de dominio del CSV de Intelligence (`oficial`, `medio_real`, `datos_reconocidos`…) describen el origen. La
  etiqueta que ponga un proveedor sobre su propia credibilidad no sustituye a esa clasificación.

## 3. Alta de un proveedor o de una API: preguntas obligatorias

Antes de incorporar cualquier API, fuente o servicio externo (de datos, de vigilancia, de correo, de lo que sea) se
contestan **por escrito** las preguntas de abajo, con enlace a la página donde consta cada respuesta y la fecha de lectura.
Las respuestas van a la fila del recurso en el anexo D (columnas `necesidad_que_resuelve`, `lo_cubre_api_football`,
`origen_del_dato`, `licencia`, `uso_comercial`, `almacenamiento_redistribucion`, `procesamiento_ia`, `coste_operativo`,
`decision_plan_maestro`) o, si el recurso no está, a una fila nueva. **Si una respuesta es «no sé», el alta no sigue.**

### 3.1 Las cuatro preguntas sobre quién lo da

1. **¿Quién es el editor?** El titular del dato o un tercero que lo revende o lo extrae.
2. **¿Tiene términos propios?** Términos del editor, no solo los de la plataforma que lo lista.
3. **¿Declara de dónde sale el dato?** Si no lo declara, se trata como extracción no autorizada.
4. **¿El precio es creíble para un dato licenciado?** Un dato en vivo de ligas de primer nivel casi gratis es una señal de
   alarma, no una ganga.

### 3.2 Las preguntas de necesidad y de coste

5. **¿Qué necesidad concreta resuelve?** Una frase, con la pantalla, el trabajo o el protocolo que la usa. «Puede servir»
   no es una necesidad.
6. **¿Lo da ya API-Football?** Se mira el inventario del anexo C (1.049 campos de 39 endpoints) y la cobertura medida. Si lo
   da, no se paga dos veces (IA-043).
7. **¿Hay una alternativa gratuita u oficial?** Una web o un RSS oficial, un dato abierto con licencia clara o algo que ya
   está en la base.
8. **¿Qué permiten los términos?** Tres respuestas separadas: **uso comercial**, **almacenamiento y redistribución**, y
   **procesamiento con IA** (pasarlo a un modelo de lenguaje). Cada una «sí», «no» o «con condiciones», con la cláusula.
9. **¿Cuánto cuesta y en qué presupuesto entra?** Coste al mes en el uso previsto, límites del plan y qué pasa al
   superarlos. Va a la partida correspondiente del anexo F.
10. **¿Quién lo mantiene?** Qué código hay que escribir y vigilar, qué secreto añade (y dónde se guarda), qué aviso salta si
    deja de responder y cómo se retira.

### 3.3 Lo que nunca se da de alta

- **Ofertas de terceros en RapidAPI** o en cualquier mercado de APIs: RapidAPI no licencia datos ni garantiza su origen.
  Solo vale una API publicada allí por su propio titular, y entonces se contrata con el titular.
- **Extractores web** (servicios de scraping como Apify y similares, y bibliotecas que leen webs ajenas) y **APIs internas
  o no oficiales** de webs y aplicaciones (Sofascore, FotMob, FIFA, UEFA, WhoScored y las de la sección 4).
- **Telegram como fuente**: sus términos vetan usar sus datos con IA; solo se usa como canal de salida propio.
- Cualquier recurso cuyo uso exija **aceptar términos, crear una cuenta o firmar**, mientras no lo haga el dueño. La sesión
  prepara el alta, deja la pieza apagada tras su interruptor `FBI_*` y lo reporta como pendiente del dueño.

### 3.4 Quién decide

La sesión prepara las respuestas; el **dueño** decide el alta, lee y acepta los términos y crea la cuenta. Si una respuesta
de la pregunta 8 es dudosa (uso comercial ambiguo, datos personales, procesamiento con IA), la duda se resuelve con
revisión legal **antes** del alta, no después, y mientras tanto el recurso cuenta como «no».

## 4. Lista de exclusión inicial

Estado del 18–20-nov-2026. Una entrada nueva se añade por PR con su motivo y su fuente; una entrada solo sale si su titular
publica términos que lo permitan, se contestan otra vez las preguntas de la sección 3 y el dueño lo firma.

### 4.1 Ofertas de terceros en RapidAPI

| Qué | Por qué | Estado |
| --- | --- | --- |
| «Sofascore» en RapidAPI (editor «Api Dojo») | Sofascore declara que no ofrece API | No usar |
| «FlashScore», «LiveScore Football» en RapidAPI | Cuenta genérica; editor «datascraper» | No usar |
| «Free Football API Data» y similares | Origen no declarado | No usar |
| APIs no oficiales de X e Instagram | Extracción declarada | No usar |
| API-Football en RapidAPI (editor «api-sports») | Legítima, pero duplica lo contratado directamente | No contratar |

### 4.2 Extractores web y bibliotecas de scraping

| Qué | Por qué | Estado |
| --- | --- | --- |
| Servicios de extracción (Apify y similares) aplicados a webs de fútbol | Trasladan a PrediGol el riesgo legal del sitio extraído | No usar |
| Bibliotecas `ScraperFC`, `soccerdata`, `understat` y `worldfootballR` (R-0217, R-0222, R-0228, R-0233) | Leen webs cuyos términos prohíben la extracción | No instalar en producción ni en el LAB |
| Cualquier robot propio que lea una web ajena | Nada de scraping (regla del plan) | No escribir |

### 4.3 APIs internas, sitios que prohíben la extracción y APIs sin origen declarado

| Qué | Por qué | Estado |
| --- | --- | --- |
| Sofascore, API interna (R-0073, R-0391) | Declara que no puede dar sus datos como API por sus acuerdos con proveedores | No usar, ni directamente ni por extractores |
| FotMob, API interna (R-0055, R-0381) | Sus términos prohíben robots y scraping; uso personal no comercial | No usar |
| FIFA y UEFA, APIs internas (R-0053, R-0080) | Uso privado no comercial; prohíben programas automatizados, scraping o entrenar IA con su contenido | No automatizar |
| Fantasy Premier League, API no oficial (R-0052) | Uso privado y personal; prohíbe crear bases de datos | No usar |
| WhoScored (R-0395) y Understat (R-0081) | Prohíben copiar o descargar; Understat no tiene API ni licencia | No usar |
| Transfermarkt, Flashscore y football-data.co.uk | Documentados en el proyecto: prohíben bots, IA, minería o uso comercial | No usar |
| TheStatsAPI, PitchAPI y OpenFoot | Mapas de tiros y de calor sin declarar de dónde sale el dato | No usar hasta que acrediten su licencia por escrito |
| Kalshi y Polymarket | Licencias personales; prohíben robots, minería o cualquier uso en IA | No usar |
| ScoreBat Video API (R-0071) | La alternativa con condiciones claras es el reproductor oficial de vídeos de canales oficiales | No usar |
| IFAB, texto de las Reglas (R-0626) | Prohíbe reproducir; licencia no comercial | No ingerir; redacción propia revisada por una persona |
| RSSSF (R-0387) | Todos los derechos reservados | Solo consulta puntual con cita; nunca en bloque |
| Telegram como fuente de datos | Términos contra el uso con IA | Solo canal de salida |

### 4.4 Datasets con etiqueta abierta y origen restringido

| Dataset | Etiqueta | Origen | Estado |
| --- | --- | --- | --- |
| Transfermarkt de dcaribou (R-0125) | CC0 | Extracción de Transfermarkt | No usar |
| European Soccer Database (R-0123) | ODbL | football-data.co.uk y sofifa; el autor pide no hacer uso comercial | No usar |
| Atributos FIFA 23 (R-0124) | CC0 | sofifa; derechos de EA Sports | No usar |
| Beat the Bookie (R-0115) | CC BY-SA 4.0 | Extracción de portales sin nombrar | No usar, ni como referencia interna |
| Club Football Match Data 2000–2025, DataHub (ligas europeas), lesiones de la Premier 2012–2025, engsoccerdata | MIT, dominio público, CC BY 4.0, GPL | Toman de fuentes que no permiten reutilizar | No usar |

### 4.5 Dominios de noticias

| Qué | Por qué | Estado |
| --- | --- | --- |
| Dominios de las clases `apuestas_o_pronosticos` (68), `agregador_o_refrito` (26), `contenido_generado_o_baja_calidad` (21) y `no_futbol_u_otro` (2) del CSV de dominios | 117 dominios que no aportan origen propio | No dar de alta como fuente |
| Dominios de la clase `dudoso` (168) del mismo CSV | Sin evidencia suficiente | Solo con revisión previa, dominio a dominio |

El CSV de dominios (570 filas clasificadas el 16-nov-2026) lo mantiene la sesión de Intelligence; este documento no lo
cambia y, si ambos discrepan, manda el CSV.

## 5. Lista de comprobación de un experimento

Vale para el LAB, para un protocolo de patrones y para cualquier comparación en sombra. Sigue el protocolo de
investigación de patrones de la investigación del 18-nov-2026 (sección 12). Quien presenta un resultado marca cada punto;
un punto sin marcar se dice en el informe, no se omite. **Los umbrales que el protocolo propone están sin validar**: se
fijan con simulación sobre datos propios antes de adoptarse.

### 5.1 Tres carriles que no se mezclan

| Carril | Qué contiene | Dónde puede aparecer |
| --- | --- | --- |
| A · Informativo | Estadística descriptiva con n, intervalo y comparación con la liga | Pantallas, sin lenguaje de señal |
| B · LAB privado | Experimentos preregistrados y en sombra | Solo en el LAB |
| C · Capacidad autorizada | Lo que pasó la puerta y firmó el dueño | Producto, tras su interruptor `FBI_*` |

### 5.2 Los trece pasos

| Paso | Qué se marca | Dónde existe ya |
| --- | --- | --- |
| 1. Pregunta y mecanismo | Qué se espera y por qué, escrito **antes** de mirar los datos | Parcial |
| 2. Filtro de la estadística | La estadística es estable, discrimina entre equipos y no repite a otra ([Franks et al. 2016](https://arxiv.org/abs/1609.09830)) | Nuevo |
| 3. Registro previo | Datos, ventana, métrica, reglas de PASA y RECHAZA y número de comparaciones, con huella SHA-256 y firma según IA-143 | `fbi/research/protocol.py` |
| 4. Hoja de fugas | Cada variable con el momento en que se conoce; el modelo solo ve lo sabido antes del saque inicial y las cuotas de ese momento (IA-061) ([Kapoor y Narayanan](https://arxiv.org/abs/2207.07048)) | `fbi/ai/known_at.py` y la auditoría nocturna |
| 5. Partición en tres tramos | Exploración, confirmación y una bóveda que se abre una sola vez; la selección de variables va **dentro** de cada tramo, nunca antes de partir | Nuevo: falta la bóveda |
| 6. Líneas base | La tasa base de la liga, el modelo vigente y el mercado sin margen. Sin comparar con los tres, no hay mejora | `fbi/backtesting/walkforward.py`, `fbi/evaluation/board.py` |
| 7. Estimar con contracción | Tasas encogidas hacia la media de la liga, nunca crudas con n pequeño; muestra mínima fijada de antemano y, por debajo, «no evaluado» | `fbi/players/rates.py`; árbitro |
| 8. Incertidumbre con dependencia | Wilson para proporciones; errores agrupados por partido; bootstrap por jornadas | `fbi/statmath/formulas.py`, `fbi/research/pattern_search.py`, `fbi/evaluation/board.py` |
| 9. Multiplicidad | Libro con **todas** las pruebas hechas; control de falsos descubrimientos en el cribado ([Benjamini y Hochberg 1995](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x)) | Parcial: hoy solo Bonferroni en `fbi/research/pattern_search.py` |
| 10. Estabilidad y placebos | Mismo signo en las dos mitades y en dos tercios de las competiciones | Parcial |
| 11. Réplica prospectiva | Datos posteriores al registro, en sombra | Parcial |
| 12. Valor incremental | Métricas de probabilidad (log loss o Brier y calibración, no solo aciertos), frente al modelo vigente y al mercado | `fbi/models/metrics.py` |
| 13. Veredicto y memoria | Se guarda también el resultado negativo, con fecha; el texto no afirma causalidad ni rentabilidad | Sí |

Además, en cada experimento: **datos con licencia** para ese uso (sección 1); **coste** en peticiones a API-Football y en
tokens, contra el presupuesto; y **nada sale de sombra** sin su control, su firma y su interruptor.

### 5.3 Niveles de evidencia

| Nivel | Qué significa | Dónde puede aparecer |
| --- | --- | --- |
| E0 | Anécdota o muestra menor que el mínimo | En ningún sitio como tendencia |
| E1 | Descriptivo con n e intervalo, encogido | Carril A |
| E2 | Asociación que sobrevive a la multiplicidad, la estabilidad y los placebos | Carril B; hipótesis registrada |
| E3 | E2 replicado de forma prospectiva | Carril B; factor de contexto candidato |
| E4 | E3 con mejora validada frente al mercado | Carril C, solo con firma del dueño |

Tres recordatorios del mismo protocolo: quien prueba muchas variantes y se queda con la mejor encuentra «señal» aunque no
la haya; una racha corta tiene un intervalo enorme («8 de los últimos 10» es compatible con una moneda al aire); y un
patrón conocido puede ser cierto y no aportar nada, porque el mercado ya lo descuenta. Separar lo exploratorio de lo
confirmatorio es la recomendación central de
[Gelman y Loken](https://sites.stat.columbia.edu/gelman/research/unpublished/p_hacking.pdf).

## 6. Página interna de lecturas

Biblioteca de libros, cursos y guías **de acceso legal**, ordenada por método y por el lugar de PrediGol donde se aplica.
Todo se lee en el sitio de su titular: aquí no se copia ni se resume texto protegido, solo se dice qué método aporta y
dónde sirve. Los artículos (168 en el catálogo) los indexa por método la tarea PM-11-08; los métodos ya en uso están en la
tabla de la sección 10 del plan.

### 6.1 Gratis para leer no es libre para reutilizar

| Categoría | Qué permite | Columna «Acceso» de abajo |
| --- | --- | --- |
| **Libre para reutilizar** | Copiar y adaptar con atribución (CC BY), sin obligaciones (CC0) o conservando el aviso (MIT, BSD, Apache) | `reutilizable` |
| **Gratis para leer, no comercial o sin derivadas** | Leer, enlazar y citar la idea (CC BY-NC, BY-NC-SA, BY-NC-ND) | `leer (NC)` |
| **Gratis para leer, derechos reservados** | Leer y enlazar | `leer (©)` |
| De pago | Nada sin comprar | No se incluye |

Ni siquiera lo `reutilizable` se pega en un prompt (sección 1). Lo `leer (NC)` no puede acabar en el producto: un PrediGol
con suscripciones es un uso comercial.

### 6.2 Lista corta

Cubre casi todo lo que el LAB necesita: [ISLP](https://www.statlearning.com/), [FPP en Python](https://otexts.com/fpppy/),
las guías de scikit-learn de [calibración](https://scikit-learn.org/stable/modules/calibration.html) y de
[errores comunes](https://scikit-learn.org/stable/common_pitfalls.html), y
[Rules of ML](https://developers.google.com/machine-learning/guides/rules-of-ml).

### 6.3 Por método y lugar de aplicación

| Método | Lectura | Acceso | Dónde se aplica en PrediGol |
| --- | --- | --- | --- |
| Validación temporal (origen rodante) y pronóstico distribucional | [FPP3](https://otexts.com/fpp3/) (R-0404) y [FPP en Python](https://otexts.com/fpppy/) (R-0405) | leer (©) | `fbi/backtesting/walkforward.py`, `fbi/countcal/walkforward.py` |
| Calibración: sigmoide, isotónica (solo con más de unos 1.000 casos), temperatura multiclase; calibrar con datos distintos de los de ajuste | [scikit-learn: calibración](https://scikit-learn.org/stable/modules/calibration.html) (R-0428) | reutilizable (BSD) | `fbi/countcal/calibrator.py`; retador barato de 1X2 en el LAB |
| Fugas por seleccionar variables antes de partir; preprocesado dentro de la validación | [scikit-learn: errores comunes](https://scikit-learn.org/stable/common_pitfalls.html) (R-0429) | reutilizable (BSD) | Sección 5, pasos 4 y 5 |
| Disciplina del registro de modelos: primer modelo simple, evaluar con datos posteriores | [Rules of ML](https://developers.google.com/machine-learning/guides/rules-of-ml) (R-0426) | reutilizable (CC BY 4.0) | `fbi/models/families.py` (ninguna familia entra por existir) |
| Remuestreo, regularización y árboles | [ISLR2 e ISLP](https://www.statlearning.com/) (R-0399, R-0400) y sus [cursos](https://www.statlearning.com/online-courses) (R-0421) | leer (©) | Base común para leer los informes del LAB |
| Sesgo y varianza, boosting, validación | [Elements of Statistical Learning](https://hastie.su.domains/ElemStatLearn/) (R-0412) | leer (©) | Por qué más flexibilidad no mejora con pocas variables |
| Sesgo de seleccionar variables fuera del remuestreo | [Feature Engineering and Selection](https://feat.engineering/) (R-0403) | leer (©) | Cualquier ampliación de las variables de `fbi/features` |
| Calibración, espacio de estados, decisión bajo incertidumbre | [Probabilistic ML](https://probml.github.io/pml-book/book1.html) (R-0408, R-0409) | leer (NC) | Retador dinámico y regla de valor con intervalo (LAB) |
| Importancias (SHAP, ALE, permutación) sin leerlas como efectos causales | [Interpretable ML](https://christophm.github.io/interpretable-ml-book/) (R-0407) | leer (NC) | Textos de explicación (`fbi/api/services/explain.py`) |
| Modelos jerárquicos, contracción y flujo bayesiano | [BDA3](https://sites.stat.columbia.edu/gelman/book) (R-0401), [curso de Aalto](https://github.com/avehtari/BDA_course_Aalto) (R-0419), [BMCP](https://bayesiancomputationbook.com/welcome.html) (R-0413); [Statistical Rethinking 2025](https://github.com/rmcelreath/stat_rethinking_2025) (R-0432) | leer (NC); el repositorio de Statistical Rethinking es reutilizable (CC0) | Contracción de tasas (sección 5, paso 7); un retador bayesiano solo si se aprueba |
| Regresión aplicada | [Regression and Other Stories](https://avehtari.github.io/ROS-Examples/) (R-0411) | leer (uso personal) | Lectura de contrastes del LAB |
| Pronóstico en general | [Petropoulos et al. 2022](https://doi.org/10.1016/j.ijforecast.2021.11.001) (R-0425) | reutilizable (CC BY 4.0) | Consulta por método |
| Cómo dibujar la incertidumbre | [Fundamentals of Data Visualization](https://clauswilke.com/dataviz/) (R-0406), capítulo 16; [Understanding Uncertainty](http://understandinguncertainty.org/visualising-uncertainty) (R-0433) | leer (NC); licencia no revisada | Bandas e intervalos de las gráficas |
| Accesibilidad de gráficas | [W3C WAI: imágenes complejas](https://www.w3.org/WAI/tutorials/images/complex/) (R-0434) | licencia de documentos del W3C, no revisada | Texto alternativo de gráficas en la web |
| Simulación de goles con Poisson | [Curso Soccermatics](https://soccermatics.readthedocs.io) (R-0420), bloque 5 | leer (©) | `fbi/models/goals.py` (Poisson y Dixon-Coles) |
| Modelos de goles ya implementados | [penaltyblog](https://penaltyblog.readthedocs.io/en/latest/models/overview.html) | reutilizable (MIT) | Contraste barato en el LAB |
| Pitch control y EPV | [Friends of Tracking](https://github.com/Friends-of-Tracking-Data-FoTD/LaurieOnTracking) (R-0422) | reutilizable (MIT, código) | Formación; nada ejecutable sin datos de seguimiento |
| Pruebas de datos y de modelo | [Made With ML](https://madewithml.com/) (R-0424) | reutilizable (MIT) | Lecciones; su pila ya está descartada |
| Predicción conforme | [Angelopoulos y Bates 2021](https://arxiv.org/abs/2107.07511) (R-0436); [MAPIE](https://mapie.readthedocs.io/en/latest/) (R-0438) | licencia del preprint no comprobada; MAPIE BSD | Intervalos de líneas (`fbi/models/line_intervals.py`), solo como lectura |

Fuera de la página: los libros de pago (Soccermatics en papel, The Expected Goals Philosophy, Football Hackers: R-0415 a
R-0417), que no aportan método que no esté ya en fuentes gratuitas, y cualquier lectura cuya licencia no se haya leído.

### 6.4 Dónde seguir la literatura sin pagar

| Recurso | Condición | Uso |
| --- | --- | --- |
| [arXiv](https://info.arxiv.org/help/api/tou.html) (R-0002) | API gratuita; una petición cada 3 s y una conexión; metadatos CC0, texto según cada artículo | Búsqueda mensual en `stat.AP` y `cs.LG` |
| [OpenAlex](https://help.openalex.org/access/pricing/) | Registros CC0; cupo gratuito diario | Saber si un DOI tiene copia abierta |
| [Semantic Scholar](https://www.semanticscholar.org/product/api) | Cupo compartido sin clave | Leer primero el resumen |
| [Journal of Sports Analytics](https://doaj.org/toc/2215-020X) | Acceso abierto según DOAJ | Lectura directa |

Lo que aparezca entra como **método candidato** con su referencia, nunca como texto en un prompt, y pasa por la sección 5
antes de tocar una cifra.

## 7. Revisión trimestral

Próxima el **20-feb-2027**, después cada tres meses. Se releen la lista de exclusión (sección 4), los términos de los
proveedores dados de alta (cambian: los de UptimeRobot cambiaron el 26-may-2026), las licencias y enlaces de la página de
lecturas (sección 6) y las referencias marcadas «no reabierta». Lo que cambie entra por PR con su fecha de lectura.

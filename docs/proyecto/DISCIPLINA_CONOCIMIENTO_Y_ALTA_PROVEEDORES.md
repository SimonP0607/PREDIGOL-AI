# Disciplina de conocimiento y regla de alta de proveedores

*PM-00-04 del Plan Maestro PM (OP-05) · código DOC-007 · escrito el 20-nov-2026 · próxima revisión: 20-feb-2027 y
después cada trimestre.*

Este documento fija dos cosas que cada sesión volvía a comprobar por su cuenta: **qué conocimiento puede entrar en
PrediGol y por dónde**, y **qué hay que contestar antes de dar de alta una API o una fuente nueva**. Vale para el código,
para los prompts, para el LAB y para cualquier plan nuevo. Lo que aquí se prohíbe no se activa con un interruptor: hace
falta cambiar este documento por PR, con la firma del dueño.

Fuentes: plan maestro PM, secciones 7 («RapidAPI: sirve para descubrir, no para contratar») y 10 («Biblioteca científica»)
en [`PLAN_MAESTRO_INNOVACION_COBERTURA_2026.md`](PLAN_MAESTRO_INNOVACION_COBERTURA_2026.md); anexo D del plan (catálogo de
110 recursos de API, que vive en el trabajo de planificación y no en el repositorio); clasificación de dominios
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

## 2. Origen antes que etiqueta

Lo que hace fiable un dato es **quién lo produce**, no el nombre con que se anuncia ni la red por la que llega.

- Una oferta llamada «Sofascore», «FlashScore» o «Free Football API» no es de esas marcas si la publica otra cuenta: se
  mira el editor, no el título.
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
- **Scraping** de webs, aplicaciones o redes, y **APIs no oficiales** (incluidas las de X e Instagram que declaran
  extracción).
- **Telegram como fuente**: sus términos vetan usar sus datos con IA; solo se usa como canal de salida propio.
- Cualquier recurso cuyo uso exija **aceptar términos, crear una cuenta o firmar**, mientras no lo haga el dueño. La sesión
  prepara el alta, deja la pieza apagada tras su interruptor `FBI_*` y lo reporta como pendiente del dueño.

### 3.4 Quién decide

La sesión prepara las respuestas; el **dueño** decide el alta, lee y acepta los términos y crea la cuenta. Las dudas
legales (uso comercial ambiguo, datos personales, procesamiento con IA) van al abogado antes del alta, no después.

## 4. Lista de exclusión inicial

| Qué | Por qué | Estado |
| --- | --- | --- |
| «Sofascore» en RapidAPI (editor «Api Dojo») | Sofascore declara que no ofrece API | No usar |
| «FlashScore», «LiveScore Football» en RapidAPI | Cuenta genérica; editor «datascraper» | No usar |
| «Free Football API Data» y similares | Origen no declarado | No usar |
| API-Football en RapidAPI (editor «api-sports») | Legítima, pero duplica lo contratado directamente | No contratar |
| APIs no oficiales de X e Instagram | Extracción declarada | No usar |
| Telegram como fuente de datos | Términos contra el uso con IA | Solo canal de salida |
| Dominios de las clases `apuestas_o_pronosticos` (68), `agregador_o_refrito` (26), `contenido_generado_o_baja_calidad` (21) y `no_futbol_u_otro` (2) del CSV de dominios | 117 dominios que no aportan origen propio | No dar de alta como fuente |
| Dominios de la clase `dudoso` (168) del mismo CSV | Sin evidencia suficiente | Solo con revisión previa, dominio a dominio |

El CSV de dominios (570 filas clasificadas el 16-nov-2026) lo mantiene la sesión de Intelligence; este documento no lo
cambia y, si ambos discrepan, manda el CSV. Una entrada nueva en esta lista se añade por PR con su motivo y su fuente.

## 5. Lista de comprobación de un experimento

Antes de dar por bueno un resultado del LAB, de un protocolo o de una comparación en sombra, quien lo presenta marca cada
punto. Un punto sin marcar se dice en el informe; no se omite.

1. **Pregunta y criterio escritos antes de mirar los datos**: protocolo con su huella SHA-256 registrada
   (`fbi/research/protocol.py`) y firma según IA-143.
2. **Corte temporal sin fugas**: el modelo solo ve lo que se sabía antes del saque inicial; las cuotas son las de ese
   momento (IA-061).
3. **Muestra mínima** fijada de antemano, con su intervalo (Wilson para proporciones). Bajo la muestra, «no evaluado», no
   «ni bien ni mal».
4. **Línea base**: el modelo vigente y el mercado. Sin comparar con ambos, no hay mejora.
5. **Métricas propias de probabilidades**: log loss o Brier y calibración, no solo aciertos.
6. **Comparaciones múltiples**: cuántas variantes se probaron; con muchas, control de falsos descubrimientos.
7. **Datos con licencia** para ese uso (sección 1).
8. **Coste**: peticiones a API-Football y tokens gastados, contra el presupuesto.
9. **Resultado negativo registrado** igual que uno positivo, con fecha.
10. **Nada sale de sombra** sin su control, su firma y su interruptor.

## 6. Lecturas y vigilancia bibliográfica

La ruta de estudio es la tabla de métodos de la sección 10 del plan (Wilson; Poisson, Dixon-Coles y Elo; plus-minus de
jugadores; fiabilidad y resolución; capacidad predictiva superior; control de falsos descubrimientos; frecuencias
naturales; paleta para daltonismo; ventaja de local; patrones contra inyección), con el lugar donde se aplica cada uno y si
la referencia se comprobó. Se ordena por método y lugar de aplicación en PM-11-08.

- **Vigilancia mensual**: una búsqueda en arXiv (`stat.AP`, `cs.LG`) con su API oficial (anexo D, R-0002: una petición
  cada 3 s y una conexión). Lo que aparezca entra como **método candidato**, nunca como texto en un prompt.
- **Revisión trimestral** (próxima el 20-feb-2027): se releen esta lista de exclusión, los términos de los proveedores
  dados de alta (cambian: los de UptimeRobot cambiaron el 26-may-2026) y las referencias marcadas «no reabierta».

# IA en PrediGol: qué hay hoy, cuánto costaría y cómo debería funcionar (sin implementar)

> **Superado el 8-oct-2026** por `docs/owner/PREDIGOL_AI_REPORT_2026-10-08.md` (precios verificados de nuevo, volumen real medido y la capa de decisión IA ya implementada en modo shadow) y `docs/ai/AI_DECISION_LAYER.md`. Se conserva como registro de la decisión anterior.

**Estado: DEFERRED.** No se ha creado ninguna cuenta ni se ha configurado ninguna clave. Hoy la página *Evolución* la
alimenta un **monitor determinista** (reglas fijas), no una IA, y la página *IA e investigación* funciona sin modelo
de lenguaje: el informe diario lleva solo datos de la plataforma y la revisión de picks aplica solo sus reglas. El
tope mensual configurado es 20 USD y 30 preguntas al día; gastado: 0.

## 1. Lo que hay hoy (y lo que no)

| Pieza | Qué hace | ¿Es IA? |
|---|---|---|
| Monitor diario (`research_monitor`) | compara la evaluación prospectiva y las auditorías con el mercado; si una cifra está a ≥ 3 errores estándar de cero, guarda el hallazgo y propone una hipótesis "Sistema" | **No**: reglas fijas |
| Investigación semanal (`research_v2_weekly`) | walk-forward completo cuando cambia el código de los modelos o el dataset, o cada 4 semanas | **No**: estadística |
| Informe diario y revisión de picks (`ai_daily_report`, `ai_pick_review`) | sin claves: datos de la plataforma y reglas; con claves: añadiría búsqueda web con fuentes | solo si el dueño configura un proveedor |

Nada "aprende solo". Ningún resultado cambia una regla, un umbral, un modelo o un pick por sí mismo.

## 2. Precios (USD por millón de tokens, nivel estándar, leídos el 5 oct 2026)

| Modelo | Entrada | Entrada en caché | Salida | Lote (entrada / salida) |
|---|---:|---:|---:|---|
| OpenAI gpt-6-astra (tope) | 10,00 | 1,00 | 50,00 | 5 / 25 |
| OpenAI gpt-6.1-sol (medio) | 2,00 | 0,10 | 10,00 | 1 / 5 |
| OpenAI gpt-6-luna (pequeño) | 0,10 | 0,01 | 0,50 | 0,05 / 0,25 |
| Anthropic Claude Opus 5.5 | 4 | 0,20 | 20 | 2 / 10 |
| Anthropic Claude Sonnet 5.5 | 2 | 0,20 | 10 | 1 / 5 |
| Anthropic Claude Haiku 4.5 | 1 | 0,10 | 5 | 0,50 / 2,50 |
| Google Gemini 3.1 Pro (preview, ≤ 200k) | 2,00 | 0,20 | 12,00 | 1 / 6 |
| Google Gemini 3.1 Flash-Lite | 0,25 | 0,025 | 1,50 | 0,125 / 0,75 |
| DeepSeek flash (V4.1) | 0,30 (valle 0,15) | 0,006 | 1,20 (0,60) | −50 % en valle |
| Mistral Medium 3.5 (UE) | 1,5 | −90 % | 7,5 | −50 % |

Búsqueda web: OpenAI y Anthropic $10 por 1.000 búsquedas (+ tokens); Gemini 5.000 gratis al mes y luego $14/1.000;
Groq $5/1.000; Mistral $30/1.000; DeepSeek no tiene (p. ej. Brave $5/1.000).

## 3. Coste mensual estimado (30 días)

Tareas: resumen de noticias (25k tokens de entrada, 1,5k de salida, 3 búsquedas), análisis de partido (12k/1,5k),
hipótesis (22k/3k), explicación de anomalía (13k/1,5k), propuesta de experimento (29k/4,5k) y una revisión diaria
(55k/6k). Mezcla 40/40/10/6/4 %. Sin caché (estimación prudente).

| Nivel | Configuración | 50 tareas/día | 100 tareas/día | 500 tareas/día |
|---|---|---:|---:|---:|
| BAJO-A | gpt-6-luna (+ Flex/lote) | $21 | $42 | $212 |
| BAJO-B | Gemini 3.1 Flash-Lite (+ lote) | $9 | $17 | $266 |
| BAJO-C | DeepSeek flash (valle) + Brave | $18 | $36 | $180 |
| MEDIO-A | Claude Sonnet 5.5 + Haiku 4.5 | $85 | $165 | $804 |
| MEDIO-B | gpt-6.1-sol + gpt-6-luna | $67 | $130 | $629 |
| MEDIO-C | Gemini 3.1 Pro + Flash-Lite | $56 | $107 | $696 |
| ALTO-A | Claude Opus 5.5 para todo | $191 | $372 | $1.818 |
| ALTO-B | gpt-6-astra (o Claude Fable 5.1) para todo | $450 | $875 | $4.275 |

Para ~100 usuarios (≈ 50–100 tareas/día): **bajo $9–42, medio $56–165, alto $191–875 al mes.** En el nivel barato,
las búsquedas son el 50–85 % del coste: una sola investigación por partido, reutilizada. Mejorar solo la revisión
diaria a un modelo tope cuesta ~$10/mes (Opus) o ~$26 (astra).

## 4. Opciones recomendadas

| Opción | A favor | En contra |
|---|---|---|
| **1. OpenAI**: sol para análisis, luna para resúmenes, Flex/lote para lo no urgente | el nivel medio más barato; contexto de 1M; residencia de datos en la UE (+10 %); la API no entrena con los datos por defecto | la página pública de precios está desactualizada (conflicto anotado) |
| **2. Anthropic**: Sonnet por defecto, Haiku para resúmenes, Opus para la revisión diaria y las propuestas | diseñado para trabajo agéntico largo; 1M de contexto; *web fetch* sin tarifa; no entrena con los datos por defecto | ~25 % más caro en el nivel medio; sin residencia UE directa (usar Bedrock o Google Cloud UE, +10 %) |
| **3. Google**: Flash-Lite / Flash, con 3.1 Pro para análisis profundo | lo más barato hasta 100 tareas/día gracias a 5.000 búsquedas gratis | 3.1 Pro aún en preview; la promoción de Flash acaba el 31 dic 2026 |

Evitar la API propia de DeepSeek para datos de la plataforma (almacena en China y entrena salvo exclusión por email);
si se quieren esos modelos, a través de Fireworks o Together. Antes de elegir: probar las opciones 1 y 2 en ~50
partidos históricos (exactitud del SQL, que no invente estadísticas).

## 5. Arquitectura futura del AI Analyst (no implementada)

```
OBSERVAR ─► MEDIR ─► IA INVESTIGA ─► IA PROPONE ─► EXPERIMENTO AISLADO ─► BACKTEST ─► PROSPECTIVE SHADOW
                                                                                              │
PROMOCIÓN ◄─ APROBACIÓN HUMANA ◄─ PROPUESTA ◄─ COMPARACIÓN CON EL CHAMPION (puerta frente al mercado) ◄┘
```

* **Observar / medir**: lo hace ya el sistema (auditorías, evaluación prospectiva, calidad de datos), sin IA.
* **La IA investiga y propone**: lee la memoria de investigación, los informes y fuentes externas citadas; escribe
  una hipótesis con su porqué y su evidencia. Herramientas de **solo lectura** (SQL de lectura, búsqueda web).
* **Experimento aislado**: una rama de investigación con su propio registro (`analytics.experiments`), nunca en
  producción; sellado con la versión del código de modelos y del dataset.
* **Backtest + shadow prospectivo**: las mismas puertas que cualquier modelo (log loss frente al cierre sin margen,
  mezcla con el mercado, CLV con intervalos por partido).
* **Aprobación humana**: solo el dueño acepta o rechaza; solo una promoción explícita cambia producción.

Lo que **nunca** puede pasar: *mal resultado → la IA cambia producción automáticamente*. La IA no tiene permisos de
escritura en producción, no toca umbrales ni reglas, no publica picks y no promueve modelos. Cada llamada queda
registrada con su coste, su modelo y sus fuentes, bajo un tope mensual.

Fuentes: developers.openai.com (pricing, models), platform.claude.com (pricing, data residency),
ai.google.dev/gemini-api (pricing), api-docs.deepseek.com, groq.com, together.ai, docs.fireworks.ai, mistral.ai,
privacy.claude.com, openai.com (data residency Europe), cdn.deepseek.com (privacy policy), help.mistral.ai,
brave.com/search/api; conflicto de precios de OpenAI anotado (vktr.com, 22 sep 2026).

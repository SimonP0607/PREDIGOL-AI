# PREDIGOL AI REPORT — 8 de octubre de 2026

**Estado:** la capa de decisión IA está implementada, probada y validada con datos reales en una copia, en
**modo evaluación (shadow)** y **sin ningún proveedor de IA contratado ni configurado**. Hoy funciona solo con
su revisor de reglas (costo cero). Para encender el modelo de lenguaje necesito que elijas proveedor.

Detalle técnico: `docs/ai/AI_DECISION_LAYER.md`. Precios verificados en las páginas oficiales el 8-oct-2026.

## 1. Arquitectura

```
                 cada 30 min (worker ai_cycle)                       diario 07:35 (ai_learn)
  datos PrediGol ──► AI_MATCH_PACKET (as-of, con fuente por bloque)   resultados ──► post-mortem ──► memoria
  bajas/XI (API) ──► evidencias (CONFIRMADA/PROBABLE/RUMOR/…)                         │
  web (opcional) ──► búsqueda (máx. 2 por partido) → extracción (modelo barato)       ▼
                         │                                             patrones (z ≥ 3) ──► hipótesis PROPUESTA
  filtro de valor ──► shortlist ──► revisor de reglas (siempre, gratis)                │
                                └─► revisor LLM (24 h, topes, presupuesto) ──► combinada (la más prudente)
                                                    │                                   ▼
                     ANÁLISIS PREDIGOL (≤ 3 tarjetas/partido, guardado)      Evolución: RECHAZAR / INVESTIGAR /
                     picks del día y parlays (revisión congelada)            APROBAR EXPERIMENTO → backtest →
                     evaluación shadow de la IA (puerta ai-gate-v1)          shadow → PROMOVER (solo el dueño)
```

* La IA solo puede **confirmar, rebajar, rechazar o abstenerse**. No crea picks ni sube probabilidades.
* Filtrar lo que ven los usuarios exige **dos llaves**: `FBI_AI_MODE=enforce` **y** la puerta shadow superada.
* **Un análisis por partido, no por usuario**: el worker calcula y guarda; abrir un partido no llama a la IA.
* Toda llamada queda registrada (modelo, versión de prompt, hash de entrada, tokens, caché, costo, estado).

## 2. Proveedores evaluados (USD por millón de tokens, precio estándar)

| Proveedor | Modelo | Input | Output | Web | Tools | Vision | Calidad / notas |
|---|---|---:|---:|---|---|---|---|
| Anthropic | Claude Haiku 5.5 | 0,10 | 0,50 | $10/1k + tokens | sí | sí | pequeño; ×5 si el prompt > 100K (no aplica: ~4K) |
| Anthropic | Claude Sonnet 5.5 | 2 | 10 | $10/1k | sí | sí | medio-alto |
| Anthropic | Claude Opus 5.5 | 4 | 20 | $10/1k | sí | sí | alto |
| Anthropic | Claude Fable 5.1 | 10 | 50 | $10/1k | sí | sí | máximo; retención obligatoria 30 días |
| OpenAI | gpt-6-luna | 0,10 | 0,50 | $10/1k + tokens | sí | sí | pequeño (mismo precio que Haiku 5.5) |
| OpenAI | gpt-6.1-sol | 2 | 10 | $10/1k | sí | sí | medio-alto |
| OpenAI | gpt-6-astra | 10 | 50 | $10/1k | sí | sí | máximo |
| Google | Gemini 3.1 Flash-Lite | 0,25 | 1,50 | 5.000/mes gratis, luego $14/1k | sí | sí | barato |
| Google | Gemini 3.8 Flash | 0,75 → 1,50 en 2027 | 3,75 → 7,50 | ídem | sí | sí | medio; precio promocional hasta 31-dic |
| Google | Gemini 3.1 Pro (preview) | 2 | 12 | ídem | sí | sí | alto; aún preview |
| Mistral | Large 4 (preview) | 1,36 (oferta 0,68) | 4,18 (2,09) | $30/1k | sí | sí | alternativa europea |
| Mistral | Small 4 | 0,15 | 0,60 | $30/1k | sí | n/v | barato |
| DeepSeek | flash (V4.1) | 0,30 (valle 0,15) | 1,20 | no | sí | sí | **no recomendado**: datos procesados en China |
| Groq / Together / DeepInfra | gpt-oss-120b (abierto) | 0,037–0,15 | 0,17–0,60 | no / n/v | sí | n/v | muy barato; calidad en español sin verificar |

Búsqueda web aparte: Brave $5/1k · Exa $7/1k (con $10 de crédito gratis al mes; **ya integrado**) · Tavily $8/1k.
Lote (−50 %) disponible en OpenAI, Anthropic, Gemini, Mistral y Groq (no lo necesitamos: el volumen es bajo).

**Alternativas descartadas por costo y por técnica.** GPU propia en alquiler 24/7: RTX 4090 ≈ US$540/mes,
L40S ≈ 795, A100 80 GB ≈ 1.160, H100 ≈ 2.100–2.550 — entre 30 y 150 veces lo que cuesta la API para este
volumen. *Fine-tuning*: no hay un conjunto etiquetado de «buenas revisiones» y el volumen es pequeño; no se
justifica. Modelo fundacional desde cero: millones de dólares y ninguna ventaja demostrable; descartado.

## 3. Volumen real de PrediGol (copia de producción al 7-oct 03:00 UTC)

| Medida | Valor |
|---|---|
| Partidos seguidos por día | 69–91 (133 competiciones) |
| Picks shadow por día | ~1.000 (12.194 en 12 días) |
| Shortlist (pasa el filtro de valor, próximas 24–72 h) | 23–31 selecciones a la vez |
| Revisiones LLM pedidas por día | > 60 → **el tope diario (60: 50 análisis + 10 profundas) se alcanzó todos los días** |
| Búsquedas web por día | 47 de media (máx. 61) |
| Extracciones de noticias por día | 33 de media |
| Post-mortems con narrativa | ~2 por día (tope 10) |
| Paquete por partido | 1.269 tokens de media (p90 1.723, máx 4.465) |
| Prompt de una revisión | ~3.250 tokens (+30 % con el tokenizador de Claude) |
| Tiempo de un ciclo | 3,2 s de media, 9 s máx.; ciclo real con 400 partidos: 12 s |
| Almacenamiento de la capa | ~7 MB/día (~210 MB/mes): paquetes, revisiones y análisis guardados solo cuando cambian |

## 4. Simulación mensual (volumen real, topes por defecto, precios verificados)

| Perfil | Masivo / Análisis / Final | Búsqueda | Por día | Por mes | Peor caso / mes | Por partido |
|---|---|---|---:|---:|---:|---:|
| **ECONÓMICO** (Anthropic) | Haiku 5.5 / Haiku 5.5 / Sonnet 5.5 | Exa | **$0,53** | **$15,96** | $28,33 | $0,008 |
| Económico (OpenAI) | gpt-6-luna / gpt-6-luna / gpt-6.1-sol | Exa | $0,51 | $15,18 | $27,04 | $0,007 |
| **EQUILIBRADO** (Anthropic) | Haiku 5.5 / Sonnet 5.5 / Opus 5.5 | Exa | $1,42 | $42,61 | $63,63 | $0,021 |
| Equilibrado (Gemini) | 3.1 Flash-Lite / 3.8 Flash / 3.1 Pro | Google | $0,45 | $13,36 (≈ $21 desde ene-2027) | $19,14 | $0,006 |
| **MÁXIMA CALIDAD** | Sonnet 5.5 / Opus 5.5 / Fable 5.1 | Anthropic | $3,12 | $93,47 | $150,32 | $0,045 |

* En el perfil económico, la búsqueda web es el 60 % del costo (~$9,7/mes) y cabe en el crédito gratuito
  mensual de Exa: el gasto real en modelos sería **≈ $6/mes**.
* **Peor caso** = todos los topes cada día, el día más cargado ×1,5 y prompts un 50 % más largos.
* El presupuesto por defecto (US$1/día, US$20/mes) **acota** cualquier perfil: al 70 % deja el nivel final,
  al 90 % solo el modelo barato y al 100 % solo reglas. El equilibrado necesitaría subir el tope.
* Gemini: los términos de *grounding* limitan guardar resultados (≤ 2 años, fines limitados) y chocan con
  «analizar una vez y guardar»; con Gemini usaría Exa para la búsqueda.

## 5. Recomendación

| | |
|---|---|
| Proveedor | **Anthropic** (o OpenAI: mismo costo; decide por cuenta/facturación que prefieras) |
| Modelo masivo | Claude Haiku 5.5 (extracción de noticias, narrativas) |
| Modelo de análisis | Claude Haiku 5.5 (revisiones de las próximas 24 h) |
| Modelo final | Claude Sonnet 5.5 (las 10 mejores del día) |
| Búsqueda | Exa (ya integrada; $10 de crédito al mes) |
| Costo esperado / día | ≈ US$0,53 (≈ US$0,21 sin contar búsquedas cubiertas por el crédito) |
| Costo esperado / mes | ≈ US$16 (≈ US$6 fuera del crédito de Exa) |
| Worst case | ≈ US$28/mes sin tope; **US$20/mes con el tope por defecto** |

Por qué: el revisor necesita leer un JSON con cifras, citar referencias y ser prudente; eso lo hace un modelo
pequeño con salida estructurada estricta, y lo caro (razonamiento fino) se reserva para 10 casos al día. Un
perfil mayor no está justificado mientras la puerta shadow no muestre que la revisión aporta (ver §6).
Sugerencia: si quieres comparar, 7 días en shadow con Anthropic y OpenAI a la vez cuestan < US$5.

## 6. Validación con datos reales: lo que dicen los números

**Replay as-of del revisor de reglas** sobre los 10.752 picks shadow liquidados (25-sep a 7-oct, 253 partidos):

| Grupo | n | Partidos | Acierto | ROI | CLV |
|---|---:|---:|---:|---:|---:|
| Modelo solo (todos) | 10.752 | 253 | 41,2 % | −2,1 % | +2,1 % |
| Aprobados (sin señales no disponibles en el pasado) | 7.130 | — | 41,8 % | −5,8 % | +2,3 % |
| Con cautela | 3.274 | — | 38,5 % | +3,5 % | +1,6 % |
| Rechazados | 348 | 18 | 53,0 % | +22,0 % | +0,9 % |

* El mercado sigue calibrando mejor que el modelo: log loss 0,617 (mercado) frente a 0,666 (modelo); Brier
  0,214 frente a 0,235.
* **Lo que el revisor rechazó rindió mejor, no peor** (calidad de rechazo z = −0,70: en la dirección contraria
  y no significativa). Agrupando por partido, **ninguna señal** del revisor tiene un efecto significativo
  (todas |z| < 2,2; muestras de 15–250 partidos).
* Conclusión honesta: con 10 días no hay evidencia de que la revisión mejore la selección. Por diseño eso no
  cambia nada: la capa sigue en **shadow**, la puerta (`ai-gate-v1`) dice **«datos insuficientes»** y no
  ajusté ninguna regla a esta muestra. Se acumula evidencia prospectiva; las señales que la muestra sugiera
  irán como hipótesis, nunca como cambios.

## 7. Qué decides tú

1. **Proveedor y perfil** (recomendado: Económico con Anthropic u OpenAI). Tú creas la cuenta y la clave; yo
   la configuro como secreto sin mostrarla.
2. **Presupuesto**: confirmar US$1/día y US$20/mes, o ajustarlo.
3. **Búsqueda web** con Exa: sí/no.
4. **Activar la capa en el portátil** (beta en vivo) para empezar a acumular la evidencia shadow de 30 días:
   requiere aplicar las migraciones 0070–0072 (la 0070 obliga al SUPER_ADMIN a enrolar el segundo factor).

## 8. Con presupuesto de US$60–80/mes (8-oct, tarde)

El dueño fijó US$60–80 al mes y prioriza la calidad del análisis. Medí de nuevo en la copia (4–6 oct, sáb–lun,
207 partidos) **sin el tope diario**, para conocer la demanda real: el revisor pediría 97–171 revisiones de modelo
al día en las próximas 24 h (más 15 «finales»), 33–61 búsquedas y 18–52 extracciones. El tope de 60 cubría un
tercio de la demanda de un sábado.

**Corrección:** Exa cobra US$7 por 1.000 búsquedas **más US$1 por 1.000 páginas de texto**, y cada búsqueda pide el
texto de hasta 8 resultados: son ≈ US$15 por 1.000, no 7 (`fbi.ai.pricing` corregido). Exa da US$10 de crédito
al mes sin tarjeta.

Costo mensual con el mismo reparto para todos (75 revisiones de análisis + 15 finales al día; precios oficiales
verificados el 8-oct; la muestra incluye un fin de semana, así que es conservadora):

| Proveedor | Masivo / Análisis / Final | Mes típico | Peor caso sin tope |
|---|---|---:|---:|
| **Anthropic** | Haiku 5.5 / Sonnet 5.5 / Opus 5.5 | **US$71** (≈ 61 con el crédito de Exa) | US$109 |
| OpenAI | gpt-6-luna / gpt-6.1-sol / gpt-6-astra | US$82 | US$120 |
| Google | 3.1 Flash-Lite / 3.8 Flash / 3.1 Pro (preview) | US$20 (US$31 desde ene-2027) | US$27 |
| DeepSeek | V4.1 Flash / V4 Pro / V4 Pro | US$42 | US$72 |

Del costo de Anthropic: Sonnet ≈ US$36, Opus ≈ US$13,5, Exa ≈ US$21 (11 tras el crédito), Haiku < US$1.

**Recomendación:** Anthropic con Haiku 5.5 (noticias), Sonnet 5.5 (revisiones) y Opus 5.5 (las 15 mejores del día);
topes `FBI_AI_MAX_LLM_REVIEWS_PER_DAY=90`, `FBI_AI_MAX_DEEP_PER_DAY=15`, `FBI_AI_DAILY_BUDGET_USD=3.50`,
`FBI_AI_MONTHLY_BUDGET_USD=75`, y en la consola de Anthropic un límite de gasto de US$80 como segunda barrera.
Por qué: por token, los dos primeros niveles cuestan lo mismo que en OpenAI (con el tokenizador de Claude, ≈ 30 %
más tokens, una revisión de Sonnet sale ≈ 15 % más cara que una de gpt-6.1-sol) y el nivel final cuesta 60 % menos
(Opus 5.5 US$4/20 frente a Astra US$10/50): en total, ≈ US$11/mes menos; ya está integrado de forma nativa y
probado; una sola cuenta. Gemini es la alternativa barata, pero su nivel alto sigue en preview, el Flash duplica
precio en enero y los términos de la búsqueda con Google limitan guardar resultados. DeepSeek procesa los datos en China. La calidad real de
las revisiones se medirá en shadow (puerta `ai-gate-v1`) antes de que afecte a los usuarios.

Medición: `python -m scripts.ai_simulate --dsn <copia> --start 2026-10-04T00:00:00+00:00 --days 3 --search
--max-reviews 1000 --max-deep 15`, repreciada con topes de 60/10, 80/15, 90/15 y 100/15.

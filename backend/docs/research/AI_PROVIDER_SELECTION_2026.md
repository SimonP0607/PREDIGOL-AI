# AI provider selection 2026 — Football Intelligence Agent

*Research pass of 4 October 2026 (official pricing and documentation pages, accessed that day;
sources at the end). Prices in USD per 1M tokens (input / output) unless noted. Nothing here
has been purchased: anything that needs a new paid account is marked **PAYMENT REQUIRED** and
waits for the owner's decision.*

## What the agent must do

1. Answer admin questions using **only whitelisted, read-only tools** — `get_fixture`,
   `get_team`, `get_player`, `get_standings`, `get_injuries`, `get_odds`, `get_market`,
   `get_prediction`, `get_model_metrics`, `get_pick_history`, `get_data_quality`,
   `web_research`. No free SQL, no write tool.
2. Write a daily research report (team news, injuries, line-up rumours) where **every claim
   carries provenance**: source URL, published_at, retrieved_at, and a grade
   CONFIRMED / REPORTED / RUMOR.
3. Review picks by emitting **structured flags only** — it never changes a probability.

The existing code (`fbi/analyst/agent.py`) already calls the Anthropic Messages API
(`FBI_ANALYST_API_KEY`, `FBI_ANALYST_MODEL`, `FBI_ANALYST_BASE_URL`).

## Bottom line

* Workload (below): **~12.6M input tokens, ~2.01M output tokens and ~1,200 searches a month**.
* **Claude Haiku 4.5** (already integrated): **$22.65/month in tokens**, before any search —
  over a sub-$20 budget at this volume unless admin questions are capped (~30/day) and pick
  reviews are batched.
* **GPT-6 Luna**: about **$2.27/month** for the same workload, with function calling, strict
  JSON schemas and a 1.05M context — **PAYMENT REQUIRED** (a new OpenAI account, ≥ $5 prepaid).
* **Search**: our own `web_research` tool backed by a search API that returns publication
  dates. Built-in model search costs more, ties us to one vendor, and Google's terms restrict
  storing grounded results.
* **Recommendation**: keep Claude Haiku 4.5 as the working default (no new vendor), with a
  per-month spend cap; evaluate GPT-6 Luna in shadow only if the owner approves the account.
  Search: Exa free tier (no payment method) behind `web_research`; Tavily free tier as backup.

## 1. Low-cost models (verified 2026-10-04)

| Model | Input / Output | Cache hit; batch | Context (max out) | Tools; JSON schema | Notes |
|---|---|---|---|---|---|
| Claude Haiku 4.5 | $1.00 / $5.00 | $0.10; 50 % off | 200K (64K) | Yes; Yes | Caching only for prompts ≥ 4,096 tokens [1][2][3][5] |
| Claude Sonnet 5.5 (current Sonnet) | $2.00 / $10.00 | $0.20; 50 % off | 1M (128K) | Yes; Yes | New tokenizer ≈ +30 % tokens for the same text [1][2] |
| GPT-6 Luna | $0.10 / $0.50 | $0.01; 50 % off | 1.05M (128K) | Yes; Yes | Reasoning model; Responses API for tools [9][10] |
| GPT-5 mini / nano | $0.25/$2.00; $0.05/$0.40 | 50 % off | 400K | Yes; Yes | Deprecated; shut down 11 Dec 2026 [9][11][12] |
| GPT-4.1 mini | $0.40 / $1.60 | $0.10 | 1.05M (32K) | Yes; Yes | Still offered [9][11] |
| Gemini 3.5 Flash-Lite | $0.30 / $2.50 | $0.03; 50 % off | 1M (65K) | Yes; Yes | Output includes thinking tokens [16][17] |
| Gemini 3.8 Flash | $0.75 / $3.75 (→ $1.50/$7.50 from 1 Jan 2027) | 50 % off | 1M (65K) | Yes; Yes | [16] |
| DeepSeek flash (V4.1) | $0.30/$1.20 peak; $0.15/$0.60 off-peak | $0.006 | 1M (384K) | Yes; JSON mode only | Data processed in China; may train on inputs [23][24][26] |
| Mistral Small 4 | $0.15 / $0.60 | up to 90 % off; 50 % off | 256K | Yes; Yes | [27][28] |
| GPT-OSS-120B on Groq | $0.15 / $0.60 | $0.075 | 131K (65K) | Yes; Yes* | *strict schema and tools not in one request [30][31] |

Legacy: DeepSeek `deepseek-chat` / `deepseek-reasoner` retired 24 Jul 2026 [25]; Gemini 2.5
Flash/Flash-Lite limited to existing users [16][18]. Together/OpenRouter prices not verified.

## 2. Search and grounding

| Option | Price | Provenance fields | Caveats |
|---|---|---|---|
| Anthropic web search | $10 / 1k searches + tokens | URL, title, `page_age`, cited text; domain filters | Claude only [1][4] |
| OpenAI web search | $10 / 1k calls + tokens | URL, title | No date field documented [9][13] |
| Gemini grounding | 5,000/month free, then $14 / 1k | URL, title | No dates; terms forbid storing grounded results [16][19][20] |
| Perplexity Search API | $5 / 1k ($1 / 1k "fast") | title, URL, snippet, `date`, `last_updated` | [33][34] |
| Tavily | 1,000 credits/month free, then $0.008/credit | `published_date` (beta, estimate) | [35][36] |
| Brave | $5 / 1k with $5 free credit monthly | URLs, snippets, freshness filter | Card required [37][38] |
| Exa | $7 / 1k searches; $1 / 1k pages; $10 free credit monthly, no payment method | `publishedDate` (estimated), author | ZDR only on Enterprise [39][40] |
| Firecrawl | 1,000 credits/month free; 2 credits per 10 results | results + full page text | ≈ 500 searches on the free tier [41] |

## 3. Monthly cost for our workload (30 days)

Workload: 50 admin questions/day (6k in + 1k out, 3 internal tool calls) → 9.0M / 1.5M; one
daily research report (~40 searches, 60k in + 8k out) → 1.8M / 0.24M and 1,200 searches; 30
pick reviews/day (2k in + 300 out) → 1.8M / 0.27M. Total **12.6M in / 2.01M out**.

| Model | Arithmetic | Tokens/month | + built-in search | With Exa free tier |
|---|---|---|---|---|
| Claude Haiku 4.5 | 12.6 × $1.00 + 2.01 × $5.00 | **$22.65** | + $12.00 = $34.65 | $22.65 |
| GPT-6 Luna | 12.6 × $0.10 + 2.01 × $0.50 | **$2.27** | ≈ $14.27 | $2.27 (≈ $3.27 if reasoning doubles output) |
| Gemini 3.5 Flash-Lite | 12.6 × $0.30 + 2.01 × $2.50 | **$8.81** | + $0 (within free 5,000) | $8.81 |
| DeepSeek flash | 12.6 × $0.30 + 2.01 × $1.20 | **$6.19** peak ($3.10 off-peak) | — | $3.10–6.19 |

Haiku per unit: $0.011 per admin question, $0.10 per report, $0.0035 per pick review; batching
pick reviews saves $1.58/month. Haiku alone stays ≤ $15/month with ≤ ~30 questions/day.

## 4. Data protection and safety

* **Anthropic**: API data not used for training without permission; deleted within 30 days
  (flagged content up to 2 years); zero data retention via sales (batch excluded) [6][7].
* **OpenAI**: not used for training unless opted in; abuse logs up to 30 days; responses stored
  30 days unless `store:false`; ZDR needs approval [14].
* **Google**: free-tier content used to improve products (human review) — paid tier only;
  grounding stores prompts and outputs 30 days [16][20][21].
* **DeepSeek**: processed and stored in China, may train on inputs [24][26] — **not used**.
* **Mistral**: 30 days; its Agents API (web search) keeps data until account closure [29].
* **Groq**: no inference data retained by default; ZDR self-serve [32].
* **Prompt injection (OWASP LLM01)** [42]: retrieved web text is *data*, delimited and length
  capped, never placed in the system prompt; the tool allowlist is enforced server-side and
  every tool is read-only; every output is validated in code; the pick reviewer sees only
  labelled claims, never raw web text.
* Rate limits are not a constraint at this volume [8][10][15][22]; set hard spend limits.

## 5. Decision for GATE H

* **Primary: Claude Haiku 4.5** on the existing integration (no new vendor, no purchase), with
  a monthly spend cap enforced in code, pick reviews batched, and admin questions rate-limited.
* **Challenger (only with the owner's approval — PAYMENT REQUIRED): GPT-6 Luna**, run in shadow
  for a week (same tools, same prompts, answers compared) behind a small adapter.
* **Search: Exa (free tier) behind `web_research`**, Tavily free tier as fallback; built-in
  model search, Gemini grounding (storage terms) and DeepSeek (data residency) are avoided.
* **Guardrails** (implemented in `fbi.analyst`):
  1. strict JSON schemas for every structured output, validated again with Pydantic;
  2. per-claim provenance — `web_research` stores URL, publisher, `published_at` (and which
     provider field it came from) and a server-side UTC `retrieved_at`; the model cites
     `source_id`s only and the server resolves them; CONFIRMED = official club/league source or
     two independent outlets, REPORTED = one reputable outlet, RUMOR = anything else;
  3. the pick reviewer can only emit `{pick_id, flag, severity, reason, source_ids}` with
     `additionalProperties: false` — no probability field exists to change;
  4. allowlist dispatcher: typed arguments, a cap on calls per request, timeouts, no SQL;
  5. every model and tool call logged (request id, tool, arguments, result hash, latency,
     tokens, cost), with an alert at 80 % of the monthly budget.

## 6. Implementation (GATE H, 4 October 2026)

Built and tested with a mocked model and search API (`tests/integration/test_ai_layer.py`,
`test_analyst.py`, `tests/unit/test_provenance.py`); **live use waits for the owner's keys**
(`FBI_ANALYST_API_KEY` + `FBI_ANALYST_MODEL=claude-haiku-4-5`, and `EXA_API_KEY` for web
research) — creating those accounts is the owner's decision and nothing was purchased.

| Piece | Where | What it guarantees |
|---|---|---|
| Tools | `fbi/analyst/tools.py` | exactly the 12 mandated tools + `search`/`list_matches`; typed, bounded arguments, `additionalProperties: false`; read-only services; provenance block on every result; no SQL |
| Web research | `fbi/analyst/search.py` | Exa, last N ≤ 14 days, publication date kept; results registered as source ids; page text labelled untrusted |
| Provenance | `fbi/analyst/provenance.py` | a claim must cite source ids retrieved in the same run; CONFIRMED only for official domains (dated) or two independent reputable outlets; the server only lowers a grade; refused claims are listed |
| Agent loop | `fbi/analyst/agent.py` | ≤ 6 rounds (12 for the report), tool results cut at 12k characters, numbers not found in tool results flagged, structured outputs validated with strict Pydantic models |
| Cost | `fbi/analyst/budget.py`, `store.py` | every call's tokens and cost written to `analytics.ai_runs` as it happens; the month's spend checked before every call against `FBI_ANALYST_MONTHLY_BUDGET_USD` (default 20); unknown models priced at the highest rate; 30 admin questions/day |
| Daily report | `fbi/analyst/research.py` | platform data always; research as graded claims; raw URLs removed from the summary; `not_configured` recorded, never silent |
| Pick reviewer | `fbi/analyst/reviewer.py` | flags only: rules (kick-off change, price gone, market no longer priced) + the model on claims (never raw web text, no tools); news flags must cite a claim; a probability field is refused by the schema and has no column |
| Admin API | `/api/v1/admin/ai/{status,runs,report,flags}`, `POST /ai/report/run`, `/ai/review/run` | SUPER_ADMIN only; key values never returned |

## Sources (accessed 2026-10-04)

1. https://platform.claude.com/docs/en/about-claude/pricing
2. https://platform.claude.com/docs/en/about-claude/models/overview
3. https://platform.claude.com/docs/en/build-with-claude/structured-outputs
4. https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
5. https://platform.claude.com/docs/en/build-with-claude/prompt-caching
6. https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
7. https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data
8. https://platform.claude.com/docs/en/api/rate-limits
9. https://developers.openai.com/api/docs/pricing
10. https://developers.openai.com/api/docs/models/gpt-6-luna
11. https://developers.openai.com/api/docs/models/gpt-5-mini ; https://developers.openai.com/api/docs/models/gpt-4.1-mini
12. https://developers.openai.com/api/docs/deprecations
13. https://developers.openai.com/api/docs/guides/tools-web-search
14. https://developers.openai.com/api/docs/guides/your-data
15. https://developers.openai.com/api/docs/guides/rate-limits
16. https://ai.google.dev/gemini-api/docs/pricing
17. https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
18. https://ai.google.dev/gemini-api/docs/deprecations
19. https://ai.google.dev/gemini-api/docs/google-search
20. https://ai.google.dev/gemini-api/terms
21. https://ai.google.dev/gemini-api/docs/usage-policies
22. https://ai.google.dev/gemini-api/docs/rate-limits
23. https://api-docs.deepseek.com/quick_start/pricing
24. https://api-docs.deepseek.com/guides/anthropic_api
25. https://api-docs.deepseek.com/updates
26. https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html
27. https://mistral.ai/pricing/api/ ; https://mistral.ai/pricing
28. https://docs.mistral.ai/models/model-cards/mistral-small-4-0-26-03
29. https://legal.mistral.ai/terms/privacy-policy
30. https://console.groq.com/docs/models ; https://console.groq.com/docs/model/openai/gpt-oss-120b
31. https://console.groq.com/docs/structured-outputs
32. https://console.groq.com/docs/your-data
33. https://docs.perplexity.ai/docs/getting-started/pricing
34. https://docs.perplexity.ai/docs/search/quickstart
35. https://docs.tavily.com/documentation/api-credits
36. https://docs.tavily.com/documentation/api-reference/endpoint/search
37. https://brave.com/search/api/
38. https://api-dashboard.search.brave.com/app/documentation/web-search/responses
39. https://exa.ai/pricing
40. https://exa.ai/docs/reference/search
41. https://www.firecrawl.dev/pricing
42. https://genai.owasp.org/llmrisk/llm01-prompt-injection/

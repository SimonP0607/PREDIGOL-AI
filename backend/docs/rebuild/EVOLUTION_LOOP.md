# Evolution loop (GATE I)

*Written 4 October 2026. Code: `fbi/research/evolution.py`, `fbi/research/loop.py`,
`apps/worker/scheduler.py`; API `GET/POST /api/v1/admin/evolution*`; Admin Console →
Inteligencia → Evolución. Tables: `analytics.research_hypotheses`, `analytics.research_memory`
(migration 0055).*

## The rule

**A bad result never changes a rule.** The loop turns results into memory and proposals; the
owner decides; experiments run in research; only a passed gate plus an explicit promotion
reaches users.

```
result (research V2 · daily audit · prospective)
   ├─► MEMORY      what was seen, with its evidence — superseded, never deleted
   └─► HYPOTHESIS  PROPOSED by the system, the AI or the owner
          └─ owner: ACCEPT ─► experiment in research (RUNNING → DONE) ─► gate (roles vs the market)
                                                                        └─► explicit promotion
             owner: REJECT ─► kept, with the note
```

Never, anywhere in the loop: a threshold edited by a result, a model promoted automatically, a
probability changed by the LLM, a losing model hidden, negative research deleted.

## What runs, when

| Job | When (Bogotá) | Does | Cost |
|---|---|---|---|
| `research_monitor` | daily 07:05 (and at start-up if the last success is > 26 h old) | E0 audit of the settled shadow picks + prospective evaluation → memory + proposals | seconds of DB reads, 0 requests |
| `research_v2_weekly` | Monday 04:20 | `scripts/research_v2.py --apply` in its own process, **only if** the code changed since the last run or it is 4 weeks old (`v2_due`) → roles stored, memory + proposals | ~5 min CPU, 0 requests |
| `ai_daily_report` | from 06:00, once a day | research report (data always; web research with provenance when keys exist); may carry ≤ 2 AI proposals | LLM/search only if configured, inside the monthly cap |
| `ai_pick_review` | hourly | flags only on today's/tomorrow's sets | rules: DB only; model: only on changes |

All jobs catch their own errors: research never stops the worker or the odds capture.

## Memory

One current finding per topic (`superseded_by IS NULL`); a new finding on the same topic
supersedes the old one, which stays. An unchanged finding writes nothing. Topics written today:

* `audit:shadow_picks` — realised, claimed EV, EV at the pick, movement, EV at the close, luck (z);
* `prospective:<segment>:<model>` — only segments that are judged (≥ 50 matches on ≥ 5 days);
* `research_v2:champion`, `research_v2:role:<model>` — from each stored research-V2 run.

Sources are fixed: `research_v2`, `prospective`, `audit`, `owner`. The LLM cannot write memory.

## Proposals

| Key | Proposed when | Why |
|---|---|---|
| `audit:price_only:v1` | EV at the pick < 0 at ≥ 3 standard errors | The value gate's edge is disagreement with the market; test selecting only prices above the fair consensus (research only) |
| `audit:close_capture:v1` | our last consensus is > 2 h before kick-off (median) | "Movement" is not closing-line value until the close is captured |
| `prospective:beats_close:<seg>:<model>` | a judged segment's interval is wholly below 0 | Confirm in research before any role changes |
| `prospective:adds_info:<seg>:<model>` | a judged segment's blend weight interval is above 0 | Test a blend |
| `v2:challenger:<model>:<run>` | a research-V2 run finds a CHALLENGER | Review for promotion — the owner's decision |
| `plan:E4:shots`, `plan:E6:lineups`, `plan:totals_history` | a run without any CHALLENGER | New information, per `docs/research/MODEL_RESEARCH_V2_2026.md` §8–9 |
| `ai:<hash of title>` | the daily report proposes it (≤ 2 per report) | The AI suggests; it never decides |
| (none) | the owner writes one in the console | — |

A keyed proposal is made once (unique `dedup_key`), however many times the monitor sees the same
evidence. Decisions are recorded with who decided, when and a note; a decided hypothesis cannot
be decided again (HTTP 409).

## State on 4 October 2026

* The first monitor (11:09 UTC) wrote 5 findings (the audit and four judged prospective rows) and
  proposed `audit:price_only:v1` (EV at the pick −4.7 % ± 0.2 %, z ≈ −20) and
  `audit:close_capture:v1` (our last capture a median 12 h before kick-off).
* Research V2 run `…T111558Z` (no CHALLENGER, qualified models 0, `docs/rebuild/BACKTEST_V2.md`)
  wrote the champion and every model's role to memory and proposed the three plan items
  (E4 shots, E6 line-ups, historical totals prices).
* Prospective: only the "all" rows are judged (Elo and Poisson worse than the close); no segment
  proposal.
* All proposals wait for the owner (Admin → Evolución). Note for `audit:close_capture:v1`: the
  provider's final pre-match prices (`market.final_prematch_odds`, stamped a median 76-118 min
  before kick-off, GATE B) already exist for played matches - a consensus from them is the
  cheapest way to test it.
* AI proposals: none until an LLM key exists (owner's decision).

## Promotion (not automated, by design)

`analytics.experiments.research_status = 'PRODUCTION'` is what counts as a qualified model
(`GET /admin/research/v2 → qualified_models`). Nothing in the loop writes it. A promotion needs
a CHALLENGER role from a stored run, an accepted `v2:challenger:*` hypothesis and the owner's
explicit action — which this rebuild has had no reason to build yet: there is no challenger.

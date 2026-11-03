/// <reference types="bun" />
/**
 * The reviews and the shadow report of the AI decision layer name the shadow engines of plan IA phase 3 (`ma-v1`, `ma-v1-h`, `cs-v1`): the filter offers
 * them after production's three, each by a name that says it is a shadow one; choosing one says what its reviews are (evaluation only, never read by the
 * decision layer); the review of a shadow engine opens with its engine named and a Shadow badge, whatever its output keeps; the shadow report titles a
 * shadow engine by its name. Production's engines read exactly as before. In both languages.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import type { Envelope } from "@/lib/api/v1/types";
import type {
  AiEngine,
  AiReviewDetail,
  AiReviewRow,
  ShadowReportRow,
} from "@/lib/api/v1/types_ai_layer";
import {
  EngineSelect,
  EngineTag,
  ReviewDetailView,
  ReviewsTab,
  ShadowEngineNote,
  ShadowTab,
} from "./AiLayerLive";
import { REVIEW_ENGINES } from "./aiModel";

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

beforeEach(() => setLocale("es"));
afterEach(() => setLocale("es"));

const SHADOW: AiEngine[] = ["ma-v1", "ma-v1-h", "cs-v1"];
const PRODUCTION: AiEngine[] = ["combined", "rules", "llm"];

function review(over: Partial<AiReviewRow> = {}): AiReviewRow {
  return {
    id: 1,
    reviewed_at: "2026-11-03T15:00:00Z",
    fixture_id: 77,
    match: "Alpha - Beta",
    kickoff_at: "2026-11-03T20:00:00Z",
    competition: "Liga",
    market_key: "1x2",
    selection: "home",
    line: "0.00",
    odds: "2.100",
    p_model: "0.520000",
    p_market: "0.470000",
    edge: "0.050000",
    decision: "APPROVE",
    confidence: "0.700",
    engine: "combined",
    engine_version: "rules-review-v1+review-v2",
    model: null,
    reason: "price above the fair one",
    status: "ok",
    mode: "shadow",
    cost_usd: "0.000000",
    ...over,
  };
}

function detail(over: Partial<AiReviewDetail> = {}): AiReviewDetail {
  return {
    review: review(),
    output: { reason: "both agree" },
    sources: [],
    evidence: [],
    packet: null,
    components: [],
    usage: [],
    input_hash: "0123456789abcdef0123456789abcdef",
    ...over,
  };
}

function envelope<T>(data: T): Envelope<T> {
  return {
    status: "ok",
    data,
    reason: null,
    meta: {
      generated_at: "2026-11-03T16:00:00Z",
      api_version: "v1",
      count: null,
      total: null,
      limit: null,
      offset: null,
      data_as_of: null,
    },
  };
}

function inClient(seed: (qc: QueryClient) => void, node: React.ReactNode): string {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seed(qc);
  return renderToStaticMarkup(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

/** The engine filter of a rendered page (the tab has a second select, the decision's): its markup only. */
function engineFilter(html: string): string {
  const found = /<select[^>]*aria-label="(?:Motor|Engine)"[^>]*>(.*?)<\/select>/s.exec(html);
  expect(found).not.toBeNull();
  return (found as RegExpExecArray)[1] as string;
}

/** The options of a rendered select, as [value, name, selected]. */
function options(html: string): Array<[string, string, boolean]> {
  return [...html.matchAll(/<option value="([^"]*)"([^>]*)>([^<]*)<\/option>/g)].map((m) => [
    m[1] as string,
    m[3] as string,
    (m[2] as string).includes("selected"),
  ]);
}

describe("the engine filter of the reviews", () => {
  test("offers production's three and then the three shadow ones, each by a name that says what it is", () => {
    const html = renderToStaticMarkup(<EngineSelect value="combined" onChange={() => {}} />);
    expect(options(html)).toEqual([
      ["combined", "Combinada", true],
      ["rules", "Reglas", false],
      ["llm", "Modelo de lenguaje", false],
      ["ma-v1", "Multiagente (sombra)", false],
      ["ma-v1-h", "Multiagente + Council Haiku (sombra)", false],
      ["cs-v1", "Council solo (sombra)", false],
    ]);
    expect(html).toContain('aria-label="Motor"');
    setLocale("en");
    const en = renderToStaticMarkup(<EngineSelect value="cs-v1" onChange={() => {}} />);
    expect(options(en).map(([v, n, s]) => [v, n, s])).toEqual([
      ["combined", "Combined", false],
      ["rules", "Rules", false],
      ["llm", "Language model", false],
      ["ma-v1", "Multi-agent (shadow)", false],
      ["ma-v1-h", "Multi-agent + Haiku Council (shadow)", false],
      ["cs-v1", "Council only (shadow)", true],
    ]);
    expect(en).toContain('aria-label="Engine"');
  });

  test("offers every engine of the type, each once", () => {
    const values = options(renderToStaticMarkup(<EngineSelect value="llm" onChange={() => {}} />));
    expect(values.map(([v]) => v)).toEqual([...REVIEW_ENGINES]);
    expect(values.filter(([, , selected]) => selected).map(([v]) => v)).toEqual(["llm"]);
  });
});

describe("the note under the filter", () => {
  test("a shadow engine says its reviews are for the evaluation and never reach the decision layer", () => {
    for (const engine of SHADOW) {
      const out = text(renderToStaticMarkup(<ShadowEngineNote engine={engine} />));
      expect(out).toContain("Motor en sombra");
      expect(out).toContain("nunca llegan a la capa de decisión ni a los usuarios");
    }
    setLocale("en");
    const en = text(renderToStaticMarkup(<ShadowEngineNote engine="ma-v1-h" />));
    expect(en).toContain("Shadow engine");
    expect(en).toContain("never reach the decision layer or users");
  });

  test("production's engines, and a name nobody knows, have no note", () => {
    for (const engine of [...PRODUCTION, "ma-v2", ""]) {
      expect(renderToStaticMarkup(<ShadowEngineNote engine={engine} />)).toBe("");
    }
  });
});

describe("the engine of a review", () => {
  test("a shadow engine is named and carries a Shadow badge", () => {
    const out = renderToStaticMarkup(<EngineTag engine="ma-v1" />);
    expect(out).toContain('data-engine="ma-v1"');
    expect(text(out)).toBe(" Shadow Multiagente (sombra) ");
    setLocale("en");
    expect(text(renderToStaticMarkup(<EngineTag engine="cs-v1" />))).toBe(
      " Shadow Council only (shadow) ",
    );
  });

  test("production's engines are named without it, and a name nobody knows is shown as given", () => {
    expect(text(renderToStaticMarkup(<EngineTag engine="combined" />))).toBe(" Combinada ");
    expect(text(renderToStaticMarkup(<EngineTag engine="ma-v2" />))).toBe(" ma-v2 ");
  });
});

describe("the page of a review", () => {
  test("the review of a shadow engine opens with its engine named", () => {
    for (const engine of SHADOW) {
      const html = renderToStaticMarkup(
        <ReviewDetailView
          d={detail({ review: review({ id: 9, engine, engine_version: `${engine}-v1` }) })}
        />,
      );
      expect(html).toContain(`data-engine="${engine}"`);
      expect(text(html)).toContain("Shadow");
    }
    const html = renderToStaticMarkup(
      <ReviewDetailView d={detail({ review: review({ engine: "ma-v1" }) })} />,
    );
    expect(text(html)).toContain("Alpha - Beta");
    expect(text(html)).toContain("Multiagente (sombra)");
  });

  test("the review of a production engine opens as before: no engine tag, its components by their engine", () => {
    const html = renderToStaticMarkup(
      <ReviewDetailView
        d={detail({
          components: [
            review({ id: 11, engine: "rules", engine_version: "rules-review-v1" }),
            review({
              id: 12,
              engine: "llm",
              engine_version: "review-v2",
              model: "claude-haiku-5-5",
            }),
          ],
        })}
      />,
    );
    expect(html).not.toContain("ai-engine-tag");
    expect(text(html)).toContain("rules · rules-review-v1 · — ·");
    expect(text(html)).toContain("llm · review-v2 · claude-haiku-5-5 ·");
  });

  test("a component that is a shadow engine is named as one", () => {
    const html = renderToStaticMarkup(
      <ReviewDetailView d={detail({ components: [review({ id: 12, engine: "cs-v1" })] })} />,
    );
    expect(html).toContain('data-engine="cs-v1"');
    expect(text(html)).toContain("Council solo (sombra)");
  });

  test("an output that is not shaped like a review's (a shadow engine's) shows nothing for what it cannot read, and opens", () => {
    const odd = {
      reason: "the Council approves",
      positive_evidence: "a sentence, not a list",
      negative_evidence: { a: 1 },
      uncertainties: 5,
      contradictions: null,
      rejected_claims: "none",
      engines: ["match", "council"],
    } as unknown as AiReviewDetail["output"];
    const html = renderToStaticMarkup(
      <ReviewDetailView d={detail({ review: review({ engine: "ma-v1-h" }), output: odd })} />,
    );
    expect(text(html)).toContain("the Council approves");
    expect(html).toContain('data-engine="ma-v1-h"');
    expect(
      html.match(/<p class="text-caption text-subtle-foreground">—<\/p>/g)?.length,
    ).toBeGreaterThanOrEqual(4);
  });
});

describe("the reviews tab", () => {
  const seed = (engine: AiEngine, rows: AiReviewRow[]) => (qc: QueryClient) =>
    qc.setQueryData(
      live.aiReviews({ engine, decision: undefined, day: undefined, limit: 200 }).queryKey,
      envelope(rows),
    );

  test("opens on the combined review as before, with no note", () => {
    const html = inClient(seed("combined", [review()]), <ReviewsTab />);
    expect(text(html)).toContain("Alpha - Beta");
    const engines = options(engineFilter(html));
    expect(engines).toHaveLength(6);
    expect(engines.filter(([, , selected]) => selected)).toEqual([["combined", "Combinada", true]]);
    expect(text(html)).not.toContain("Motor en sombra");
  });

  test("on a shadow engine it lists that engine's reviews and says what they are", () => {
    for (const engine of SHADOW) {
      const html = inClient(
        seed(engine, [review({ id: 5, engine, match: `Gamma - Delta ${engine}` })]),
        <ReviewsTab initialEngine={engine} />,
      );
      expect(text(html)).toContain(`Gamma - Delta ${engine}`);
      expect(
        options(engineFilter(html))
          .filter(([, , selected]) => selected)
          .map(([v]) => v),
      ).toEqual([engine]);
      expect(text(html)).toContain("Motor en sombra");
    }
  });
});

describe("the shadow report", () => {
  const report = (engine: AiEngine): ShadowReportRow => ({
    engine,
    created_at: "2026-11-02T07:35:00Z",
    window_from: "2026-09-03",
    window_to: "2026-11-01",
    verdict: "insufficient",
    checks: { selections: { value: 12, need: 300, ok: false } },
    arms: { model: { n: 12 } },
  });
  const seed = (rows: ShadowReportRow[]) => (qc: QueryClient) =>
    qc.setQueryData(live.aiShadow.queryKey, envelope(rows));

  test("titles each engine by its name: a shadow one says so, production's read as before", () => {
    const html = inClient(
      seed([report("rules"), report("llm"), report("combined"), ...SHADOW.map(report)]),
      <ShadowTab />,
    );
    const titles = [...html.matchAll(/<h2 class="text-title">([^<]*)<\/h2>/g)].map((m) => m[1]);
    expect(titles).toEqual([
      "Reglas",
      "Modelo de lenguaje",
      "Combinada",
      "Multiagente (sombra)",
      "Multiagente + Council Haiku (sombra)",
      "Council solo (sombra)",
    ]);
    setLocale("en");
    const en = inClient(seed([report("combined"), report("ma-v1-h")]), <ShadowTab />);
    expect([...en.matchAll(/<h2 class="text-title">([^<]*)<\/h2>/g)].map((m) => m[1])).toEqual([
      "Combined",
      "Multi-agent + Haiku Council (shadow)",
    ]);
  });
});

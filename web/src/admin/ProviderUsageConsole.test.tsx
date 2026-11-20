/// <reference types="bun" />
/**
 * Plan PM, PM-04-05 (UX-175): the console of the provider's requests reproduces annex F's figures for a known window (20 Oct to
 * 18 Nov 2026: mean 17.845, median 15.802, largest normal day 23.430 on 2 Nov, one day with the budget spent), shows each lane
 * against its ceiling, the endpoints and the competitions - saying that what it counts by competition are stored answers, not
 * requests - and the guards.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { ProviderUsage } from "@/lib/api/v1/types_provider_usage";
import { ProviderUsageView } from "./ProviderUsageConsole";

afterAll(() => setLocale("es"));

// raw.provider_quota, 20 Oct to 18 Nov 2026 (read on the server on 20 Nov 14:48 UTC)
const ANNEX_F = [
  18648, 11825, 10665, 14266, 16810, 15276, 23320, 19413, 13534, 60000, 14671, 16734, 18396, 23430,
  19355, 14245, 14842, 14763, 16993, 15250, 22427, 17366, 11377, 13058, 13699, 16327, 13058, 23112,
  19187, 13297,
];

function day(i: number): string {
  return new Date(Date.UTC(2026, 9, 20 + i)).toISOString().slice(0, 10);
}

const usage: ProviderUsage = {
  provider: "api_football",
  generated_at: "2026-11-20T14:48:00Z",
  today: {
    day: "2026-11-20",
    spent: 10585,
    counted: 10585,
    budget: 60000,
    provider_limit: 75000,
    elapsed: 0.6167,
    projected: 17164,
    margin: 42836,
    margin_pct: 71.4,
    last_request_at: "2026-11-20T14:47:30Z",
  },
  window: {
    since: "2026-10-20",
    until: "2026-11-18",
    days: 30,
    mean: 17845.0,
    median: 15801.5,
    max: 60000,
    max_day: "2026-10-29",
    max_normal: 23430,
    max_normal_day: "2026-11-02",
    exhausted_days: 1,
  },
  days: ANNEX_F.map((spent, i) => ({
    day: day(i),
    spent,
    budget: 60000,
    exhausted: spent >= 60000,
  })),
  lanes: [
    {
      lane: "directo",
      label: "Directo",
      priority: 1,
      ceiling: 15000,
      vital: true,
      today: 3100,
      max_day: 3100,
      share: 20.7,
    },
    {
      lane: "referencia",
      label: "Referencia",
      priority: 7,
      ceiling: 15000,
      vital: false,
      today: 4200,
      max_day: 4200,
      share: 28,
    },
  ],
  endpoints: [{ endpoint: "/players/teams", lane: "referencia", today: 2000, window: 2000 }],
  competitions: [
    { league_id: 239, competition_id: 12, name: "Primera A", country: "Colombia", responses: 812 },
    { league_id: 99999, competition_id: null, name: null, country: null, responses: 3 },
  ],
  counted_since: "2026-11-20",
  guards: {
    lanes_mode: "off",
    dynamic_limits: false,
    emergency_reserve: 7000,
    account_guard: true,
    account_pause_seconds: 900,
    quiet_minutes: 0.5,
  },
};

const text = (s: string) => s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

describe("the console of the provider's requests", () => {
  test("annex F's figures of the known window", () => {
    setLocale("es");
    const words = text(renderToStaticMarkup(<ProviderUsageView usage={usage} />));
    expect(words).toContain("Media de la ventana 17.845");
    expect(words).toContain("Mediana 15.802 · 30 días");
    expect(words).toContain("Máximo de un día normal 23.430");
    expect(words).toContain("1 días con el presupuesto agotado (máximo 60.000)");
    expect(words).toContain("Margen 42.836 (71,4 %) sobre el presupuesto de 60.000");
  });

  test("lanes against their ceilings, days, endpoints, competitions and guards", () => {
    setLocale("es");
    const html = renderToStaticMarkup(<ProviderUsageView usage={usage} />);
    const words = text(html);
    expect(html.match(/data-testid="usage-lane"/g)?.length).toBe(2);
    expect(words).toContain("vital");
    expect(html).toContain('aria-label="Directo: 20,7 % del techo"');
    expect(html.match(/data-testid="usage-day"/g)?.length).toBe(14); // two weeks at a time
    expect(words).toContain("/players/teams");
    expect(words).toContain("Primera A");
    expect(words).toContain("Liga 99999 (sin alta)");
    expect(words).toContain("No son peticiones");
    expect(words).toContain("Guardián de la cuenta encendido");
    expect(words).toContain("900 s");
  });
});

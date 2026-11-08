/**
 * The owner's diagnosis of a match's news in words (IA-019): why the match has news or not, as the API decided it (the verdict's
 * code is the server's; this only says it). Times are Bogotá's, the AI's own day. Pure: no React, no fetching.
 */
import { t } from "@/lib/i18n";
import { fmtInt, localFixed, toNumber } from "@/lib/i18n/format";
import { dayKey, formatDateTime, formatTime } from "@/lib/time";
import type { Dec } from "@/lib/api/v1/types";
import type {
  DiagnosisExa,
  DiagnosisNextPass,
  DiagnosisPass,
  DiagnosisPassKind,
  DiagnosisVerdict,
  NewsDiagnosis,
  NewsStatus,
} from "@/lib/api/v1/types_news";

/** The AI's day is Bogotá's: every time of the diagnosis is said in it. */
export const DAY_ZONE = "America/Bogota";

/** «a las 09:10» on the same Bogotá day as `now`, «el 8 nov 09:10» otherwise. */
export function whenText(iso: string, now: number = Date.now()): string {
  return dayKey(iso, DAY_ZONE) === dayKey(now, DAY_ZONE)
    ? t("match.advanced.news.atTime", { time: formatTime(iso, DAY_ZONE) })
    : t("match.advanced.news.onDay", { when: formatDateTime(iso, DAY_ZONE) });
}

/** «10:00» on the same Bogotá day as `now`, «9 nov 00:05» otherwise. */
export function clockText(iso: string, now: number = Date.now()): string {
  return dayKey(iso, DAY_ZONE) === dayKey(now, DAY_ZONE)
    ? formatTime(iso, DAY_ZONE)
    : formatDateTime(iso, DAY_ZONE);
}

export function passName(kind: DiagnosisPassKind): string {
  return t(`match.advanced.news.pass.${kind}`);
}

export function usd(value: Dec | number | null | undefined, digits = 2): string {
  const n = toNumber(value);
  return n === null ? "—" : `${localFixed(n, digits)} US$`;
}

/** The verdict as one line: the reason the server found first, with its figures. */
export function verdictText(v: DiagnosisVerdict, now: number = Date.now()): string {
  const base = "match.advanced.news.verdict";
  if (v.code === "searched") {
    const parts = [
      t("match.advanced.news.count.searches", { count: v.searches ?? 0 }),
      v.pages === null || v.pages === undefined
        ? t("match.advanced.news.count.pagesUnknown")
        : t("match.advanced.news.count.pages", { count: v.pages }),
      t("match.advanced.news.count.items", { count: v.items ?? 0 }),
    ];
    return t(`${base}.searched`, {
      when: v.at ? whenText(v.at, now) : "—",
      figures: parts.join(", "),
    });
  }
  const line =
    v.code === "exa_spent"
      ? t(`${base}.exa_spent`, { reason: exaReasonText(v.exa_reason ?? "") })
      : t(`${base}.${v.code}`);
  if (v.code === "day_not_open" && v.next_at) {
    return t(`${base}.day_not_open_at`, { when: whenText(v.next_at, now) });
  }
  return v.next_pass && v.next_at
    ? `${line} ${t("match.advanced.news.nextHint", { pass: passName(v.next_pass), when: whenText(v.next_at, now) })}`
    : line;
}

export function exaReasonText(reason: string): string {
  return ["ok", "month_spent", "day_cap", "no_envelope"].includes(reason)
    ? t(`match.advanced.news.exaReason.${reason}`)
    : reason;
}

/** Exa's envelope: spent of the month against the budget, today against its cap, and whether it still allows a search. */
export function exaText(exa: DiagnosisExa | null): string {
  if (!exa) return t("match.advanced.news.exaUnknown");
  return t("match.advanced.news.exaLine", {
    spent: usd(exa.spent_month_usd),
    budget: usd(exa.budget_usd),
    today: usd(exa.spent_today_usd),
    cap: usd(exa.daily_cap_usd),
    state: exaReasonText(exa.reason),
  });
}

/** The named web counts of a pass first, in this order; any other web_* count after them, as recorded. */
const WEB_ORDER = ["web_searches", "web_asked", "web_read", "web_items", "web_new"] as const;
const WEB_FLAGS = ["web_priority", "web_press"] as const;

export function passWebText(p: DiagnosisPass): string {
  const named: readonly string[] = [...WEB_ORDER, ...WEB_FLAGS];
  const parts = WEB_ORDER.filter((k) => k in p.web).map((k) =>
    t(`match.advanced.news.web.${k}`, { count: p.web[k] ?? 0 }),
  );
  for (const k of WEB_FLAGS) if ((p.web[k] ?? 0) > 0) parts.push(t(`match.advanced.news.web.${k}`));
  for (const [k, n] of Object.entries(p.web))
    if (!named.includes(k)) parts.push(`${k} ${fmtInt(n)}`);
  if (p.near_budget) parts.push(t("match.advanced.news.web.nearBudget"));
  return parts.length ? parts.join(" · ") : t("match.advanced.news.web.none");
}

export function passStatusText(status: string): string {
  return ["ok", "partial", "skipped", "failed"].includes(status)
    ? t(`match.advanced.news.passStatus.${status}`)
    : status;
}

export function nextPassText(n: DiagnosisNextPass | null, now: number = Date.now()): string {
  if (!n) return t("match.advanced.news.noNextPass");
  const line = t("match.advanced.news.nextLine", {
    pass: passName(n.kind),
    from: clockText(n.window_from, now),
    until: clockText(n.window_until, now),
  });
  const extra = [
    n.lineups_until
      ? t("match.advanced.news.lineupsUntil", { time: formatTime(n.lineups_until, DAY_ZONE) })
      : null,
    n.due_now ? t("match.advanced.news.dueNow") : null,
  ].filter((x): x is string => x !== null);
  return [line, ...extra].join(" ");
}

export function coverageText(d: NewsDiagnosis): string {
  const group = d.match.priority_group;
  if (!d.coverage.switch_on) return t("match.advanced.news.coverage.off", { group });
  return d.coverage.covered
    ? t("match.advanced.news.coverage.yes", { group })
    : t("match.advanced.news.coverage.no", { group });
}

export function marketText(d: NewsDiagnosis, now: number = Date.now()): string {
  if (d.day.has_market === null) return t("match.advanced.news.market.untracked");
  if (!d.day.has_market) return t("match.advanced.news.market.no");
  return d.day.odds_at
    ? t("match.advanced.news.market.yesAt", { when: whenText(d.day.odds_at, now) })
    : t("match.advanced.news.market.yes");
}

export function dayText(d: NewsDiagnosis, now: number = Date.now()): string {
  return d.day.opened
    ? t("match.advanced.news.day.opened", { when: whenText(d.day.opens_at, now) })
    : t("match.advanced.news.day.opens", { when: whenText(d.day.opens_at, now) });
}

export function searchesText(d: NewsDiagnosis, now: number = Date.now()): string {
  const s = d.searches;
  if (s.searches === 0 && s.failed === 0) return t("match.advanced.news.searches.none");
  const parts = [t("match.advanced.news.count.searches", { count: s.searches })];
  if (s.failed > 0) parts.push(t("match.advanced.news.searches.failed", { count: s.failed }));
  if (s.first_at)
    parts.push(t("match.advanced.news.searches.first", { when: whenText(s.first_at, now) }));
  if (s.last_at && s.last_at !== s.first_at)
    parts.push(t("match.advanced.news.searches.last", { when: whenText(s.last_at, now) }));
  parts.push(usd(s.cost_usd, 3));
  return parts.join(" · ");
}

const STATUSES: readonly NewsStatus[] = [
  "CONFIRMED",
  "PROBABLE",
  "CONTRADICTORY",
  "RUMOR",
  "OUTDATED",
];

export function evidenceText(d: NewsDiagnosis): string {
  const total = STATUSES.reduce((n, s) => n + (d.evidence[s] ?? 0), 0);
  if (total === 0) return t("match.advanced.news.evidence.none");
  return STATUSES.filter((s) => (d.evidence[s] ?? 0) > 0)
    .map((s) => t(`match.advanced.news.evidence.${s}`, { count: d.evidence[s] ?? 0 }))
    .join(" · ");
}

/**
 * What the reader's saved picks under the filter add up to (plan UX, B5, section 30): how many and how they ended, and -
 * only from the sample the plan asks (25 settled picks) - the units, the return with its margin and the hit rate, with
 * «todavía no permite concluir» below 100; the line value of their prices (clv-v1, its definition and date); and the
 * breakdown by kind of bet, league and odds range, each row with its own sample. All of it is the server's
 * (GET /me/picks/summary), on the same filter as the list and the CSV: never a figure over part of the records.
 */
import type { ReactNode } from "react";
import { Download, Sigma } from "lucide-react";
import { t } from "@/lib/i18n";
import { DASH, fmtInt, fmtPct, toNumber } from "@/lib/i18n/format";
import { formatDateYear } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { PicksSummary, PicksTally } from "@/lib/api/v1/types_mypicks";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import { Card } from "@/product/shared/States";
import { marketName } from "@/product/shared/markets";
import { Units } from "./Badges";
import { bandLabel, countsText, signedPct } from "./picksText";
import { sampleLine } from "./sample";

function Figure({
  label,
  value,
  testId,
  tone,
}: {
  label: ReactNode;
  value: ReactNode;
  testId: string;
  tone?: string | undefined;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-label leading-tight text-subtle-foreground">{label}</dt>
      <dd className={cn("numeric mt-1 text-base font-semibold", tone)} data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

function toneOf(value: string | null): string | undefined {
  const n = toNumber(value);
  if (n === null || n === 0) return undefined;
  return n > 0 ? "text-positive" : "text-negative";
}

function TallyBlock({ s }: { s: PicksSummary }) {
  const x = s.tally;
  const counts = x.sample === "counts_only";
  return (
    <div className="space-y-3">
      <p className="text-sm" data-testid="mypicks-summary-counts">
        <span className="font-semibold">
          {t("records.mine.summary.total", { count: x.total, n: fmtInt(x.total) })}
        </span>{" "}
        <span className="text-muted-foreground">{countsText(x)}</span>
      </p>
      {counts ? null : (
        <dl className="grid grid-cols-3 gap-3">
          <Figure
            label={<GlossaryTerm term="units">{t("records.mine.summary.units")}</GlossaryTerm>}
            value={<Units value={x.units} className="text-base" />}
            testId="mypicks-summary-units"
          />
          <Figure
            label={<GlossaryTerm term="roi">{t("records.mine.results.roi")}</GlossaryTerm>}
            value={signedPct(x.roi)}
            tone={toneOf(x.roi)}
            testId="mypicks-summary-roi"
          />
          <Figure
            label={t("records.mine.results.hitRate")}
            value={fmtPct(x.hit_rate, 0)}
            testId="mypicks-summary-hit-rate"
          />
        </dl>
      )}
      {x.settled > 0 ? (
        <p
          className={cn(
            "text-caption",
            x.sample === "conclusive" ? "text-subtle-foreground" : "text-muted-foreground",
          )}
          data-testid="mypicks-summary-sample"
          data-sample={x.sample}
        >
          <GlossaryTerm term="sample">
            {sampleLine({
              n: x.settled,
              margin: toNumber(x.margin),
              min: s.min_sample,
              conclusive: s.conclusive,
            })}
          </GlossaryTerm>
        </p>
      ) : null}
    </div>
  );
}

function LineValueBlock({ s }: { s: PicksSummary }) {
  const lv = s.line_value;
  let body: string;
  if (lv.n === 0) body = t("records.mine.summary.lineValue.none");
  else if (lv.mean === null)
    body = t("records.mine.summary.lineValue.small", {
      count: lv.n,
      n: fmtInt(lv.n),
      min: fmtInt(s.min_sample),
    });
  else
    body = t("records.mine.summary.lineValue.mean", {
      mean: signedPct(lv.mean),
      positive: fmtPct(lv.positive, 0),
      count: lv.n,
      n: fmtInt(lv.n),
    });
  return (
    <div
      className="space-y-1 border-t border-border/60 pt-3"
      data-testid="mypicks-summary-line-value"
    >
      <h4 className="text-label text-subtle-foreground">
        <GlossaryTerm term="lineValue">{t("records.mine.summary.lineValue.title")}</GlossaryTerm>
      </h4>
      <p className="text-sm">{body}</p>
      {lv.minutes !== null ? (
        <p className="text-caption text-subtle-foreground">
          {t("records.mine.summary.lineValue.minutes", { minutes: fmtInt(lv.minutes) })}
        </p>
      ) : null}
      <p className="text-caption text-subtle-foreground">
        {t("records.mine.summary.lineValue.definition", {
          version: lv.version,
          since: formatDateYear(`${lv.since}T12:00:00Z`),
        })}
      </p>
    </div>
  );
}

function BreakdownRow({ label, x, testId }: { label: ReactNode; x: PicksTally; testId: string }) {
  return (
    <li
      className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 py-2"
      data-testid={testId}
      data-sample={x.sample}
    >
      <span className="min-w-0 break-words text-sm font-medium">{label}</span>
      <span className="numeric text-caption text-muted-foreground">
        {t("records.mine.summary.row", {
          total: fmtInt(x.total),
          settled: fmtInt(x.settled),
          won: fmtInt(x.won + x.half_won),
          lost: fmtInt(x.lost + x.half_lost),
        })}
        {" · "}
        {x.sample === "counts_only" ? (
          <span>{t("records.mine.summary.rowCounts")}</span>
        ) : (
          <>
            <Units value={x.units} className="text-caption" />
            {" · "}
            <span className={toneOf(x.roi)}>
              {t("records.mine.summary.rowRoi", { roi: signedPct(x.roi) })}
            </span>
          </>
        )}
      </span>
    </li>
  );
}

function Breakdown({ s }: { s: PicksSummary }) {
  if (s.tally.total === 0) return null;
  return (
    <details className="group border-t border-border/60 pt-3" data-testid="mypicks-breakdown">
      <summary className="tap-y relative cursor-pointer list-none text-sm font-semibold text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {t("records.mine.summary.breakdown")}
      </summary>
      <p className="mt-1 text-caption text-subtle-foreground">
        {t("records.mine.summary.breakdownNote", { min: fmtInt(s.min_sample) })}
      </p>
      <div className="mt-2 grid gap-4 lg:grid-cols-3">
        <section>
          <h4 className="text-label text-subtle-foreground">
            {t("records.mine.summary.byMarket")}
          </h4>
          <ul className="divide-y divide-border/60" data-testid="mypicks-breakdown-markets">
            {s.markets.map((m) => (
              <BreakdownRow
                key={m.market}
                label={marketName(m.market)}
                x={m}
                testId="mypicks-breakdown-market"
              />
            ))}
          </ul>
        </section>
        <section>
          <h4 className="text-label text-subtle-foreground">
            {t("records.mine.summary.byCompetition")}
          </h4>
          <ul className="divide-y divide-border/60" data-testid="mypicks-breakdown-competitions">
            {s.competitions.map((c) => (
              <BreakdownRow
                key={c.competition.id}
                label={c.competition.name}
                x={c}
                testId="mypicks-breakdown-competition"
              />
            ))}
          </ul>
        </section>
        <section>
          <h4 className="text-label text-subtle-foreground">{t("records.mine.summary.byBand")}</h4>
          <ul className="divide-y divide-border/60" data-testid="mypicks-breakdown-bands">
            {s.bands.map((b) => (
              <BreakdownRow
                key={b.band}
                label={<span className="numeric">{bandLabel(b.band)}</span>}
                x={b}
                testId="mypicks-breakdown-band"
              />
            ))}
          </ul>
        </section>
      </div>
    </details>
  );
}

export function PicksSummaryBlock({
  summary,
  exportHref,
  busy,
}: {
  summary: PicksSummary;
  /** The CSV of the same picks (GET /me/picks/export with the same filter). */
  exportHref: string;
  busy?: boolean | undefined;
}) {
  const filtered = summary.filter.active > 0;
  return (
    <Card className={cn("space-y-3 p-4 transition-opacity", busy && "opacity-70")} as="section">
      <div
        className="flex flex-wrap items-center justify-between gap-2"
        data-testid="mypicks-summary"
      >
        <h3 className="inline-flex items-center gap-1.5 font-display text-sm font-semibold">
          <Sigma aria-hidden className="h-4 w-4 text-primary" />
          {filtered ? t("records.mine.summary.filtered") : t("records.mine.summary.all")}
        </h3>
        {summary.tally.total > 0 ? (
          <a
            href={exportHref}
            download
            data-testid="mypicks-export"
            className="tap-y relative inline-flex h-9 items-center gap-1.5 rounded-full border border-border-strong px-3.5 text-xs font-semibold hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Download aria-hidden className="h-3.5 w-3.5" />
            {t("records.mine.summary.export")}
          </a>
        ) : null}
      </div>
      <TallyBlock s={summary} />
      <LineValueBlock s={summary} />
      <Breakdown s={summary} />
    </Card>
  );
}

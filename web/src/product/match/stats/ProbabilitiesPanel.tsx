/**
 * The probabilities by market of a match (plan EA, EA-202; maqueta V2·8): the three marks of every price in force - the model's
 * figure ▮ (only on a market the catalogue holds evaluable, with its seal), the implied probability │ (the margin-free consensus) and
 * the history ● (n/N with its Wilson interval) - and the state of each market in words. A total with a line opens its lines.
 * Nothing here selects or recommends: the prices to choose stay in the catalogue below, as they were. The owner also sees the figure
 * of the models still in validation, labelled as such (decision D-EA-2). Shown while FBI_MARKET_PROBS is on.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import { isMissing, present, type Probability } from "@/lib/api/v1/types_intelligence";
import type { MarketMarks, SelectionMarks } from "@/lib/api/v1/types_stats";
import { useStatsSwitches } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { fmtLine } from "@/lib/i18n/format";
import { formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ChartCard, ChipChoice } from "@/components/analytics/stats/ChartCard";
import { catalogSelection, catalogTitle, periodLabel } from "../marketCatalog";

type Sides = { home: string; away: string };
const FEATURED_UNITS = new Set(["1X2", "OU", "BTTS"]);

/** The bar of the model, the tick of the implied, the dot of the history: three marks, never one number. */
export function TriMark({ s, owner }: { s: SelectionMarks; owner: boolean }) {
  const model: Probability | null = present(s.model) ?? (owner ? present(s.model_shadow) : null);
  const shadow = !present(s.model) && model !== null;
  const implied = present(s.implied);
  const history = present(s.history);
  return (
    <div className="relative h-3.5 flex-1 rounded-full bg-elevated" aria-hidden>
      {model ? (
        <span
          className={cn(
            "absolute inset-y-0 left-0 rounded-full",
            shadow ? "bg-warning/50" : "bg-primary",
          )}
          style={{ width: `${Math.max(2, model.pct)}%` }}
        />
      ) : null}
      {implied ? (
        <span
          className="absolute -top-0.5 h-[1.125rem] w-0.5 bg-foreground-soft"
          style={{ left: `${implied.pct}%` }}
        />
      ) : null}
      {history ? (
        <span
          className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-gold"
          style={{ left: `${history.pct}%` }}
        />
      ) : null}
    </div>
  );
}

function Seal({ p }: { p: Probability }) {
  return (
    <span className="text-[11px] text-subtle-foreground">
      {p.calibration === "calibrada" ? t("stats.sealCalibrated") : t("stats.sealUncalibrated")} ·{" "}
      {p.origin}
    </span>
  );
}

function SelectionRow({
  m,
  s,
  sides,
  index,
  owner,
}: {
  m: MarketMarks;
  s: SelectionMarks;
  sides: Sides;
  index: number;
  owner: boolean;
}) {
  const model = present(s.model);
  const shadow = owner && !model ? present(s.model_shadow) : null;
  const implied = present(s.implied);
  const history = present(s.history);
  const name = catalogSelection(
    m.kind,
    s.selection,
    s.line === 0 && m.kind !== "asian_handicap" && m.kind !== "over_under" ? null : s.line,
    sides,
    index,
  );
  const label = [
    name,
    model ? `${t("stats.triModel")} ${model.pct} %` : null,
    shadow ? `${t("stats.shadowLabel")} ${shadow.pct} %` : null,
    implied ? t("stats.implied", { pct: implied.pct }) : null,
    history ? t("stats.history", { hits: history.hits, n: history.n }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="space-y-1" aria-label={label}>
      <div className="flex items-center gap-2">
        <span className="w-28 shrink-0 truncate text-caption text-foreground-soft sm:w-36">
          {name}
        </span>
        <TriMark s={s} owner={owner} />
        <span className="numeric w-11 shrink-0 text-right text-sm font-semibold">
          {model ? (
            `${model.pct} %`
          ) : shadow ? (
            <span className="text-warning">{shadow.pct} %</span>
          ) : (
            "—"
          )}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-3 pl-0 text-[12px] text-subtle-foreground sm:pl-38">
        {implied ? (
          <span className="numeric">{t("stats.implied", { pct: implied.pct })}</span>
        ) : null}
        {history ? (
          <span className="numeric text-gold">
            {t("stats.history", { hits: history.hits, n: history.n })} ({history.wilson_low}–
            {history.wilson_high} %)
          </span>
        ) : null}
        {model ? <Seal p={model} /> : null}
        {shadow ? <span className="text-warning">{t("stats.shadowLabel")}</span> : null}
      </div>
    </li>
  );
}

function MarketCard({ m, sides, owner }: { m: MarketMarks; sides: Sides; owner: boolean }) {
  const lines = useMemo(
    () => [...new Set(m.selections.map((s) => s.line))].sort((a, b) => a - b),
    [m.selections],
  );
  const withLines = lines.length > 1 && (m.kind === "over_under" || m.kind === "asian_handicap");
  const main = lines.includes(2.5) ? 2.5 : (lines[Math.floor(lines.length / 2)] ?? 0);
  const [line, setLine] = useState<number>(main);
  const shown = withLines ? m.selections.filter((s) => s.line === line) : m.selections;
  const code = m.key.split(".")[0] ?? "";
  const title = `${catalogTitle({ code, subject: m.subject }, sides)}${m.period !== "FT" ? ` · ${periodLabel(m.period)}` : ""}`;
  return (
    <ChartCard
      title={title}
      subtitle={t(`stats.stateNote.${m.state}`)}
      testId={`probs-${m.unit}`}
      actions={
        <span
          className={cn(
            "rounded-lg px-2 py-1 text-[12px] font-semibold",
            m.state === "evaluable"
              ? "bg-primary-soft text-primary"
              : m.state === "en_calibracion"
                ? "bg-warning-soft text-warning"
                : "bg-elevated text-muted-foreground",
          )}
        >
          {t(`stats.state.${m.state}`)}
        </span>
      }
    >
      {withLines ? (
        <ChipChoice
          value={String(line)}
          onChange={(v) => setLine(Number(v))}
          label={t("stats.lineLabel")}
          options={lines
            .slice(0, 8)
            .map((l) => ({ value: String(l), label: fmtLine(l, m.kind === "asian_handicap") }))}
        />
      ) : null}
      <ul className="space-y-3">
        {shown.map((s, i) => (
          <SelectionRow
            key={`${s.selection}${s.line}`}
            m={m}
            s={s}
            sides={sides}
            index={i}
            owner={owner}
          />
        ))}
      </ul>
    </ChartCard>
  );
}

export function ProbabilitiesPanel({
  fixtureId,
  category,
  sides,
}: {
  fixtureId: string;
  /** «featured» or a category of the catalogue: the panel shows the markets of the chip the reader is on. */
  category: string;
  sides: Sides;
}) {
  const { owner: showAdmin } = useStatsSwitches();
  const q = useQuery(live.matchMarketProbs(fixtureId, showAdmin));
  if (!q.data) return null;
  const data = q.data.data;
  const markets = data.markets.items.filter((m) =>
    category === "featured"
      ? FEATURED_UNITS.has(m.unit) && m.period === "FT"
      : m.category === category,
  );
  if (!markets.length) return null;
  const books = Math.max(
    0,
    ...markets.flatMap((m) =>
      m.selections.map((s) => (isMissing(s.implied) ? 0 : s.implied.books)),
    ),
  );
  const when = markets
    .flatMap((m) => m.selections.map((s) => (isMissing(s.implied) ? "" : s.implied.as_of)))
    .filter(Boolean)
    .sort()
    .at(-1);
  return (
    <section
      className="mb-4 space-y-3"
      data-testid="probabilities-panel"
      aria-label={t("stats.probsTitle")}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-subheading">{t("stats.probsTitle")}</h3>
        <span className="text-caption text-muted-foreground">{t("stats.triLegend")}</span>
      </div>
      {when ? (
        <p className="text-caption text-subtle-foreground">
          {t("stats.probsSub", { books, when: formatRelative(when) })}
        </p>
      ) : null}
      <div className="grid items-start gap-3 lg:grid-cols-2">
        {markets.slice(0, 12).map((m) => (
          <MarketCard key={m.key} m={m} sides={sides} owner={showAdmin} />
        ))}
      </div>
      <details className="text-caption text-subtle-foreground">
        <summary className="flex min-h-11 cursor-pointer items-center">
          {t("stats.methodTitle")}
        </summary>
        <p className="leading-relaxed">{t("stats.methodBody")}</p>
      </details>
    </section>
  );
}

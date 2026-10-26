/**
 * /transparency - «Cómo le va a PrediGol» (plan UX, A12; section 31 of the plan): what PrediGol published and how it went in
 * fixed periods, the days without picks and why, by kind of bet, the line value, the forecast's calibration and what is still
 * in evaluation - every figure beside its sample, never a streak, a star pick or a projection. Readers see it once the owner
 * opens it (FBI_TRANSPARENCY, after P9); the owner always sees it, labelled as a preview while readers do not.
 * Cards stacked on a phone, the figure and its n together.
 */
import { useId, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  CalendarX2,
  FlaskConical,
  Gauge,
  Layers,
  ListChecks,
  Scale,
} from "lucide-react";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";
import { live } from "@/lib/api/v1/queries";
import { dateTimeOf } from "@/lib/format";
import { cn } from "@/lib/utils";
import { fmtUnits } from "@/product/records/units";
import { ExplainLayers } from "@/product/shared/ExplainLayers";
import { Card, EmptyState, ErrorState, PageTitle, SkeletonCards } from "@/product/shared/States";
import type {
  ForecastCalibration,
  Transparency,
  TransparencyMarketTally,
  TransparencyPeriodTally,
} from "@/lib/api/v1/types_transparency";
import {
  countsOf,
  dayText,
  intText,
  marginPoints,
  pctText,
  percentOf,
  reasonsOf,
  roiText,
  sampleNote,
  topStop,
} from "./model";

function Block({
  id,
  title,
  subtitle,
  icon,
  children,
}: {
  id: string;
  title: string;
  subtitle?: string | undefined;
  icon: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  return (
    <Card className="p-4 sm:p-5" id={`transparency-${id}`}>
      <div
        aria-labelledby={titleId}
        data-testid={`transparency-${id}`}
        className="space-y-3"
        role="group"
      >
        <div>
          <h2
            id={titleId}
            className="flex items-center gap-2 font-display text-base font-semibold tracking-tight sm:text-lg"
          >
            <span aria-hidden className="text-subtle-foreground">
              {icon}
            </span>
            {title}
          </h2>
          {subtitle ? <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p> : null}
        </div>
        {children}
      </div>
    </Card>
  );
}

function Note({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p className="text-caption leading-snug text-subtle-foreground" data-testid={testId}>
      {children}
    </p>
  );
}

/** A figure and what it counts, together (plan: «la cifra y su n juntas»). */
function Figure({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-caption text-muted-foreground">{label}</dt>
      <dd className="numeric text-base font-semibold text-foreground" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

function TallyBody({
  tally,
  data,
  testId,
}: {
  tally: TransparencyPeriodTally | TransparencyMarketTally;
  data: Transparency;
  testId: string;
}) {
  const note = sampleNote(tally, data.min_sample, data.conclusive);
  const counts = countsOf(tally);
  return (
    <div className="space-y-2" data-testid={testId} data-settled={tally.settled}>
      <p className="numeric text-sm font-semibold text-foreground">
        {t("transparency.published.published", { count: tally.published })}
        <span className="font-normal text-muted-foreground">
          {" · "}
          {t("transparency.published.settled", { count: tally.settled })}
        </span>
      </p>
      {counts.length > 0 ? (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 sm:grid-cols-3">
          {counts.map(([key, n]) => (
            <Figure
              key={key}
              label={t(`transparency.published.counts.${key}`)}
              value={intText(n)}
            />
          ))}
        </dl>
      ) : null}
      {tally.units !== null ? (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-border pt-2">
          <Figure
            label={t("transparency.published.units")}
            value={fmtUnits(tally.units)}
            testId={`${testId}-units`}
          />
          <Figure
            label={t("transparency.published.roi")}
            value={t("transparency.published.roiValue", {
              roi: roiText(tally),
              margin: marginPoints(tally),
            })}
            testId={`${testId}-roi`}
          />
        </dl>
      ) : null}
      {tally.units !== null ? (
        <Note>{t("transparency.published.margin", { points: marginPoints(tally) })}</Note>
      ) : null}
      {note ? <Note testId={`${testId}-sample`}>{note}</Note> : null}
    </div>
  );
}

function PublishedBlock({ data }: { data: Transparency }) {
  return (
    <Block
      id="published"
      title={t("transparency.published.title")}
      subtitle={t("transparency.published.subtitle")}
      icon={<ListChecks className="h-4 w-4" />}
    >
      <div className="grid gap-3 md:grid-cols-3">
        {data.periods.map((p) => (
          <div
            key={p.period}
            className="rounded-lg bg-elevated/60 p-3"
            data-testid={`transparency-period-${p.period}`}
          >
            <h3 className="font-display text-sm font-semibold">
              {t(`transparency.published.periods.${p.period}`)}
            </h3>
            <p className="mb-2 text-caption text-subtle-foreground">
              {p.since
                ? t("transparency.published.range", {
                    since: dayText(p.since),
                    until: dayText(p.until),
                  })
                : t("transparency.published.rangeAll", { until: dayText(p.until) })}
            </p>
            <TallyBody tally={p} data={data} testId={`transparency-tally-${p.period}`} />
          </div>
        ))}
      </div>
    </Block>
  );
}

function DaysBlock({ data }: { data: Transparency }) {
  const days = data.days;
  const stop = topStop(days.stops);
  return (
    <Block
      id="days"
      title={t("transparency.days.title")}
      subtitle={t("transparency.days.subtitle")}
      icon={<CalendarX2 className="h-4 w-4" />}
    >
      {days.days === 0 ? (
        <Note>{t("transparency.days.noneYet")}</Note>
      ) : days.without === 0 ? (
        <p className="text-sm">
          {t("transparency.days.allPicked", {
            since: dayText(days.since),
            until: dayText(days.until),
          })}
        </p>
      ) : (
        <>
          <p className="numeric text-sm font-semibold" data-testid="transparency-days-summary">
            {t("transparency.days.summary", {
              without: intText(days.without),
              days: intText(days.days),
              since: dayText(days.since),
              until: dayText(days.until),
            })}
          </p>
          <ul className="space-y-1.5">
            {reasonsOf(days).map(([reason, n]) => (
              <li
                key={reason}
                className="flex items-baseline justify-between gap-3 text-sm"
                data-testid={`transparency-reason-${reason}`}
              >
                <span className="min-w-0">{t(`transparency.days.reasons.${reason}`)}</span>
                <span className="numeric shrink-0 font-semibold">
                  {t("transparency.days.reasonDays", { count: n })}
                </span>
              </li>
            ))}
          </ul>
          {days.measured > 0 ? (
            <div
              className="space-y-1 rounded-lg bg-elevated/60 p-3 text-sm"
              data-testid="transparency-measured"
            >
              <p>
                {t("transparency.days.measured", { count: days.measured })}
                {stop
                  ? ` ${t("transparency.days.stopCommon", { stop: t(`transparency.days.stops.${stop}`) })}`
                  : ""}
              </p>
              <Note>{t("transparency.days.reconstructed")}</Note>
            </div>
          ) : null}
          <details
            className="group rounded-lg border border-border"
            data-testid="transparency-day-list"
          >
            <summary className="flex min-h-11 cursor-pointer items-center px-3 text-sm font-medium text-primary">
              {t("transparency.days.list", { count: days.items.length })}
            </summary>
            <ul className="divide-y divide-border border-t border-border">
              {days.items.map((d) => (
                <li
                  key={d.day}
                  className="space-y-0.5 px-3 py-2 text-sm"
                  data-testid="transparency-day"
                >
                  <p className="font-medium">{dayText(d.day)}</p>
                  <p className="text-muted-foreground">
                    {t(`transparency.days.reasons.${d.reason}`)}
                  </p>
                  <p className="numeric text-caption text-subtle-foreground">
                    {t("transparency.days.matches", { count: d.matches })}
                    {d.measured > 0
                      ? ` · ${t("transparency.days.measuredDay", { count: d.measured })}`
                      : ""}
                    {d.stop ? ` · ${t(`transparency.days.stops.${d.stop}`)}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </Block>
  );
}

function marketName(key: string): string {
  const names: Record<string, string> = {
    "1X2": t("transparency.markets.names.1X2"),
    OU: t("transparency.markets.names.OU"),
    BTTS: t("transparency.markets.names.BTTS"),
    AH: t("transparency.markets.names.AH"),
    DC: t("transparency.markets.names.DC"),
    other: t("transparency.markets.names.other"),
  };
  return names[key] ?? key;
}

function MarketsBlock({ data }: { data: Transparency }) {
  return (
    <Block
      id="markets"
      title={t("transparency.markets.title")}
      subtitle={t("transparency.markets.subtitle", { count: data.min_sample })}
      icon={<Layers className="h-4 w-4" />}
    >
      {data.markets.length === 0 ? (
        <Note testId="transparency-markets-none">{t("transparency.markets.none")}</Note>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {data.markets.map((m) => (
            <div
              key={m.market}
              className="rounded-lg bg-elevated/60 p-3"
              data-testid={`transparency-market-${m.market}`}
            >
              <h3 className="mb-1.5 font-display text-sm font-semibold">{marketName(m.market)}</h3>
              <TallyBody tally={m} data={data} testId={`transparency-market-tally-${m.market}`} />
            </div>
          ))}
        </div>
      )}
    </Block>
  );
}

function LineValueBlock({ data }: { data: Transparency }) {
  const lv = data.line_value;
  return (
    <Block
      id="line-value"
      title={t("transparency.lineValue.title")}
      icon={<Scale className="h-4 w-4" />}
    >
      <p className="text-sm text-muted-foreground">{t("transparency.lineValue.definition")}</p>
      <Note testId="transparency-line-value-version">
        {t("transparency.lineValue.version", { version: lv.version, since: dayText(lv.since) })}
      </Note>
      {lv.n === 0 ? (
        <p className="text-sm" data-testid="transparency-line-value-none">
          {t("transparency.lineValue.none")}
        </p>
      ) : lv.mean === null ? (
        <p className="text-sm">{t("transparency.lineValue.small", { count: lv.n })}</p>
      ) : (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
          <Figure
            label={t("transparency.lineValue.mean")}
            value={pctText(lv.mean, 1, true)}
            testId="transparency-line-value-mean"
          />
          <Figure label={t("transparency.lineValue.positive")} value={pctText(lv.positive)} />
          <p className="col-span-2 numeric text-caption text-muted-foreground">
            {t("transparency.lineValue.n", { count: lv.n })}
          </p>
        </dl>
      )}
      {lv.minutes !== null ? (
        <Note>{t("transparency.lineValue.minutes", { minutes: intText(lv.minutes) })}</Note>
      ) : null}
    </Block>
  );
}

function ForecastCard({ f, data }: { f: ForecastCalibration; data: Transparency }) {
  const calibrated = f.state === "CALIBRATED";
  return (
    <div
      className="space-y-2 rounded-lg bg-elevated/60 p-3"
      data-testid={`transparency-forecast-${f.market}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="font-display text-sm font-semibold">
          {t(`transparency.forecast.markets.${f.market}`)}
        </h3>
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-caption font-medium",
            calibrated ? "border-positive/40 text-positive" : "border-warning/40 text-warning",
          )}
          data-testid={`transparency-forecast-state-${f.market}`}
        >
          {calibrated
            ? t("transparency.forecast.calibrated")
            : t("transparency.forecast.uncalibrated")}
        </span>
      </div>
      <p className="numeric text-caption text-muted-foreground">
        {t("transparency.forecast.matches", { count: f.matches })}
        {f.matches > 0
          ? ` · ${t("transparency.forecast.calibratedOf", { calibrated: intText(f.calibrated), matches: intText(f.matches) })}`
          : ""}
      </p>
      {!calibrated ? (
        <Note>{t("transparency.forecast.uncalibratedNote")}</Note>
      ) : f.bins.length === 0 ? (
        <Note>{t("transparency.forecast.small", { count: data.min_calibration })}</Note>
      ) : (
        <>
          <table className="w-full text-sm" data-testid={`transparency-bins-${f.market}`}>
            <caption className="mb-1 text-left text-caption text-muted-foreground">
              {f.selection
                ? t(`transparency.forecast.side.${f.selection}`)
                : t("transparency.forecast.allOutcomes")}
            </caption>
            <thead>
              <tr className="text-left text-caption text-subtle-foreground">
                <th scope="col" className="py-1 font-medium">
                  {t("transparency.forecast.said")}
                </th>
                <th scope="col" className="py-1 font-medium">
                  {t("transparency.forecast.happened")}
                </th>
                <th scope="col" className="py-1 text-right font-medium">
                  {t("transparency.forecast.cases")}
                </th>
              </tr>
            </thead>
            <tbody className="numeric">
              {f.bins.map((b) => (
                <tr key={b.low} className="border-t border-border">
                  <th scope="row" className="py-1 font-normal">
                    {t("transparency.forecast.bin", {
                      low: percentOf(b.low),
                      high: percentOf(b.high),
                    })}
                  </th>
                  <td className="py-1">{pctText(b.observed)}</td>
                  <td className="py-1 text-right">{intText(b.n)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {f.omitted > 0 ? (
            <Note>
              {t("transparency.forecast.omitted", { count: intText(f.omitted), min: data.min_bin })}
            </Note>
          ) : null}
        </>
      )}
    </div>
  );
}

function ForecastBlock({ data }: { data: Transparency }) {
  return (
    <Block
      id="forecast"
      title={t("transparency.forecast.title")}
      subtitle={t("transparency.forecast.subtitle", { days: data.calibration_days })}
      icon={<Gauge className="h-4 w-4" />}
    >
      <div className="grid gap-3 md:grid-cols-3">
        {data.forecasts.map((f) => (
          <ForecastCard key={f.market} f={f} data={data} />
        ))}
      </div>
    </Block>
  );
}

function EvaluationBlock({ data }: { data: Transparency }) {
  const ev = data.evaluation;
  return (
    <Block
      id="evaluation"
      title={t("transparency.evaluation.title")}
      icon={<FlaskConical className="h-4 w-4" />}
    >
      {ev.pairs === 0 ? (
        <p className="text-sm">{t("transparency.evaluation.nothing")}</p>
      ) : (
        <>
          <p className="numeric text-sm" data-testid="transparency-evaluation-summary">
            {t("transparency.evaluation.summary", {
              markets: intText(ev.markets),
              pairs: intText(ev.pairs),
              passed: intText(ev.passed_markets),
            })}
          </p>
          {ev.passed_markets === 0 ? (
            <p className="text-sm font-medium">{t("transparency.evaluation.noneYet")}</p>
          ) : null}
          {ev.since ? (
            <Note>{t("transparency.evaluation.since", { since: dayText(ev.since) })}</Note>
          ) : null}
        </>
      )}
      <p
        className="numeric text-sm text-muted-foreground"
        data-testid="transparency-evaluation-qualified"
      >
        {t("transparency.evaluation.qualified", { count: intText(ev.qualified) })}
      </p>
      <Note>{t("transparency.evaluation.never")}</Note>
    </Block>
  );
}

const STEPS = ["model", "value", "risk", "context", "one"] as const;

function HowBlock() {
  return (
    <Block
      id="how"
      title={t("transparency.how.title")}
      subtitle={t("transparency.how.intro")}
      icon={<BarChart3 className="h-4 w-4" />}
    >
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {STEPS.map((s) => (
          <li key={s}>{t(`transparency.how.steps.${s}`)}</li>
        ))}
      </ul>
      <ExplainLayers compact />
    </Block>
  );
}

function DefinitionsBlock({ data }: { data: Transparency }) {
  return (
    <Block
      id="definitions"
      title={t("transparency.definitions.title")}
      subtitle={t("transparency.definitions.subtitle")}
      icon={<ListChecks className="h-4 w-4" />}
    >
      <ul className="space-y-1 text-sm">
        {data.definitions.map((d) => (
          <li key={d.key} data-testid={`transparency-definition-${d.key}`}>
            {t("transparency.definitions.line", {
              name: t(`transparency.definitions.names.${d.key}`),
              version: d.version,
              since: dayText(d.since),
            })}
          </li>
        ))}
      </ul>
    </Block>
  );
}

export function TransparencyBody({ data }: { data: Transparency }) {
  return (
    <div className="flex flex-col gap-4" data-testid="transparency-body">
      <PublishedBlock data={data} />
      <DaysBlock data={data} />
      <MarketsBlock data={data} />
      <LineValueBlock data={data} />
      <ForecastBlock data={data} />
      <EvaluationBlock data={data} />
      <HowBlock />
      <DefinitionsBlock data={data} />
      {data.data_as_of ? (
        <Note>{t("transparency.page.dataAsOf", { time: dateTimeOf(data.data_as_of) })}</Note>
      ) : null}
    </div>
  );
}

export function TransparencyPage() {
  const auth = useAuth();
  // The owner reviews the page before readers see it (P9): the console's preview, always on for the owner here.
  const preview = auth.showAdmin ? "shadow" : undefined;
  const q = useQuery(live.transparency(preview));
  let body: ReactNode;
  if (q.isPending) body = <SkeletonCards count={4} />;
  else if (q.isError)
    body = (
      <Card>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Card>
    );
  else if (q.data.status !== "ok" || q.data.data === null)
    body = (
      <Card>
        <EmptyState title={t("transparency.page.notAvailable")} />
      </Card>
    );
  else body = <TransparencyBody data={q.data.data} />;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5" data-testid="transparency-page">
      <PageTitle title={t("transparency.page.title")} subtitle={t("transparency.page.subtitle")} />
      {preview && !auth.user?.transparency ? (
        <p
          className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-foreground"
          data-testid="transparency-preview"
        >
          {t("transparency.page.preview")}
        </p>
      ) : null}
      {body}
    </div>
  );
}

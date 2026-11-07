/**
 * PRONÓSTICO PREDIGOL (plan F5) - what PrediGol expects of the match, apart from whether it is well paid and from
 * what it recommends. Per core market (result, total goals, both teams to score) the probability of each outcome
 * with the interval the model measured, and whether it was calibrated: "Calibrada" only where a champion calibrator
 * exists, "Sin calibrar" - with the reason - everywhere else, so that the page never claims a correction it has not
 * proven.
 *
 * A forecast is not a price. A user sees no odds, no edge and no pick here: those are the decision layer's, and a
 * pick is what the Picks tab shows. Whether users see this block at all is the owner's decision (the API answers
 * `not_available` until then, and the block renders nothing for them). The Admin Console's preview sees it with the
 * fair odds beside each number and, folded away, what the decision layer and the pick engine said about the same
 * match - three answers that are not one - and, in a block of its own, what the families (the goals of each half, the
 * corners, the cards) forecast for it: research, uncalibrated, and never mixed into the forecast above (plan F10.17b).
 */
import { useEffect, useId, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { CircleCheck, Gauge } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtPct, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import { formatRelative } from "@/lib/time";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import { track } from "@/lib/track";
import type { Section } from "@/lib/api/v1/types";
import type {
  FamilyMarket,
  ForecastMarket,
  ForecastOutcome,
  ForecastPickRow,
  ForecastValueRow,
  MatchForecast,
} from "@/lib/api/v1/types_forecast";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import { familyName, marketText, ruleKeyText } from "@/live/familiesText";
import { ShadowBadge } from "@/product/shared/Bits";
import { ExplainLayers } from "@/product/shared/ExplainLayers";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import {
  FORECAST_ID,
  barPercent,
  basisNote,
  calibrationLabel,
  familyOutcomeText,
  familyPercent,
  forecastMarketTitle,
  forecastScreen,
  groupFamilies,
  intervalSpan,
  intervalText,
  modelLabel,
  noForecastText,
  outcomeLabel,
  type ForecastLoad,
} from "./forecast";
import { marketTitle, ppParts, selectionPhrase, type Sides } from "./intelligence";

const CALIBRATED_TAG = "border-positive/40 bg-positive-soft text-positive";
const UNCALIBRATED_TAG = "border-border-strong bg-elevated text-muted-foreground";
const LIKELY_TAG = "border-primary/40 bg-primary/10 text-primary";

function Tag({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-micro font-semibold leading-tight",
        tone,
      )}
    >
      {children}
    </span>
  );
}

/** The probability as a solid bar; the interval the model measured as a thin line with an end mark on each side. */
function RangeBar({ outcome }: { outcome: ForecastOutcome }) {
  const span = intervalSpan(outcome);
  return (
    <div aria-hidden className="relative mt-1.5 h-2 rounded-full bg-muted/70">
      <div
        className={cn(
          "absolute inset-y-0 left-0 rounded-full",
          outcome.likely ? "bg-primary" : "bg-primary/55",
        )}
        style={{ width: `${barPercent(outcome.probability)}%` }}
      />
      {span ? (
        <>
          <span
            className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-foreground/50"
            style={{ left: `${span.left}%`, width: `${span.right - span.left}%` }}
          />
          <span
            className="absolute top-1/2 h-3.5 w-px -translate-y-1/2 bg-foreground/60"
            style={{ left: `${span.left}%` }}
          />
          <span
            className="absolute top-1/2 h-3.5 w-px -translate-y-1/2 bg-foreground/60"
            style={{ left: `${span.right}%` }}
          />
        </>
      ) : null}
    </div>
  );
}

function OutcomeRow({
  market,
  outcome,
  sides,
  preview,
}: {
  market: ForecastMarket;
  outcome: ForecastOutcome;
  sides: Sides;
  preview: boolean;
}) {
  // Defence in depth: the API sends the fair odds to the preview alone, and the view shows them to it alone.
  const fair = preview && outcome.fair_odds ? outcome.fair_odds : null;
  const model =
    preview && market.calibration === "CALIBRATED" && outcome.model_probability
      ? outcome.model_probability
      : null;
  return (
    <li
      data-testid="forecast-outcome"
      data-selection={outcome.selection}
      data-likely={outcome.likely ? "true" : "false"}
      className="min-w-0"
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span className="min-w-0 break-words">{outcomeLabel(market, outcome, sides)}</span>
          {outcome.likely ? <Tag tone={LIKELY_TAG}>{t("match.forecast.likely")}</Tag> : null}
        </span>
        <span className="numeric shrink-0 text-base font-semibold">
          {fmtPct(outcome.probability, 0)}
        </span>
      </div>
      <RangeBar outcome={outcome} />
      <p className="mt-1 flex flex-wrap gap-x-2 text-caption text-muted-foreground">
        <GlossaryTerm term="range">{intervalText(outcome)}</GlossaryTerm>
        {fair ? (
          <span className="numeric">
            · {t("match.forecast.admin.fairOdds", { odds: fmtOdds(fair) })}
          </span>
        ) : null}
        {model ? (
          <span className="numeric">
            · {t("match.forecast.admin.modelNumber", { p: fmtPct(model, 0) })}
          </span>
        ) : null}
      </p>
    </li>
  );
}

function MarketView({
  market,
  sides,
  preview,
}: {
  market: ForecastMarket;
  sides: Sides;
  preview: boolean;
}) {
  const calibrated = market.calibration === "CALIBRATED";
  const note = basisNote(market.basis);
  return (
    <section
      data-testid="forecast-market"
      data-market={market.market}
      data-calibration={market.calibration}
      className="min-w-0 space-y-3 rounded-lg border border-border/70 bg-elevated/30 p-3"
    >
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h3 className="min-w-0 break-words text-sm font-semibold">{forecastMarketTitle(market)}</h3>
        <Tag tone={calibrated ? CALIBRATED_TAG : UNCALIBRATED_TAG}>
          {calibrated ? <CircleCheck aria-hidden className="h-3 w-3" /> : null}
          <GlossaryTerm term="calibrated">{calibrationLabel(market.calibration)}</GlossaryTerm>
        </Tag>
      </header>
      <ul className="space-y-3">
        {market.outcomes.map((o) => (
          <OutcomeRow
            key={o.selection}
            market={market}
            outcome={o}
            sides={sides}
            preview={preview}
          />
        ))}
      </ul>
      <p className="text-caption leading-snug text-subtle-foreground">
        {note ? <span data-testid="forecast-basis">{note} </span> : null}
        {/* The model's name is the owner's preview only (plan UX, A9): a reader gets null. */}
        {market.model ? (
          <>
            <span>{t("match.forecast.model", { model: modelLabel(market.model) })}</span>
            <span> · {t("match.forecast.updated", { when: formatRelative(market.known_at) })}</span>
          </>
        ) : (
          <span>{t("match.forecast.updated", { when: formatRelative(market.known_at) })}</span>
        )}
      </p>
    </section>
  );
}

// ── the preview's own detail: the value and the picks, apart from the forecast ──

function reasonLine(section: Section<unknown>): string {
  return noForecastText(section.code ?? null);
}

function ValueList({ section, sides }: { section: Section<ForecastValueRow[]>; sides: Sides }) {
  return (
    <div data-testid="forecast-value" className="space-y-1.5">
      <h4 className="text-caption font-semibold text-muted-foreground">
        {t("match.forecast.admin.valueTitle")}
      </h4>
      {section.status !== "ok" || section.data.length === 0 ? (
        <p className="text-caption text-subtle-foreground">{reasonLine(section)}</p>
      ) : (
        <ul className="space-y-1.5">
          {section.data.map((r) => {
            const edge = ppParts(r.edge);
            return (
              <li
                key={`${r.market}-${r.selection}-${r.line}`}
                className="min-w-0 rounded-md border border-border/60 bg-card/60 px-2.5 py-1.5"
              >
                <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
                  <span className="min-w-0 break-words font-medium">
                    {marketTitle(r.market, r.line)} —{" "}
                    {selectionPhrase(
                      { market: r.market, selection: r.selection, line: r.line },
                      sides,
                    )}
                  </span>
                  <span className="shrink-0 text-caption font-semibold text-muted-foreground">
                    {r.state}
                  </span>
                </p>
                <p className="numeric mt-0.5 flex flex-wrap gap-x-3 text-caption text-muted-foreground">
                  <span>
                    {t("match.forecast.admin.odds")} {fmtOdds(r.odds)}
                  </span>
                  <span>
                    {t("match.forecast.admin.edge")} {edge ? `${edge.value} ${edge.unit}` : "—"}
                  </span>
                  <span>
                    {t("match.forecast.admin.ev")} {fmtSignedPct(r.ev)}
                  </span>
                </p>
                {r.reasons.length ? (
                  <p className="mt-0.5 break-words text-caption text-subtle-foreground">
                    {r.reasons.join(" · ")}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function PickList({ section, sides }: { section: Section<ForecastPickRow[]>; sides: Sides }) {
  return (
    <div data-testid="forecast-picks" className="space-y-1.5">
      <h4 className="text-caption font-semibold text-muted-foreground">
        {t("match.forecast.admin.picksTitle")}
      </h4>
      {section.status !== "ok" || section.data.length === 0 ? (
        <p className="text-caption text-subtle-foreground">{reasonLine(section)}</p>
      ) : (
        <ul className="space-y-1.5">
          {section.data.map((p) => (
            <li
              key={p.id}
              className="min-w-0 rounded-md border border-border/60 bg-card/60 px-2.5 py-1.5"
            >
              <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
                <span className="min-w-0 break-words font-medium">
                  {marketTitle(p.market, p.line)} —{" "}
                  {selectionPhrase(
                    { market: p.market, selection: p.selection, line: p.line },
                    sides,
                  )}
                </span>
                <span className="shrink-0 text-caption font-semibold text-muted-foreground">
                  {p.status} · {p.mode}
                </span>
              </p>
              <p className="numeric mt-0.5 flex flex-wrap gap-x-3 text-caption text-muted-foreground">
                <span>
                  {t("match.forecast.admin.odds")} {fmtOdds(p.odds)}
                </span>
                {toNumber(p.probability) !== null ? <span>{fmtPct(p.probability, 1)}</span> : null}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Folded away: the forecast is what the block says; the rest is for telling the three answers apart. */
function AdminDetails({ data, sides }: { data: MatchForecast; sides: Sides }) {
  if (!data.value && !data.picks) return null;
  return (
    <details
      data-testid="forecast-admin"
      className="rounded-lg border border-info/30 bg-info-soft/30 px-3 py-2"
    >
      <summary className="cursor-pointer text-xs font-semibold text-info focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
        {t("match.forecast.admin.detailsTitle")}
      </summary>
      <div className="mt-2 space-y-3">
        {data.value ? <ValueList section={data.value} sides={sides} /> : null}
        {data.picks ? <PickList section={data.picks} sides={sides} /> : null}
      </div>
    </details>
  );
}

// ── what the families forecast: research, apart from the forecast and from the value ──

function FamilyMarketView({ market, sides }: { market: FamilyMarket; sides: Sides }) {
  return (
    <li
      data-testid="family-market"
      data-market={market.market}
      data-calibration={market.calibration}
      className="min-w-0 space-y-1.5 rounded-md border border-border/60 bg-card/60 px-2.5 py-2"
    >
      <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-xs">
        <span className="min-w-0 break-words font-medium">{marketText(market.market)}</span>
        <Tag tone={UNCALIBRATED_TAG}>{calibrationLabel(market.calibration)}</Tag>
      </p>
      <p data-testid="family-rule" className="text-caption leading-snug text-subtle-foreground">
        {market.rule
          ? t("match.forecast.admin.settledWith", { rule: ruleKeyText(market.rule) })
          : t("match.forecast.admin.noRule")}
      </p>
      <ul className="space-y-1">
        {market.lines.map((line) => (
          <li
            key={line.line}
            data-testid="family-line"
            data-line={line.line}
            className="flex flex-wrap gap-x-3 gap-y-0.5 text-caption"
          >
            {line.outcomes.map((o) => (
              <span
                key={o.selection}
                data-testid="family-outcome"
                data-selection={o.selection}
                data-likely={o.likely ? "true" : "false"}
                className={cn(
                  "numeric min-w-0 break-words",
                  o.likely ? "font-semibold text-foreground" : "text-muted-foreground",
                )}
              >
                {familyOutcomeText(market, line, o, sides)} {familyPercent(o.probability)}
                {o.fair_odds ? (
                  <span title={t("match.forecast.admin.fairOdds", { odds: fmtOdds(o.fair_odds) })}>
                    {" "}
                    ({fmtOdds(o.fair_odds)})
                  </span>
                ) : null}
              </span>
            ))}
          </li>
        ))}
      </ul>
      <p className="text-caption leading-snug text-subtle-foreground">
        <span>{t("match.forecast.model", { model: modelLabel(market.model) })}</span>
        <span> · {t("match.forecast.updated", { when: formatRelative(market.known_at) })}</span>
      </p>
    </li>
  );
}

/**
 * Folded away, in a block of its own: the families' forecasts are research (the model's own number, uncalibrated, with no interval), they are not
 * the forecast above, and the owner has not decided that a user sees them. One folded group per family, so that ~130 numbers do not push the page.
 */
function FamiliesDetails({ section, sides }: { section: Section<FamilyMarket[]>; sides: Sides }) {
  const groups = section.status === "ok" ? groupFamilies(section.data) : [];
  return (
    <details
      data-testid="forecast-families"
      className="rounded-lg border border-info/30 bg-info-soft/30 px-3 py-2"
    >
      <summary className="cursor-pointer text-xs font-semibold text-info focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
        {t("match.forecast.admin.familiesTitle")}
      </summary>
      <div className="mt-2 space-y-2">
        <p className="text-caption leading-snug text-subtle-foreground">
          {t("match.forecast.admin.familiesNote")}
        </p>
        {groups.length === 0 ? (
          <p data-testid="forecast-families-none" className="text-caption text-subtle-foreground">
            {reasonLine(section)}
          </p>
        ) : (
          groups.map((group) => (
            <details
              key={group.family}
              data-testid="family-group"
              data-family={group.family}
              className="rounded-md border border-border/60 bg-card/40 px-2.5 py-1.5"
            >
              <summary className="cursor-pointer text-xs font-medium focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
                {familyName(group.family)}
                <span className="font-normal text-muted-foreground">
                  {" "}
                  · {t("match.forecast.admin.familyMarkets", { n: group.markets.length })}
                </span>
              </summary>
              <ul className="mt-2 space-y-2">
                {group.markets.map((m) => (
                  <FamilyMarketView key={m.market} market={m} sides={sides} />
                ))}
              </ul>
            </details>
          ))
        )}
      </div>
    </details>
  );
}

// ── the block ───────────────────────────────────────────────────────────────

/**
 * The block from an answer of the API. Apart from the query so that it can be rendered from a fixture: `preview` is
 * the Admin Console's shadow preview, the only view that sees the fair odds, the value, the picks and the families.
 */
export function ForecastView({
  load,
  home,
  away,
  preview,
}: {
  load: ForecastLoad;
  home: string;
  away: string;
  preview: boolean;
}) {
  const titleId = useId();
  const screen = forecastScreen(load, preview);
  if (screen.kind === "nothing") return null;
  const sides: Sides = { home, away };
  const data = screen.kind === "forecast" || screen.kind === "none" ? screen.data : null;
  return (
    <section
      id={FORECAST_ID}
      aria-labelledby={titleId}
      data-testid="forecast-block"
      data-screen={screen.kind}
      data-preview={preview ? "true" : "false"}
      className={cn(
        "min-w-0 scroll-mt-20 rounded-xl border border-border bg-card",
        preview && "border-info/40",
      )}
    >
      <header className="flex items-start justify-between gap-3 px-4 pt-3.5">
        <div className="min-w-0">
          <h2
            id={titleId}
            className="flex items-center gap-2 font-display text-[0.95rem] font-bold uppercase tracking-[0.08em]"
          >
            <Gauge aria-hidden className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 break-words">{t("match.forecast.title")}</span>
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("match.forecast.subtitle")}</p>
        </div>
        {preview ? <ShadowBadge compact /> : null}
      </header>
      <div className="space-y-3 px-4 pb-4 pt-3">
        {screen.kind === "loading" ? <SkeletonBlock className="h-40" /> : null}
        {screen.kind === "error" ? (
          <ErrorState error={screen.error} onRetry={screen.retry} className="py-5" />
        ) : null}
        {screen.kind === "none" ? (
          <p className="text-sm text-muted-foreground" data-empty-state data-testid="forecast-none">
            {noForecastText(screen.code)}
          </p>
        ) : null}
        {screen.kind === "forecast" ? (
          <>
            {/* Full width in the Resumen (plan Partidos y Match Center, R1): the markets side by side, up to three. */}
            <div
              data-testid="forecast-markets"
              className={cn(
                "grid items-start gap-3",
                screen.markets.length >= 2 && "md:grid-cols-2",
                screen.markets.length >= 3 && "lg:grid-cols-3",
              )}
            >
              {screen.markets.map((m) => (
                <MarketView
                  key={`${m.market}-${m.line}`}
                  market={m}
                  sides={sides}
                  preview={preview}
                />
              ))}
            </div>
            {/* forecast ≠ value ≠ pick (plan UX, A3): where the three answers are told apart */}
            <ExplainLayers compact />
          </>
        ) : null}
        {preview && data ? <AdminDetails data={data} sides={sides} /> : null}
        {preview && data?.families ? (
          <FamiliesDetails section={data.families} sides={sides} />
        ) : null}
      </div>
    </section>
  );
}

/** The Resumen's block: loads the forecast for the signed-in view (a user's, or the Admin Console's preview). */
export function ForecastBlock({ ctx }: { ctx: MatchCtx }) {
  const shadow = usePreviewParam();
  const q = useQuery(live.matchForecast(ctx.fixtureId, shadow));
  const load: ForecastLoad = q.isPending
    ? { status: "pending" }
    : q.isError
      ? { status: "error", error: q.error, retry: () => void q.refetch() }
      : { status: "success", envelope: q.data };
  const shown = forecastScreen(load, shadow === "shadow").kind === "forecast";
  // Plan UX, A6 and A9: a reader saw PrediGol's forecast of this match (once per match opened; the owner is never measured).
  useEffect(() => {
    if (shown && shadow !== "shadow") track("forecast_viewed", { match_id: Number(ctx.fixtureId) });
  }, [shown, shadow, ctx.fixtureId]);
  return (
    <ForecastView
      load={load}
      home={ctx.match.home.name}
      away={ctx.match.away.name}
      preview={shadow === "shadow"}
    />
  );
}

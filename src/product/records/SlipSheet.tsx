/**
 * "Mi parlay": the user's own parlay. The selections they added and what the parlay adds up to -
 * worked out at once on this device, then refined by the server's deterministic check (POST
 * /me/parlays/validate: rules and arithmetic) - and saving it as a parlay of their own. Opened
 * from the floating button on every product page, from "Mis picks" and from "Parlays".
 *
 * The AI never analyses a user's own parlay: nothing here calls an AI endpoint, and the panel
 * says so ("Cálculo instantáneo · sin IA").
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarDays,
  ChevronRight,
  History,
  Layers,
  Target,
  Trash2,
  TrendingUp,
  X,
  XCircle,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import { DASH, fmtOdds, fmtPct, fmtSignedPct, localFixed, toNumber } from "@/lib/i18n/format";
import { formatKickoff } from "@/lib/time";
import { v1 } from "@/lib/api/v1/client";
import type { ParlayValidation, ValidationIssue } from "@/lib/api/v1/types_records";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { OddsPill } from "@/product/shared/Bits";
import { errorMessage } from "@/product/shared/States";
import { marketName, riskLabel, selectionLabel } from "@/product/shared/markets";
import { useRefreshMine } from "./hooks";
import {
  MAX_SLIP_LEGS,
  MIN_SLIP_LEGS,
  explainedReasons,
  hasStarted,
  selectionKey,
  slipEstimate,
  slipOdds,
  toProbability,
  type DependencyLevel,
  type SlipEstimate,
  type SlipLeg,
} from "./model";
import { useSlip } from "./slipContext";

/** The server is asked once the legs stop changing for this long; the client's figures show at once. */
const CHECK_DELAY_MS = 250;
/** "Análisis PrediGol" on the match page (its block carries this id). */
const ANALYSIS_HASH = "predigol-intelligence";
/** The user's parlays in "Mis picks". */
const HISTORY_HASH = "my-parlays";

type ServerLeg = ParlayValidation["legs"][number];

function issueText(kind: "error" | "warning", issue: ValidationIssue): string {
  const code =
    issue.code === "same_competition_day" && issue.significant
      ? "same_competition_day_measured"
      : issue.code;
  return translateOr(`records.slip.${kind}.${code}`, issue.code, {
    leg: issue.leg,
    with: issue.with,
    min: issue.min ?? MIN_SLIP_LEGS,
    max: issue.max ?? MAX_SLIP_LEGS,
    legs: (issue.legs ?? []).join(", "),
    rho: issue.rho === null || issue.rho === undefined ? DASH : localFixed(issue.rho, 3),
    probability: fmtPct(issue.probability, 2),
  });
}

function legsBody(legs: readonly SlipLeg[]) {
  return legs.map((l) => ({
    fixture_id: l.fixture_id,
    market_key: l.market_key,
    selection: l.selection,
    line: l.line,
  }));
}

/** The value once it has stopped changing for `ms`. */
function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return settled;
}

/** A probability with the digits it needs: 54,3 % · 0,42 % · < 0,01 %. */
function fmtProbability(p: number | null): string {
  if (p === null) return DASH;
  if (p < 0.0001) return `< ${fmtPct(0.0001, 2)}`;
  return fmtPct(p, p < 0.01 ? 2 : 1);
}

const LEG_LINK =
  "inline-flex min-h-8 items-center gap-0.5 rounded-md text-xs font-medium text-primary transition-colors hover:text-primary/80 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function LegRow({
  leg,
  n,
  price,
  probability,
  onRemove,
  onLeave,
}: {
  leg: SlipLeg;
  n: number;
  price: string | null;
  probability: number | null;
  onRemove: () => void;
  onLeave: () => void;
}) {
  const selection = selectionLabel({
    market_key: leg.market_key,
    selection: leg.selection,
    line: leg.line,
    home: leg.home,
    away: leg.away,
  });
  const match = `${leg.home} – ${leg.away}`;
  const params = { fixtureId: String(leg.fixture_id) };
  return (
    <li className="py-3" data-testid="slip-leg" data-fixture-id={leg.fixture_id}>
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="numeric mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-gold-soft text-[0.65rem] font-semibold text-gold-strong"
        >
          {n}
        </span>
        <div className="min-w-0 flex-1">
          <p
            className="break-words text-sm font-semibold leading-snug"
            data-testid="slip-leg-match"
          >
            {match}
          </p>
          <p className="mt-0.5 text-caption text-muted-foreground">
            <span className="numeric">{formatKickoff(leg.kickoff_at)}</span>
            {hasStarted(leg) ? (
              <span className="font-medium text-negative">
                {" · "}
                {t("records.actions.started")}
              </span>
            ) : null}
          </p>
        </div>
        <button
          type="button"
          onClick={onRemove}
          title={t("records.slip.remove")}
          aria-label={t("records.slip.removeLeg", { selection, match })}
          data-testid="slip-remove"
          className="-mr-1.5 -mt-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-1.5 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 pl-8">
        <p className="break-words text-sm leading-snug" data-testid="slip-leg-selection">
          <span className="text-muted-foreground">{marketName(leg.market_key)}</span>
          <span className="text-subtle-foreground"> · </span>
          <span className="font-semibold">{selection}</span>
        </p>
        <div className="flex flex-col items-end gap-1">
          {price ? (
            <OddsPill odds={price} size="sm" />
          ) : (
            <span className="text-caption text-subtle-foreground">{t("records.slip.noPrice")}</span>
          )}
          <span
            className="inline-flex items-baseline gap-1 whitespace-nowrap"
            title={t("records.slip.legProbabilityHelp")}
            data-testid="slip-leg-probability"
          >
            <span className="text-caption text-subtle-foreground">
              {t("records.slip.legProbability")}
            </span>
            <span className="numeric text-xs font-semibold">{fmtProbability(probability)}</span>
          </span>
        </div>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-4 pl-8">
        <Link
          to="/matches/$fixtureId"
          params={params}
          onClick={onLeave}
          aria-label={t("records.slip.openMatchLabel", { match })}
          data-testid="slip-open-match"
          className={LEG_LINK}
        >
          {t("records.slip.openMatch")}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
        <Link
          to="/matches/$fixtureId"
          params={params}
          hash={ANALYSIS_HASH}
          onClick={onLeave}
          aria-label={t("records.slip.viewAnalysisLabel", { match })}
          data-testid="slip-view-analysis"
          className={LEG_LINK}
        >
          {t("records.slip.viewAnalysis")}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </div>
    </li>
  );
}

const DEPENDENCY_TONE: Record<DependencyLevel, string> = {
  low: "border-positive/40 bg-positive-soft text-positive",
  medium: "border-warning/40 bg-warning-soft text-warning",
  high: "border-negative/40 bg-negative-soft text-negative",
};

function dependencyText(dependency: NonNullable<SlipEstimate["dependency"]>): string {
  const reasons = explainedReasons(dependency.reasons);
  if (reasons.length > 0) {
    return reasons.map((r) => t(`records.slip.dependency.reason.${r}`)).join(" ");
  }
  return dependency.level === "low"
    ? t("records.slip.measures.independent")
    : t("records.slip.measures.dependent");
}

/** A figure of the summary: its value, or "calculando…" while the server works it out. */
function Value({
  pending,
  numeric = true,
  className,
  testId,
  source,
  children,
}: {
  pending: boolean;
  numeric?: boolean;
  className?: string | undefined;
  testId?: string | undefined;
  source?: string | undefined;
  children: ReactNode;
}) {
  return (
    <span
      data-testid={testId}
      data-source={source}
      className={
        pending
          ? "text-sm italic text-muted-foreground"
          : cn(numeric && "numeric", "font-semibold", className)
      }
    >
      {pending ? t("records.slip.summary.calculating") : children}
    </span>
  );
}

/**
 * What the parlay adds up to, by numbers already known: the combined odds, PrediGol's estimate that
 * every leg wins (adjusted for dependence by the server - never a blind product of dependent legs),
 * the market's fair probability, how much the legs depend on each other, the value and the risk.
 */
function Summary({
  legs,
  combined,
  estimate,
  validation,
  waiting,
}: {
  legs: number;
  combined: number | null;
  estimate: SlipEstimate;
  validation: ParlayValidation | null;
  waiting: boolean;
}) {
  const p = estimate.probability;
  const dep = estimate.dependency;
  const fair = toProbability(validation?.fair_probability);
  const ev = toNumber(validation?.expected_value);
  const risk = validation?.risk ?? null;
  const estimatedNote = p
    ? p.source === "server"
      ? t("records.slip.summary.estimatedServer")
      : waiting
        ? t("records.slip.summary.estimatedProvisional")
        : t("records.slip.summary.estimatedIndependent")
    : waiting
      ? dep && dep.level !== "low"
        ? t("records.slip.summary.estimatedWaiting")
        : t("records.slip.summary.estimatedServer")
      : validation
        ? t("records.slip.summary.estimatedNone")
        : null;
  const dependencyNote = dep
    ? dependencyText(dep)
    : waiting
      ? t("records.slip.dependency.pending")
      : null;
  return (
    <section
      aria-labelledby="slip-summary-title"
      aria-busy={waiting}
      data-testid="slip-summary"
      className="gold-ring rounded-xl border bg-card p-4"
    >
      <h3 id="slip-summary-title" className="sr-only">
        {t("records.slip.summary.title")}
      </h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-4" data-testid="slip-measures">
        <div
          className="col-span-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border/60 pb-3"
          data-testid="slip-combined"
        >
          <dt className="text-label text-subtle-foreground">{t("records.slip.combined")}</dt>
          <dd className="ml-auto text-right">
            {combined !== null ? (
              <span
                className="numeric text-2xl font-semibold text-gold-strong"
                data-testid="slip-combined-odds"
              >
                {fmtOdds(combined)}
              </span>
            ) : (
              <Value
                pending={waiting}
                numeric={false}
                testId="slip-combined-odds"
                className="text-xs font-normal text-muted-foreground"
              >
                {t("records.slip.noCombined")}
              </Value>
            )}
          </dd>
        </div>

        <div className="min-w-0">
          <dt className="text-caption font-medium text-muted-foreground">
            {t("records.slip.summary.estimated")}
          </dt>
          <dd className="mt-0.5">
            <Value
              pending={p === null && waiting}
              testId="slip-estimated-probability"
              source={p ? p.source : waiting ? "pending" : "none"}
              className="text-lg text-foreground"
            >
              {fmtProbability(p ? p.value : null)}
            </Value>
            {estimatedNote ? (
              <span className="mt-0.5 block text-caption text-subtle-foreground">
                {estimatedNote}
              </span>
            ) : null}
          </dd>
        </div>

        <div className="min-w-0">
          <dt className="text-caption font-medium text-muted-foreground">
            {t("records.slip.summary.fair")}
          </dt>
          <dd className="mt-0.5">
            <Value
              pending={waiting}
              testId="slip-fair-probability"
              className="text-lg text-foreground"
            >
              {fmtProbability(fair)}
            </Value>
            <span className="mt-0.5 block text-caption text-subtle-foreground">
              {t("records.slip.summary.fairHelp")}
            </span>
          </dd>
        </div>

        {legs >= MIN_SLIP_LEGS ? (
          <div
            className="col-span-2 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-lg bg-elevated/50 px-3 py-2.5"
            data-testid="slip-dependency"
            data-level={dep ? dep.level : waiting ? "pending" : "unknown"}
            data-source={dep?.source}
          >
            <dt className="text-caption font-medium text-muted-foreground">
              {t("records.slip.summary.dependency")}
            </dt>
            <dd>
              {dep ? (
                <span
                  className={cn(
                    "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-wider",
                    DEPENDENCY_TONE[dep.level],
                  )}
                >
                  {t(`records.slip.dependency.level.${dep.level}`)}
                </span>
              ) : (
                <Value pending={waiting}>{DASH}</Value>
              )}
            </dd>
            {dependencyNote ? (
              <dd className="col-span-2 text-caption text-muted-foreground">{dependencyNote}</dd>
            ) : null}
          </div>
        ) : null}

        <div className="min-w-0">
          <dt className="text-caption font-medium text-muted-foreground">
            {t("records.slip.measures.ev")}
          </dt>
          <dd className="mt-0.5">
            <Value
              pending={waiting}
              testId="slip-ev"
              className={cn(
                "text-sm",
                ev !== null && ev !== 0 && (ev > 0 ? "text-positive" : "text-negative"),
              )}
            >
              {ev === null ? DASH : fmtSignedPct(ev)}
            </Value>
          </dd>
        </div>

        <div className="min-w-0">
          <dt className="text-caption font-medium text-muted-foreground">
            {t("records.slip.measures.risk")}
          </dt>
          <dd className="mt-0.5">
            <Value pending={waiting} numeric={false} testId="slip-risk" className="text-sm">
              {risk ? translateOr(`records.slip.risk.${risk}`, riskLabel(risk)) : DASH}
            </Value>
          </dd>
        </div>
      </dl>
    </section>
  );
}

function Issues({ validation }: { validation: ParlayValidation }) {
  if (validation.errors.length === 0 && validation.warnings.length === 0) return null;
  return (
    <ul className="space-y-1.5" data-testid="slip-issues">
      {validation.errors.map((e, i) => (
        <li
          key={`e${i}`}
          data-testid="slip-error"
          className="flex items-start gap-2 rounded-md bg-negative-soft px-2.5 py-1.5 text-xs text-negative"
        >
          <XCircle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words">{issueText("error", e)}</span>
        </li>
      ))}
      {validation.warnings.map((w, i) => (
        <li
          key={`w${i}`}
          data-testid="slip-warning"
          className="flex items-start gap-2 rounded-md bg-warning-soft px-2.5 py-1.5 text-xs text-warning"
        >
          <AlertTriangle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words">{issueText("warning", w)}</span>
        </li>
      ))}
    </ul>
  );
}

function NoAiCaption() {
  return (
    <p
      className="flex items-center justify-center gap-1.5 text-center text-caption font-medium text-subtle-foreground"
      data-testid="slip-no-ai"
    >
      <Zap aria-hidden className="h-3.5 w-3.5 shrink-0 text-gold" />
      {t("records.slip.noAi")}
    </p>
  );
}

const SOURCES: ReadonlyArray<{
  to: "/picks" | "/odds" | "/matches" | "/parlays";
  nav: string;
  what: string;
  icon: LucideIcon;
}> = [
  { to: "/picks", nav: "nav.picks", what: "records.slip.guide.picks", icon: Target },
  { to: "/odds", nav: "nav.odds", what: "records.slip.guide.odds", icon: TrendingUp },
  { to: "/matches", nav: "nav.matches", what: "records.slip.guide.match", icon: CalendarDays },
  { to: "/parlays", nav: "nav.parlays", what: "records.slip.guide.parlays", icon: Layers },
];

/** Nothing in the slip yet: where selections come from, the rules, and how the numbers are worked out. */
function EmptySlip({ onLeave }: { onLeave: () => void }) {
  return (
    <div className="space-y-5 py-6" data-empty-state data-testid="slip-empty">
      <div className="text-center">
        <span
          aria-hidden
          className="mx-auto flex h-11 w-11 items-center justify-center rounded-full border border-gold/40 bg-gold-soft text-gold-strong"
        >
          <Layers className="h-5 w-5" />
        </span>
        <p className="mt-3 font-display text-base font-semibold">{t("records.slip.empty")}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t("records.slip.guide.how")}</p>
      </div>
      <ul className="space-y-2">
        {SOURCES.map(({ to, nav, what, icon: Icon }) => (
          <li key={to}>
            <Link
              to={to}
              onClick={onLeave}
              data-testid="slip-source"
              className="flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2.5 transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Icon aria-hidden className="h-4 w-4 shrink-0 text-gold" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold">{t(nav)}</span>
                <span className="block break-words text-caption text-muted-foreground">
                  {t(what)}
                </span>
              </span>
              <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
            </Link>
          </li>
        ))}
      </ul>
      <section
        aria-labelledby="slip-rules-title"
        className="rounded-lg border border-border bg-elevated/40 p-3.5"
      >
        <h3 id="slip-rules-title" className="text-label text-subtle-foreground">
          {t("records.slip.guide.rules")}
        </h3>
        <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground marker:text-gold">
          <li>{t("records.slip.guide.ruleCount", { min: MIN_SLIP_LEGS, max: MAX_SLIP_LEGS })}</li>
          <li>{t("records.slip.guide.ruleReplace")}</li>
          <li>{t("records.slip.guide.ruleKickoff")}</li>
        </ul>
      </section>
      <div
        className="flex items-start gap-2.5 rounded-lg border border-gold/30 bg-gold-soft/40 p-3.5"
        data-testid="slip-no-ai"
      >
        <Zap aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
        <p className="min-w-0 text-xs text-muted-foreground">
          <span className="block font-semibold text-foreground">{t("records.slip.noAi")}</span>
          {t("records.slip.guide.noAi")}
        </p>
      </div>
    </div>
  );
}

const SECONDARY =
  "inline-flex h-10 min-w-0 items-center justify-center gap-1.5 rounded-full border border-border-strong px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function SlipSheet() {
  const slip = useSlip();
  const refresh = useRefreshMine();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const legs = slip.legs;
  const leave = () => slip.setOpen(false);

  // The server checks the legs once they stop changing; until it answers, the client's figures stand.
  const settled = useSettled(legs, CHECK_DELAY_MS);
  const body = useMemo(() => legsBody(settled), [settled]);
  const check = useQuery({
    queryKey: ["v1", "me", "validate", body],
    queryFn: () => v1.validateParlay(body),
    enabled: slip.open && body.length > 0,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
  // The latest answer, perhaps for an earlier set of legs: only what it says of each selection is reused.
  const latest = check.data?.data ?? null;
  // The answer for exactly these legs, or none yet.
  const current = settled === legs && !check.isPlaceholderData;
  const validation = current ? latest : null;
  const failed = current && check.isError;
  const waiting = legs.length > 0 && validation === null && !failed;

  const serverLegs = useMemo(() => {
    const byKey = new Map<string, ServerLeg>();
    for (const l of latest?.legs ?? []) byKey.set(selectionKey(l), l);
    return byKey;
  }, [latest]);
  const shown = legs.map((leg) => {
    const server = serverLegs.get(leg.key);
    return {
      leg,
      price: server?.odds ?? leg.odds,
      // PrediGol's probability: the one it carried when added, else the server's.
      probability: toProbability(leg.p_model) ?? toProbability(server?.p_model),
    };
  });
  const estimate = slipEstimate(
    shown.map(({ leg, probability }) => ({ home: leg.home, away: leg.away, p_model: probability })),
    validation,
    failed,
  );
  const combined = validation
    ? toNumber(validation.combined_odds)
    : slipOdds(shown.map(({ leg, price }) => ({ ...leg, odds: price })));

  const create = useMutation({
    mutationFn: () => v1.createParlay({ name: name.trim() || null, legs: legsBody(legs) }),
    onSuccess: () => {
      toast.success(t("records.toast.parlaySaved"), {
        action: {
          label: t("records.slip.history"),
          onClick: () => void navigate({ to: "/my-picks", hash: HISTORY_HASH }),
        },
      });
      slip.clear(true);
      setName("");
      slip.setOpen(false);
      void refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const missing = Math.max(0, MIN_SLIP_LEGS - legs.length);
  const canSave =
    legs.length >= MIN_SLIP_LEGS &&
    validation?.ok === true &&
    !check.isFetching &&
    !create.isPending;
  const empty = legs.length === 0;

  return (
    <Sheet open={slip.open} onOpenChange={slip.setOpen}>
      <SheetContent
        side="right"
        closeLabel={t("common.close")}
        className="flex w-full flex-col gap-0 p-0 sm:max-w-md"
        data-testid="slip-sheet"
      >
        <SheetHeader className="border-b border-border px-5 pb-4 pt-5 text-left">
          <SheetTitle className="flex flex-wrap items-center gap-2 pr-8 font-display">
            <Layers aria-hidden className="h-5 w-5 text-gold" />
            {t("records.slip.title")}
            {empty ? null : (
              <span
                className="numeric rounded-full border border-gold/40 bg-gold-soft px-2 py-0.5 text-[0.7rem] font-semibold text-gold-strong"
                data-testid="slip-count"
              >
                <span aria-hidden>
                  {legs.length}/{MAX_SLIP_LEGS}
                </span>
                <span className="sr-only">
                  {t("records.slip.count", { count: legs.length, max: MAX_SLIP_LEGS })}
                </span>
              </span>
            )}
          </SheetTitle>
          <SheetDescription>
            {t("records.slip.subtitle", { min: MIN_SLIP_LEGS, max: MAX_SLIP_LEGS })}
          </SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-5">
          {empty ? (
            <EmptySlip onLeave={leave} />
          ) : (
            <>
              <ol className="divide-y divide-border/60">
                {shown.map(({ leg, price, probability }, i) => (
                  <LegRow
                    key={leg.key}
                    leg={leg}
                    n={i + 1}
                    price={price}
                    probability={probability}
                    onRemove={() => slip.remove(leg.key)}
                    onLeave={leave}
                  />
                ))}
              </ol>
              <div className="space-y-3 pb-5 pt-1">
                {missing > 0 ? (
                  <p className="text-xs text-muted-foreground" data-testid="slip-need-more">
                    {t("records.slip.needMore", { count: missing })}
                  </p>
                ) : null}
                <Summary
                  legs={legs.length}
                  combined={combined}
                  estimate={estimate}
                  validation={validation}
                  waiting={waiting}
                />
                <NoAiCaption />
                {validation ? <Issues validation={validation} /> : null}
                {failed ? (
                  <p className="text-xs text-negative" role="alert" data-testid="slip-check-error">
                    {errorMessage(check.error)}
                  </p>
                ) : null}
                <p className="text-caption text-subtle-foreground">{t("records.slip.note")}</p>
              </div>
            </>
          )}
        </div>

        <div className="space-y-2.5 border-t border-border bg-card px-5 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3">
          {empty ? null : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (canSave) create.mutate();
              }}
            >
              <label htmlFor="slip-name" className="text-label text-subtle-foreground">
                {t("records.slip.name")}
              </label>
              <div className="mt-1.5 flex gap-2">
                <input
                  id="slip-name"
                  type="text"
                  value={name}
                  maxLength={80}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t("records.slip.namePlaceholder")}
                  data-testid="slip-name"
                  className="h-10 min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-sm focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <button
                  type="submit"
                  disabled={!canSave}
                  data-testid="slip-save"
                  className="inline-flex h-10 shrink-0 items-center justify-center rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {create.isPending
                    ? t("records.slip.saving")
                    : waiting && missing === 0
                      ? t("records.slip.checking")
                      : t("records.slip.save")}
                </button>
              </div>
            </form>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Link
              to="/my-picks"
              hash={HISTORY_HASH}
              onClick={leave}
              data-testid="slip-history"
              className={cn(SECONDARY, empty && "col-span-2")}
            >
              <History aria-hidden className="h-4 w-4 shrink-0" />
              <span className="truncate">{t("records.slip.history")}</span>
            </Link>
            {empty ? null : (
              <button
                type="button"
                onClick={() => slip.clear()}
                data-testid="slip-clear"
                className={SECONDARY}
              >
                <Trash2 aria-hidden className="h-4 w-4 shrink-0" />
                <span className="truncate">{t("records.slip.clear")}</span>
              </button>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

/** The way back to the slip from anywhere in the product, while it has something in it. */
export function SlipButton() {
  const slip = useSlip();
  const n = slip.legs.length;
  if (n === 0) return null;
  return (
    <button
      type="button"
      onClick={() => slip.setOpen(true)}
      data-testid="slip-open"
      className="fixed bottom-20 right-4 z-40 inline-flex h-11 items-center gap-2 rounded-full border border-gold/50 bg-card px-4 text-sm font-semibold text-gold-strong shadow-lg transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:bottom-6"
    >
      <Layers aria-hidden className="h-4 w-4" />
      {t("records.slip.open", { count: n })}
    </button>
  );
}

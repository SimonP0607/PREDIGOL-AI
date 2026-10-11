/** The automatic parlay builder's answer (REVIEW point 15): the parlay with why, or why there is none. */
import { useState, type ReactNode } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { Check, ListX } from "lucide-react";
import { toast } from "sonner";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtPct, localDecimalText } from "@/lib/i18n/format";
import { formatDate, formatRelative } from "@/lib/time";
import { v1 } from "@/lib/api/v1/client";
import type { BuiltParlay } from "@/lib/api/v1/types_builder";
import { RiskBadge, ShadowBadge } from "@/product/shared/Bits";
import { errorMessage } from "@/product/shared/States";
import { useRefreshMine } from "@/product/records/hooks";
import { useSlip } from "@/product/records/slipContext";
import { adviceFor, builtToSlip, legsBody } from "./builderForm";
import { LegRow } from "./LegRow";
import { viewOfBuilt } from "./legs";

function Stat({ label, title, children }: { label: string; title?: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-label leading-tight text-subtle-foreground" title={title}>
        {label}
      </dt>
      <dd className="mt-1.5">{children}</dd>
    </div>
  );
}

/** "De 739 selecciones con valor en tu ventana, 412 no pasan de 3,00..." - each stage the parlay went through. */
function funnelText(body: BuiltParlay): string {
  const f = body.funnel;
  return t("parlays.builder.result.funnel", {
    passing: f.passing,
    risk: f.risk,
    max: fmtOdds(f.max_odds ?? null),
    reviewed: f.reviewed,
    matching: f.matching,
    combinable: f.combinable,
    matches: f.matches,
  });
}

export function Result({ body }: { body: BuiltParlay }) {
  const slip = useSlip();
  const navigate = useNavigate();
  const refresh = useRefreshMine();
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: () =>
      v1.createParlay({
        name: t("parlays.builder.savedName", { date: formatDate(new Date().toISOString()) }).slice(
          0,
          80,
        ),
        legs: legsBody(body.legs),
      }),
    onSuccess: () => {
      setSaved(true);
      toast.success(t("parlays.builder.savedToast"), {
        action: {
          label: t("parlays.builder.seeMine"),
          onClick: () => void navigate({ to: "/my-picks", hash: "my-parlays" }),
        },
      });
      void refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const shadow = body.source === "shadow_preview";
  const p = body.p_all_low === null ? null : Number(body.p_all_low);
  const open = () => {
    if (slip.legs.length) toast(t("parlays.builder.replacedSlip"));
    slip.load(builtToSlip(body.legs));
    slip.setOpen(true);
    toast.success(t("parlays.builder.loadedToast"));
  };
  return (
    <div data-testid="builder-result" data-status={body.status}>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 sm:px-5">
        <h3 className="font-display text-base font-semibold">
          {t("parlays.builder.result.title")}
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {t("parlays.legs", { count: body.legs.length })}
          </span>
        </h3>
        {shadow ? <ShadowBadge /> : null}
      </div>
      {shadow ? (
        <p className="px-4 pt-1 text-caption text-info sm:px-5">
          {t("parlays.builder.result.shadow")}
        </p>
      ) : null}
      <ol
        aria-label={t("parlays.legsList")}
        className="mt-3 divide-y divide-border/60 border-y border-border/60"
      >
        {body.legs.map((leg, i) => (
          <LegRow key={`${leg.fixture_id}-${leg.pick_id}`} leg={viewOfBuilt(leg, i + 1)} />
        ))}
      </ol>
      <div className="bg-gold-soft/30 px-4 py-4 sm:px-5" data-testid="builder-summary">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
          <Stat label={t("parlays.builder.result.combined")}>
            <span
              className="numeric text-[1.75rem] font-semibold leading-none tracking-tight text-gold-strong"
              data-testid="builder-combined-odds"
            >
              {fmtOdds(body.combined_odds)}
            </span>
          </Stat>
          <Stat
            label={t("parlays.builder.result.pAll")}
            title={t("parlays.builder.result.pAllHelp")}
          >
            <span className="numeric text-lg font-semibold leading-none">
              {fmtPct(p, p !== null && p < 0.01 ? 2 : 1)}
            </span>
          </Stat>
          <Stat label={t("parlays.builder.result.pMarket")}>
            <span className="numeric text-lg font-semibold leading-none text-muted-foreground">
              {fmtPct(body.p_all_market, 1)}
            </span>
          </Stat>
          <Stat label={t("parlays.builder.result.risk")}>
            <RiskBadge risk={body.risk} />
          </Stat>
        </dl>
        <div className="mt-4 space-y-1.5">
          <p className="text-[0.68rem] font-semibold uppercase tracking-wider text-subtle-foreground">
            {t("parlays.builder.result.why.title")}
          </p>
          <ul className="space-y-1 text-caption text-muted-foreground">
            {[
              t("parlays.builder.result.why.gate"),
              t("parlays.builder.result.why.risk", { max: fmtOdds(body.funnel.max_odds ?? null) }),
              t("parlays.builder.result.why.context"),
              t("parlays.builder.result.why.independent"),
              t("parlays.builder.result.why.growth"),
              ...(body.correlated_pairs > 0
                ? [t("parlays.builder.result.why.correlated", { count: body.correlated_pairs })]
                : []),
            ].map((line) => (
              <li key={line} className="flex items-start gap-1.5">
                <Check aria-hidden className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
          <p className="pt-1 text-caption text-subtle-foreground" data-testid="builder-funnel">
            {funnelText(body)}
            {body.prices_as_of
              ? ` · ${t("parlays.builder.result.pricesAt", { when: formatRelative(body.prices_as_of) })}`
              : ""}
          </p>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={saved || save.isPending}
            data-testid="builder-save"
            className="inline-flex min-h-10 items-center gap-1.5 rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saved ? <Check aria-hidden className="h-4 w-4" /> : null}
            {saved
              ? t("parlays.builder.saved")
              : save.isPending
                ? t("parlays.builder.saving")
                : t("parlays.builder.save")}
          </button>
          <button
            type="button"
            onClick={open}
            data-testid="builder-open-slip"
            className="inline-flex min-h-10 items-center gap-1.5 rounded-full border border-gold/50 bg-gold-soft px-4 text-sm font-semibold text-gold-strong transition-colors hover:bg-gold-soft/70"
          >
            {t("parlays.builder.openSlip")}
          </button>
        </div>
      </div>
    </div>
  );
}

export function NoParlay({ body }: { body: BuiltParlay }) {
  const f = body.filters;
  const reason = body.reason ?? "no_candidates";
  const text =
    reason === "too_few_legs"
      ? t("parlays.builder.none.too_few_legs", { count: body.funnel.matches, min: f.min_legs })
      : t(`parlays.builder.none.${reason}`, {
          min: f.min_legs,
          cap: f.max_total_odds ? localDecimalText(String(Number(f.max_total_odds))) : "",
          max: fmtOdds(body.funnel.max_odds ?? null),
        });
  return (
    <div
      data-testid="builder-result"
      data-status={body.status}
      data-reason={reason}
      className="flex items-start gap-3 px-4 py-5 sm:px-5"
    >
      <span
        aria-hidden
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-gold/30 bg-gold-soft text-gold"
      >
        <ListX className="h-5 w-5" />
      </span>
      <div className="min-w-0 space-y-1.5 pt-0.5">
        <p className="font-display text-sm font-bold uppercase tracking-wider">
          {t("parlays.builder.none.title")}
        </p>
        <p className="text-sm text-muted-foreground">{text}</p>
        <p className="text-sm text-muted-foreground">
          {t(`parlays.builder.advice.${adviceFor(body.reason)}`)}
        </p>
        {body.funnel.passing > 0 ? (
          <p className="text-caption text-subtle-foreground" data-testid="builder-funnel">
            {funnelText(body)}
          </p>
        ) : null}
        <p className="text-caption text-subtle-foreground">{t("parlays.empty.never")}</p>
      </div>
    </div>
  );
}

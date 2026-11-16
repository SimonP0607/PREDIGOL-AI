/**
 * «Mi parlay» as a card at the side of a desk (plan maestro unificado, sheets C06 and K08): the same parlay as the sheet -
 * one store, the same legs - shown while the reader picks prices. Its figures are the sheet's own client figures (the
 * product of the prices; PrediGol's estimate only when the legs carry it); saving opens the sheet, where the server checks
 * the parlay before it is kept. Nothing here calls an AI («Cálculo instantáneo · sin IA»).
 */
import { Layers, Trash2, X } from "lucide-react";
import { t } from "@/lib/i18n";
import { formatOdds, fmtPct } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { selectionLabel } from "@/product/shared/markets";
import { MAX_SLIP_LEGS, MIN_SLIP_LEGS, slipEstimate, slipOdds, toProbability } from "./model";
import { useSlip } from "./slipContext";

export function SlipCard({ className }: { className?: string | undefined }) {
  const slip = useSlip();
  const legs = slip.legs;
  const combined = slipOdds(legs);
  const estimate = slipEstimate(
    legs.map((l) => ({ home: l.home, away: l.away, p_model: toProbability(l.p_model) })),
    null,
  );
  const p = estimate.probability?.value ?? null;
  const missing = Math.max(0, MIN_SLIP_LEGS - legs.length);
  return (
    <section
      data-testid="slip-card"
      aria-labelledby="slip-card-title"
      className={cn("card-surface space-y-4 rounded-feature border-gold/45 p-5", className)}
    >
      <header className="flex items-center justify-between gap-2">
        <h2
          id="slip-card-title"
          className="flex items-center gap-2 font-display text-lg font-semibold"
        >
          <Layers aria-hidden className="h-5 w-5 text-gold" />
          {t("records.slip.title")}
        </h2>
        {legs.length > 0 ? (
          <span
            className="numeric flex h-6 min-w-6 items-center justify-center rounded-full bg-gold px-1.5 text-xs font-bold text-gold-foreground"
            data-testid="slip-card-count"
          >
            <span aria-hidden>{legs.length}</span>
            <span className="sr-only">
              {t("records.slip.count", { count: legs.length, max: MAX_SLIP_LEGS })}
            </span>
          </span>
        ) : null}
      </header>
      <p className="text-caption text-muted-foreground">
        {t("records.slip.subtitle", { min: MIN_SLIP_LEGS, max: MAX_SLIP_LEGS })}
      </p>
      {legs.length === 0 ? (
        <p className="rounded-control border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
          {t("odds.byMatch.slipEmpty")}
        </p>
      ) : (
        <ol className="divide-y divide-border/70">
          {legs.map((leg) => (
            <li key={leg.key} className="flex items-start gap-2 py-3" data-testid="slip-card-leg">
              <div className="min-w-0 flex-1">
                <p className="break-words text-sm font-semibold leading-snug">
                  {selectionLabel({
                    market_key: leg.market_key,
                    selection: leg.selection,
                    line: leg.line,
                    home: leg.home,
                    away: leg.away,
                  })}
                </p>
                <p className="break-words text-caption text-muted-foreground">
                  {leg.home} – {leg.away}
                  {leg.bookmaker ? ` · ${leg.bookmaker}` : ""}
                </p>
              </div>
              <span className="numeric shrink-0 text-sm font-bold">{formatOdds(leg.odds)}</span>
              <button
                type="button"
                onClick={() => slip.remove(leg.key)}
                title={t("records.slip.remove")}
                aria-label={t("records.slip.remove")}
                className="tap relative -mr-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X aria-hidden className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ol>
      )}
      {legs.length > 0 ? (
        <>
          <div className="flex items-end justify-between gap-3 border-t border-border pt-3">
            <div>
              <p className="text-label text-subtle-foreground">{t("odds.byMatch.combined")}</p>
              <p
                className="numeric font-display text-3xl font-bold text-gold-strong"
                data-testid="slip-card-odds"
              >
                {combined === null ? "—" : formatOdds(combined)}
              </p>
            </div>
            {p !== null ? (
              <div className="text-right">
                <p className="text-caption text-muted-foreground">{t("odds.byMatch.estimated")}</p>
                <p className="numeric text-lg font-semibold">{fmtPct(p)}</p>
              </div>
            ) : null}
          </div>
          {missing > 0 ? (
            <p className="text-xs text-muted-foreground">
              {t("records.slip.needMore", { count: missing })}
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => slip.setOpen(true)}
            data-testid="slip-card-save"
            className="inline-flex h-11 w-full items-center justify-center rounded-control border border-gold/60 bg-gold-soft text-sm font-semibold text-gold-strong transition-colors hover:bg-gold/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("odds.byMatch.save")}
          </button>
          <div className="flex items-center justify-between gap-2 text-caption">
            <button
              type="button"
              onClick={() => slip.clear()}
              data-testid="slip-card-clear"
              className="tap-y relative inline-flex items-center gap-1 font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Trash2 aria-hidden className="h-3.5 w-3.5" />
              {t("records.slip.clear")}
            </button>
            <span className="text-subtle-foreground">{t("odds.byMatch.noAi")}</span>
          </div>
        </>
      ) : null}
      <p className="text-caption text-subtle-foreground">{t("records.slip.note")}</p>
    </section>
  );
}

/**
 * "Mi parlay": the selections the user has added, checked against the rules by the server as
 * they change (POST /me/parlays/validate), and saved as a parlay of their own. Opened from the
 * floating button on every product page and from "Mis picks".
 */
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Layers, Trash2, X, XCircle } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import { fmtOdds } from "@/lib/i18n/format";
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
import { selectionLabel } from "@/product/shared/markets";
import { useRefreshMine } from "./hooks";
import { MAX_SLIP_LEGS, MIN_SLIP_LEGS, slipOdds, type SlipLeg } from "./model";
import { useSlip } from "./slipContext";

function issueText(kind: "error" | "warning", issue: ValidationIssue): string {
  return translateOr(`records.slip.${kind}.${issue.code}`, issue.code, {
    leg: issue.leg,
    with: issue.with,
    min: issue.min ?? MIN_SLIP_LEGS,
    max: issue.max ?? MAX_SLIP_LEGS,
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

function LegRow({
  leg,
  n,
  price,
  onRemove,
}: {
  leg: SlipLeg;
  n: number;
  price: string | null;
  onRemove: () => void;
}) {
  const label = selectionLabel({
    market_key: leg.market_key,
    selection: leg.selection,
    line: leg.line,
    home: leg.home,
    away: leg.away,
  });
  return (
    <li className="flex items-center gap-3 py-3" data-testid="slip-leg">
      <span
        aria-hidden
        className="numeric flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-gold-soft text-[0.65rem] font-semibold text-gold-strong"
      >
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold">{label}</div>
        <div className="mt-0.5 truncate text-caption text-muted-foreground">
          <span className="numeric">{formatKickoff(leg.kickoff_at)}</span> · {leg.home} – {leg.away}
        </div>
      </div>
      {price ? (
        <OddsPill odds={price} size="sm" />
      ) : (
        <span className="text-caption text-subtle-foreground">{t("records.slip.noPrice")}</span>
      )}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`${t("records.slip.remove")}: ${label}`}
        data-testid="slip-remove"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X aria-hidden className="h-4 w-4" />
      </button>
    </li>
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
          {issueText("error", e)}
        </li>
      ))}
      {validation.warnings.map((w, i) => (
        <li
          key={`w${i}`}
          data-testid="slip-warning"
          className="flex items-start gap-2 rounded-md bg-warning-soft px-2.5 py-1.5 text-xs text-warning"
        >
          <AlertTriangle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {issueText("warning", w)}
        </li>
      ))}
    </ul>
  );
}

export function SlipSheet() {
  const slip = useSlip();
  const refresh = useRefreshMine();
  const [name, setName] = useState("");
  const legs = slip.legs;
  const body = legsBody(legs);
  const check = useQuery({
    queryKey: ["v1", "me", "validate", body],
    queryFn: () => v1.validateParlay(body),
    enabled: slip.open && legs.length > 0,
    staleTime: 30_000,
  });
  const validation = check.data?.data ?? null;
  const create = useMutation({
    mutationFn: () => v1.createParlay({ name: name.trim() || null, legs: body }),
    onSuccess: () => {
      toast.success(t("records.toast.parlaySaved"));
      slip.clear(true);
      setName("");
      slip.setOpen(false);
      void refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const priceOf = (n: number, leg: SlipLeg): string | null =>
    validation?.legs.find((l) => l.leg === n)?.odds ?? leg.odds;
  const combined = validation ? validation.combined_odds : slipOdds(legs);
  const missing = Math.max(0, MIN_SLIP_LEGS - legs.length);
  const canSave =
    legs.length >= MIN_SLIP_LEGS &&
    validation?.ok === true &&
    !check.isFetching &&
    !create.isPending;

  return (
    <Sheet open={slip.open} onOpenChange={slip.setOpen}>
      <SheetContent
        side="right"
        closeLabel={t("common.close")}
        className="flex w-full flex-col gap-0 p-0 sm:max-w-md"
        data-testid="slip-sheet"
      >
        <SheetHeader className="border-b border-border px-5 pb-4 pt-5 text-left">
          <SheetTitle className="flex items-center gap-2 font-display">
            <Layers aria-hidden className="h-5 w-5 text-gold" />
            {t("records.slip.title")}
          </SheetTitle>
          <SheetDescription>
            {t("records.slip.subtitle", { min: MIN_SLIP_LEGS, max: MAX_SLIP_LEGS })}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-5">
          {legs.length === 0 ? (
            <div className="py-10 text-center" data-empty-state>
              <p className="font-display text-sm font-semibold">{t("records.slip.empty")}</p>
              <p className="mt-1 text-xs text-muted-foreground">{t("records.slip.emptyBody")}</p>
            </div>
          ) : (
            <>
              <ol className="divide-y divide-border/60">
                {legs.map((leg, i) => (
                  <LegRow
                    key={leg.key}
                    leg={leg}
                    n={i + 1}
                    price={priceOf(i + 1, leg)}
                    onRemove={() => slip.remove(leg.key)}
                  />
                ))}
              </ol>
              <div className="space-y-3 pb-4">
                {missing > 0 ? (
                  <p className="text-xs text-muted-foreground">
                    {t("records.slip.needMore", { count: missing })}
                  </p>
                ) : null}
                {validation ? <Issues validation={validation} /> : null}
                {check.isError ? (
                  <p className="text-xs text-negative">{errorMessage(check.error)}</p>
                ) : null}
                <p className="text-caption text-subtle-foreground">{t("records.slip.note")}</p>
              </div>
            </>
          )}
        </div>

        {legs.length > 0 ? (
          <div className="space-y-3 border-t border-border bg-card px-5 pb-5 pt-4">
            <div className="flex items-end justify-between gap-3">
              <span className="text-label text-subtle-foreground">
                {t("records.slip.combined")}
              </span>
              <span
                className={cn(
                  "numeric font-semibold",
                  combined ? "text-2xl text-gold-strong" : "text-xs text-muted-foreground",
                )}
                data-testid="slip-combined"
              >
                {check.isFetching && !validation
                  ? t("records.slip.checking")
                  : combined
                    ? fmtOdds(combined)
                    : t("records.slip.noCombined")}
              </span>
            </div>
            <label className="block">
              <span className="text-label text-subtle-foreground">{t("records.slip.name")}</span>
              <input
                type="text"
                value={name}
                maxLength={80}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("records.slip.namePlaceholder")}
                data-testid="slip-name"
                className="mt-1.5 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => slip.clear()}
                data-testid="slip-clear"
                className="inline-flex h-10 items-center gap-1.5 rounded-full border border-border-strong px-4 text-sm font-medium text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
              >
                <Trash2 aria-hidden className="h-4 w-4" />
                {t("records.slip.clear")}
              </button>
              <button
                type="button"
                disabled={!canSave}
                onClick={() => create.mutate()}
                data-testid="slip-save"
                className="inline-flex h-10 flex-1 items-center justify-center rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {create.isPending ? t("records.slip.saving") : t("records.slip.save")}
              </button>
            </div>
          </div>
        ) : null}
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

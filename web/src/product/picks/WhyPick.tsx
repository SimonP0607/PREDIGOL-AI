/**
 * «¿Por qué PrediGol eligió este pick?» (plan UX, B3; section 28): a button on every published pick - the list of picks, the day's
 * set, a match's analysis - and a sheet with the five layers, the conclusion first and open, the others folded under 44 px rows
 * (section 36: on a phone it comes up from the bottom; at a desk, from the side). The pick's state is said in words with its
 * reason, the pick of the day's state when it was chosen beside it, and the notice «no garantiza · +18» with the responsible
 * gaming resources closes every explanation.
 *
 * Opening it records `pick_explanation_opened` (once per opening); nothing is asked of the API until it opens.
 */
import { useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronDown, CircleHelp, Loader2 } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { PickExplanation } from "@/lib/api/v1/types_explanation";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Disclaimer } from "@/components/system/Disclaimer";
import { ProbCompare } from "@/product/shared/Bits";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import { UserStatusBadge } from "@/product/shared/UserStatusBadge";
import { reasonText } from "@/product/shared/userStatus";
import { useTransparencyOpen } from "@/product/transparency/useTransparencyOpen";
import {
  HOW_STEPS,
  conclusionText,
  contextEmptyText,
  dayText,
  contextLines,
  howText,
  marketLines,
  riskLines,
  selectionOf,
} from "./explanation";

/** A finger, or a screen too narrow for a side panel: the sheet comes up from the bottom (the «Reportar» sheet's rule). */
const SHEET_QUERY = "(pointer: coarse), (max-width: 639px)";

function fromBottom(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.(SHEET_QUERY).matches;
}

export function WhyPickButton({
  pickId,
  testId = "why-pick",
  className,
}: {
  pickId: number;
  testId?: string;
  className?: string | undefined;
}) {
  const [open, setOpen] = useState(false);
  const [side, setSide] = useState<"bottom" | "right">("bottom");
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      {/* The sheet's own trigger: it opens it, says so (aria-haspopup, aria-expanded) and gets the focus back on close. */}
      <SheetTrigger asChild>
        <button
          type="button"
          data-testid={testId}
          onClick={() => {
            setSide(fromBottom() ? "bottom" : "right");
            track("pick_explanation_opened", { pick_id: pickId });
          }}
          className={cn(
            "tap-y relative inline-flex min-h-9 items-center gap-1.5 rounded-full border border-border-strong px-3 text-xs font-semibold text-foreground transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          <CircleHelp aria-hidden className="h-3.5 w-3.5 shrink-0" />
          {t("picks.why.open")}
        </button>
      </SheetTrigger>
      <SheetContent
        side={side}
        closeLabel={t("picks.why.close")}
        data-testid="why-sheet"
        className={cn(
          "overflow-y-auto",
          side === "bottom"
            ? "max-h-[92dvh] rounded-t-2xl px-4 pb-[calc(1.25rem+env(safe-area-inset-bottom))] pt-5"
            : "w-full px-5 py-5 sm:max-w-md",
        )}
      >
        {open ? <WhyPickContent pickId={pickId} /> : null}
      </SheetContent>
    </Sheet>
  );
}

function WhyPickContent({ pickId }: { pickId: number }) {
  const preview = usePreviewParam();
  const transparency = useTransparencyOpen();
  const q = useQuery(live.pickExplanation(pickId, preview));
  const e = q.data?.data;
  return (
    <div className="space-y-4">
      <SheetHeader className="space-y-1 pr-8 text-left">
        <SheetTitle className="font-display text-lg leading-snug">
          {t("picks.why.title")}
        </SheetTitle>
        <SheetDescription className="text-sm text-muted-foreground">
          {e
            ? `${e.match.home.name} – ${e.match.away.name} · ${selectionOf(e)}`
            : t("picks.why.subtitle")}
        </SheetDescription>
      </SheetHeader>
      {q.isPending ? (
        <div aria-busy="true" aria-label={t("common.loading")} className="space-y-3">
          <Loader2 aria-hidden className="h-4 w-4 animate-spin text-muted-foreground" />
          <SkeletonBlock className="h-24" />
          <SkeletonBlock className="h-40" />
        </div>
      ) : q.isError || !e ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-5" />
      ) : (
        <PickExplanationView e={e} transparency={transparency} />
      )}
    </div>
  );
}

/** One layer folded under its title (a 44 px row); the conclusion is never folded. */
function Fold({ layer, open, children }: { layer: string; open: boolean; children: ReactNode }) {
  return (
    <details
      open={open}
      data-testid={`why-layer-${layer}`}
      className="group border-t border-border pt-1"
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <h3 className="min-w-0 break-words">{t(`picks.why.layers.${layer}`)}</h3>
        <ChevronDown
          aria-hidden
          className="h-4 w-4 shrink-0 transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="space-y-2 pb-3">{children}</div>
    </details>
  );
}

function Lines({ lines, testId }: { lines: string[]; testId: string }) {
  return (
    <ul className="space-y-1.5" data-testid={testId}>
      {lines.map((line, i) => (
        <li key={i} className="text-sm leading-relaxed text-foreground/90">
          {line}
        </li>
      ))}
    </ul>
  );
}

export function PickExplanationView({
  e,
  transparency = false,
}: {
  e: PickExplanation;
  /** «Cómo le va a PrediGol» is open to this account: layer 5 links to it. */
  transparency?: boolean;
}) {
  const conclusionId = useId();
  const context = contextLines(e);
  const day = e.day;
  return (
    <div className="space-y-3" data-testid="why-explanation" data-status={e.user_status}>
      <div className="space-y-1.5">
        <UserStatusBadge state={e} testId="why-status" />
        <p className="text-xs text-muted-foreground" data-testid="why-status-reason">
          {e.started ? t("picks.why.startedState") : null} {reasonText(e.status_reason)}
        </p>
        {day ? (
          <div
            className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground"
            data-testid="why-day"
          >
            <span>{dayText(e)}</span>
            {day.user_status !== e.user_status || day.context_pending !== e.context_pending ? (
              <UserStatusBadge state={day} pendingNote={false} testId="why-day-status" />
            ) : null}
          </div>
        ) : null}
      </div>

      <section
        aria-labelledby={conclusionId}
        data-testid="why-layer-conclusion"
        className="space-y-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5"
      >
        <h3
          id={conclusionId}
          className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground"
        >
          {t("picks.why.layers.conclusion")}
        </h3>
        <p className="text-sm font-medium leading-relaxed">{conclusionText(e)}</p>
      </section>

      <div>
        <Fold layer="context" open={false}>
          {context.length ? (
            <Lines lines={context} testId="why-context" />
          ) : (
            <p className="text-sm text-muted-foreground" data-testid="why-context-empty">
              {contextEmptyText(e)}
            </p>
          )}
          {e.narrative ? (
            <p className="text-caption text-subtle-foreground">
              {t("picks.why.context.narrative")}
            </p>
          ) : null}
        </Fold>
        <Fold layer="market" open={false}>
          <ProbCompare model={e.market.p_model} market={e.market.p_market} />
          <Lines lines={marketLines(e)} testId="why-market" />
        </Fold>
        <Fold layer="risks" open={false}>
          <Lines lines={riskLines(e)} testId="why-risks" />
          {e.review && e.review.risks.length ? (
            <div className="space-y-1" data-testid="why-review">
              <p className="text-xs font-semibold text-muted-foreground">
                {t("picks.why.risks.review")}
              </p>
              <Lines lines={e.review.risks} testId="why-review-risks" />
            </div>
          ) : null}
        </Fold>
        <Fold layer="how" open={false}>
          <ol className="list-decimal space-y-1 pl-5 text-sm" data-testid="why-how-steps">
            {HOW_STEPS.map((s) => (
              <li key={s}>{t(`transparency.how.steps.${s}`)}</li>
            ))}
          </ol>
          <p className="text-sm font-medium" data-testid="why-how">
            {howText(e)}
          </p>
          {transparency ? (
            <Link
              to="/transparency"
              hash="how"
              data-testid="why-how-more"
              className="tap-y relative inline-flex text-xs font-semibold text-primary underline-offset-2 hover:underline"
            >
              {t("picks.why.how.more")}
            </Link>
          ) : null}
        </Fold>
      </div>
      <Disclaimer className="border-t border-border pt-3 text-center text-caption text-muted-foreground" />
    </div>
  );
}

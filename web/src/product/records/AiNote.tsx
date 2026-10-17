/**
 * The AI decision layer's review of a recorded selection, frozen with it: what PrediGol's review said (approve,
 * caution, reject, abstain), its main reason and its risks. "Analizado por PrediGol AI" only when a language
 * model took part; otherwise the rules reviewer says so. In shadow mode a user sees only that PrediGol AI looked
 * at it (the API withholds the decision); the owner's preview and an enforced review show everything.
 */
import { BrainCircuit } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import type { ItemAi, ParlayProgress } from "@/lib/api/v1/types_records";

const TONE: Record<NonNullable<ItemAi["decision"]>, string> = {
  APPROVE: "text-positive",
  DOWNGRADE: "text-warning",
  REJECT: "text-negative",
  ABSTAIN: "text-subtle-foreground",
};

export function AiNote({
  ai,
  compact = false,
}: {
  ai: ItemAi | null | undefined;
  compact?: boolean;
}) {
  if (!ai) return null;
  if (!ai.decision) {
    // Shadow, for a user: only that PrediGol AI looked at it - nothing it decided.
    return ai.by_llm ? (
      <p
        className="flex items-center gap-1 text-caption text-subtle-foreground"
        data-testid="ai-note"
      >
        <BrainCircuit aria-hidden className="h-3 w-3" />
        {t("records.ai.byAi")}
      </p>
    ) : null;
  }
  const risks = ai.risks ?? [];
  return (
    <div className="space-y-1" data-testid="ai-note" data-decision={ai.decision}>
      <p className="flex flex-wrap items-center gap-x-1.5 text-caption">
        <BrainCircuit aria-hidden className="h-3 w-3 text-subtle-foreground" />
        <span className="text-subtle-foreground">
          {ai.by_llm ? t("records.ai.byAi") : t("records.ai.byRules")}
        </span>
        <span className={cn("font-medium", TONE[ai.decision])}>
          {t(`records.ai.decision.${ai.decision}`)}
        </span>
      </p>
      {!compact && ai.reason ? (
        <p className="text-caption text-muted-foreground">{ai.reason}</p>
      ) : null}
      {!compact && risks.length ? (
        <ul className="list-disc space-y-0.5 pl-4 text-caption text-muted-foreground">
          {risks.slice(0, 2).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

const PROGRESS_STYLE: Record<ParlayProgress, string> = {
  OPEN: "border-info/40 bg-info-soft text-info",
  PARTIAL_WON: "border-positive/40 bg-positive-soft text-positive",
  PARTIAL_LOST: "border-negative/40 bg-negative-soft text-negative",
  WON: "border-positive/40 bg-positive-soft text-positive",
  LOST: "border-negative/40 bg-negative-soft text-negative",
  VOID: "border-border-strong bg-muted text-muted-foreground",
};

/** How the legs stand: open, partially won, partially lost (lost, legs still to play), won, lost, void. */
export function ProgressBadge({
  progress,
  pending,
}: {
  progress: ParlayProgress;
  pending?: number | undefined;
}) {
  return (
    <span
      data-testid="parlay-progress"
      data-progress={progress}
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide",
        PROGRESS_STYLE[progress],
      )}
      title={pending ? t("records.progress.pending", { count: pending }) : undefined}
    >
      {t(`records.progress.${progress}`)}
    </span>
  );
}

/**
 * The visible state of a pick (plan UX, B3; section 28): one badge for the four states of the one table
 * (backend fbi/picks/user_status.py) - its words and an icon, so it never depends on colour alone - and, beside a
 * RECOMMENDED by the value rule alone, «Revisión de contexto aún no aplicada» (plan UX, A1, defect F48).
 *
 *   RECOMMENDED      Recomendado      Picks, Inicio, the match, the day's set: the only state a reader is shown (UX-002)
 *   CAUTION          Cautela          the owner's preview only (the applied AI review downgrades it)
 *   NOT_RECOMMENDED  No recomendado   the owner's preview only (no value at its price, or the applied review rejects it)
 *   EVALUATION       En evaluación    the owner's preview only: its model has not beaten the market yet
 */
import { useJustChanged } from "./motion";
import { Ban, CheckCircle2, FlaskConical, TriangleAlert, type LucideIcon } from "lucide-react";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { PickState, UserStatus } from "@/lib/api/v1/types_product";
import { STATUS_TONE, statusText } from "./userStatus";

const STATUS_ICON: Record<UserStatus, LucideIcon> = {
  RECOMMENDED: CheckCircle2,
  CAUTION: TriangleAlert,
  NOT_RECOMMENDED: Ban,
  EVALUATION: FlaskConical,
};

export function UserStatusBadge({
  state,
  pendingNote = true,
  className,
  testId = "pick-status",
}: {
  state: PickState;
  /** «Revisión de contexto aún no aplicada» under a RECOMMENDED by the value rule alone (the default). */
  pendingNote?: boolean;
  className?: string | undefined;
  testId?: string;
}) {
  // An answer without a known state (an API older than B3, during a rollback of the backend alone) shows no badge: never
  // a state that does not correspond to a real one.
  const Icon = STATUS_ICON[state.user_status] as LucideIcon | undefined;
  // a pick whose state changed under the reader's eyes (closing plan 5.1): one short swell, never on first render
  const changed = useJustChanged(state.user_status);
  if (!Icon) return null;
  const pending = pendingNote && state.context_pending && state.user_status === "RECOMMENDED";
  return (
    <span
      className={cn(
        "inline-flex min-w-0 flex-col items-start gap-0.5",
        changed && "motion-pop",
        className,
      )}
      data-testid={testId}
      data-status={state.user_status}
      data-reason={state.status_reason}
    >
      <StatusBadge tone={STATUS_TONE[state.user_status]} dot={false}>
        <Icon aria-hidden className="h-3 w-3 shrink-0" />
        {statusText(state.user_status)}
      </StatusBadge>
      {pending ? (
        <span className="text-caption text-subtle-foreground" data-testid={`${testId}-pending`}>
          {t("picks.status.contextPending")}
        </span>
      ) : null}
    </span>
  );
}

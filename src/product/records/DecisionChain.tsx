/**
 * Where a recorded pick stands, step by step - so an evaluation pick is never read as a recommendation:
 *
 *   Elegido por el modelo (elo_ologit) -> Revisado por la IA: Rebajado -> No publicado (evaluación) -> Liquidado: Perdido
 *
 * The AI step is its NEWEST review before kick-off (``ai_latest``), else the one frozen when the pick entered the
 * set; in shadow a user sees only that the AI reviewed it. "Publicado" is never true while publishing is disabled.
 */
import { BrainCircuit, Calculator, CheckCheck, Megaphone } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import type { AiLatest, ItemAi, ResultStatus } from "@/lib/api/v1/types_records";
import { resultTone } from "./model";

type Decision = NonNullable<ItemAi["decision"]>;

const DECISION_TONE: Record<Decision, string> = {
  APPROVE: "text-positive",
  DOWNGRADE: "text-warning",
  REJECT: "text-negative",
  ABSTAIN: "text-subtle-foreground",
};

function Step({
  icon,
  children,
  last = false,
}: {
  icon: ReactNode;
  children: ReactNode;
  last?: boolean;
}) {
  return (
    <li className="flex min-w-0 items-center gap-1">
      <span aria-hidden className="text-subtle-foreground [&>svg]:h-3 [&>svg]:w-3">
        {icon}
      </span>
      <span className="min-w-0">{children}</span>
      {last ? null : (
        <span aria-hidden className="px-0.5 text-subtle-foreground">
          →
        </span>
      )}
    </li>
  );
}

export function DecisionChain({
  model,
  ai,
  aiLatest,
  status,
  evaluation,
  className,
}: {
  model: string | null | undefined;
  ai: ItemAi | null | undefined;
  aiLatest: AiLatest | null | undefined;
  status: ResultStatus;
  /** From the evaluation set (shadow picks): never a recommendation. */
  evaluation: boolean;
  className?: string | undefined;
}) {
  const decision: Decision | null = aiLatest?.decision ?? ai?.decision ?? null;
  const reviewed = Boolean(aiLatest ?? ai);
  const tone = resultTone(status);
  return (
    <ol
      data-testid="decision-chain"
      data-ai={decision ?? (reviewed ? "reviewed" : "none")}
      className={cn("flex flex-wrap items-center gap-x-1 gap-y-0.5 text-caption", className)}
    >
      <Step icon={<Calculator />}>
        {t("records.chain.model", { model: model ?? t("records.chain.unknownModel") })}
      </Step>
      <Step icon={<BrainCircuit />}>
        {decision ? (
          <>
            {t("records.chain.ai")}{" "}
            <span className={cn("font-medium", DECISION_TONE[decision])}>
              {t(`records.ai.decision.${decision}`)}
            </span>
          </>
        ) : reviewed ? (
          t("records.chain.aiReviewed")
        ) : (
          <span className="text-subtle-foreground">{t("records.chain.aiNone")}</span>
        )}
      </Step>
      <Step icon={<Megaphone />}>
        <span className={evaluation ? "text-warning" : undefined}>
          {evaluation ? t("records.chain.evaluation") : t("records.chain.notPublished")}
        </span>
      </Step>
      <Step icon={<CheckCheck />} last>
        {status === "PENDING" ? (
          t("records.chain.open")
        ) : (
          <span
            className={cn(
              "font-medium",
              tone === "win" ? "text-positive" : tone === "loss" ? "text-negative" : undefined,
            )}
          >
            {t("records.chain.settled", { status: t(`records.status.${status}`) })}
          </span>
        )}
      </Step>
    </ol>
  );
}

/**
 * Where a recorded pick stands, step by step - so an evaluation pick is never read as a recommendation.
 *
 *   admin:  Elegido por el modelo (elo_ologit) -> IA: confirmado -> No publicado (evaluación)
 *   user:   IA: confirmado
 *
 * REVIEW PREDIGOL, point 1: a user does not know the models and what he sees is published, so he gets only what
 * helps him - that the AI looked at it and what it said. Nobody gets "Liquidado: Perdido": the card's result says
 * it at its foot. The AI step is the NEWEST review before kick-off (``ai_latest``), else the one frozen when the
 * pick entered the set. "Publicado" is never true while publishing is disabled.
 */
import { BrainCircuit, Calculator, Megaphone } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import type { AiLatest, ItemAi } from "@/lib/api/v1/types_records";

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
  evaluation,
  admin,
  className,
}: {
  model: string | null | undefined;
  ai: ItemAi | null | undefined;
  aiLatest: AiLatest | null | undefined;
  /** From the evaluation set (shadow picks): never a recommendation. */
  evaluation: boolean;
  /** SUPER_ADMIN, not previewing as a USER: the model and the publication steps too. */
  admin: boolean;
  className?: string | undefined;
}) {
  const decision: Decision | null = aiLatest?.decision ?? ai?.decision ?? null;
  const reviewed = Boolean(aiLatest ?? ai);
  // A user sees the AI step only when the AI looked at the pick; nothing to say otherwise.
  if (!admin && !reviewed) return null;
  return (
    <ol
      data-testid="decision-chain"
      data-ai={decision ?? (reviewed ? "reviewed" : "none")}
      data-audience={admin ? "admin" : "user"}
      className={cn("flex flex-wrap items-center gap-x-1 gap-y-0.5 text-caption", className)}
    >
      {admin ? (
        <Step icon={<Calculator />}>
          {t("records.chain.model", { model: model ?? t("records.chain.unknownModel") })}
        </Step>
      ) : null}
      <Step icon={<BrainCircuit />} last={!admin}>
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
      {admin ? (
        <Step icon={<Megaphone />} last>
          <span className={evaluation ? "text-warning" : undefined}>
            {evaluation ? t("records.chain.evaluation") : t("records.chain.notPublished")}
          </span>
        </Step>
      ) : null}
    </ol>
  );
}

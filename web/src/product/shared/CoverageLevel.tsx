/**
 * A coverage level of `coverage-levels-v1` (C-16) as a tag, shared by the owner's console of the matrix (UX-174) and the readers'
 * pages of plan PM (the competition's page, UX-178; the directory, UX-179). Its letter is always written - the colour never says it
 * alone - and its meaning goes to a screen reader and a tap. The level measures the data PrediGol has, not the quality of a league.
 */
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import type { CoverageLevel } from "@/lib/api/v1/types_availability";
import { cn } from "@/lib/utils";
import { t } from "./availabilityText";

export const LEVEL_TONE: Record<CoverageLevel, BadgeTone> = {
  A: "positive",
  B: "brand",
  C: "warning",
  D: "negative",
  MI: "neutral",
};

/** A level as a tag: its letter, and «Nivel C: cobertura parcial» for a screen reader and on hover. */
export function LevelBadge({ level }: { level: CoverageLevel }) {
  return (
    <span title={t(`availability.level.${level}`)}>
      <StatusBadge tone={LEVEL_TONE[level]} dot={false} className="numeric min-w-8 justify-center">
        <span aria-hidden>{level}</span>
        <span className="sr-only">
          {t("availability.level.label", {
            level,
            meaning: t(`availability.level.${level}`),
          })}
        </span>
      </StatusBadge>
    </span>
  );
}

/** «Cobertura A · completa», the head of a competition's page: the summary as the directory writes it (B* / C* without odds). */
export function CoverageChip({
  level,
  label,
  className,
}: {
  level: CoverageLevel;
  /** The summary as C-16 writes it (`summary_label`); the level when absent. */
  label?: string | undefined;
  className?: string | undefined;
}) {
  return (
    <span data-testid="coverage-chip" data-level={level} className={cn("inline-flex", className)}>
      <StatusBadge tone={LEVEL_TONE[level]} dot={false}>
        {t("availability.level.chip", {
          level: label ?? level,
          meaning: t(`availability.level.${level}`),
        })}
      </StatusBadge>
    </span>
  );
}

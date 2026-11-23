/**
 * The small parts every story is drawn with (plan de correcciones UX, AP-N01 to AP-N04): the level of confirmation - in words and
 * with a symbol, its meaning on a tap, never only a colour -, the category, the notices («las fuentes se contradicen») and the
 * monogram that stands where a picture would be (never a third party's).
 */
import {
  AlertTriangle,
  ArrowLeftRight,
  BadgeCheck,
  CircleDot,
  CircleHelp,
  History,
  Quote,
} from "lucide-react";
import { hintProps } from "@/components/system/tapHint";
import { cn } from "@/lib/utils";
import type {
  StoryCard,
  StoryCategory,
  StoryLevel,
  StoryWarning,
} from "@/lib/api/v1/types_stories";
import { categoryWord, levelHelp, levelOf, levelWord, monogramOf } from "./stories";
import { t } from "./storyText";

const LEVEL_TONE: Readonly<Record<StoryLevel | "none", string>> = {
  oficial: "border-positive/40 bg-positive-soft text-positive",
  dos_origenes: "border-positive/30 bg-positive-soft/60 text-positive",
  declaracion: "border-info/40 bg-info-soft text-info",
  un_medio: "border-warning/40 bg-warning-soft text-warning",
  rumor: "border-border-strong bg-elevated text-muted-foreground",
  none: "border-border bg-elevated/60 text-subtle-foreground",
};
const LEVEL_ICON = {
  oficial: BadgeCheck,
  dos_origenes: CircleDot,
  declaracion: Quote,
  un_medio: CircleDot,
  rumor: CircleHelp,
  none: CircleHelp,
} as const;

export function LevelChip({ level }: { level: StoryLevel | null }) {
  const key = level ?? "none";
  const Icon = LEVEL_ICON[key];
  const help = levelHelp(level);
  return (
    <span
      {...hintProps(help)}
      data-testid="story-level"
      data-level={key}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-micro font-semibold",
        LEVEL_TONE[key],
      )}
    >
      <Icon aria-hidden className="h-3 w-3 shrink-0" />
      {levelWord(level)}
      <span className="sr-only">: {help}</span>
    </span>
  );
}

export function CategoryChip({ category }: { category: StoryCategory }) {
  return (
    <span
      data-testid="story-category"
      className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-micro font-medium text-muted-foreground"
    >
      {categoryWord(category)}
    </span>
  );
}

const WARNING_ICON = { contradiccion: ArrowLeftRight, desactualizada: History } as const;
const WARNING_WORD: Readonly<Record<StoryWarning, string>> = {
  contradiccion: "stories.warning.contradiccion",
  desactualizada: "stories.warning.desactualizada",
};

export function WarningChips({ warnings }: { warnings: readonly StoryWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <>
      {warnings.map((w) => {
        const Icon = WARNING_ICON[w] ?? AlertTriangle;
        return (
          <span
            key={w}
            data-testid="story-warning"
            data-warning={w}
            className="inline-flex items-center gap-1 rounded-full border border-warning/40 bg-warning-soft px-2 py-0.5 text-micro font-semibold text-warning"
          >
            <Icon aria-hidden className="h-3 w-3 shrink-0" />
            {t(WARNING_WORD[w])}
          </span>
        );
      })}
    </>
  );
}

/** The letters of the story's protagonist where a picture would be: PrediGol's own mark, never a third party's. */
export function Monogram({
  card,
  className,
}: {
  card: Pick<StoryCard, "entities">;
  className?: string;
}) {
  return (
    <span
      role="img"
      aria-label={t("stories.monogram")}
      data-testid="story-monogram"
      className={cn(
        "flex shrink-0 items-center justify-center rounded-card border border-border-strong bg-elevated font-display font-bold tracking-wide text-primary",
        className ?? "h-14 w-14 text-lg",
      )}
    >
      {monogramOf(card)}
    </span>
  );
}

/** The level of a story card, or null (the chip says «sin nivel todavía»). */
export function LevelOf({ card }: { card: Pick<StoryCard, "level"> }) {
  return <LevelChip level={levelOf(card)} />;
}

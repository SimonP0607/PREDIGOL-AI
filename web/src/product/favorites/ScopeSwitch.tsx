/**
 * The reader's own or everything (plan UX, B2; section 38: «filtro por defecto en Partidos y Picks»): two buttons with
 * their counts - «Tus ligas · 12» and «Todos · 340» (or «Sugeridas» while the reader chose none). The reader's own come
 * first by default; everything else is one tap away and always counted, so nothing is hidden without saying so.
 */
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { Scope } from "./follow";

const BUTTON =
  "tap-y relative inline-flex min-h-9 items-center whitespace-nowrap rounded-full px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-11";

export function ScopeSwitch({
  value,
  onChange,
  mine,
  all,
  suggested,
  ns,
  testId,
}: {
  value: Scope;
  onChange: (next: Scope) => void;
  /** How many the reader's own are, and how many in all. */
  mine: number;
  all: number;
  suggested: boolean;
  /** The page's own words: «Todos» the matches, «Todas» the selections. */
  ns: "matches" | "picks";
  testId: string;
}) {
  const option = (scope: Scope, label: string) => (
    <button
      type="button"
      aria-pressed={value === scope}
      onClick={() => onChange(scope)}
      data-testid={`${testId}-${scope}`}
      className={cn(
        BUTTON,
        value === scope
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-elevated hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
  return (
    <div
      role="group"
      aria-label={t(`${ns}.scope.label`)}
      data-testid={testId}
      data-scope={value}
      className="inline-flex max-w-full shrink-0 items-center gap-0.5 rounded-full border border-border bg-card p-0.5"
    >
      {option("mine", t(suggested ? `${ns}.scope.suggested` : `${ns}.scope.mine`, { count: mine }))}
      {option("all", t(`${ns}.scope.all`, { count: all }))}
    </div>
  );
}

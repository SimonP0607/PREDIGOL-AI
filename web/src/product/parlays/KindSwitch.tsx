/**
 * «Del día | Multi-día» on a phone (plan de Inicio, 2.4): two long parlay cards one after the other become one card and a
 * switch between them. From `md` up both stay, side by side or one over the other, and the switch is not there. The cards
 * are all in the page either way: what the switch hides is hidden with CSS, so nothing waits for a click to exist.
 */
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import type { RecordKind } from "@/lib/api/v1/types_records";
import { PARLAY_ICON } from "./parlayText";

const KINDS: readonly RecordKind[] = ["daily", "multiday"];

export function KindSwitch({
  active,
  onChange,
  className,
}: {
  active: RecordKind;
  onChange: (kind: RecordKind) => void;
  className?: string | undefined;
}) {
  return (
    <div
      role="group"
      aria-label={t("parlays.kindSwitch.label")}
      data-testid="parlay-kind-switch"
      className={cn(
        "grid grid-cols-2 gap-1 rounded-xl border border-border bg-card p-1 md:hidden",
        className,
      )}
    >
      {KINDS.map((kind) => {
        const Icon = PARLAY_ICON[kind];
        const on = kind === active;
        return (
          <button
            key={kind}
            type="button"
            aria-pressed={on}
            data-testid={`parlay-kind-${kind}`}
            onClick={() => onChange(kind)}
            className={cn(
              "tap-y relative flex min-h-11 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              on ? "bg-gold-soft text-gold-strong" : "text-muted-foreground hover:bg-elevated",
            )}
          >
            <Icon aria-hidden className="h-4 w-4 shrink-0" />
            {t(`parlays.kindSwitch.${kind}`)}
          </button>
        );
      })}
    </div>
  );
}

/** What a kind's card wears when the switch has the other one open: hidden on a phone, there from `md` up. */
export function kindVisibility(kind: RecordKind, active: RecordKind): string {
  return kind === active ? "" : "hidden md:block";
}

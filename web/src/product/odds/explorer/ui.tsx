/**
 * The explorer's small parts: a toggle chip, a strip of chips that scrolls sideways, a skeleton bone and an arrow that says
 * which way a price went.
 */
import { useRef, type ReactNode } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { t } from "@/lib/i18n";
import { useScrollCue } from "@/lib/scrollCue";
import { cn } from "@/lib/utils";

/** An on/off filter: «Solo con cuota justa», «Mis equipos y ligas». */
export function ToggleChip({
  on,
  onChange,
  children,
  testId,
  className,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  children: ReactNode;
  testId?: string | undefined;
  className?: string | undefined;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={() => onChange(!on)}
      data-testid={testId}
      className={cn(
        "tap-y relative inline-flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        on
          ? "border-primary/50 bg-primary/12 text-primary"
          : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
        className,
      )}
    >
      {children}
    </button>
  );
}

/** A row of chips that scrolls sideways on a phone, its edge fading where more wait (the product's scroll strip). */
export function Strip({
  label,
  children,
  className,
  testId,
}: {
  label: string;
  children: ReactNode;
  className?: string | undefined;
  testId?: string | undefined;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useScrollCue(ref);
  return (
    <div
      ref={ref}
      role="group"
      aria-label={label}
      data-testid={testId}
      // py-1: the chips' 44 px reach (tap-y) stays inside the strip.
      className={cn("scroll-strip flex items-center gap-1.5 py-1", className)}
    >
      {children}
    </div>
  );
}

/** A chip of a strip: one of a set, pressed while it is the one on show. */
export function Chip({
  on,
  onClick,
  children,
  title,
  testId,
  className,
}: {
  on: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string | undefined;
  testId?: string | undefined;
  className?: string | undefined;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      title={title}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        "tap-y relative inline-flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        on
          ? "border-primary/50 bg-primary/12 text-primary"
          : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
        className,
      )}
    >
      {children}
    </button>
  );
}

/** A skeleton's piece: still with «reduce motion» (no shimmer). */
export function Bone({ className }: { className?: string | undefined }) {
  return (
    <div
      aria-hidden
      className={cn("rounded-md bg-muted/70 motion-safe:animate-pulse", className)}
    />
  );
}

/** Which way a price went in the last update: an arrow and words, never colour alone (WCAG 1.4.1). */
export function MoveArrow({ move, className }: { move: "up" | "down"; className?: string }) {
  const Icon = move === "up" ? ArrowUp : ArrowDown;
  return (
    <span
      data-testid="explorer-move"
      data-move={move}
      title={t(`explorer.price.moved.${move}`)}
      className={cn("inline-flex items-center text-muted-foreground", className)}
    >
      <Icon aria-hidden className="h-3 w-3" />
      <span className="sr-only">{t(`explorer.price.moved.${move}`)}</span>
    </span>
  );
}

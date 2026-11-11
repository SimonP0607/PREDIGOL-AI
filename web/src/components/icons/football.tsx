/**
 * The football icons of «Noche de partido» (plan maestro UX/UI 2026, PR-07; the system's sheet 6). Lucide draws
 * everything else; these five are football's own, on the same 24 px grid, 2 px stroke and round ends, in the current
 * colour - so they sit beside a Lucide icon without a seam. One icon, one meaning: a goal, a substitution, a penalty
 * and the two cards. They are decoration beside the words that say it (`aria-hidden`): a card's colour never tells a
 * booking alone.
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

function Glyph({ className, children }: { className?: string | undefined; children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      className={cn("h-4 w-4 shrink-0", className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

/** A goal: the ball. */
export function BallIcon({ className }: { className?: string | undefined }) {
  return (
    <Glyph className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5l4 3-1.5 4.5h-5L8 10.5z" />
    </Glyph>
  );
}

/** A substitution: one comes on, one goes off. */
export function SubstitutionIcon({ className }: { className?: string | undefined }) {
  return (
    <Glyph className={className}>
      <path d="M7 20V6" />
      <path d="m3 10 4-4 4 4" />
      <path d="M17 4v14" />
      <path d="m13 14 4 4 4-4" />
    </Glyph>
  );
}

/** A penalty: the goal and the spot. */
export function PenaltyIcon({ className }: { className?: string | undefined }) {
  return (
    <Glyph className={className}>
      <path d="M3 20V6h18v14" />
      <circle cx="12" cy="16" r="1.5" />
    </Glyph>
  );
}

/** A booking: yellow, red, or the second yellow that becomes red. 10 by 14 px, as a card is. */
export function CardIcon({
  tone,
  className,
}: {
  tone: "yellow" | "red" | "second";
  className?: string | undefined;
}) {
  if (tone === "second") {
    return (
      <span aria-hidden className={cn("relative inline-block h-4 w-3.5 shrink-0", className)}>
        <span className="absolute left-0 top-0 h-3.5 w-2.5 rounded-[2.5px] bg-card-yellow" />
        <span className="absolute bottom-0 right-0 h-3.5 w-2.5 rounded-[2.5px] bg-negative ring-1 ring-card" />
      </span>
    );
  }
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-3.5 w-2.5 shrink-0 rounded-[2.5px]",
        tone === "yellow" ? "bg-card-yellow" : "bg-negative",
        className,
      )}
    />
  );
}

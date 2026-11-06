/**
 * A score's number that flashes gold for a moment when it grows (closing plan 5.1: «gol en vivo»). It never flashes on
 * the first render - a score that was already there does not announce itself - and not with reduced motion. It only
 * shows the number it is given: it computes nothing and changes no state of a match.
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { FLASH_MS, useJustChanged } from "./motion";

export function GoalDigit({
  value,
  className,
  children,
}: {
  value: number | null;
  className?: string | undefined;
  children?: ReactNode;
}) {
  const flash = useJustChanged(value, FLASH_MS);
  return (
    <span className={cn(className, flash && "motion-goal inline-block")}>{children ?? value}</span>
  );
}

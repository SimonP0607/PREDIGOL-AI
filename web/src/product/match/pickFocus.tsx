/**
 * «Más sobre este pick» (plan de Inicio, 2.3): a link from Inicio names the pick it comes from (`/matches/123?pick=45`). The
 * match opens on its Resumen, brings that pick into view and marks it; its explanation opens by itself. The link is read from
 * the address like the section is (`?s=`): nothing is asked of the API for it, and a pick the match no longer lists is
 * simply not found - the page reads as any other.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { useRouterState } from "@tanstack/react-router";
import { cn } from "@/lib/utils";

/** The pick the link names, or null. */
export function focusedPickOf(searchStr: string): number | null {
  const raw = new URLSearchParams(searchStr).get("pick");
  const id = raw === null ? NaN : Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function useFocusedPick(): number | null {
  const searchStr = useRouterState({ select: (s) => s.location.searchStr });
  return focusedPickOf(searchStr);
}

export function PickAnchor({
  pickId,
  focused,
  children,
}: {
  pickId: number;
  focused: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focused) return;
    ref.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [focused]);
  return (
    <div
      ref={ref}
      id={`pick-${pickId}`}
      data-focused={focused ? "true" : undefined}
      className={cn(
        "min-w-0 scroll-mt-24 rounded-xl",
        focused && "ring-2 ring-primary ring-offset-2 ring-offset-background",
      )}
    >
      {children}
    </div>
  );
}

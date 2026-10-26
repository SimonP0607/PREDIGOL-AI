/**
 * The welcome and the first-visit hints on the page (plan UX, A13; section 20): what GET /auth/me says about them, kept in
 * step with what the API answers when the welcome is done or a hint dismissed - so the gate stops sending the reader to
 * /welcome, and a dismissed hint never shows again, at once and on every page.
 */
import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import type { Me } from "@/lib/api/v1/types_auth";
import type { HintKey, OnboardingState, WelcomeStep } from "@/lib/api/v1/types_favorites";

const STEPS: readonly WelcomeStep[] = ["football", "about"];

/** The welcome's steps, as the API lists them (football always; about only for a new account). */
export function welcomeSteps(me: Pick<Me, "welcome_steps"> | null | undefined): WelcomeStep[] {
  const listed = (me?.welcome_steps ?? []).filter((s): s is WelcomeStep =>
    (STEPS as readonly string[]).includes(s),
  );
  return listed.length > 0 ? listed : ["football"];
}

/** The account as GET /auth/me would now say it, after the API's answer about the welcome or a hint. */
export function withOnboarding(me: Me, state: OnboardingState): Me {
  return {
    ...me,
    welcome_due: state.welcome_due,
    welcome_steps: state.welcome_due ? state.welcome_steps : [],
    hints_seen: state.hints_seen,
  };
}

/** Whether a page shows its hint: a reader's account whose API keeps the hints, and this one not dismissed yet. */
export function hintShown(me: Me | null | undefined, hint: HintKey): boolean {
  if (!me || me.role !== "USER" || !Array.isArray(me.hints_seen)) return false;
  return !me.hints_seen.includes(hint);
}

/** Records the API's answer in the cached account (the gate and every hint read it). */
export function useOnboardingState(): (state: OnboardingState) => void {
  const qc = useQueryClient();
  return useCallback(
    (state: OnboardingState) => {
      qc.setQueryData<Me | null>(["auth", "me"], (me) => (me ? withOnboarding(me, state) : me));
    },
    [qc],
  );
}

/**
 * A page's first-visit hint: shown until the reader dismisses it, then never again. The dismissal hides it at once (the
 * cached account first); the API keeps it - a failure there shows it again on the next visit, never an error.
 */
export function useHint(hint: HintKey): { shown: boolean; dismiss: () => void } {
  const auth = useAuth();
  const qc = useQueryClient();
  const record = useOnboardingState();
  const shown = hintShown(auth.user, hint);
  const dismiss = useCallback(() => {
    qc.setQueryData<Me | null>(["auth", "me"], (me) =>
      me ? { ...me, hints_seen: [...(me.hints_seen ?? []), hint] } : me,
    );
    v1.dismissHint(hint).then(record, () => undefined);
  }, [hint, qc, record]);
  return { shown, dismiss };
}

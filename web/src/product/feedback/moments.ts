/**
 * The pieces of the monthly survey a page uses (plan UX, B6): whether this account is a reader the survey and «¿Te sirvió?»
 * are for, and «this was a useful moment». The provider that listens is FeedbackProvider.tsx.
 */
import { createContext, useContext, useEffect } from "react";
import type { FeedbackTrigger } from "@/lib/api/v1/types_feedback";
import { useAuth } from "@/lib/auth/AuthProvider";

export interface FeedbackValue {
  /** A useful moment happened: the survey may follow. */
  moment: (trigger: FeedbackTrigger) => void;
}

export const FeedbackContext = createContext<FeedbackValue | null>(null);

/** A reader the survey and «¿Te sirvió?» are for: signed in, nothing owed, never the owner (even as a reader). */
export function useFeedbackReader(): boolean {
  const auth = useAuth();
  return (
    auth.status === "signed-in" &&
    !auth.isSuperAdmin &&
    (auth.user?.consents_due ?? []).length === 0
  );
}

/** «This was a useful moment» once ``ready`` (the analysis is on the screen, the result is shown). */
export function useUsefulMoment(trigger: FeedbackTrigger, ready: boolean): void {
  const feedback = useContext(FeedbackContext);
  useEffect(() => {
    if (ready) feedback?.moment(trigger);
  }, [feedback, ready, trigger]);
}

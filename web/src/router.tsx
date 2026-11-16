import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";
import { LiveApiError } from "@/lib/api/v1/client";

/**
 * A 4xx from the API is an answer, not a glitch: a missing fixture stays
 * missing however often it is asked for. Only transport failures and 5xx are
 * retried, and only twice.
 */
function retry(failures: number, error: unknown): boolean {
  if (error instanceof LiveApiError && error.status >= 400 && error.status < 500) return false;
  return failures < 2;
}

/**
 * A screen's cross-fade that a quicker navigation replaces is skipped by the browser, which rejects that transition's
 * promises («Transition was skipped»). Nothing waits on them here, so the rejection is expected, not an error: each
 * transition's promises are given a handler once, at the source (UX-139: the console's tabs, changed fast, logged it).
 */
function quietSkippedTransitions(): void {
  if (typeof document === "undefined" || typeof document.startViewTransition !== "function") return;
  const doc = document as Document & { __quietTransitions?: boolean };
  if (doc.__quietTransitions) return;
  doc.__quietTransitions = true;
  const start = document.startViewTransition.bind(document);
  document.startViewTransition = ((...args: Parameters<typeof start>) => {
    const transition = start(...args);
    const swallow = () => undefined;
    transition.ready.catch(swallow);
    transition.finished.catch(swallow);
    transition.updateCallbackDone.catch(swallow);
    return transition;
  }) as typeof document.startViewTransition;
}

export const getRouter = () => {
  quietSkippedTransitions();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry, staleTime: 15_000, refetchOnWindowFocus: false } },
  });

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
    // a short cross-fade between screens where the browser has View Transitions (closing plan 5.1)
    defaultViewTransition: true,
  });

  return router;
};

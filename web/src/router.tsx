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

export const getRouter = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry, staleTime: 15_000, refetchOnWindowFocus: false } },
  });

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
  });

  return router;
};

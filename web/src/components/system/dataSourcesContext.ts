/**
 * Contexts and hooks behind the page-level data-source badge. See
 * components/system/DataSources.tsx for the reasoning.
 */
import { createContext, useContext, useEffect, useId } from "react";
import { useQuery, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import { DATA_MODE } from "@/lib/api/mode";

export type Source = "live" | "demo";
export type Registry = {
  register: (id: string, s: Source) => void;
  unregister: (id: string) => void;
};
export type PageLabel = "live" | "demo" | "hybrid";

export const RegistryContext = createContext<Registry | null>(null);
export const SourcesContext = createContext<ReadonlySet<Source>>(new Set());

export function useRegisterSource(source: Source): void {
  const id = useId();
  const registry = useContext(RegistryContext);
  useEffect(() => {
    registry?.register(id, source);
    return () => registry?.unregister(id);
  }, [registry, id, source]);
}

/** useQuery for the FastAPI service. Registers the page as showing live data. */
export function useLiveQuery<T>(
  options: UseQueryOptions<T, Error, T, readonly unknown[]>,
): UseQueryResult<T, Error> {
  useRegisterSource("live");
  return useQuery(options);
}

export function usePageDataLabel(): PageLabel {
  const sources = useContext(SourcesContext);
  if (sources.has("live") && sources.has("demo")) return "hybrid";
  if (sources.has("live")) return "live";
  if (sources.has("demo")) return "demo";
  return DATA_MODE === "mock" ? "demo" : DATA_MODE === "hybrid" ? "hybrid" : "live";
}

/**
 * Page-level data provenance, derived - never declared.
 *
 * Every component that renders live data registers "live" while it is
 * mounted; every demo region registers "demo". The topbar badge reads the set:
 *
 *   only live  -> LIVE DATA
 *   only demo  -> DEMO DATA
 *   both       -> HYBRID
 *
 * Because registration follows what is actually mounted, a page cannot show
 * a demo figure under a LIVE badge by forgetting to update a label.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { t } from "@/lib/i18n";
import { Database, FlaskConical, Layers } from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE_URL } from "@/lib/api/mode";
import {
  RegistryContext,
  SourcesContext,
  useRegisterSource,
  usePageDataLabel,
  type PageLabel,
  type Registry,
  type Source,
} from "./dataSourcesContext";

export function DataSourcesProvider({ children }: { children: React.ReactNode }) {
  const entries = useRef(new Map<string, Source>());
  const [sources, setSources] = useState<ReadonlySet<Source>>(new Set());
  const publish = useCallback(() => {
    const next = new Set(entries.current.values());
    setSources((prev) =>
      prev.size === next.size && [...prev].every((s) => next.has(s)) ? prev : next,
    );
  }, []);
  const registry = useMemo<Registry>(
    () => ({
      register: (id, s) => {
        entries.current.set(id, s);
        publish();
      },
      unregister: (id) => {
        entries.current.delete(id);
        publish();
      },
    }),
    [publish],
  );
  return (
    <RegistryContext.Provider value={registry}>
      <SourcesContext.Provider value={sources}>{children}</SourcesContext.Provider>
    </RegistryContext.Provider>
  );
}

/** Wraps any subtree that renders the demo adapter. */
export function DemoRegion({ children }: { children: React.ReactNode }) {
  useRegisterSource("demo");
  return <>{children}</>;
}

const LABELS: Record<
  PageLabel,
  { text: () => string; title: () => string; tone: string; Icon: typeof Database }
> = {
  live: {
    text: () => t("admin.shell.liveData"),
    title: () =>
      t("admin.shell.liveTitle", { url: API_BASE_URL || t("admin.shell.notConfigured") }),
    tone: "border-positive/35 bg-positive-soft text-positive",
    Icon: Database,
  },
  demo: {
    text: () => t("admin.shell.demoData"),
    title: () => t("admin.shell.demoTitle"),
    tone: "border-warning/35 bg-warning-soft text-warning",
    Icon: FlaskConical,
  },
  hybrid: {
    text: () => t("admin.shell.hybrid"),
    title: () => t("admin.shell.hybridTitle"),
    tone: "border-info/35 bg-info-soft text-info",
    Icon: Layers,
  },
};

export function PageDataModeBadge({ className }: { className?: string }) {
  const label = usePageDataLabel();
  const { tone, Icon } = LABELS[label];
  const text = LABELS[label].text();
  const title = LABELS[label].title();
  return (
    <span
      role="status"
      aria-label={t("admin.shell.dataSource", { text })}
      title={title}
      data-testid="data-mode-badge"
      data-mode={label}
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-caption font-medium uppercase tracking-wider whitespace-nowrap",
        tone,
        className,
      )}
    >
      <Icon aria-hidden className="h-3 w-3" />
      {text}
    </span>
  );
}

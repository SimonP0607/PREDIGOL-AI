/**
 * AI Analyst, live. The analyst answers only from API tools, and every figure
 * cites the tool call it came from; numbers it cannot source are listed as
 * unverified. Without an LLM configured on the API host it says so, and the
 * same tools can be run by hand below - they are the analyst's only inputs.
 */
import { t } from "@/lib/i18n";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { SegmentedTabs } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, StatusNotice } from "@/components/system/LiveState";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { ToolResult, ToolSpec } from "@/lib/api/v1/types";
import { utcDateTime } from "./format";

export function AnalystLive() {
  const status = useLiveQuery(live.analyst);
  const s = status.data?.data;
  const configured = s?.configured ?? false;
  const [question, setQuestion] = useState("");
  const ask = useMutation({ mutationFn: (q: string) => v1.ask(q) });
  const reply = ask.data?.data ?? null;

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.aiAnalyst.title")}
        description={t("admin.pages.aiAnalyst.description")}
      />
      {status.isError ? <ApiErrorNotice error={status.error} /> : null}
      {s && !configured ? (
        <WarningBanner>
          No language model is configured on the API host ({s.missing.join(", ")} unset), so the
          analyst cannot answer. Nothing is sent anywhere. The tools below are exactly what it would
          read, and they work now.
        </WarningBanner>
      ) : null}

      <Panel
        title="Ask"
        subtitle="Questions go to the API host, which calls the model and the tools. The browser never sees a key."
      >
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (question.trim()) ask.mutate(question.trim());
          }}
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={1000}
            disabled={!configured}
            placeholder={
              configured
                ? "e.g. How did Dixon-Coles do against the market?"
                : "Not configured on the API host"
            }
            aria-label="Question for the analyst"
            className="h-9 min-w-0 flex-1 rounded-md border border-border bg-card px-3 text-sm placeholder:text-subtle-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={!configured || ask.isPending || !question.trim()}
            className="h-9 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {ask.isPending ? "Asking…" : "Ask"}
          </button>
        </form>
        {ask.isError ? <ApiErrorNotice error={ask.error} className="mt-3" /> : null}
        {ask.data && ask.data.status !== "ok" ? (
          <StatusNotice
            status={ask.data.status}
            reason={ask.data.reason}
            compact
            className="mt-3"
          />
        ) : null}
        {reply ? (
          <div className="mt-4 space-y-3">
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{reply.text}</p>
            {reply.unverified_figures.length ? (
              <WarningBanner>
                Unverified figures (not found in any tool result):{" "}
                {reply.unverified_figures.join(", ")}
              </WarningBanner>
            ) : null}
            <div className="space-y-1">
              {reply.citations.map((c) => (
                <div
                  key={c.id}
                  className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground"
                >
                  <StatusBadge tone={c.ok ? "info" : "negative"}>{c.id}</StatusBadge>
                  <span className="numeric">{c.tool}</span>
                  <span>{JSON.stringify(c.arguments)}</span>
                  <span>· {c.provenance?.endpoint ?? c.error}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </Panel>

      {s ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <ToolConsole tools={s.tools} />
          <Panel title="Rules the analyst works under">
            <ul className="list-disc space-y-1.5 pl-4 text-xs text-muted-foreground">
              {s.rules.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </Panel>
        </div>
      ) : null}
    </div>
  );
}

function ToolConsole({ tools }: { tools: ToolSpec[] }) {
  const names = tools.map((t) => t.name);
  const [name, setName] = useState(names[0] ?? "get_data_quality");
  const tool = tools.find((t) => t.name === name) ?? tools[0];
  const [args, setArgs] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState<{ name: string; args: Record<string, string> } | null>(
    null,
  );
  const run = useQuery({
    queryKey: ["v1", "analyst-tool", submitted],
    queryFn: () => v1.analystTool(submitted!.name, submitted!.args),
    enabled: submitted !== null,
    retry: false,
  });
  const props = Object.entries(tool?.parameters.properties ?? {});
  return (
    <Panel
      title="Tool console"
      subtitle="Run any analyst tool by hand and see exactly what it would read"
      bodyClassName="p-4 space-y-3"
    >
      <SegmentedTabs
        tabs={names}
        value={name}
        onChange={(n) => {
          setName(n);
          setArgs({});
        }}
        label="Tool"
      />
      <p className="text-caption text-muted-foreground">{tool?.description}</p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted({ name, args: { ...args } });
        }}
      >
        {props.map(([key, spec]) => (
          <label key={key} className="flex flex-col gap-1 text-caption text-subtle-foreground">
            {key}
            {tool?.parameters.required?.includes(key) ? " *" : ""}
            <input
              value={args[key] ?? ""}
              onChange={(e) => setArgs((a) => ({ ...a, [key]: e.target.value }))}
              inputMode={spec.type === "integer" ? "numeric" : "text"}
              className="h-8 w-40 rounded-md border border-border bg-card px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </label>
        ))}
        <button
          type="submit"
          className="h-8 rounded-md border border-border px-3 text-xs hover:bg-elevated"
        >
          Run
        </button>
      </form>
      {run.isError ? <ApiErrorNotice error={run.error} /> : null}
      {run.data ? <ToolOutput result={run.data} /> : null}
    </Panel>
  );
}

function ToolOutput({ result }: { result: ToolResult }) {
  return (
    <div className="space-y-2">
      <div className="grid gap-x-6 sm:grid-cols-2">
        <KeyValue label="Status" value={result.status ?? "—"} />
        <KeyValue label="Endpoint" value={result.provenance.endpoint} />
        <KeyValue label="Generated" value={utcDateTime(result.provenance.generated_at)} />
        <KeyValue label="Data as of" value={utcDateTime(result.provenance.data_as_of)} />
      </div>
      {result.reason ? (
        <StatusNotice status={result.status ?? "not_available"} reason={result.reason} compact />
      ) : null}
      <pre className="max-h-96 overflow-auto rounded-md border border-border bg-card p-3 text-caption leading-relaxed text-muted-foreground">
        {JSON.stringify(result.data, null, 2)}
      </pre>
    </div>
  );
}

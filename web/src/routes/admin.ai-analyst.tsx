import { useState } from "react";
import { DATA_MODE } from "@/lib/api/mode";
import { DemoRegion } from "@/components/system/DataSources";
import { AiResearchLive } from "@/live/AiResearchLive";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState, KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { ProvenanceChip } from "@/components/primitives/Indicators";
import { queries } from "@/lib/api/resources";
import { dateTimeOf } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AnalystAnswer } from "@/types/domain";

export const Route = createFileRoute("/admin/ai-analyst")({
  head: () => ({
    meta: [
      { title: "AI Analyst · PrediGol Admin" },
      {
        name: "description",
        content:
          "Research assistant grounded in the platform's structured data: models, probabilities, prices and provenance.",
      },
      { property: "og:title", content: "AI Analyst · PrediGol Admin" },
      {
        property: "og:description",
        content: "Research workspace answering only from structured, traceable platform data.",
      },
    ],
  }),
  component: RouteComponent,
});

function RouteComponent() {
  if (DATA_MODE !== "mock") return <AiResearchLive />;
  return (
    <DemoRegion>
      <AnalystPage />
    </DemoRegion>
  );
}

function AnalystPage() {
  const answers = useQuery(queries.analyst);
  const list = answers.data ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [unsupported, setUnsupported] = useState(false);

  const selected = list.find((a) => a.id === selectedId) ?? null;

  function ask(question: string) {
    const hit = list.find((a) => a.question.toLowerCase() === question.trim().toLowerCase());
    if (hit) {
      setSelectedId(hit.id);
      setUnsupported(false);
    } else {
      setSelectedId(null);
      setUnsupported(true);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "System" }, { label: "AI Analyst" }]}
        title="AI Analyst"
        description="A research workspace over internal tools — not a chatbot. Every answer is composed from structured records and cites what produced it."
      />

      <WarningBanner tone="info">
        The analyst answers only from structured platform data: predictions, odds snapshots, model
        evaluations and data-quality records. It never speculates and it never recommends a stake.
      </WarningBanner>

      <div className="grid gap-4 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="space-y-4">
          <Panel title="Ask" subtitle="Questions resolve against the internal tool registry.">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                ask(draft);
              }}
              className="flex gap-2"
            >
              <label htmlFor="analyst-q" className="sr-only">
                Research question
              </label>
              <input
                id="analyst-q"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Ask a research question"
                className="h-8 min-w-0 flex-1 rounded-md border border-border bg-card px-2 text-xs placeholder:text-subtle-foreground focus:border-border-strong focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              <button
                type="submit"
                className="inline-flex h-8 items-center gap-1 rounded-md border border-primary/40 bg-primary/12 px-2.5 text-xs text-primary hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                Run
                <ArrowRight aria-hidden className="h-3 w-3" />
              </button>
            </form>
          </Panel>

          <Panel title="Suggested queries" subtitle="Backed by tools that already return data.">
            <ul className="space-y-1.5">
              {list.map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setDraft(a.question);
                      setSelectedId(a.id);
                      setUnsupported(false);
                    }}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-md border px-2.5 py-2 text-left text-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                      selectedId === a.id
                        ? "border-primary/40 bg-primary/10 text-foreground"
                        : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
                    )}
                  >
                    <Sparkles aria-hidden className="mt-0.5 h-3 w-3 shrink-0 text-primary/70" />
                    {a.question}
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        {selected ? (
          <AnswerView answer={selected} />
        ) : (
          <Panel bodyClassName="">
            <EmptyState
              title={unsupported ? "No grounded answer for that question" : "No question selected"}
              description={
                unsupported
                  ? "The analyst only answers when an internal tool can produce structured evidence. Rephrase using one of the suggested queries."
                  : "Pick a suggested query or type a question. Answers always carry evidence, metrics and traceability."
              }
              icon={<Sparkles className="h-5 w-5" />}
            />
          </Panel>
        )}
      </div>
    </div>
  );
}

function AnswerView({ answer }: { answer: AnalystAnswer }) {
  return (
    <div className="space-y-4">
      <Panel
        title="Answer"
        subtitle={answer.question}
        actions={<StatusBadge tone="brand">Grounded</StatusBadge>}
      >
        <p className="text-sm leading-relaxed text-foreground/90">{answer.answer}</p>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Evidence" subtitle="Each statement maps to a stored record.">
          <ul className="space-y-2">
            {answer.evidence.map((e) => (
              <li key={e} className="flex items-start gap-2 text-xs text-muted-foreground">
                <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                <span>{e}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Metrics" subtitle="Every number carries the record it came from.">
          <div className="space-y-0">
            {answer.metrics.map((m) => (
              <KeyValue
                key={m.label}
                label={m.label}
                value={
                  <span className="inline-flex items-baseline gap-2">
                    <span>{m.value}</span>
                    <span className="text-caption text-subtle-foreground">{m.source}</span>
                  </span>
                }
              />
            ))}
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Related fixtures">
          {answer.relatedFixtures.length === 0 ? (
            <p className="text-xs text-subtle-foreground">
              No fixture is implicated by this answer.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {answer.relatedFixtures.map((f) => (
                <li key={f.id}>
                  <Link
                    to="/matches/$fixtureId"
                    params={{ fixtureId: f.id }}
                    className="text-xs text-primary hover:underline"
                  >
                    {f.label}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Related models">
          {answer.relatedModels.length === 0 ? (
            <p className="text-xs text-subtle-foreground">No model is implicated by this answer.</p>
          ) : (
            <ul className="space-y-1.5">
              {answer.relatedModels.map((m) => (
                <li key={m.id}>
                  <Link to="/admin/models" className="text-xs text-primary hover:underline">
                    {m.label}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Traceability">
          <div className="flex flex-wrap gap-2">
            {answer.sources.map((s) => (
              <ProvenanceChip key={s.label} label={s.kind} value={s.reference} />
            ))}
          </div>
          <div className="mt-3 space-y-0">
            {answer.sources.map((s) => (
              <KeyValue key={s.label} label={s.label} value={dateTimeOf(s.capturedAt)} />
            ))}
            <KeyValue label="Answer generated" value={dateTimeOf(answer.generatedAt)} />
          </div>
        </Panel>
      </div>
    </div>
  );
}

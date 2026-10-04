/**
 * The evolution loop (GATE I): results become memory and proposals, and only the owner
 * decides. Accepting a hypothesis opens an experiment in research - it changes no rule, model
 * or pick; nothing reaches users without a passed gate and an explicit promotion.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { t } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel } from "@/components/primitives/Panel";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { Hypothesis, HypothesisStatus, MemoryEntry } from "@/lib/api/v1/types_ai";
import { utcDateTime } from "./format";

const STATUS_TONE: Record<HypothesisStatus, BadgeTone> = {
  PROPOSED: "info",
  ACCEPTED: "positive",
  REJECTED: "neutral",
  RUNNING: "brand",
  DONE: "positive",
};
const STEPS = ["s1", "s2", "s3", "s4", "s5"] as const;
const INPUT =
  "w-full rounded-md border border-border bg-card px-2 py-1.5 text-xs text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

function Decide({ h }: { h: Hypothesis }) {
  const [note, setNote] = useState("");
  const qc = useQueryClient();
  const decide = useMutation({
    mutationFn: (decision: "accept" | "reject") => v1.decideHypothesis(h.id, decision, note),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v1", "evolution"] }),
  });
  return (
    <div className="space-y-2">
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={500}
        placeholder={t("ai.evolution.note")}
        aria-label={t("ai.evolution.note")}
        className={INPUT}
      />
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={decide.isPending}
          onClick={() => decide.mutate("accept")}
          className="h-7 rounded-md border border-positive/40 bg-positive-soft px-2.5 text-xs text-positive disabled:opacity-50"
        >
          {t("ai.evolution.accept")}
        </button>
        <button
          type="button"
          disabled={decide.isPending}
          onClick={() => decide.mutate("reject")}
          className="h-7 rounded-md border border-border px-2.5 text-xs hover:bg-elevated disabled:opacity-50"
        >
          {t("ai.evolution.reject")}
        </button>
      </div>
      {decide.isError ? <ApiErrorNotice error={decide.error} /> : null}
    </div>
  );
}

function HypothesisCard({ h }: { h: Hypothesis }) {
  return (
    <li className="space-y-2 rounded-md border border-border p-3" data-testid="hypothesis">
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge tone={STATUS_TONE[h.status]}>
          <span data-status={h.status}>{t(`ai.evolution.status.${h.status}`)}</span>
        </StatusBadge>
        <StatusBadge tone={h.proposed_by === "ai" ? "brand" : "neutral"}>
          {t(`ai.evolution.by.${h.proposed_by}`)}
        </StatusBadge>
        <span className="text-caption text-subtle-foreground">{utcDateTime(h.created_at)}</span>
      </div>
      <p className="text-sm font-medium">{h.title}</p>
      <p className="text-xs text-muted-foreground">{h.hypothesis}</p>
      <p className="text-caption text-subtle-foreground">
        <span className="font-medium">{t("ai.evolution.rationale")}:</span> {h.rationale}
      </p>
      {Object.keys(h.evidence).length ? (
        <details className="text-caption text-subtle-foreground">
          <summary className="cursor-pointer">{t("ai.evolution.evidence")}</summary>
          <pre className="mt-1 max-h-48 overflow-auto rounded border border-border bg-card p-2">
            {JSON.stringify(h.evidence, null, 2)}
          </pre>
        </details>
      ) : null}
      {h.status === "PROPOSED" ? (
        <Decide h={h} />
      ) : h.decided_at ? (
        <p className="text-caption text-subtle-foreground">
          {t("ai.evolution.decided", { who: h.decided_by ?? "—", when: utcDateTime(h.decided_at) })}
          {h.decision_note ? ` · ${h.decision_note}` : ""}
        </p>
      ) : null}
    </li>
  );
}

function Propose() {
  const [title, setTitle] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [rationale, setRationale] = useState("");
  const qc = useQueryClient();
  const make = useMutation({
    mutationFn: () => v1.proposeHypothesis({ title, hypothesis, rationale }),
    onSuccess: () => {
      setTitle("");
      setHypothesis("");
      setRationale("");
      void qc.invalidateQueries({ queryKey: ["v1", "evolution"] });
    },
  });
  const ready =
    title.trim().length >= 5 && hypothesis.trim().length >= 5 && rationale.trim().length >= 5;
  return (
    <Panel title={t("ai.evolution.propose.title")} subtitle={t("ai.evolution.propose.subtitle")}>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) make.mutate();
        }}
      >
        <label className="block space-y-1 text-caption text-subtle-foreground">
          {t("ai.evolution.propose.fieldTitle")}
          <input
            value={title}
            maxLength={160}
            onChange={(e) => setTitle(e.target.value)}
            className={INPUT}
          />
        </label>
        <label className="block space-y-1 text-caption text-subtle-foreground">
          {t("ai.evolution.propose.fieldHypothesis")}
          <textarea
            value={hypothesis}
            maxLength={600}
            rows={2}
            onChange={(e) => setHypothesis(e.target.value)}
            className={INPUT}
          />
        </label>
        <label className="block space-y-1 text-caption text-subtle-foreground">
          {t("ai.evolution.propose.fieldRationale")}
          <textarea
            value={rationale}
            maxLength={1000}
            rows={2}
            onChange={(e) => setRationale(e.target.value)}
            className={INPUT}
          />
        </label>
        <button
          type="submit"
          disabled={!ready || make.isPending}
          className="h-8 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          {t("ai.evolution.propose.submit")}
        </button>
        {make.isSuccess ? (
          <p className="text-caption text-positive">{t("ai.evolution.propose.done")}</p>
        ) : null}
        {make.isError ? <ApiErrorNotice error={make.error} /> : null}
      </form>
    </Panel>
  );
}

function MemoryList({ memory }: { memory: MemoryEntry[] }) {
  if (!memory.length)
    return <p className="text-xs text-subtle-foreground">{t("ai.evolution.emptyMemory")}</p>;
  return (
    <ul className="space-y-2" data-testid="memory">
      {memory.map((m) => (
        <li key={m.id} className="space-y-1 border-b border-border pb-2 last:border-0">
          <div className="flex flex-wrap items-center gap-1.5 text-caption text-subtle-foreground">
            <StatusBadge tone="neutral">{t(`ai.evolution.source.${m.source}`)}</StatusBadge>
            <span className="numeric">{m.topic}</span>
            <span>· {utcDateTime(m.created_at)}</span>
            {m.versions > 1 ? (
              <span>· {t("ai.evolution.versions", { count: localInt(m.versions) })}</span>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">{m.finding}</p>
        </li>
      ))}
    </ul>
  );
}

export function EvolutionLive() {
  const q = useLiveQuery(live.evolution);
  const d = q.data?.data ?? null;
  const proposed = d?.hypotheses.filter((h) => h.status === "PROPOSED") ?? [];
  const decided = d?.hypotheses.filter((h) => h.status !== "PROPOSED") ?? [];
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.evolution.title")}
        description={t("admin.pages.evolution.description")}
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={5} cols={3} /> : null}
      {d ? (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Panel title={t("ai.evolution.loopTitle")}>
              <ol className="list-decimal space-y-1.5 pl-4 text-xs text-muted-foreground">
                {STEPS.map((s) => (
                  <li key={s}>{t(`ai.evolution.loop.${s}`)}</li>
                ))}
              </ol>
            </Panel>
            <Panel bodyClassName="p-4 space-y-1">
              <KeyValue
                label={t("ai.evolution.lastMonitor")}
                value={d.last_monitor ? utcDateTime(d.last_monitor) : t("ai.evolution.never")}
              />
              <KeyValue
                label={t("ai.evolution.lastV2")}
                value={d.last_v2 ? `${d.last_v2.name}` : t("ai.evolution.never")}
              />
              <p className="pt-1 text-caption text-subtle-foreground">
                {d.v2_due ? t("ai.evolution.due", { reason: d.v2_due }) : t("ai.evolution.notDue")}
              </p>
            </Panel>
          </div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <div className="space-y-4">
              <Panel
                title={t("ai.evolution.hypotheses")}
                subtitle={`${proposed.length} · ${decided.length}`}
              >
                {d.hypotheses.length ? (
                  <ul className="space-y-2">
                    {[...proposed, ...decided].map((h) => (
                      <HypothesisCard key={h.id} h={h} />
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-subtle-foreground">{t("ai.evolution.empty")}</p>
                )}
              </Panel>
            </div>
            <div className="space-y-4">
              <Propose />
              <Panel title={t("ai.evolution.memory")} subtitle={t("ai.evolution.memoryHelp")}>
                <MemoryList memory={d.memory} />
              </Panel>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

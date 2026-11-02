/**
 * LEARNING NOTES and RESEARCH FINDINGS (plan F8): what the AI's daily learning cycle wrote down (``ai.memory_events``) and what the
 * model research concluded (each topic keeps its earlier findings). The two used to sit in the AI decision layer and in
 * Evolución; they are memory, so they are here. Reading only.
 */
import { useState } from "react";
import { t, translateOr } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import { Choice, Note, Toolbar } from "./AiBits";
import { utcDateTime } from "./format";

/** The kinds of note the learning cycle writes (``MemoryKind`` of the API). */
export const NOTE_KINDS = [
  "match_result",
  "pick_result",
  "context_error",
  "news_signal",
  "injury_signal",
  "market_signal",
  "model_failure",
  "model_success",
  "league_pattern",
  "team_pattern",
  "player_pattern",
  "review_quality",
  "pick_postmortem",
] as const;

export function LearningNotes() {
  const [kind, setKind] = useState("");
  const q = useLiveQuery(live.aiMemory(kind || undefined));
  const rows = q.data?.data ?? [];
  return (
    <div className="space-y-3" data-testid="memory-notes">
      <Toolbar>
        <Choice label={t("memory.events.kind")} value={kind} onChange={setKind}>
          <option value="">{t("memory.events.allKinds")}</option>
          {NOTE_KINDS.map((k) => (
            <option key={k} value={k}>
              {translateOr(`ai.layer.memoryKind.${k}`, k)}
            </option>
          ))}
        </Choice>
      </Toolbar>
      <Note>{t("memory.events.note")}</Note>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={4} cols={3} /> : null}
      {q.isSuccess && rows.length === 0 ? <Note>{t("ai.layer.memory.empty")}</Note> : null}
      {rows.length ? (
        <Panel bodyClassName="p-3">
          <ul className="space-y-2">
            {rows.map((m) => (
              <li
                key={m.id}
                className="space-y-0.5 border-b border-border pb-2 text-xs last:border-0"
              >
                <div className="flex flex-wrap items-center gap-1.5 text-caption text-subtle-foreground">
                  <StatusBadge tone="neutral">
                    {translateOr(`ai.layer.memoryKind.${m.kind}`, m.kind)}
                  </StatusBadge>
                  <span>
                    {m.entity_type}:{m.entity_id}
                  </span>
                  <span>· {utcDateTime(m.created_at)}</span>
                  {m.result ? <span>· {m.result}</span> : null}
                  <span>· {m.version}</span>
                </div>
                {m.hypothesis ? <p className="text-muted-foreground">{m.hypothesis}</p> : null}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}

export function ResearchFindings() {
  const q = useLiveQuery(live.evolution);
  const memory = q.data?.data?.memory ?? [];
  return (
    <div className="space-y-3" data-testid="memory-research">
      <Note>{t("memory.research.note")}</Note>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={4} cols={3} /> : null}
      {q.isSuccess && memory.length === 0 ? <Note>{t("ai.evolution.emptyMemory")}</Note> : null}
      {memory.length ? (
        <Panel title={t("ai.evolution.memory")} subtitle={t("ai.evolution.memoryHelp")}>
          <ul className="space-y-2">
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
        </Panel>
      ) : null}
    </div>
  );
}

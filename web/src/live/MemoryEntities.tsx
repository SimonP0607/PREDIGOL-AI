/**
 * ENTITIES (plan F8): the longitudinal memory of teams, leagues, markets, referees, coaches and players, one row per series, with the
 * version of the memory that wrote it, how far to trust it (confidence) and what it rests on (the matches, or the decisions and the
 * post-mortems that judged them). Reading only.
 */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import { fmtSignedPct } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { SelectFilter } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { IntelMemoryRow } from "@/lib/api/v1/types_intel";
import { toNum } from "./aiModel";
import { Note } from "./AiBits";
import {
  ASPECTS,
  DASH,
  aspectLabel,
  confidenceText,
  confidenceTone,
  detailOf,
  evidenceParts,
  recordText,
  sampleOf,
} from "./memoryText";

const TYPES = ["team", "competition", "market", "referee", "coach", "player"] as const;
const LIMIT = 200;
/** The matches of a series that are linked, newest first. */
const LINKED = 3;

function Evidence({ row }: { row: IntelMemoryRow }) {
  const parts = evidenceParts(row.evidence_ref);
  if (!parts.length) return <span className="text-subtle-foreground">{DASH}</span>;
  return (
    <div className="space-y-0.5 text-xs" data-testid="memory-evidence">
      {parts.map((p) => (
        <div key={p.kind}>
          <span>{p.text}</span>
          {p.sample ? (
            <span className="text-subtle-foreground">
              {" "}
              ({t("memory.entities.evidenceNewest", { count: p.ids.length })})
            </span>
          ) : null}
          {p.kind === "fixtures" ? (
            <span className="ml-1.5 inline-flex flex-wrap gap-x-1.5 font-mono text-caption">
              {p.ids.slice(0, LINKED).map((id) => (
                <Link
                  key={id}
                  to="/matches/$fixtureId"
                  params={{ fixtureId: String(id) }}
                  className="text-primary hover:underline"
                >
                  #{id}
                </Link>
              ))}
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function EntityRow({ m }: { m: IntelMemoryRow }) {
  const s = m.stats as Record<string, unknown>;
  const sample = sampleOf(m);
  const last10 = s["last10"];
  return (
    <TRow>
      <TD className="max-w-[12rem] break-words">
        {m.entity_name ?? m.entity_id}
        <div className="text-caption text-subtle-foreground">
          {t(`intel.memory.types.${m.entity_type}`)}
        </div>
      </TD>
      <TD>{aspectLabel(m.aspect)}</TD>
      <TD>
        {m.as_of_day}
        <div className="text-caption text-subtle-foreground">{m.version}</div>
      </TD>
      <TD align="right">{sample === null ? DASH : String(sample)}</TD>
      <TD>
        <StatusBadge tone={confidenceTone(m.confidence)}>
          {confidenceText(m.confidence)}
        </StatusBadge>
      </TD>
      <TD>
        <Evidence row={m} />
      </TD>
      <TD align="right">{recordText(m)}</TD>
      <TD align="right">
        {fmtSignedPct(toNum(s["clv_mean"] as number | string | null | undefined))}
      </TD>
      <TD className="font-mono text-caption">
        {Array.isArray(last10) ? (last10 as string[]).join("") : DASH}
      </TD>
      <TD className="text-xs">{detailOf(m)}</TD>
    </TRow>
  );
}

/** The table of the series: one row each, with its version, confidence and evidence. */
export function EntityTable({ items }: { items: IntelMemoryRow[] }) {
  return (
    <Panel bodyClassName="p-0">
      <TableShell>
        <THead>
          <TH>{t("intel.memory.type")}</TH>
          <TH>{t("intel.memory.aspect")}</TH>
          <TH>{t("intel.memory.asOf")}</TH>
          <TH align="right">{t("memory.entities.sample")}</TH>
          <TH>{t("memory.entities.confidence")}</TH>
          <TH>{t("memory.entities.evidence")}</TH>
          <TH align="right">{t("intel.memory.record")}</TH>
          <TH align="right">{t("intel.memory.clv")}</TH>
          <TH>{t("intel.memory.last10")}</TH>
          <TH>{t("intel.memory.detail")}</TH>
        </THead>
        <tbody>
          {items.map((m) => (
            <EntityRow key={`${m.entity_type}-${m.entity_id}-${m.aspect}`} m={m} />
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}

export function EntityMemory() {
  const [type, setType] = useState<string>("team");
  const [aspect, setAspect] = useState("");
  const [search, setSearch] = useState("");
  const q = useLiveQuery(
    live.intelMemory({
      entity_type: type || undefined,
      aspect: aspect || undefined,
      q: search || undefined,
      limit: LIMIT,
    }),
  );
  const items = q.data?.data?.items ?? [];
  const total = q.data?.data?.total ?? items.length;
  return (
    <div className="space-y-3" data-testid="memory-entities">
      <div className="flex flex-wrap items-end gap-3">
        <SelectFilter
          label={t("intel.memory.type")}
          value={type}
          onChange={setType}
          options={[
            { value: "", label: t("memory.entities.allTypes") },
            ...TYPES.map((x) => ({ value: x, label: t(`intel.memory.types.${x}`) })),
          ]}
        />
        <SelectFilter
          label={t("intel.memory.aspect")}
          value={aspect}
          onChange={setAspect}
          options={[
            { value: "", label: t("memory.entities.allAspects") },
            ...ASPECTS.map((x) => ({ value: x, label: aspectLabel(x) })),
          ]}
        />
        <label className="flex flex-col gap-1 text-caption uppercase tracking-wider text-subtle-foreground">
          {t("intel.memory.search")}
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 w-48 min-h-11 rounded-md border border-border bg-card px-2 text-xs sm:min-h-8"
          />
        </label>
      </div>
      <details className="rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
        <summary className="tap relative cursor-pointer text-foreground">
          {t("memory.entities.confidence")}
        </summary>
        <p className="mt-2 max-w-4xl">{t("memory.entities.help")}</p>
      </details>
      <Note>{t("intel.memory.streakNote")}</Note>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={5} cols={6} /> : null}
      {q.data && items.length === 0 ? <Note>{t("intel.memory.empty")}</Note> : null}
      {items.length ? (
        <>
          <p className="text-caption text-subtle-foreground">
            {t("memory.entities.shown", { shown: items.length, total })}
            {items.some((m) => m.confidence === null)
              ? ` · ${t("memory.entities.legacyNote")}`
              : ""}
          </p>
          <EntityTable items={items} />
        </>
      ) : null}
    </div>
  );
}

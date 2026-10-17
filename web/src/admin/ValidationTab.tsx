/**
 * Historical validation (GATE C) in the Admin Console: finished matches by state, the rules
 * they failed, competition-seasons by data class with their score components, and the
 * quarantined matches. Read-only; the validation runs after each Elo refresh.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MetricCard, Panel } from "@/components/primitives/Panel";
import {
  LimitedRows,
  TableShell,
  TableSkeleton,
  TD,
  TH,
  THead,
  TRow,
} from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { FilterBar, SearchFilter, SelectFilter, ToggleFilter } from "@/components/system/Filters";
import { live } from "@/lib/api/v1/queries";
import type { CompetitionScoreRow, DataClass, ScoresQuery } from "@/lib/api/v1/types_truth";
import { t, translateOr } from "@/lib/i18n";
import { localInt, localPct } from "@/lib/i18n/format";
import { formatDateTime, formatRelative } from "@/lib/time";
import { EmptyState, ErrorState } from "@/product/shared/States";

const CLASSES: DataClass[] = ["MODEL_READY", "PARTIAL", "PRODUCT_ONLY", "INSUFFICIENT"];
const CLASS_TONE: Record<DataClass, BadgeTone> = {
  MODEL_READY: "positive",
  PARTIAL: "info",
  PRODUCT_ONLY: "warning",
  INSUFFICIENT: "neutral",
};

function pct(v: number | undefined): string {
  return v === undefined ? "—" : localPct(v, 0);
}

/** The thresholds a competition-season missed, in the reader's language (mirrors the API's rule). */
function why(r: CompetitionScoreRow): string {
  const c = r.components;
  const out: string[] = [];
  const few = (need: number) =>
    r.finished < need ? out.push(t("truth.validation.why.fewMatches", { n: r.finished, need })) : 0;
  const below = (
    key: "results" | "integrity" | "prices" | "elo",
    v: number | undefined,
    need: number,
  ) =>
    v !== undefined && v < need
      ? out.push(t(`truth.validation.why.${key}`, { v: pct(v), need: localPct(need, 0) }))
      : 0;
  if (r.data_class === "INSUFFICIENT") {
    few(10);
    below("results", c["results"], 0.8);
  } else if (r.data_class === "PRODUCT_ONLY") {
    below("results", c["results"], 0.95);
    below("integrity", c["integrity"], 0.98);
    few(30);
  } else if (r.data_class === "PARTIAL") {
    below("prices", c["odds"], 0.6);
    below("elo", c["elo"], 0.95);
    few(50);
  }
  return out.length ? out.join(" · ") : t("truth.validation.none");
}

export function ValidationTab() {
  const summary = useQuery({ ...live.validation });
  if (summary.isPending) return <TableSkeleton rows={10} cols={6} />;
  if (summary.isError)
    return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;
  const s = summary.data?.data;
  if (!s || s.fixtures === 0)
    return <EmptyState title={summary.data?.reason ?? t("truth.validation.never")} />;
  const states = s.states;
  const total = s.fixtures;
  return (
    <div className="space-y-4" data-testid="validation">
      <p className="text-sm text-muted-foreground">
        {t("truth.validation.subtitle", {
          version: s.rule_version ?? "—",
          ago: s.computed_at ? formatRelative(s.computed_at) : "—",
        })}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label={t("truth.validation.cards.approved")}
          value={localInt(states.HISTORICAL_APPROVED ?? 0)}
          hint={t("truth.validation.cards.approvedHint", {
            share: total ? localPct((states.HISTORICAL_APPROVED ?? 0) / total, 1) : "—",
            total: localInt(total),
          })}
          tone="positive"
        />
        <MetricCard
          label={t("truth.validation.cards.validated")}
          value={localInt(states.VALIDATED ?? 0)}
          hint={t("truth.validation.cards.validatedHint")}
        />
        <MetricCard
          label={t("truth.validation.cards.quarantined")}
          value={localInt(states.QUARANTINED ?? 0)}
          hint={t("truth.validation.cards.quarantinedHint")}
          tone={(states.QUARANTINED ?? 0) > 0 ? "warning" : "default"}
        />
        <MetricCard
          label={t("truth.validation.cards.ingested")}
          value={localInt(states.INGESTED ?? 0)}
          hint={t("truth.validation.cards.ingestedHint")}
        />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title={t("truth.validation.classes")} bodyClassName="px-4 py-3">
          <ul className="space-y-2">
            {CLASSES.map((k) => (
              <li key={k} className="flex items-start justify-between gap-3">
                <div>
                  <StatusBadge tone={CLASS_TONE[k]}>
                    {t(`truth.validation.classNames.${k}`)}
                  </StatusBadge>
                  <div className="mt-0.5 text-caption text-subtle-foreground">
                    {t(`truth.validation.classHints.${k}`)}
                  </div>
                </div>
                <span className="numeric text-sm">{localInt(s.classes[k] ?? 0)}</span>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title={t("truth.validation.rules")} bodyClassName="px-4 py-3">
          <ul className="space-y-1.5 text-xs">
            {Object.entries(s.failed)
              .sort((a, b) => b[1] - a[1])
              .map(([rule, n]) => (
                <li key={rule} className="flex justify-between gap-3">
                  <span className="text-muted-foreground">
                    {translateOr(`truth.validation.ruleNames.${rule}`, rule)}
                  </span>
                  <span className="numeric">{localInt(n)}</span>
                </li>
              ))}
          </ul>
        </Panel>
        <Panel title={t("truth.validation.segments")} bodyClassName="px-4 py-3">
          <ul className="space-y-1.5 text-xs">
            {Object.entries(s.approved_by_segment)
              .sort((a, b) => b[1] - a[1])
              .map(([seg, n]) => (
                <li key={seg} className="flex justify-between gap-3">
                  <span className="text-muted-foreground">
                    {translateOr(`truth.validation.segmentNames.${seg}`, seg)}
                  </span>
                  <span className="numeric">{localInt(n)}</span>
                </li>
              ))}
          </ul>
        </Panel>
      </div>
      <Competitions />
      <Quarantine />
    </div>
  );
}

function Competitions() {
  const [klass, setKlass] = useState<DataClass | "">("");
  const [search, setSearch] = useState("");
  const [current, setCurrent] = useState(true);
  const [tracked, setTracked] = useState(true);
  const query: ScoresQuery = { current, tracked, limit: 500 };
  if (klass) query.class = klass;
  if (search.trim().length >= 2) query.q = search.trim();
  const q = useQuery({ ...live.competitionScores(query) });
  const rows = q.data?.data ?? [];
  return (
    <Panel
      title={t("truth.validation.competitions")}
      subtitle={t("truth.validation.competitionsSubtitle")}
      bodyClassName=""
    >
      <FilterBar className="m-3">
        <SelectFilter
          label={t("truth.validation.filters.class")}
          value={klass}
          options={[
            { value: "", label: t("truth.validation.filters.all") },
            ...CLASSES.map((k) => ({ value: k, label: t(`truth.validation.classNames.${k}`) })),
          ]}
          onChange={(v) => setKlass(v as DataClass | "")}
        />
        <SearchFilter
          label={t("truth.validation.filters.search")}
          value={search}
          onChange={setSearch}
        />
        <ToggleFilter
          label={t("truth.validation.filters.current")}
          checked={current}
          onChange={setCurrent}
        />
        <ToggleFilter
          label={t("truth.validation.filters.tracked")}
          checked={tracked}
          onChange={setTracked}
        />
      </FilterBar>
      {q.isPending ? (
        <TableSkeleton rows={10} cols={9} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title={q.data?.reason ?? t("common.noData")} />
      ) : (
        <LimitedRows rows={rows} step={30}>
          {(shown) => (
            <TableShell>
              <THead>
                <TH>{t("truth.validation.col.competition")}</TH>
                <TH>{t("truth.validation.col.class")}</TH>
                <TH align="right">{t("truth.validation.col.score")}</TH>
                <TH align="right">{t("truth.validation.col.finished")}</TH>
                <TH align="right">{t("truth.validation.col.approved")}</TH>
                <TH align="right">{t("truth.validation.col.quarantined")}</TH>
                <TH align="right">{t("truth.validation.col.results")}</TH>
                <TH align="right">{t("truth.validation.col.stats")}</TH>
                <TH align="right">{t("truth.validation.col.odds")}</TH>
                <TH align="right">{t("truth.validation.col.elo")}</TH>
                <TH>{t("truth.validation.col.why")}</TH>
              </THead>
              <tbody>
                {shown.map((r) => (
                  <TRow key={r.competition_season_id}>
                    <TD>
                      <div className="text-sm">{r.competition}</div>
                      <div className="text-caption text-subtle-foreground">
                        {r.country ?? ""} · {r.season} ·{" "}
                        {translateOr(`truth.validation.segmentNames.${r.segment}`, r.segment)}
                      </div>
                    </TD>
                    <TD>
                      <StatusBadge tone={CLASS_TONE[r.data_class]}>
                        {t(`truth.validation.classNames.${r.data_class}`)}
                      </StatusBadge>
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {pct(r.score)}
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {localInt(r.finished)}
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {localInt(r.approved)}
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {localInt(r.quarantined)}
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {pct(r.components["results"])}
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {pct(r.components["stats"])}
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {pct(r.components["odds"])}
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {pct(r.components["elo"])}
                    </TD>
                    <TD className="max-w-xs text-xs text-muted-foreground">{why(r)}</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </LimitedRows>
      )}
    </Panel>
  );
}

function Quarantine() {
  const q = useQuery({ ...live.quarantine });
  const rows = q.data?.data ?? [];
  return (
    <Panel
      title={t("truth.validation.quarantine")}
      subtitle={t("truth.validation.quarantineSubtitle")}
      bodyClassName=""
    >
      {q.isPending ? (
        <TableSkeleton rows={6} cols={4} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title={q.data?.reason ?? t("common.noData")} />
      ) : (
        <LimitedRows rows={rows} step={20}>
          {(shown) => (
            <TableShell>
              <THead>
                <TH>{t("truth.validation.col.kickoff")}</TH>
                <TH>{t("truth.validation.col.match")}</TH>
                <TH>{t("truth.validation.col.competition")}</TH>
                <TH>{t("truth.validation.col.rules")}</TH>
              </THead>
              <tbody>
                {shown.map((r) => (
                  <TRow key={r.fixture_id}>
                    <TD className="text-xs text-muted-foreground">
                      {formatDateTime(r.kickoff_at)}
                    </TD>
                    <TD className="text-sm">
                      {r.home} – {r.away}
                      <div className="text-caption text-subtle-foreground">
                        #{r.provider_fixture_id} · {r.status_short}
                      </div>
                    </TD>
                    <TD className="text-xs">
                      {r.competition} · {r.season}
                    </TD>
                    <TD className="max-w-sm text-xs text-muted-foreground">
                      {r.failed
                        .map((f) => translateOr(`truth.validation.ruleNames.${f}`, f))
                        .join(" · ")}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </LimitedRows>
      )}
    </Panel>
  );
}

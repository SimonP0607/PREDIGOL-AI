/**
 * Data truth: the provider against the database (the last audit), how current every
 * dataset is (measured now), every league table, the model data gate, the findings
 * and every repair applied to stored data. Read-only: the audit itself runs as
 * `python -m scripts.truth_audit` on the machine.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
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
import { SegmentedTabs, SelectFilter } from "@/components/system/Filters";
import { SeverityBadge } from "@/components/system/Timelines";
import { live } from "@/lib/api/v1/queries";
import type {
  FindingKind,
  FreshnessDataset,
  FreshnessState,
  GateReport,
  Severity,
  TruthMatrixRow,
  TruthSummary,
} from "@/lib/api/v1/types_truth";
import { t, translateOr } from "@/lib/i18n";
import { localInt, localPct } from "@/lib/i18n/format";
import { formatDateTime, formatRelative } from "@/lib/time";
import { EmptyState, ErrorState } from "@/product/shared/States";

const TABS = ["matrix", "freshness", "standings", "gate", "findings", "repairs", "runs"] as const;
type Tab = (typeof TABS)[number];
const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
const KINDS: FindingKind[] = [
  "mismatch",
  "missing_in_db",
  "missing_in_api",
  "not_stored",
  "stale",
  "provider_lag",
  "inconsistent",
];

const STATE_TONE: Record<FreshnessState, BadgeTone> = {
  FRESH: "positive",
  STALE: "negative",
  UNKNOWN: "neutral",
  UNAVAILABLE: "info",
};

function datasetName(name: string): string {
  return translateOr(`truth.datasets.${name}`, name);
}

function StateBadge({ state }: { state: FreshnessState | null | undefined }) {
  if (!state) return <span className="text-xs text-subtle-foreground">—</span>;
  return <StatusBadge tone={STATE_TONE[state]}>{t(`truth.state.${state}`)}</StatusBadge>;
}

function Sev({ severity }: { severity: Severity | null | undefined }) {
  if (!severity) return <span className="text-xs text-subtle-foreground">—</span>;
  if (severity === "info") return <StatusBadge tone="neutral">info</StatusBadge>;
  return <SeverityBadge severity={severity} />;
}

/** "FRESH 87 % · STALE 12 %" in the reader's language, from the counts. */
function shareLabel(counts: Partial<Record<FreshnessState, number>> | undefined): string {
  const order: FreshnessState[] = ["STALE", "UNKNOWN", "UNAVAILABLE", "FRESH"];
  const total = order.reduce((s, k) => s + (counts?.[k] ?? 0), 0);
  if (!counts || total === 0) return "—";
  return order
    .filter((k) => (counts[k] ?? 0) > 0)
    .map((k) => {
      const n = counts[k] ?? 0;
      // a handful out of thousands rounds to 0 %: say how many instead of a misleading zero
      const share = n / total < 0.005 ? localInt(n) : localPct(n / total, 0);
      return `${t(`truth.state.${k}`)} ${share}`;
    })
    .join(" · ");
}

function sideText(
  side: { key?: string; params?: Record<string, number> } | undefined,
  fallback: string,
): string {
  if (!side?.key) return fallback;
  const vars = Object.fromEntries(
    Object.entries(side.params ?? {}).map(([k, v]) => [k, typeof v === "number" ? localInt(v) : v]),
  );
  return translateOr(`truth.sides.${side.key}`, fallback, vars);
}

function differenceText(row: TruthMatrixRow): string {
  const kinds = Object.entries(row.by_kind ?? {}).sort((a, b) => b[1] - a[1]);
  if (kinds.length === 0) {
    return row.checked
      ? t("truth.matrix.noDifference")
      : row.difference || t("truth.matrix.notCompared");
  }
  return kinds.map(([k, n]) => `${localInt(n)} ${translateOr(`truth.kinds.${k}`, k)}`).join(", ");
}

function safeText(row: TruthMatrixRow): { text: string; tone: BadgeTone } {
  const code = row.safe_code;
  if (!code) return { text: row.model_safe, tone: "neutral" };
  const tone: BadgeTone =
    code === "no"
      ? "negative"
      : code === "partial"
        ? "warning"
        : code === "na"
          ? "neutral"
          : "positive";
  const reasons = (row.safe_reasons ?? []).map((r) => translateOr(`truth.safeReason.${r}`, r));
  return {
    text: t(`truth.safe.${code}`) + (reasons.length ? ` — ${reasons.join(", ")}` : ""),
    tone,
  };
}

export function DataTruthPage() {
  const [tab, setTab] = useState<Tab>("matrix");
  const latest = useQuery({ ...live.truthLatest });
  const fresh = useQuery({ ...live.freshness });
  const gate = useQuery({ ...live.gate(72) });
  const summary = latest.data?.data ?? null;

  const serious = summary
    ? (summary.run.by_severity.critical ?? 0) + (summary.run.by_severity.high ?? 0)
    : null;
  const datasets = fresh.data?.data?.datasets ?? [];
  const freshCount = datasets.filter((d) => d.status === "FRESH").length;
  const baseline = gate.data?.data?.models.find((m) => m.model === "market_baseline");

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: t("admin.groups.system") }, { label: t("truth.breadcrumb") }]}
        title={t("truth.title")}
        description={t("truth.description")}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label={t("truth.cards.lastAudit")}
          value={summary ? formatRelative(summary.run.finished_at ?? summary.run.started_at) : "—"}
          hint={
            summary
              ? t("truth.cards.lastAuditHint", {
                  id: summary.run.id,
                  requests: localInt(summary.run.requests),
                })
              : t("truth.noAudit")
          }
        />
        <MetricCard
          label={t("truth.cards.serious")}
          value={serious === null ? "—" : localInt(serious)}
          hint={
            summary ? t("truth.cards.seriousHint", { total: localInt(summary.run.findings) }) : ""
          }
          tone={serious ? "negative" : "default"}
        />
        <MetricCard
          label={t("truth.cards.fresh")}
          value={datasets.length ? `${freshCount} / ${datasets.length}` : "—"}
          hint={t("truth.cards.freshHint")}
          tone={datasets.length && freshCount < datasets.length ? "warning" : "default"}
        />
        <MetricCard
          label={t("truth.cards.gate")}
          value={baseline ? localInt(baseline.passing) : "—"}
          hint={
            baseline && gate.data?.data
              ? t("truth.cards.gateHint", {
                  pass: localInt(baseline.passing),
                  total: localInt(gate.data.data.fixtures),
                  hours: gate.data.data.horizon_hours,
                })
              : ""
          }
        />
      </div>

      <SegmentedTabs
        tabs={TABS}
        value={tab}
        onChange={setTab}
        label={t("truth.title")}
        format={(v) => t(`truth.tabs.${v}`)}
      />

      {tab === "matrix" ? (
        <MatrixTab summary={summary} loading={latest.isPending} error={latest.error} />
      ) : null}
      {tab === "freshness" ? (
        <FreshnessTab
          datasets={datasets}
          measuredAt={fresh.data?.data?.measured_at ?? null}
          loading={fresh.isPending}
          error={fresh.error}
        />
      ) : null}
      {tab === "standings" ? <StandingsTab /> : null}
      {tab === "gate" ? (
        <GateTab report={gate.data?.data ?? null} loading={gate.isPending} error={gate.error} />
      ) : null}
      {tab === "findings" ? <FindingsTab summary={summary} /> : null}
      {tab === "repairs" ? <RepairsTab /> : null}
      {tab === "runs" ? <RunsTab /> : null}
    </div>
  );
}

function MatrixTab({
  summary,
  loading,
  error,
}: {
  summary: TruthSummary | null;
  loading: boolean;
  error: unknown;
}) {
  if (loading) return <TableSkeleton rows={10} cols={6} />;
  if (error) return <ErrorState error={error} />;
  if (!summary) return <EmptyState title={t("truth.noAudit")} />;
  return (
    <Panel
      title={t("truth.matrix.title")}
      subtitle={t("truth.matrix.subtitle", {
        id: summary.run.id,
        date: formatDateTime(summary.run.started_at),
      })}
      bodyClassName=""
    >
      <TableShell>
        <THead>
          <TH>{t("truth.matrix.dataset")}</TH>
          <TH>{t("truth.matrix.api")}</TH>
          <TH>{t("truth.matrix.db")}</TH>
          <TH>{t("truth.matrix.difference")}</TH>
          <TH>{t("truth.matrix.freshness")}</TH>
          <TH>{t("truth.matrix.safe")}</TH>
        </THead>
        <tbody>
          {summary.matrix.map((row) => {
            const safe = safeText(row);
            return (
              <TRow key={row.dataset}>
                <TD>
                  <div className="text-sm font-medium">{datasetName(row.dataset)}</div>
                  <div className="text-caption text-subtle-foreground">
                    {translateOr(`truth.role.${row.role}`, row.role)}
                  </div>
                </TD>
                <TD className="max-w-[16rem] text-xs text-muted-foreground">
                  {sideText(row.api_key, row.api)}
                </TD>
                <TD className="max-w-[14rem] text-xs text-muted-foreground">
                  {sideText(row.db_key, row.db)}
                </TD>
                <TD className="max-w-[18rem] text-xs">
                  {row.checked ? (
                    <div className="numeric text-caption text-subtle-foreground">
                      {t("truth.matrix.agree", {
                        matched: localInt(row.matched),
                        checked: localInt(row.checked),
                      })}
                    </div>
                  ) : null}
                  <div className="flex items-center gap-1.5">
                    {row.worst ? <Sev severity={row.worst} /> : null}
                    <span>{differenceText(row)}</span>
                  </div>
                </TD>
                <TD className="text-xs">
                  <StateBadge state={row.freshness_status} />
                  <div className="mt-1 text-caption text-subtle-foreground">
                    {row.freshness_counts ? shareLabel(row.freshness_counts) : row.freshness}
                  </div>
                </TD>
                <TD>
                  <StatusBadge tone={safe.tone} dot={false}>
                    {safe.text}
                  </StatusBadge>
                </TD>
              </TRow>
            );
          })}
        </tbody>
      </TableShell>
    </Panel>
  );
}

function FreshnessTab({
  datasets,
  measuredAt,
  loading,
  error,
}: {
  datasets: FreshnessDataset[];
  measuredAt: string | null;
  loading: boolean;
  error: unknown;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (loading) return <TableSkeleton rows={12} cols={4} />;
  if (error) return <ErrorState error={error} />;
  return (
    <Panel
      title={t("truth.freshness.title")}
      subtitle={`${t("truth.freshness.subtitle")} ${measuredAt ? t("truth.freshness.measured", { ago: formatRelative(measuredAt) }) : ""}`}
      bodyClassName=""
    >
      <TableShell>
        <THead>
          <TH>{t("truth.freshness.dataset")}</TH>
          <TH>{t("truth.freshness.status")}</TH>
          <TH>{t("truth.freshness.share")}</TH>
          <TH>{t("truth.freshness.rule")}</TH>
        </THead>
        <tbody>
          {datasets.map((d) => (
            <FreshnessRow
              key={d.dataset}
              d={d}
              open={open === d.dataset}
              onToggle={() => setOpen(open === d.dataset ? null : d.dataset)}
            />
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}

function FreshnessRow({
  d,
  open,
  onToggle,
}: {
  d: FreshnessDataset;
  open: boolean;
  onToggle: () => void;
}) {
  const worst = d.by_competition.filter((c) => (c.STALE ?? 0) + (c.UNKNOWN ?? 0) > 0).slice(0, 12);
  const examples = [...(d.examples.STALE ?? []), ...(d.examples.UNKNOWN ?? [])].slice(0, 8);
  return (
    <>
      <TRow>
        <TD>
          <button
            type="button"
            onClick={onToggle}
            className="text-left text-sm font-medium hover:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            aria-expanded={open}
          >
            {datasetName(d.dataset)}
          </button>
          <div className="text-caption text-subtle-foreground">
            {t("truth.freshness.entities", {
              n: localInt(d.total),
              entity: translateOr(`truth.freshness.entity.${d.entity}`, d.entity),
            })}
          </div>
        </TD>
        <TD>
          <StateBadge state={d.status} />
        </TD>
        <TD className="text-xs text-muted-foreground">{shareLabel(d.counts)}</TD>
        <TD className="max-w-md text-xs text-muted-foreground">
          {translateOr(`truth.freshness.sla.${d.dataset}`, d.sla)}
        </TD>
      </TRow>
      {open && (worst.length > 0 || examples.length > 0) ? (
        <tr className="border-b border-border bg-elevated/40">
          <td colSpan={4} className="px-4 py-3 text-xs">
            {worst.length > 0 ? (
              <div className="mb-2">
                <div className="mb-1 text-label text-subtle-foreground">
                  {t("truth.freshness.worst")}
                </div>
                <ul className="grid gap-x-6 gap-y-0.5 sm:grid-cols-2">
                  {worst.map((c) => (
                    <li key={c.competition} className="flex justify-between gap-3">
                      <span className="truncate">{c.competition}</span>
                      <span className="numeric text-subtle-foreground">{shareLabel(c)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {examples.length > 0 ? (
              <div>
                <div className="mb-1 text-label text-subtle-foreground">
                  {t("truth.freshness.examples")}
                </div>
                <ul className="space-y-0.5 font-mono text-[11px] text-muted-foreground">
                  {examples.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </td>
        </tr>
      ) : null}
    </>
  );
}

function StandingsTab() {
  const q = useQuery({ ...live.standingsAudit });
  const rows = q.data?.data ?? [];
  if (q.isPending) return <TableSkeleton rows={12} cols={8} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (rows.length === 0) return <EmptyState title={q.data?.reason ?? t("common.noData")} />;
  return (
    <Panel
      title={t("truth.standings.title")}
      subtitle={t("truth.standings.subtitle")}
      bodyClassName=""
    >
      <LimitedRows rows={rows} step={40}>
        {(shown) => (
          <TableShell>
            <THead>
              <TH>{t("truth.standings.competition")}</TH>
              <TH>{t("truth.standings.status")}</TH>
              <TH>{t("truth.standings.reason")}</TH>
              <TH>{t("truth.standings.snapshot")}</TH>
              <TH>{t("truth.standings.checked")}</TH>
              <TH>{t("truth.standings.lastMatch")}</TH>
              <TH align="right">{t("truth.standings.rows")}</TH>
              <TH>{t("truth.standings.extended")}</TH>
            </THead>
            <tbody>
              {shown.map((r) => (
                <TRow key={`${r.competition_id}-${r.season}`}>
                  <TD>
                    <div className="text-sm">{r.competition}</div>
                    <div className="text-caption text-subtle-foreground">
                      {r.country ?? ""} · {r.season}
                      {r.groups > 1
                        ? ` · ${r.groups} ${t("truth.standings.groups").toLowerCase()}`
                        : ""}
                    </div>
                  </TD>
                  <TD>
                    <StateBadge state={r.status} />
                  </TD>
                  <TD className="max-w-xs text-xs text-muted-foreground">
                    {translateOr(`truth.standings.reasons.${r.reason_code}`, r.reason)}
                  </TD>
                  <TD className="text-xs text-muted-foreground">
                    {r.snapshot_at ? formatRelative(r.snapshot_at) : "—"}
                  </TD>
                  <TD className="text-xs text-muted-foreground">
                    {r.checked_at ? formatRelative(r.checked_at) : "—"}
                  </TD>
                  <TD className="text-xs text-muted-foreground">
                    {r.last_finished_at ? formatDateTime(r.last_finished_at) : "—"}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(r.rows)}
                    {r.rows_skipped ? (
                      <div className="text-caption text-warning">
                        {t("truth.standings.skipped", { n: localInt(r.rows_skipped) })}
                      </div>
                    ) : null}
                  </TD>
                  <TD className="text-xs">
                    {r.extended ? t("truth.standings.yes") : t("truth.standings.no")}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </LimitedRows>
    </Panel>
  );
}

function GateTab({
  report,
  loading,
  error,
}: {
  report: GateReport | null;
  loading: boolean;
  error: unknown;
}) {
  if (loading) return <TableSkeleton rows={6} cols={4} />;
  if (error) return <ErrorState error={error} />;
  if (!report) return <EmptyState title={t("common.noData")} />;
  const models = report.models.map((m) => m.model);
  return (
    <div className="space-y-4">
      <Panel
        title={t("truth.gate.title")}
        subtitle={t("truth.gate.subtitle", {
          hours: report.horizon_hours,
          n: localInt(report.fixtures),
        })}
        bodyClassName=""
      >
        <TableShell>
          <THead>
            <TH>{t("truth.gate.model")}</TH>
            <TH align="right">{t("truth.gate.pass")}</TH>
            <TH align="right">{t("truth.gate.blocked")}</TH>
            <TH>{t("truth.gate.blockedBy")}</TH>
            <TH>{t("truth.gate.needs")}</TH>
          </THead>
          <tbody>
            {report.models.map((m) => (
              <TRow key={m.model}>
                <TD className="text-sm font-medium">
                  {translateOr(`truth.gate.models.${m.model}`, m.model)}
                </TD>
                <TD align="right" className="numeric text-positive">
                  {localInt(m.passing)}
                </TD>
                <TD align="right" className="numeric text-negative">
                  {localInt(m.blocked)}
                </TD>
                <TD className="text-xs text-muted-foreground">
                  {Object.entries(m.blocked_by)
                    .map(([d, n]) => `${datasetName(d)} ${localInt(n)}`)
                    .join(" · ") || "—"}
                </TD>
                <TD className="text-xs text-muted-foreground">
                  {Object.entries(m.needs)
                    .map(
                      ([d, need]) =>
                        `${datasetName(d)} (${translateOr(`truth.role.${need}`, need)})`,
                    )
                    .join(", ")}
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>
      <Panel title={t("truth.gate.fixtures")} bodyClassName="">
        <LimitedRows rows={report.sample} step={30}>
          {(shown) => (
            <TableShell>
              <THead>
                <TH>{t("truth.gate.kickoff")}</TH>
                <TH>{t("truth.gate.competition")}</TH>
                {models.map((m) => (
                  <TH key={m}>{translateOr(`truth.gate.models.${m}`, m)}</TH>
                ))}
                <TH>{t("truth.gate.why")}</TH>
              </THead>
              <tbody>
                {shown.map((g) => {
                  const why = Object.entries(g.datasets)
                    .filter(([, v]) => v.state !== "ok")
                    .map(
                      ([d, v]) =>
                        `${datasetName(d)}: ${translateOr(`truth.gate.states.${v.state}`, v.state)}${v.why ? ` (${v.why})` : ""}`,
                    );
                  return (
                    <TRow key={g.provider_fixture_id}>
                      <TD className="text-xs">{formatDateTime(g.kickoff_at)}</TD>
                      <TD className="text-xs">{g.competition}</TD>
                      {models.map((m) => (
                        <TD key={m}>
                          {g.models[m] ? (
                            <StatusBadge tone="positive">{t("truth.gate.states.ok")}</StatusBadge>
                          ) : (
                            <StatusBadge tone="negative">{t("truth.gate.blocked")}</StatusBadge>
                          )}
                        </TD>
                      ))}
                      <TD className="max-w-md text-xs text-muted-foreground">
                        {why.join(" · ") || "—"}
                      </TD>
                    </TRow>
                  );
                })}
              </tbody>
            </TableShell>
          )}
        </LimitedRows>
      </Panel>
    </div>
  );
}

const PAGE = 100;

function FindingsTab({ summary }: { summary: TruthSummary | null }) {
  const [dataset, setDataset] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [kind, setKind] = useState("all");
  const [offset, setOffset] = useState(0);
  const runId = summary?.run.id ?? 0;
  const query = useMemo(
    () => ({
      dataset: dataset === "all" ? undefined : dataset,
      severity: severity === "all" ? undefined : (severity as Severity),
      kind: kind === "all" ? undefined : (kind as FindingKind),
      limit: PAGE,
      offset,
    }),
    [dataset, severity, kind, offset],
  );
  const q = useQuery({ ...live.truthFindings(runId, query) });
  if (!summary) return <EmptyState title={t("truth.noAudit")} />;
  const total = q.data?.meta?.total ?? 0;
  const rows = q.data?.data ?? [];
  const datasets = Object.keys(summary.datasets).sort();
  const reset = (f: () => void) => {
    f();
    setOffset(0);
  };
  return (
    <Panel title={t("truth.findings.title", { id: summary.run.id })} bodyClassName="">
      <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-3">
        <SelectFilter
          label={t("truth.findings.dataset")}
          value={dataset}
          onChange={(v) => reset(() => setDataset(v))}
          options={[
            { value: "all", label: t("truth.findings.all") },
            ...datasets.map((d) => ({ value: d, label: datasetName(d) })),
          ]}
        />
        <SelectFilter
          label={t("truth.findings.severity")}
          value={severity}
          onChange={(v) => reset(() => setSeverity(v))}
          options={[
            { value: "all", label: t("truth.findings.all") },
            ...SEVERITIES.map((s) => ({
              value: s,
              label: translateOr(`admin.status.severity.${s}`, s),
            })),
          ]}
        />
        <SelectFilter
          label={t("truth.findings.kind")}
          value={kind}
          onChange={(v) => reset(() => setKind(v))}
          options={[
            { value: "all", label: t("truth.findings.all") },
            ...KINDS.map((k) => ({ value: k, label: t(`truth.kinds.${k}`) })),
          ]}
        />
        <span className="numeric ml-auto text-caption text-subtle-foreground">
          {t("truth.findings.total", { n: localInt(total) })}
        </span>
      </div>
      {q.isPending ? (
        <TableSkeleton rows={10} cols={6} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title={q.data?.reason ?? t("common.noData")} />
      ) : (
        <>
          <TableShell>
            <THead>
              <TH>{t("truth.findings.severity")}</TH>
              <TH>{t("truth.findings.dataset")}</TH>
              <TH>{t("truth.findings.entity")}</TH>
              <TH>{t("truth.findings.field")}</TH>
              <TH>{t("truth.findings.api")}</TH>
              <TH>{t("truth.findings.db")}</TH>
            </THead>
            <tbody>
              {rows.map((f) => (
                <TRow key={f.id}>
                  <TD>
                    <Sev severity={f.severity} />
                    <div className="mt-1 text-caption text-subtle-foreground">
                      {t(`truth.kinds.${f.kind}`)}
                    </div>
                  </TD>
                  <TD className="text-xs">{datasetName(f.dataset)}</TD>
                  <TD className="max-w-[16rem] text-xs">
                    <div>{f.entity}</div>
                    {f.note ? (
                      <div
                        className="mt-0.5 text-caption text-subtle-foreground"
                        title={t("truth.findings.note")}
                      >
                        {f.note}
                      </div>
                    ) : null}
                  </TD>
                  <TD className="text-xs text-muted-foreground">{f.field}</TD>
                  <TD className="max-w-[12rem] break-words font-mono text-[11px]">
                    {f.api_value ?? "—"}
                  </TD>
                  <TD className="max-w-[12rem] break-words font-mono text-[11px]">
                    {f.db_value ?? "—"}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
          <div className="flex items-center justify-center gap-3 border-t border-border px-4 py-2.5 text-xs">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
              className="rounded-md border border-border px-2.5 py-1 disabled:opacity-40"
            >
              {t("truth.findings.prev")}
            </button>
            <span className="numeric text-subtle-foreground">
              {t("truth.findings.page", {
                from: localInt(offset + 1),
                to: localInt(Math.min(offset + PAGE, total)),
                total: localInt(total),
              })}
            </span>
            <button
              type="button"
              disabled={offset + PAGE >= total}
              onClick={() => setOffset(offset + PAGE)}
              className="rounded-md border border-border px-2.5 py-1 disabled:opacity-40"
            >
              {t("truth.findings.next")}
            </button>
          </div>
        </>
      )}
    </Panel>
  );
}

function RepairsTab() {
  const q = useQuery({ ...live.repairs });
  const rows = q.data?.data ?? [];
  if (q.isPending) return <TableSkeleton rows={8} cols={6} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (rows.length === 0) return <EmptyState title={q.data?.reason ?? t("common.noData")} />;
  return (
    <Panel title={t("truth.repairs.title")} subtitle={t("truth.repairs.subtitle")} bodyClassName="">
      <LimitedRows rows={rows} step={50}>
        {(shown) => (
          <TableShell>
            <THead>
              <TH>{t("truth.repairs.when")}</TH>
              <TH>{t("truth.repairs.rule")}</TH>
              <TH>{t("truth.repairs.entity")}</TH>
              <TH>{t("truth.repairs.before")}</TH>
              <TH>{t("truth.repairs.after")}</TH>
            </THead>
            <tbody>
              {shown.map((r) => (
                <TRow key={r.id}>
                  <TD className="text-xs">{formatDateTime(r.repaired_at)}</TD>
                  <TD className="text-xs">
                    <div>{translateOr(`truth.repairs.rules.${r.rule}`, r.rule)}</div>
                    <div className="text-caption text-subtle-foreground">{r.reason}</div>
                  </TD>
                  <TD className="font-mono text-[11px]">
                    {r.entity} {r.provider_ref ?? r.entity_id}
                  </TD>
                  <TD className="font-mono text-[11px] text-negative">{r.before_value ?? "—"}</TD>
                  <TD className="font-mono text-[11px] text-positive">{r.after_value ?? "—"}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </LimitedRows>
    </Panel>
  );
}

function RunsTab() {
  const q = useQuery({ ...live.truthRuns });
  const rows = q.data?.data ?? [];
  if (q.isPending) return <TableSkeleton rows={5} cols={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (rows.length === 0) return <EmptyState title={t("truth.noAudit")} />;
  return (
    <Panel title={t("truth.runs.title")} bodyClassName="">
      <TableShell>
        <THead>
          <TH>{t("truth.runs.id")}</TH>
          <TH>{t("truth.runs.started")}</TH>
          <TH>{t("truth.runs.status")}</TH>
          <TH align="right">{t("truth.runs.requests")}</TH>
          <TH>{t("truth.runs.findings")}</TH>
        </THead>
        <tbody>
          {rows.map((r) => (
            <TRow key={r.id}>
              <TD className="numeric text-xs">#{r.id}</TD>
              <TD className="text-xs">{formatDateTime(r.started_at)}</TD>
              <TD className="text-xs">{r.status}</TD>
              <TD align="right" className="numeric text-xs">
                {localInt(r.requests)}
              </TD>
              <TD className="text-xs">
                {SEVERITIES.filter((s) => r.by_severity[s])
                  .map(
                    (s) =>
                      `${localInt(r.by_severity[s] ?? 0)} ${translateOr(`admin.status.severity.${s}`, s)}`,
                  )
                  .join(" · ") || "—"}
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}

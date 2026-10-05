/**
 * The AI layer in the Admin Console (GATE H): whether it is configured and what it cost this
 * month, the daily research report with its graded claims, the pick reviewer's flags, and the
 * record of every run. Flags and claims are information for the owner: nothing here can change
 * a probability, a price or a pick.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { t } from "@/lib/i18n";
import { localFixed, localInt } from "@/lib/i18n/format";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { SegmentedTabs } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, StatusNotice } from "@/components/system/LiveState";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type {
  AiClaimRow,
  AiFlagRow,
  AiRunRow,
  AiStatus,
  ClaimGrade,
  FlagSeverity,
  SetSource,
} from "@/lib/api/v1/types_ai";
import { Markdown } from "./Markdown";
import { utcDateTime } from "./format";

const GRADE_TONE: Record<ClaimGrade, BadgeTone> = {
  CONFIRMED: "positive",
  REPORTED: "info",
  RUMOR: "warning",
};
const SEVERITY_TONE: Record<FlagSeverity, BadgeTone> = {
  info: "info",
  warn: "warning",
  review: "negative",
};
const RUN_TONE: Record<string, BadgeTone> = {
  ok: "positive",
  running: "info",
  failed: "negative",
  not_configured: "neutral",
  over_budget: "warning",
};

function usd(v: string | number): string {
  const n = Number(v);
  return Number.isFinite(n) ? `${localFixed(n, n < 1 ? 4 : 2)} USD` : "—";
}

/** Compact: two decimals, more only for a non-zero amount under a cent. */
function money(n: number): string {
  return localFixed(n, n > 0 && n < 0.01 ? 4 : 2);
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function AiStatusStrip({ status }: { status: AiStatus }) {
  const spent = Number(status.budget.spent_usd);
  const cap = Number(status.budget.cap_usd);
  const share = cap > 0 ? Math.min(1, spent / cap) : 0;
  return (
    <div className="space-y-3" data-testid="ai-status">
      {!status.llm_configured || !status.search_configured ? (
        <WarningBanner>
          {t("ai.status.notConfigured", { missing: status.missing.join(", ") })}
        </WarningBanner>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Panel bodyClassName="p-3">
          <KeyValue
            label={t("ai.status.llm")}
            value={
              <StatusBadge tone={status.llm_configured ? "positive" : "neutral"}>
                {status.llm_configured ? (status.model ?? t("ai.status.on")) : t("ai.status.off")}
              </StatusBadge>
            }
          />
        </Panel>
        <Panel bodyClassName="p-3">
          <KeyValue
            label={t("ai.status.search")}
            value={
              <StatusBadge tone={status.search_configured ? "positive" : "neutral"}>
                {status.search_configured ? t("ai.status.on") : t("ai.status.off")}
              </StatusBadge>
            }
          />
        </Panel>
        <Panel bodyClassName="p-3">
          <KeyValue
            label={t("ai.status.budget", { month: status.budget.month })}
            value={
              <Numeric className="text-xs">
                {t("ai.status.spent", { spent: money(spent), cap: money(cap) })}
              </Numeric>
            }
          />
          <div
            className="mt-2 h-1.5 overflow-hidden rounded bg-muted"
            role="meter"
            aria-valuemin={0}
            aria-valuemax={cap}
            aria-valuenow={spent}
            aria-label={t("ai.status.budget", { month: status.budget.month })}
          >
            <div
              className={share >= 0.8 ? "h-full bg-warning" : "h-full bg-primary"}
              style={{ width: `${share * 100}%` }}
            />
          </div>
        </Panel>
        <Panel bodyClassName="p-3">
          <KeyValue
            label={t("ai.status.questions")}
            value={
              <Numeric>
                {localInt(status.questions_today)} / {localInt(status.questions_per_day)}
              </Numeric>
            }
          />
        </Panel>
      </div>
    </div>
  );
}

function ClaimsTable({ claims }: { claims: AiClaimRow[] }) {
  return (
    <TableShell>
      <THead>
        <TH>{t("ai.report.cols.claim")}</TH>
        <TH>{t("ai.report.cols.grade")}</TH>
        <TH>{t("ai.report.cols.source")}</TH>
        <TH>{t("ai.report.cols.published")}</TH>
        <TH>{t("ai.report.cols.retrieved")}</TH>
      </THead>
      <tbody>
        {claims.map((c) => (
          <TRow key={c.id}>
            <TD className="max-w-md text-sm">{c.claim}</TD>
            <TD>
              <StatusBadge tone={GRADE_TONE[c.confidence]}>
                <span data-testid="claim-grade">{t(`ai.grade.${c.confidence}`)}</span>
              </StatusBadge>
            </TD>
            <TD className="text-xs">
              <a
                href={c.source_url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                {c.publisher ?? host(c.source_url)}
                <ExternalLink aria-hidden className="h-3 w-3" />
              </a>
              {c.also_urls.length ? (
                <span className="ml-1 text-caption text-subtle-foreground">
                  +{c.also_urls.map(host).join(", ")}
                </span>
              ) : null}
            </TD>
            <TD className="text-caption text-muted-foreground">
              {c.published_at ? utcDateTime(c.published_at) : t("ai.report.noDate")}
            </TD>
            <TD className="text-caption text-muted-foreground">{utcDateTime(c.retrieved_at)}</TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

export function ReportTab() {
  const [day, setDay] = useState("");
  const report = useLiveQuery(live.aiReport(day));
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: () => v1.aiReportRun(day || undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v1", "ai"] }),
  });
  const r = report.data?.data ?? null;
  return (
    <Panel
      title={t("ai.report.title")}
      subtitle={t("ai.report.subtitle")}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1 text-caption text-subtle-foreground">
            {t("ai.report.day")}
            <input
              type="date"
              value={day}
              onChange={(e) => setDay(e.target.value)}
              className="h-7 rounded-md border border-border bg-card px-1.5 text-xs text-foreground"
            />
          </label>
          <button
            type="button"
            onClick={() => run.mutate()}
            disabled={run.isPending}
            data-testid="ai-report-run"
            className="h-7 rounded-md border border-border px-2.5 text-xs hover:bg-elevated disabled:opacity-50"
          >
            {run.isPending ? t("ai.report.running") : t("ai.report.run")}
          </button>
        </div>
      }
      bodyClassName="p-4 space-y-4"
    >
      {report.isError ? <ApiErrorNotice error={report.error} /> : null}
      {run.isError ? <ApiErrorNotice error={run.error} /> : null}
      {report.isLoading ? <TableSkeleton rows={4} cols={3} /> : null}
      {report.data && report.data.status !== "ok" ? (
        <StatusNotice
          status={report.data.status}
          reason={report.data.status === "empty" ? t("ai.report.notYet") : report.data.reason}
          compact
        />
      ) : null}
      {r ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
            <StatusBadge tone={RUN_TONE[r.run_status] ?? "neutral"}>
              {t(`ai.runStatus.${r.run_status}`)}
            </StatusBadge>
            <span>
              {t("ai.report.meta", {
                when: utcDateTime(r.created_at),
                model: r.model ?? "—",
                cost: usd(r.cost_usd),
              })}
            </span>
          </div>
          <div data-testid="ai-report">
            <Markdown text={r.markdown} />
          </div>
          <div className="space-y-2">
            <p className="text-xs font-semibold">{t("ai.report.claims")}</p>
            <p className="text-caption text-subtle-foreground">{t("ai.grade.help")}</p>
            {r.claims.length ? (
              <ClaimsTable claims={r.claims} />
            ) : (
              <p className="text-caption text-subtle-foreground">{t("ai.report.noClaims")}</p>
            )}
          </div>
        </>
      ) : null}
    </Panel>
  );
}

function FlagLine({ f }: { f: AiFlagRow }) {
  return (
    <li className="flex flex-col gap-1 rounded-md border border-border p-2.5 sm:flex-row sm:items-start sm:gap-3">
      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        <StatusBadge tone={SEVERITY_TONE[f.severity]}>
          {t(`ai.flags.severity.${f.severity}`)}
        </StatusBadge>
        <StatusBadge tone="neutral">{t(`ai.flags.code.${f.code}`)}</StatusBadge>
        <StatusBadge tone={f.engine === "model" ? "brand" : "neutral"}>
          {t(`ai.flags.engine.${f.engine}`)}
        </StatusBadge>
      </div>
      <div className="min-w-0 space-y-0.5">
        <p className="text-xs font-medium">
          {f.rank ? t("ai.flags.rank", { rank: f.rank }) : null} · {f.match}
        </p>
        <p className="text-xs text-muted-foreground">{f.note}</p>
        {f.claim_ids.length ? (
          <p className="text-caption text-subtle-foreground">
            {t("ai.flags.claims", { ids: f.claim_ids.map((c) => `#${c}`).join(", ") })}
          </p>
        ) : null}
      </div>
    </li>
  );
}

export function FlagsTab() {
  const [source, setSource] = useState<SetSource>("evaluation");
  const [day, setDay] = useState("");
  const flags = useLiveQuery(live.aiFlags(source, day));
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: () => v1.aiReviewRun(source, day || undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v1", "ai"] }),
  });
  const d = flags.data?.data ?? null;
  return (
    <Panel
      title={t("ai.flags.title")}
      subtitle={t("ai.flags.subtitle")}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={day}
            aria-label={t("ai.report.day")}
            onChange={(e) => setDay(e.target.value)}
            className="h-7 rounded-md border border-border bg-card px-1.5 text-xs text-foreground"
          />
          <button
            type="button"
            onClick={() => run.mutate()}
            disabled={run.isPending}
            className="h-7 rounded-md border border-border px-2.5 text-xs hover:bg-elevated disabled:opacity-50"
          >
            {t("ai.flags.run")}
          </button>
        </div>
      }
      bodyClassName="p-4 space-y-3"
    >
      <SegmentedTabs
        tabs={["evaluation", "qualified"] as const}
        value={source}
        onChange={setSource}
        label={t("ai.flags.sourceLabel")}
        format={(s) => t(`ai.flags.source.${s}`)}
      />
      {flags.isError ? <ApiErrorNotice error={flags.error} /> : null}
      {run.isError ? <ApiErrorNotice error={run.error} /> : null}
      {flags.data && flags.data.status !== "ok" ? (
        <StatusNotice status={flags.data.status} reason={flags.data.reason} compact />
      ) : null}
      {d && d.flags.length ? (
        <ul className="space-y-2" data-testid="ai-flags">
          {d.flags.map((f) => (
            <FlagLine key={f.id} f={f} />
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

function tokens(r: AiRunRow): string {
  return r.input_tokens || r.output_tokens
    ? `${localInt(r.input_tokens)} / ${localInt(r.output_tokens)}`
    : "—";
}

export function UsageTab({ status }: { status: AiStatus | null }) {
  const runs = useLiveQuery(live.aiRuns);
  const rows = runs.data?.data ?? [];
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Panel title={t("ai.usage.title")} subtitle={t("ai.usage.subtitle")} bodyClassName="">
        {runs.isError ? <ApiErrorNotice error={runs.error} className="m-4" /> : null}
        {runs.data && runs.data.status !== "ok" ? (
          <StatusNotice
            status={runs.data.status}
            reason={runs.data.reason}
            compact
            className="m-4"
          />
        ) : null}
        {rows.length ? (
          <TableShell>
            <THead>
              <TH>{t("ai.usage.cols.started")}</TH>
              <TH>{t("ai.usage.cols.kind")}</TH>
              <TH>{t("ai.usage.cols.status")}</TH>
              <TH>{t("ai.usage.cols.model")}</TH>
              <TH align="right">{t("ai.usage.cols.tokens")}</TH>
              <TH align="right">{t("ai.usage.cols.cost")}</TH>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TRow key={r.id}>
                  <TD className="text-caption text-muted-foreground">
                    {utcDateTime(r.started_at)}
                  </TD>
                  <TD className="text-xs">{t(`ai.kind.${r.kind}`)}</TD>
                  <TD>
                    <StatusBadge tone={RUN_TONE[r.status] ?? "neutral"}>
                      {t(`ai.runStatus.${r.status}`)}
                    </StatusBadge>
                    {r.error ? (
                      <p
                        className="mt-1 max-w-xs truncate text-caption text-subtle-foreground"
                        title={r.error}
                      >
                        {r.error}
                      </p>
                    ) : null}
                  </TD>
                  <TD className="text-caption text-muted-foreground">{r.model ?? "—"}</TD>
                  <TD align="right">
                    <Numeric className="text-xs">{tokens(r)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric className="text-xs">{usd(r.cost_usd)}</Numeric>
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        ) : null}
      </Panel>
      <Panel title={t("ai.schedule.title")}>
        <ul className="list-disc space-y-1.5 pl-4 text-xs text-muted-foreground">
          {Object.keys(status?.schedule ?? {}).map((k) => (
            <li key={k}>{t(`ai.schedule.${k}`)}</li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

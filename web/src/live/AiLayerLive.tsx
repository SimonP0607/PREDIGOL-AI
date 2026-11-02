/**
 * La capa de decisión IA (Admin Console): the views of the AI decision layer, as the pages of plan F13 hold them (see adminAi.ts).
 * OPERACIÓN holds the mode, the last cycles and the owner's "run now" (StatusStrip), the reviews with their whole audit trail
 * (ReviewsTab) and the evidence with its sources (EvidenceTab); what it costs is one view with the rest of the AI's costs
 * (AiCosts). APRENDIZAJE holds the experimental comparison - model alone, model + rules, model + AI, market - and the AI's own
 * shadow evaluation (ComparisonPanel, ShadowTab); everything in shadow until the owner's switch AND a passed gate. Its memory is in Memoria.
 */
import { useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { t, translateOr } from "@/lib/i18n";
import { localFixed, localInt } from "@/lib/i18n/format";
import { int } from "@/lib/format";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type {
  AiClaim,
  AiComparisonRow,
  AiDecision,
  AiOverview,
  AiReviewDetail,
  EvidenceStatus,
  ShadowArm,
  ShadowReportRow,
} from "@/lib/api/v1/types_ai_layer";
import { Note } from "./AiBits";
import {
  DECISION_TONE,
  EVIDENCE_TONE,
  fixedText,
  gateTone,
  pct,
  probText,
  sampleCounts,
  signedText,
  toNum,
  usd,
} from "./aiModel";
import { utcDateTime } from "./format";

const DECISIONS: AiDecision[] = ["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"];
const STATUSES: EvidenceStatus[] = ["CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY", "OUTDATED"];
const ARMS = ["model", "model_ai", "approved", "downgraded", "rejected", "abstained"] as const;
const COMPARISON_ARMS = ["model", "model_rules", "model_ai", "market"] as const;
const CLAIM_GROUPS = [
  "positive_evidence",
  "negative_evidence",
  "uncertainties",
  "contradictions",
] as const;
const SELECT =
  "h-8 rounded-md border border-border bg-card px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";
/** The comparison grid: the arm, then nine figures. */
const COMPARE_GRID = "grid grid-cols-[minmax(8.5rem,1.5fr)_repeat(9,minmax(4.25rem,1fr))]";

function percent(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? "—" : `${localFixed(100 * n, digits)} %`;
}

// ── the comparison (model alone, with rules, with AI, market) ──────────────────

function compareCells(r: AiComparisonRow): string[] {
  return [
    int(r.n),
    fixedText(r.logloss, 3),
    fixedText(r.brier, 3),
    probText(r.ece, 1),
    signedText(r.roi, 1),
    signedText(r.clv, 1),
    signedText(r.ev_market, 1),
    probText(r.hit_rate, 1),
    toNum(r.max_drawdown) === null
      ? "—"
      : t("ai.layer.compare.units", { n: fixedText(r.max_drawdown, 2) }),
  ];
}

/**
 * MODELO SOLO / MODELO + REGLAS / MODELO + IA / MERCADO on the same settled selections (shadow). A grid with
 * table semantics: it scrolls inside its own box on a phone.
 */
export function ComparisonPanel() {
  const q = useLiveQuery(live.aiComparison);
  const c = q.data?.data ?? null;
  const rank = (arm: string) => {
    const i = (COMPARISON_ARMS as readonly string[]).indexOf(arm);
    return i < 0 ? COMPARISON_ARMS.length : i;
  };
  const rows = c ? [...c.rows].sort((a, b) => rank(a.arm) - rank(b.arm)) : [];
  const sample = sampleCounts(c?.sample);
  const headers = [
    t("ai.layer.compare.cols.n"),
    t("ai.layer.compare.cols.logloss"),
    t("ai.layer.compare.cols.brier"),
    t("ai.layer.compare.cols.ece"),
    t("ai.layer.compare.cols.roi"),
    t("ai.layer.compare.cols.clv"),
    t("ai.layer.compare.cols.ev"),
    t("ai.layer.shadow.hit"),
    t("ai.layer.shadow.drawdown"),
  ];
  return (
    <Panel
      title={t("ai.layer.compare.title")}
      subtitle={t("ai.layer.compare.subtitle")}
      actions={c?.shadow ? <StatusBadge tone="brand">{t("ai.v2.shadowBadge")}</StatusBadge> : null}
    >
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={4} cols={6} /> : null}
      {c ? (
        <div className="space-y-3" data-testid="ai-comparison">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-subtle-foreground">
            <span>{t("ai.layer.compare.gate")}</span>
            <StatusBadge tone={gateTone(c.verdict)}>
              {translateOr(`ai.layer.gate.${c.verdict ?? "none"}`, c.verdict ?? "—")}
            </StatusBadge>
            {c.window_from && c.window_to ? (
              <span className="numeric">
                {t("ai.layer.shadow.window", { from: c.window_from, to: c.window_to })}
              </span>
            ) : null}
            <span className="numeric">
              {t("ai.layer.compare.sample", {
                selections: int(sample.selections),
                days: int(sample.days),
                rejected: int(sample.rejected),
              })}
            </span>
          </div>
          {rows.every((r) => !r.n) ? <Note>{t("ai.layer.compare.empty")}</Note> : null}
          {rows.length ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <div role="table" aria-label={t("ai.layer.compare.title")} className="min-w-[46rem]">
                <div role="rowgroup">
                  <div role="row" className={`${COMPARE_GRID} border-b border-border bg-card`}>
                    <span
                      role="columnheader"
                      className="px-3 py-2 text-label text-subtle-foreground"
                    >
                      {t("ai.layer.shadow.armLabel")}
                    </span>
                    {headers.map((h) => (
                      <span
                        key={h}
                        role="columnheader"
                        className="px-2 py-2 text-right text-label text-subtle-foreground"
                      >
                        {h}
                      </span>
                    ))}
                  </div>
                </div>
                <div role="rowgroup">
                  {rows.map((r) => (
                    <div
                      key={r.arm}
                      role="row"
                      className={`${COMPARE_GRID} border-b border-border/60 text-xs last:border-0 ${
                        r.arm === "market" ? "bg-elevated/40" : ""
                      }`}
                    >
                      <span role="rowheader" className="px-3 py-2.5 font-medium">
                        {translateOr(`ai.layer.compare.arm.${r.arm}`, r.label)}
                      </span>
                      {compareCells(r).map((v, i) => (
                        <span
                          key={headers[i] ?? i}
                          role="cell"
                          className="numeric px-2 py-2.5 text-right"
                        >
                          {v}
                        </span>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
          <Note>
            {t("ai.layer.compare.marketNote")} {t("ai.layer.compare.evNote")}{" "}
            {t("ai.layer.compare.clvNote")}
          </Note>
        </div>
      ) : null}
    </Panel>
  );
}

// ── status ───────────────────────────────────────────────────────────────────

function RunNow() {
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: (kind: "analysis" | "learning") => v1.requestAiRun({ kind }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["v1", "ai-layer"] }),
  });
  const requests = useLiveQuery(live.aiRunRequests);
  const rows = requests.data?.data ?? [];
  return (
    <Panel title={t("ai.layer.run.title")} subtitle={t("ai.layer.run.subtitle")}>
      <div className="flex flex-wrap gap-2">
        {(["analysis", "learning"] as const).map((k) => (
          <button
            key={k}
            type="button"
            disabled={run.isPending}
            onClick={() => run.mutate(k)}
            className="h-8 rounded-md border border-primary/40 bg-primary/12 px-3 text-xs text-primary disabled:opacity-50"
          >
            {t(`ai.layer.run.${k}`)}
          </button>
        ))}
      </div>
      {run.isError ? <ApiErrorNotice error={run.error} /> : null}
      {rows.length ? (
        <ul
          className="mt-3 space-y-1 text-caption text-subtle-foreground"
          data-testid="ai-run-requests"
        >
          {rows.slice(0, 6).map((r) => (
            <li key={r.id}>
              #{r.id} · {translateOr(`ai.layer.run.${r.kind}`, r.kind)} ·{" "}
              {utcDateTime(r.requested_at)} ·{" "}
              {translateOr(`ai.layer.run.status.${r.status}`, r.status)}
              {r.error ? ` · ${r.error}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

/** A label and a chip that wrap onto two lines on a phone instead of cutting the chip. */
function ChipRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border/60 py-1.5 last:border-0">
      <span className="text-caption uppercase tracking-wider text-subtle-foreground">{label}</span>
      {children}
    </div>
  );
}

/** The mode and whether it filters anything; the last cycles and today's counts; the owner's "run now". */
export function StatusStrip({ o }: { o: AiOverview | null }) {
  return (
    <div className="grid gap-3 lg:grid-cols-3" data-testid="ai-layer-status">
      {o ? (
        <>
          <Panel bodyClassName="p-3 space-y-1">
            <ChipRow label={t("ai.layer.modeLabel")}>
              <StatusBadge tone="info">
                {translateOr(`ai.layer.mode.${o.settings.mode}`, o.settings.mode)}
              </StatusBadge>
            </ChipRow>
            <ChipRow label={t("ai.layer.enforcement")}>
              <StatusBadge tone={o.enforcement.enforced ? "warning" : "neutral"}>
                {o.enforcement.enforced ? t("ai.layer.enforced") : t("ai.layer.notEnforced")}
              </StatusBadge>
            </ChipRow>
            <p className="text-caption text-subtle-foreground">
              {translateOr(
                `ai.layer.enforcementReason.${o.enforcement.reason}`,
                o.enforcement.reason,
              )}
            </p>
            <KeyValue
              label={t("ai.layer.search")}
              value={
                o.settings.search_configured
                  ? (o.settings.search ?? "—")
                  : t("ai.layer.notConfigured")
              }
            />
          </Panel>
          <Panel bodyClassName="p-3 space-y-1">
            {o.last_cycles.length === 0 ? (
              <p className="text-xs text-subtle-foreground">{t("ai.layer.noCycle")}</p>
            ) : (
              o.last_cycles.map((c) => (
                <KeyValue
                  key={c.id}
                  label={translateOr(`ai.layer.cycle.${c.kind}`, c.kind)}
                  value={`${utcDateTime(c.started_at)} · ${translateOr(
                    `ai.layer.cycleStatus.${c.status}`,
                    c.status,
                  )}`}
                />
              ))
            )}
            {Object.entries(o.today).map(([k, v]) => (
              <KeyValue key={k} label={translateOr(`ai.layer.today.${k}`, k)} value={int(v)} />
            ))}
          </Panel>
        </>
      ) : null}
      <RunNow />
    </div>
  );
}

// ── reviews ──────────────────────────────────────────────────────────────────

function ClaimList({ claims }: { claims: AiClaim[] | undefined }) {
  if (!claims || claims.length === 0)
    return <p className="text-caption text-subtle-foreground">—</p>;
  return (
    <ul className="space-y-1">
      {claims.map((c, i) => (
        <li key={i} className="text-xs">
          <StatusBadge
            tone={c.type === "DATA" ? "positive" : c.type === "NEWS" ? "info" : "neutral"}
          >
            {translateOr(`ai.layer.claimType.${c.type}`, c.type)}
          </StatusBadge>{" "}
          {c.text}
          {c.refs && c.refs.length ? (
            <span className="ml-1 text-caption text-subtle-foreground">[{c.refs.join(", ")}]</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function ReviewDetailView({ d }: { d: AiReviewDetail }) {
  const out = d.output;
  return (
    <div className="space-y-3" data-testid="ai-review-detail">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <StatusBadge tone={DECISION_TONE[d.review.decision]}>
          {t(`ai.layer.decision.${d.review.decision}`)}
        </StatusBadge>
        <span className="font-medium">{d.review.match}</span>
        <span className="text-subtle-foreground">
          {d.review.market_key} · {d.review.selection} · {utcDateTime(d.review.reviewed_at)}
        </span>
      </div>
      {out.reason ? <p className="text-sm">{out.reason}</p> : null}
      <div className="grid gap-3 lg:grid-cols-2">
        {CLAIM_GROUPS.map((g) => (
          <div key={g} className="rounded-md border border-border p-2.5">
            <h4 className="mb-1 text-caption uppercase tracking-wider text-subtle-foreground">
              {t(`ai.layer.claims.${g}`)}
            </h4>
            <ClaimList claims={out[g]} />
          </div>
        ))}
      </div>
      {out.rejected_claims && out.rejected_claims.length ? (
        <div className="rounded-md border border-warning/30 bg-warning-soft/40 p-2.5">
          <h4 className="mb-1 text-caption uppercase tracking-wider text-warning">
            {t("ai.layer.claims.rejected")}
          </h4>
          <ul className="space-y-1 text-xs">
            {out.rejected_claims.map((r, i) => (
              <li key={i}>
                «{r.text}» — {r.why}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title={t("ai.layer.audit.engines")} bodyClassName="p-3">
          {d.components.length === 0 ? (
            <p className="text-caption text-subtle-foreground">—</p>
          ) : (
            <ul className="space-y-1 text-xs">
              {d.components.map((c) => (
                <li key={c.id}>
                  {c.engine} · {c.engine_version} · {c.model ?? "—"} ·{" "}
                  <StatusBadge tone={DECISION_TONE[c.decision]}>
                    {t(`ai.layer.decision.${c.decision}`)}
                  </StatusBadge>{" "}
                  · {c.status}
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title={t("ai.layer.audit.packet")} bodyClassName="p-3 space-y-1">
          {d.packet ? (
            <>
              <KeyValue
                label={t("ai.layer.audit.hash")}
                value={d.packet.packet_hash.slice(0, 16)}
              />
              <KeyValue label={t("ai.layer.audit.asOf")} value={utcDateTime(d.packet.as_of)} />
              <KeyValue
                label={t("ai.layer.audit.tokens")}
                value={localInt(d.packet.approx_tokens)}
              />
              <KeyValue
                label={t("ai.layer.audit.missing")}
                value={d.packet.missing.length ? d.packet.missing.join(", ") : "—"}
              />
              <details className="text-caption text-subtle-foreground">
                <summary className="cursor-pointer">{t("ai.layer.audit.content")}</summary>
                <pre className="mt-1 max-h-72 overflow-auto rounded border border-border bg-card p-2">
                  {JSON.stringify(d.packet.content, null, 2)}
                </pre>
              </details>
            </>
          ) : (
            <p className="text-caption text-subtle-foreground">—</p>
          )}
        </Panel>
      </div>
      <Panel title={t("ai.layer.audit.usage")} bodyClassName="p-0">
        {d.usage.length === 0 ? (
          <p className="p-3 text-caption text-subtle-foreground">{t("ai.layer.audit.noUsage")}</p>
        ) : (
          <TableShell compact>
            <THead>
              <TH>{t("ai.layer.audit.call")}</TH>
              <TH align="right">{t("ai.layer.audit.in")}</TH>
              <TH align="right">{t("ai.layer.audit.out")}</TH>
              <TH align="right">{t("ai.layer.audit.cached")}</TH>
              <TH align="right">{t("ai.layer.audit.cost")}</TH>
            </THead>
            <tbody>
              {d.usage.map((u) => (
                <TRow key={u.id}>
                  <TD className="text-xs">
                    {u.provider}:{u.model} · {u.purpose} · {u.status}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(u.input_tokens)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(u.output_tokens)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(u.cached_tokens)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {usd(u.cost_usd)}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>
      {d.evidence.length ? (
        <Panel title={t("ai.layer.audit.evidence")} bodyClassName="p-3">
          <ul className="space-y-1 text-xs">
            {d.evidence.map((e) => (
              <li key={String(e["id"])}>
                <StatusBadge tone={EVIDENCE_TONE[(e["status"] as EvidenceStatus) ?? "OUTDATED"]}>
                  {translateOr(
                    `ai.layer.evidenceStatus.${String(e["status"])}`,
                    String(e["status"]),
                  )}
                </StatusBadge>{" "}
                {String(e["claim"])} · {String(e["source_name"])}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      <p className="text-caption text-subtle-foreground">
        {t("ai.layer.audit.inputHash")}:{" "}
        <span className="numeric">{d.input_hash.slice(0, 24)}</span>
      </p>
    </div>
  );
}

export function ReviewsTab() {
  const [engine, setEngine] = useState<"combined" | "rules" | "llm">("combined");
  const [decision, setDecision] = useState<AiDecision | "">("");
  const [day, setDay] = useState("");
  const [selected, setSelected] = useState(0);
  const q = useLiveQuery(
    live.aiReviews({ engine, decision: decision || undefined, day: day || undefined, limit: 200 }),
  );
  const rows = q.data?.data ?? [];
  const detail = useLiveQuery(live.aiReview(selected));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={engine}
          onChange={(e) => setEngine(e.target.value as typeof engine)}
          className={SELECT}
          aria-label={t("ai.layer.filters.engine")}
        >
          {(["combined", "rules", "llm"] as const).map((x) => (
            <option key={x} value={x}>
              {t(`ai.layer.engine.${x}`)}
            </option>
          ))}
        </select>
        <select
          value={decision}
          onChange={(e) => setDecision(e.target.value as AiDecision | "")}
          className={SELECT}
          aria-label={t("ai.layer.filters.decision")}
        >
          <option value="">{t("ai.layer.filters.all")}</option>
          {DECISIONS.map((x) => (
            <option key={x} value={x}>
              {t(`ai.layer.decision.${x}`)}
            </option>
          ))}
        </select>
        <input
          type="date"
          value={day}
          onChange={(e) => setDay(e.target.value)}
          className={SELECT}
          aria-label={t("ai.layer.filters.day")}
        />
      </div>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={6} cols={6} /> : null}
      {!q.isLoading && rows.length === 0 ? (
        <p className="text-xs text-subtle-foreground">{t("ai.layer.reviews.empty")}</p>
      ) : null}
      {rows.length ? (
        <Panel bodyClassName="p-0">
          <TableShell>
            <THead>
              <TH>{t("ai.layer.reviews.match")}</TH>
              <TH>{t("ai.layer.reviews.selection")}</TH>
              <TH align="right">{t("ai.layer.reviews.odds")}</TH>
              <TH align="right">{t("ai.layer.reviews.model")}</TH>
              <TH align="right">{t("ai.layer.reviews.market")}</TH>
              <TH>{t("ai.layer.reviews.decision")}</TH>
              <TH>{t("ai.layer.reviews.reason")}</TH>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TRow key={r.id} onClick={() => setSelected(r.id)} selected={r.id === selected}>
                  <TD className="text-xs">
                    <div className="font-medium">{r.match}</div>
                    <div className="text-caption text-subtle-foreground">
                      {r.competition} · {utcDateTime(r.kickoff_at)}
                    </div>
                  </TD>
                  <TD className="text-xs">
                    {r.market_key} · {r.selection}
                    {Number(r.line) !== 0 ? ` ${r.line}` : ""}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {r.odds ?? "—"}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {pct(r.p_model) ?? "—"}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {pct(r.p_market) ?? "—"}
                  </TD>
                  <TD>
                    <StatusBadge tone={DECISION_TONE[r.decision]}>
                      {t(`ai.layer.decision.${r.decision}`)}
                    </StatusBadge>
                  </TD>
                  <TD className="min-w-[16rem] max-w-[28rem] whitespace-normal break-words text-xs leading-snug text-muted-foreground">
                    {r.reason ?? "—"}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Panel>
      ) : null}
      {selected ? (
        <Panel title={t("ai.layer.reviews.detail", { id: localInt(selected) })}>
          {detail.isError ? <ApiErrorNotice error={detail.error} /> : null}
          {detail.data?.data ? (
            <ReviewDetailView d={detail.data.data} />
          ) : (
            <TableSkeleton rows={3} cols={3} />
          )}
        </Panel>
      ) : null}
    </div>
  );
}

// ── evidence ─────────────────────────────────────────────────────────────────

export function EvidenceTab() {
  const [status, setStatus] = useState<EvidenceStatus | "">("");
  const q = useLiveQuery(live.aiEvidence({ status: status || undefined }));
  const rows = q.data?.data ?? [];
  return (
    <div className="space-y-3">
      <select
        value={status}
        onChange={(e) => setStatus(e.target.value as EvidenceStatus | "")}
        className={SELECT}
        aria-label={t("ai.layer.filters.status")}
      >
        <option value="">{t("ai.layer.filters.all")}</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {t(`ai.layer.evidenceStatus.${s}`)}
          </option>
        ))}
      </select>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {rows.length === 0 && !q.isLoading ? (
        <p className="text-xs text-subtle-foreground">{t("ai.layer.evidence.empty")}</p>
      ) : (
        <Panel bodyClassName="p-0">
          <TableShell>
            <THead>
              <TH>{t("ai.layer.evidence.claim")}</TH>
              <TH>{t("ai.layer.evidence.source")}</TH>
              <TH>{t("ai.layer.evidence.when")}</TH>
              <TH>{t("ai.layer.evidence.status")}</TH>
            </THead>
            <tbody>
              {rows.map((e) => (
                <TRow key={e.id}>
                  <TD className="text-xs">
                    <div>{e.claim}</div>
                    <div className="text-caption text-subtle-foreground">
                      {e.match ?? "—"} · {e.team ?? "—"} ·{" "}
                      {translateOr(`ai.layer.evidenceKind.${e.kind}`, e.kind)}
                    </div>
                  </TD>
                  <TD className="text-xs">
                    {e.source_url ? (
                      <a
                        href={e.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline"
                      >
                        {e.source_name}
                      </a>
                    ) : (
                      e.source_name
                    )}
                    <div className="text-caption text-subtle-foreground">
                      {translateOr(`ai.layer.tierName.${e.source_tier}`, e.source_tier)}
                    </div>
                  </TD>
                  <TD className="text-caption text-subtle-foreground">
                    {e.published_at ? utcDateTime(e.published_at) : "—"}
                    <div>{utcDateTime(e.retrieved_at)}</div>
                  </TD>
                  <TD className="text-xs">
                    <StatusBadge tone={EVIDENCE_TONE[e.status]}>
                      {t(`ai.layer.evidenceStatus.${e.status}`)}
                    </StatusBadge>
                    <div className="text-caption text-subtle-foreground">{e.status_reason}</div>
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Panel>
      )}
    </div>
  );
}

// ── shadow ───────────────────────────────────────────────────────────────────

function ArmRow({ name, a }: { name: string; a: ShadowArm | undefined }) {
  if (!a || !a.n) return null;
  return (
    <TRow>
      <TD className="text-xs">{t(`ai.layer.shadow.arm.${name}`)}</TD>
      <TD align="right" className="numeric text-xs">
        {localInt(a.n)}
      </TD>
      <TD align="right" className="numeric text-xs">
        {percent(a.hit_rate)}
      </TD>
      <TD align="right" className="numeric text-xs">
        {percent(a.roi)}
      </TD>
      <TD align="right" className="numeric text-xs">
        {percent(a.clv)}
      </TD>
      <TD align="right" className="numeric text-xs">
        {a.logloss_model ?? "—"} / {a.logloss_market ?? "—"}
      </TD>
      <TD align="right" className="numeric text-xs">
        {a.brier_model ?? "—"} / {a.brier_market ?? "—"}
      </TD>
      <TD align="right" className="numeric text-xs">
        {a.max_drawdown ?? "—"}
      </TD>
    </TRow>
  );
}

export function ShadowTab() {
  const q = useLiveQuery(live.aiShadow);
  const rows: ShadowReportRow[] = q.data?.data ?? [];
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (q.isLoading) return <TableSkeleton rows={4} cols={6} />;
  if (!rows.length)
    return <p className="text-xs text-subtle-foreground">{t("ai.layer.shadow.empty")}</p>;
  return (
    <div className="space-y-4">
      <WarningBanner tone="info">{t("ai.layer.shadow.help")}</WarningBanner>
      {rows.map((r) => (
        <Panel
          key={r.engine}
          title={t(`ai.layer.engine.${r.engine}`)}
          subtitle={t("ai.layer.shadow.window", { from: r.window_from, to: r.window_to })}
          actions={
            <StatusBadge tone={gateTone(r.verdict)}>
              {t(`ai.layer.gate.${r.verdict ?? "none"}`)}
            </StatusBadge>
          }
          bodyClassName="p-0"
        >
          <TableShell>
            <THead>
              <TH>{t("ai.layer.shadow.armLabel")}</TH>
              <TH align="right">{t("ai.layer.compare.cols.n")}</TH>
              <TH align="right">{t("ai.layer.shadow.hit")}</TH>
              <TH align="right">{t("ai.layer.compare.cols.roi")}</TH>
              <TH align="right">{t("ai.layer.compare.cols.clv")}</TH>
              <TH align="right">{t("ai.layer.shadow.logloss")}</TH>
              <TH align="right">{t("ai.layer.compare.cols.brier")}</TH>
              <TH align="right">{t("ai.layer.shadow.drawdown")}</TH>
            </THead>
            <tbody>
              {ARMS.map((a) => (
                <ArmRow key={a} name={a} a={r.arms[a]} />
              ))}
            </tbody>
          </TableShell>
          {r.checks ? (
            <ul className="flex flex-wrap gap-1.5 p-3">
              {Object.entries(r.checks).map(([k, c]) => (
                <li key={k}>
                  <StatusBadge tone={c.ok ? "positive" : "neutral"}>
                    {translateOr(`ai.layer.shadow.check.${k}`, k)}: {c.ok ? "✓" : "✗"}
                  </StatusBadge>
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>
      ))}
    </div>
  );
}

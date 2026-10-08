/**
 * La capa de decisión IA (Admin Console): the mode and the configured models (never a key), the budget and
 * how the layer degrades, whether enforcement is on (the owner's switch AND a passed shadow gate), the last
 * cycles and the owner's "run now"; then the reviews with their whole audit trail, the evidence with its
 * sources, what it costs (measured, and simulated per provider before one is chosen), the AI's own shadow
 * evaluation against the model alone and the market, and its memory.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { t } from "@/lib/i18n";
import { localFixed, localInt } from "@/lib/i18n/format";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { SegmentedTabs } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type {
  AiClaim,
  AiDecision,
  AiOverview,
  AiReviewDetail,
  EvidenceStatus,
  ShadowArm,
  ShadowReportRow,
} from "@/lib/api/v1/types_ai_layer";
import { DECISION_TONE, EVIDENCE_TONE, pct } from "./aiModel";
import { utcDateTime } from "./format";

const TABS = ["reviews", "evidence", "costs", "shadow", "memory"] as const;
type Tab = (typeof TABS)[number];
const DECISIONS: AiDecision[] = ["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"];
const STATUSES: EvidenceStatus[] = ["CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY", "OUTDATED"];
const ARMS = ["model", "model_ai", "approved", "downgraded", "rejected", "abstained"] as const;
const CLAIM_GROUPS = [
  "positive_evidence",
  "negative_evidence",
  "uncertainties",
  "contradictions",
] as const;
const SELECT =
  "h-8 rounded-md border border-border bg-card px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

function usd(n: number | string | null | undefined): string {
  if (n === null || n === undefined || n === "") return "—";
  const v = Number(n);
  return `US$ ${localFixed(v, v > 0 && v < 0.01 ? 4 : 2)}`;
}

function percent(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? "—" : `${localFixed(100 * n, digits)} %`;
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
              #{r.id} · {t(`ai.layer.run.${r.kind}`)} · {utcDateTime(r.requested_at)} ·{" "}
              {t(`ai.layer.run.status.${r.status}`)}
              {r.error ? ` · ${r.error}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

function StatusStrip({ o }: { o: AiOverview }) {
  const s = o.settings;
  return (
    <div className="space-y-3" data-testid="ai-layer-status">
      {!s.llm_configured ? (
        <WarningBanner tone="info">
          {t("ai.layer.noModel", { missing: s.missing.join(", ") || "—" })}
        </WarningBanner>
      ) : null}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Panel bodyClassName="p-3 space-y-1">
          <KeyValue
            label={t("ai.layer.modeLabel")}
            value={<StatusBadge tone="info">{t(`ai.layer.mode.${s.mode}`)}</StatusBadge>}
          />
          <KeyValue
            label={t("ai.layer.enforcement")}
            value={
              <StatusBadge tone={o.enforcement.enforced ? "warning" : "neutral"}>
                {o.enforcement.enforced ? t("ai.layer.enforced") : t("ai.layer.notEnforced")}
              </StatusBadge>
            }
          />
          <p className="text-caption text-subtle-foreground">
            {t(`ai.layer.enforcementReason.${o.enforcement.reason}`, {
              reason: o.enforcement.reason,
            })}
          </p>
        </Panel>
        <Panel bodyClassName="p-3 space-y-1">
          {(["bulk", "analysis", "final"] as const).map((tier) => {
            const tm = s.tiers[tier];
            return (
              <KeyValue
                key={tier}
                label={t(`ai.layer.tier.${tier}`)}
                value={
                  tm ? (
                    <span title={tm.key_present ? "" : t("ai.layer.keyMissing")}>
                      {tm.provider}:{tm.model}
                      {tm.key_present ? "" : " ⚠"}
                    </span>
                  ) : (
                    t("ai.layer.notConfigured")
                  )
                }
              />
            );
          })}
          <KeyValue
            label={t("ai.layer.search")}
            value={s.search_configured ? (s.search ?? "—") : t("ai.layer.notConfigured")}
          />
        </Panel>
        <Panel bodyClassName="p-3 space-y-1">
          <KeyValue
            label={t("ai.layer.budget.state")}
            value={
              <StatusBadge
                tone={
                  o.budget.state === "NORMAL"
                    ? "positive"
                    : o.budget.state === "EXHAUSTED"
                      ? "negative"
                      : "warning"
                }
              >
                {t(`ai.layer.budget.${o.budget.state}`)}
              </StatusBadge>
            }
          />
          <KeyValue
            label={t("ai.layer.budget.today")}
            value={`${usd(o.budget.spent_today_usd)} / ${usd(o.budget.daily_budget_usd)}`}
          />
          <KeyValue
            label={t("ai.layer.budget.month")}
            value={`${usd(o.budget.spent_month_usd)} / ${usd(o.budget.monthly_budget_usd)}`}
          />
          <KeyValue
            label={t("ai.layer.caps")}
            value={t("ai.layer.capsValue", {
              reviews: localInt(s.max_llm_reviews_per_day),
              deep: localInt(s.max_deep_per_day),
            })}
          />
        </Panel>
        <Panel bodyClassName="p-3 space-y-1">
          {o.last_cycles.length === 0 ? (
            <p className="text-xs text-subtle-foreground">{t("ai.layer.noCycle")}</p>
          ) : (
            o.last_cycles.map((c) => (
              <KeyValue
                key={c.id}
                label={t(`ai.layer.cycle.${c.kind}`)}
                value={`${utcDateTime(c.started_at)} · ${t(`ai.layer.cycleStatus.${c.status}`)}`}
              />
            ))
          )}
          {Object.entries(o.today).map(([k, v]) => (
            <KeyValue key={k} label={t(`ai.layer.today.${k}`)} value={localInt(v)} />
          ))}
        </Panel>
      </div>
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
            {t(`ai.layer.claimType.${c.type}`)}
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
                  {t(`ai.layer.evidenceStatus.${String(e["status"])}`)}
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

function ReviewsTab() {
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
                  <TD className="max-w-[22rem] truncate text-xs text-muted-foreground">
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

function EvidenceTab() {
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
                      {e.match ?? "—"} · {e.team ?? "—"} · {t(`ai.layer.evidenceKind.${e.kind}`)}
                    </div>
                  </TD>
                  <TD className="text-xs">
                    {e.source_url ? (
                      <a
                        href={e.source_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-primary hover:underline"
                      >
                        {e.source_name}
                      </a>
                    ) : (
                      e.source_name
                    )}
                    <div className="text-caption text-subtle-foreground">
                      {t(`ai.layer.tierName.${e.source_tier}`)}
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

// ── costs ────────────────────────────────────────────────────────────────────

function CostsTab() {
  const q = useLiveQuery(live.aiCosts);
  const c = q.data?.data ?? null;
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (!c) return <TableSkeleton rows={4} cols={5} />;
  const periods = (["today", "7d", "30d", "month"] as const).map((k) => [k, c.periods[k]] as const);
  const worst = new Map(c.worst_case.map((w) => [w.profile, w]));
  return (
    <div className="space-y-4">
      <Panel
        title={t("ai.layer.costs.measured")}
        subtitle={t("ai.layer.costs.measuredHelp")}
        bodyClassName="p-0"
      >
        <TableShell>
          <THead>
            <TH>{t("ai.layer.costs.period")}</TH>
            <TH align="right">{t("ai.layer.costs.requests")}</TH>
            <TH align="right">{t("ai.layer.costs.tokens")}</TH>
            <TH align="right">{t("ai.layer.costs.cost")}</TH>
            <TH align="right">{t("ai.layer.costs.perMatch")}</TH>
            <TH align="right">{t("ai.layer.costs.perReview")}</TH>
            <TH align="right">{t("ai.layer.costs.perApproved")}</TH>
          </THead>
          <tbody>
            {periods.map(([k, p]) => (
              <TRow key={k}>
                <TD className="text-xs">{t(`ai.layer.costs.periods.${k}`)}</TD>
                <TD align="right" className="numeric text-xs">
                  {localInt(p.requests)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {localInt(p.input_tokens)} / {localInt(p.output_tokens)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(p.cost_usd)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(p.cost_per_match)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(p.cost_per_review)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(p.cost_per_approved)}
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>
      <Panel
        title={t("ai.layer.costs.simulation")}
        subtitle={t("ai.layer.costs.simulationHelp")}
        bodyClassName="p-0"
      >
        <TableShell>
          <THead>
            <TH>{t("ai.layer.costs.profile")}</TH>
            <TH align="right">{t("ai.layer.costs.day")}</TH>
            <TH align="right">{t("ai.layer.costs.month")}</TH>
            <TH align="right">{t("ai.layer.costs.perMatch")}</TH>
            <TH align="right">{t("ai.layer.costs.worstMonth")}</TH>
          </THead>
          <tbody>
            {c.simulation.map((s) => (
              <TRow key={s.profile}>
                <TD className="text-xs">
                  <div className="font-medium">{t(`ai.layer.profile.${s.profile}`)}</div>
                  <div className="text-caption text-subtle-foreground">{s.note}</div>
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(s.day_usd)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(s.month_usd)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(s.per_match_usd)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(worst.get(s.profile)?.month_usd)}
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>
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

function ShadowTab() {
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
            <StatusBadge
              tone={
                r.verdict === "pass" ? "positive" : r.verdict === "fail" ? "negative" : "neutral"
              }
            >
              {t(`ai.layer.gate.${r.verdict ?? "none"}`)}
            </StatusBadge>
          }
          bodyClassName="p-0"
        >
          <TableShell>
            <THead>
              <TH>{t("ai.layer.shadow.armLabel")}</TH>
              <TH align="right">n</TH>
              <TH align="right">{t("ai.layer.shadow.hit")}</TH>
              <TH align="right">ROI</TH>
              <TH align="right">CLV</TH>
              <TH align="right">{t("ai.layer.shadow.logloss")}</TH>
              <TH align="right">Brier</TH>
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
                    {t(`ai.layer.shadow.check.${k}`)}: {c.ok ? "✓" : "✗"}
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

// ── memory ───────────────────────────────────────────────────────────────────

function MemoryTab() {
  const q = useLiveQuery(live.aiMemory());
  const rows = q.data?.data ?? [];
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (!rows.length && !q.isLoading)
    return <p className="text-xs text-subtle-foreground">{t("ai.layer.memory.empty")}</p>;
  return (
    <Panel bodyClassName="p-3">
      <ul className="space-y-2">
        {rows.map((m) => (
          <li key={m.id} className="space-y-0.5 border-b border-border pb-2 text-xs last:border-0">
            <div className="flex flex-wrap items-center gap-1.5 text-caption text-subtle-foreground">
              <StatusBadge tone="neutral">{t(`ai.layer.memoryKind.${m.kind}`)}</StatusBadge>
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
  );
}

export function AiLayerLive() {
  const q = useLiveQuery(live.aiOverview);
  const [tab, setTab] = useState<Tab>("reviews");
  const o = q.data?.data ?? null;
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.aiLayer.title")}
        description={t("admin.pages.aiLayer.description")}
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {o ? <StatusStrip o={o} /> : q.isLoading ? <TableSkeleton rows={2} cols={4} /> : null}
      <RunNow />
      <SegmentedTabs
        tabs={TABS}
        value={tab}
        onChange={setTab}
        label={t("ai.layer.tabs.label")}
        format={(x) => t(`ai.layer.tabs.${x}`)}
      />
      {tab === "reviews" ? <ReviewsTab /> : null}
      {tab === "evidence" ? <EvidenceTab /> : null}
      {tab === "costs" ? <CostsTab /> : null}
      {tab === "shadow" ? <ShadowTab /> : null}
      {tab === "memory" ? <MemoryTab /> : null}
    </div>
  );
}

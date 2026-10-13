/**
 * PrediGol Intelligence (Admin Console): the decision layer in shadow. "El día" says what was analysed, what became of
 * every candidate (rejected, investigation, caution, approved, picks of the day), how deep the AI went, what it cost,
 * where the news came from, the picks of the day of daily-set-v6 beside v5 and the day's learning report. Then each
 * decision whole (ten filters, the score and the stake with their components, the AI's context and evidence, the model
 * and the calibrator, the outcome and the post-mortem), the match dossier and its narrative, calibration with its
 * gates, the longitudinal memory, the market discovery engine, and the costs, runs and leakage audit.
 */
import { useState, type ReactNode } from "react";
import { t, translateOr } from "@/lib/i18n";
import { fmtOdds, fmtPct, fmtSignedPct, localFixed, localInt } from "@/lib/i18n/format";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel } from "@/components/primitives/Panel";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { SegmentedTabs, SelectFilter } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import { shiftDay } from "@/lib/time";
import type {
  IntelCalibrationRow,
  IntelContext,
  IntelDecisionRow,
  IntelFilter,
  IntelPlayer,
  IntelState,
  IntelTeamBlock,
  IntelTeamProfile,
} from "@/lib/api/v1/types_intel";
import { Note, Stat, StatGrid, SubTitle } from "./AiBits";
import { bogotaDateTime, dayLabel, selectionText, toNum, usd } from "./aiModel";
import { Markdown } from "./Markdown";
import { durationMs } from "./format";

const TABS = ["day", "decisions", "match", "calibration", "memory", "markets", "costs"] as const;
type Tab = (typeof TABS)[number];
const STATES: IntelState[] = [
  "RECHAZADO",
  "INVESTIGACION",
  "CAUTELA",
  "APROBADO",
  "CANDIDATO_PARLAY",
  "PICK_PREMIUM",
  "PICK_DEL_DIA",
];
const MARKETS = ["1X2", "OU", "BTTS", "DC", "AH"] as const;
const ENTITY_TYPES = ["team", "competition", "market", "referee", "coach", "player"] as const;
const CRITERIA = [
  "coverage",
  "history",
  "real_price",
  "model",
  "calibration",
  "backtest",
  "vs_market",
  "shadow",
  "volume",
  "stability",
] as const;
const DASH = "—";

const STATE_TONE: Record<IntelState, BadgeTone> = {
  RECHAZADO: "negative",
  INVESTIGACION: "info",
  CAUTELA: "warning",
  APROBADO: "positive",
  CANDIDATO_PARLAY: "positive",
  PICK_PREMIUM: "brand",
  PICK_DEL_DIA: "brand",
};
const CONTEXT_TONE: Record<IntelContext, BadgeTone> = {
  FULL: "positive",
  PARTIAL: "info",
  LIMITED: "warning",
  PENDING: "neutral",
  AI_OFF: "neutral",
};

function num(v: unknown): number | null {
  return toNum(v as number | string | null | undefined);
}

function fixed(v: unknown, digits = 3): string {
  const n = num(v);
  return n === null ? DASH : localFixed(n, digits);
}

function StateBadge({ state }: { state: IntelState }) {
  return (
    <StatusBadge tone={STATE_TONE[state] ?? "neutral"}>
      {translateOr(`intel.state.${state}`, state)}
    </StatusBadge>
  );
}

function ContextBadge({ status }: { status: IntelContext }) {
  return (
    <StatusBadge tone={CONTEXT_TONE[status] ?? "neutral"} dot={false}>
      {translateOr(`intel.context.${status}`, status)}
    </StatusBadge>
  );
}

function Loading({ q }: { q: { isLoading: boolean; error: unknown } }) {
  if (q.error) return <ApiErrorNotice error={q.error} />;
  if (q.isLoading) return <TableSkeleton rows={5} cols={6} />;
  return null;
}

function Section({ title, help, children }: { title: string; help?: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <SubTitle>{title}</SubTitle>
      {help ? <Note>{help}</Note> : null}
      {children}
    </div>
  );
}

// ── the day ──────────────────────────────────────────────────────────────────

function DayView({ onOpen }: { onOpen: (id: number) => void }) {
  const [day, setDay] = useState<string | undefined>(undefined);
  const q = useLiveQuery(live.intelDay(day));
  const d = q.data?.data;
  if (!d) return <Loading q={q} />;
  const s = d.decisions.by_state;
  const picks = d.selections_v6.filter((x) => x.kind === "pick");
  const parlays = d.selections_v6.filter((x) => x.kind === "parlay");
  const briefs = d.depth.briefs;
  const passes = d.depth.passes;
  return (
    <div className="space-y-4" data-testid="intel-day">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="tap-y rounded-md border border-border px-2.5 py-1 text-xs"
          onClick={() => setDay(shiftDay(d.day, -1))}
        >
          ← {t("intel.day.prev")}
        </button>
        <span className="text-sm font-medium">{dayLabel(d.day)}</span>
        <button
          type="button"
          className="tap-y rounded-md border border-border px-2.5 py-1 text-xs"
          onClick={() => setDay(shiftDay(d.day, 1))}
        >
          {t("intel.day.next")} →
        </button>
        {day ? (
          <button
            type="button"
            className="tap-y rounded-md px-2 py-1 text-xs text-primary"
            onClick={() => setDay(undefined)}
          >
            {t("intel.day.today")}
          </button>
        ) : null}
      </div>
      <StatGrid className="lg:grid-cols-4" testId="intel-day-stats">
        <Stat label={t("intel.day.analysed")} value={localInt(d.fixtures.fixtures ?? 0)} />
        <Stat
          label={t("intel.day.withCandidates")}
          value={localInt(d.fixtures.with_candidates ?? 0)}
        />
        <Stat label={t("intel.day.decisions")} value={localInt(d.decisions.total)} />
        <Stat
          label={t("intel.day.picksOfDay")}
          value={localInt(picks.length)}
          tone={picks.length ? "positive" : "muted"}
        />
        <Stat label={t("intel.state.RECHAZADO")} value={localInt(s.RECHAZADO ?? 0)} tone="muted" />
        <Stat label={t("intel.state.INVESTIGACION")} value={localInt(s.INVESTIGACION ?? 0)} />
        <Stat label={t("intel.state.CAUTELA")} value={localInt(s.CAUTELA ?? 0)} tone="warning" />
        <Stat
          label={t("intel.state.APROBADO")}
          value={localInt((s.APROBADO ?? 0) + (s.CANDIDATO_PARLAY ?? 0) + (s.PICK_PREMIUM ?? 0))}
          tone="positive"
        />
        <Stat
          label={t("intel.day.limited")}
          value={localInt(d.decisions.by_context.LIMITED ?? 0)}
        />
        <Stat label={t("intel.day.cost")} value={usd(d.cost_usd)} />
        <Stat
          label={t("intel.day.tokens")}
          value={`${localInt(d.tokens.in)} / ${localInt(d.tokens.out)}`}
        />
      </StatGrid>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={t("intel.day.v6Title")}>
          {picks.length === 0 ? (
            <Note>{t("intel.day.v6Empty")}</Note>
          ) : (
            <TableShell compact>
              <THead>
                <TH>#</TH>
                <TH align="right">{t("intel.cols.odds")}</TH>
                <TH align="right">{t("intel.cols.pCal")}</TH>
                <TH align="right">{t("intel.cols.evCal")}</TH>
                <TH align="right">{t("intel.cols.stake")}</TH>
              </THead>
              <tbody>
                {picks.map((p) => (
                  <TRow key={`p${p.rank}`} onClick={() => onOpen(p.decision_ids[0] ?? 0)}>
                    <TD>{p.rank}</TD>
                    <TD align="right">{fmtOdds(p.odds)}</TD>
                    <TD align="right">{fmtPct(p.p_est)}</TD>
                    <TD align="right">{fmtSignedPct(p.ev)}</TD>
                    <TD align="right">{fixed(p.stake_units, 2)} u</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
          {parlays.length ? (
            <Note className="mt-2">{t("intel.day.parlays", { n: parlays.length })}</Note>
          ) : null}
        </Panel>
        <Panel title={t("intel.day.v5Title")}>
          {d.daily_set_v5.length === 0 ? (
            <Note>{t("intel.day.v5Empty")}</Note>
          ) : (
            <TableShell compact>
              <THead>
                <TH>{t("intel.cols.match")}</TH>
                <TH>{t("intel.cols.selection")}</TH>
                <TH align="right">{t("intel.cols.odds")}</TH>
                <TH>{t("intel.cols.result")}</TH>
              </THead>
              <tbody>
                {d.daily_set_v5.map((x) => (
                  <TRow key={x.rank}>
                    <TD className="max-w-[12rem] break-words">{x.match}</TD>
                    <TD>{selectionText(x.market_key, x.selection, x.line, x.match)}</TD>
                    <TD align="right">{fmtOdds(x.odds)}</TD>
                    <TD>{x.status}</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>
      </div>

      <Panel title={t("intel.day.depthTitle")}>
        <StatGrid className="lg:grid-cols-4">
          <Stat
            label={t("intel.day.passes")}
            value={passes.map((p) => `${p.pass} ${localInt(p.n)}`).join(" · ") || DASH}
          />
          <Stat
            label={t("intel.day.briefs")}
            value={`${localInt(briefs.llm ?? 0)} / ${localInt((briefs.briefs ?? 0) - (briefs.llm ?? 0))}`}
          />
          <Stat label={t("intel.day.narratives")} value={localInt(briefs.with_narrative ?? 0)} />
          <Stat
            label={t("intel.day.web")}
            value={localInt(passes.reduce((a, p) => a + (num(p.web) ?? 0), 0))}
          />
          <Stat
            label={t("intel.day.l2")}
            value={localInt(passes.reduce((a, p) => a + (num(p.l2) ?? 0), 0))}
          />
          <Stat
            label={t("intel.day.l3")}
            value={localInt(passes.reduce((a, p) => a + (num(p.l3) ?? 0), 0))}
          />
          <Stat
            label={t("intel.day.marginalSaved")}
            value={localInt(passes.reduce((a, p) => a + (num(p.marginal_saved) ?? 0), 0))}
          />
        </StatGrid>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={t("intel.day.sourcesTitle")} subtitle={t("intel.day.sourcesHelp")}>
          {d.sources.length === 0 ? (
            <Note>{t("intel.day.sourcesEmpty")}</Note>
          ) : (
            <TableShell compact>
              <THead>
                <TH>{t("intel.day.origin")}</TH>
                <TH>{t("intel.day.status")}</TH>
                <TH>{t("intel.day.tier")}</TH>
                <TH align="right">n</TH>
              </THead>
              <tbody>
                {d.sources.slice(0, 16).map((x) => (
                  <TRow key={`${x.origin}-${x.status}-${x.source_tier}`}>
                    <TD>{x.origin}</TD>
                    <TD>{x.status}</TD>
                    <TD>{x.source_tier}</TD>
                    <TD align="right">{localInt(x.n)}</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>
        <Panel title={t("intel.day.calibrationTitle")}>
          <CalibrationTable rows={d.calibration} />
        </Panel>
      </div>

      <Panel title={t("intel.day.reportTitle")}>
        {d.report ? <Markdown text={d.report.text} /> : <Note>{t("intel.day.reportEmpty")}</Note>}
      </Panel>
    </div>
  );
}

function CalibrationTable({ rows }: { rows: IntelCalibrationRow[] }) {
  if (!rows.length) return <Note>{t("intel.calibration.empty")}</Note>;
  return (
    <TableShell compact>
      <THead>
        <TH>{t("intel.cols.model")}</TH>
        <TH>{t("intel.calibration.role")}</TH>
        <TH align="right">{t("intel.calibration.loglossCal")}</TH>
        <TH align="right">{t("intel.calibration.loglossRaw")}</TH>
        <TH align="right">{t("intel.calibration.loglossMarket")}</TH>
        <TH align="right">{t("intel.calibration.ece")}</TH>
        <TH>{t("intel.calibration.edge")}</TH>
      </THead>
      <tbody>
        {rows.map((r) => (
          <TRow key={`${r.market_key}-${r.model_name}`}>
            <TD>
              {r.market_key} · {r.model_name}{" "}
              <span className="text-caption text-muted-foreground">({r.method})</span>
            </TD>
            <TD>
              <StatusBadge
                tone={
                  r.role === "CHAMPION" ? "positive" : r.role === "RETIRED" ? "negative" : "info"
                }
                dot={false}
              >
                {r.role}
              </StatusBadge>
            </TD>
            <TD align="right">{fixed(r.logloss_cal, 4)}</TD>
            <TD align="right">{fixed(r.logloss_raw, 4)}</TD>
            <TD align="right">{fixed(r.logloss_market, 4)}</TD>
            <TD align="right">{fixed(r.ece, 3)}</TD>
            <TD>
              <StatusBadge tone={r.edge === "VALIDATED" ? "positive" : "neutral"} dot={false}>
                {r.edge === "VALIDATED"
                  ? t("intel.calibration.validated")
                  : t("intel.calibration.notValidated")}
              </StatusBadge>
            </TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

// ── decisions ────────────────────────────────────────────────────────────────

function DecisionsView({ onOpen }: { onOpen: (id: number) => void }) {
  const [state, setState] = useState<string>("");
  const [market, setMarket] = useState<string>("");
  const q = useLiveQuery(
    live.intelDecisions({
      state: (state || undefined) as IntelState | undefined,
      market: market || undefined,
    }),
  );
  const items: IntelDecisionRow[] = q.data?.data?.items ?? [];
  return (
    <div className="space-y-3" data-testid="intel-decisions">
      <div className="flex flex-wrap gap-3">
        <SelectFilter
          label={t("intel.decisions.filterState")}
          value={state}
          onChange={setState}
          options={[
            { value: "", label: t("intel.decisions.all") },
            ...STATES.map((s) => ({ value: s, label: t(`intel.state.${s}`) })),
          ]}
        />
        <SelectFilter
          label={t("intel.decisions.filterMarket")}
          value={market}
          onChange={setMarket}
          options={[
            { value: "", label: t("intel.decisions.all") },
            ...MARKETS.map((m) => ({ value: m, label: m })),
          ]}
        />
      </div>
      <Loading q={q} />
      {q.data && items.length === 0 ? <Note>{t("intel.decisions.empty")}</Note> : null}
      {items.length ? (
        <Panel bodyClassName="p-0">
          <TableShell>
            <THead>
              <TH>{t("intel.cols.match")}</TH>
              <TH>{t("intel.cols.selection")}</TH>
              <TH align="right">{t("intel.cols.odds")}</TH>
              <TH align="right">{t("intel.cols.pModel")}</TH>
              <TH align="right">{t("intel.cols.pCal")}</TH>
              <TH align="right">{t("intel.cols.pMarket")}</TH>
              <TH align="right">{t("intel.cols.evCal")}</TH>
              <TH align="right">{t("intel.cols.score")}</TH>
              <TH>{t("intel.cols.state")}</TH>
              <TH>{t("intel.cols.context")}</TH>
              <TH align="right">{t("intel.cols.stake")}</TH>
              <TH>{t("intel.cols.result")}</TH>
              <TH align="right">{t("intel.cols.clv")}</TH>
            </THead>
            <tbody>
              {items.map((x) => (
                <TRow key={x.id} onClick={() => onOpen(x.id)}>
                  <TD className="max-w-[14rem]">
                    <div className="break-words text-sm">{x.match}</div>
                    <div className="text-caption text-muted-foreground">
                      {x.competition} · {bogotaDateTime(x.kickoff_at)} · {x.checkpoint}
                    </div>
                  </TD>
                  <TD>{selectionText(x.market_key, x.selection, x.line, x.match)}</TD>
                  <TD align="right">{fmtOdds(x.odds)}</TD>
                  <TD align="right">{fmtPct(x.p_model)}</TD>
                  <TD align="right">{fmtPct(x.p_cal)}</TD>
                  <TD align="right">{fmtPct(x.p_market)}</TD>
                  <TD align="right">{fmtSignedPct(x.ev_cal)}</TD>
                  <TD align="right">{fixed(x.score, 1)}</TD>
                  <TD>
                    <StateBadge state={x.state} />
                  </TD>
                  <TD>
                    <ContextBadge status={x.context_status} />
                  </TD>
                  <TD align="right">{fixed(x.stake_units, 2)}</TD>
                  <TD>{x.result_status ?? DASH}</TD>
                  <TD align="right">{fmtSignedPct(x.clv)}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Panel>
      ) : null}
    </div>
  );
}

function FilterList({ filters }: { filters: IntelFilter[] }) {
  return (
    <ul className="space-y-1.5" data-testid="intel-filters">
      {filters.map((f) => (
        <li key={`${f.n}-${f.key}`} className="flex items-start gap-2 text-xs">
          <StatusBadge
            tone={
              f.ok === null
                ? "neutral"
                : f.ok
                  ? "positive"
                  : f.effect === "CAUTELA"
                    ? "warning"
                    : "negative"
            }
            dot={false}
          >
            {f.ok === null ? "?" : f.ok ? "OK" : (f.effect ?? "NO")}
          </StatusBadge>
          <span className="min-w-0">
            <span className="font-medium">{translateOr(`intel.filter.${f.key}`, f.key)}</span>
            <span className="text-muted-foreground"> — {f.why}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function DecisionDetail({
  id,
  onClose,
  onMatch,
}: {
  id: number;
  onClose: () => void;
  onMatch: (fixture: number) => void;
}) {
  const q = useLiveQuery(live.intelDecision(id));
  const d = q.data?.data;
  if (!d) return <Loading q={q} />;
  const x = d.decision;
  const stake = (x.stake_components ?? {}) as Record<string, unknown>;
  const ctx = (x.context ?? {}) as Record<string, unknown>;
  const review = d.review as Record<string, unknown> | null;
  const pm = d.postmortem as Record<string, unknown> | null;
  const outcome = d.outcome as Record<string, unknown> | null;
  const cal = d.calibrator as Record<string, unknown> | null;
  const pick = d.pick as Record<string, unknown> | null;
  return (
    <Panel
      title={t("intel.detail.title", { id: x.id })}
      subtitle={`${x.match} · ${x.competition} · ${selectionText(x.market_key, x.selection, x.line, x.match)}`}
      actions={
        <div className="flex gap-2">
          <button
            type="button"
            className="text-xs text-primary"
            onClick={() => onMatch(Number(x["fixture_id"]))}
          >
            {t("intel.tabs.match")}
          </button>
          <button type="button" className="text-xs text-muted-foreground" onClick={onClose}>
            {t("intel.detail.close")}
          </button>
        </div>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2" data-testid="intel-decision-detail">
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge state={x.state} />
            <ContextBadge status={String(x["context_status"]) as IntelContext} />
            <span className="text-xs text-muted-foreground">
              {String(x["checkpoint"])} · {bogotaDateTime(String(x["known_at"]))}
            </span>
          </div>
          <StatGrid className="lg:grid-cols-3">
            <Stat
              label={t("intel.cols.odds")}
              value={fmtOdds(num(x["odds"]))}
              hint={String(x["bookmaker"] ?? "")}
            />
            <Stat label={t("intel.cols.pModel")} value={fmtPct(num(x["p_model"]))} />
            <Stat label={t("intel.cols.pCal")} value={fmtPct(num(x["p_cal"]))} />
            <Stat label={t("intel.cols.pMarket")} value={fmtPct(num(x["p_market"]))} />
            <Stat
              label={t("intel.cols.evCal")}
              value={fmtSignedPct(num(x["ev_cal"]))}
              hint={t("intel.detail.evRaw", { ev: fmtSignedPct(num(x["ev_raw"])) })}
            />
            <Stat label={t("intel.cols.score")} value={fixed(x["score"], 1)} />
          </StatGrid>
          <Section title={t("intel.detail.filters")}>
            <FilterList filters={x.filters} />
          </Section>
          <Section title={t("intel.detail.score")}>
            {x.score_components ? (
              <TableShell compact>
                <THead>
                  <TH>{t("intel.detail.score")}</TH>
                  <TH align="right">{t("intel.detail.weight")}</TH>
                  <TH align="right">{t("intel.detail.points")}</TH>
                </THead>
                <tbody>
                  {x.score_components.map((c) => (
                    <TRow key={c.key}>
                      <TD>
                        <div className="text-xs font-medium">{c.key}</div>
                        <div className="text-caption text-muted-foreground">{c.detail}</div>
                      </TD>
                      <TD align="right">{c.weight}</TD>
                      <TD align="right">{localFixed(c.points, 1)}</TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            ) : (
              <Note>{DASH}</Note>
            )}
          </Section>
          <Section title={t("intel.detail.stake")}>
            <KeyValue label={t("intel.cols.stake")} value={`${fixed(x["stake_units"], 2)} u`} />
            <KeyValue
              label={t("intel.detail.kelly")}
              value={fmtSignedPct(num(stake["kelly_full"]))}
            />
            <KeyValue
              label={t("intel.detail.fraction")}
              value={String(stake["kelly_fraction"] ?? DASH)}
            />
            <KeyValue label={t("intel.detail.cap")} value={String(stake["cap"] ?? DASH)} />
            <Note>{t("intel.detail.unit")}</Note>
          </Section>
        </div>
        <div className="space-y-4">
          <Section title={t("intel.detail.review")}>
            {review ? (
              <>
                <KeyValue label={t("intel.detail.decision")} value={String(review["decision"])} />
                <KeyValue
                  label={t("intel.detail.engine")}
                  value={String(review["engine_version"] ?? "")}
                />
                <p className="text-xs">
                  {String(((review["output"] ?? {}) as Record<string, unknown>)["reason"] ?? "")}
                </p>
              </>
            ) : (
              <Note>{t("intel.detail.noReview")}</Note>
            )}
            <KeyValue
              label={t("intel.detail.signals")}
              value={
                Object.keys((ctx["signals"] ?? {}) as Record<string, unknown>).join(", ") || DASH
              }
            />
          </Section>
          <Section title={t("intel.detail.evidence")}>
            {d.evidence.length ? (
              <ul className="space-y-1.5 text-xs">
                {d.evidence.slice(0, 12).map((e) => (
                  <li key={String(e["id"])} className="break-words">
                    <StatusBadge tone="neutral" dot={false}>
                      {String(e["status"])}
                    </StatusBadge>{" "}
                    <span className="text-muted-foreground">{String(e["source_tier"])}</span> ·{" "}
                    {String(e["claim"])}
                    {e["source_url"] ? (
                      <a
                        className="ml-1 text-primary"
                        href={String(e["source_url"])}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                      >
                        {String(e["source_name"] ?? t("intel.detail.source"))}
                      </a>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <Note>{t("intel.detail.noEvidence")}</Note>
            )}
          </Section>
          <Section title={t("intel.detail.pick")}>
            <KeyValue
              label={t("intel.cols.model")}
              value={`${String(pick?.["model"] ?? x["model_name"])}`}
            />
            <KeyValue
              label={t("intel.detail.modelVersion")}
              value={String(pick?.["model_version"] ?? DASH)}
            />
            <KeyValue
              label={t("intel.detail.features")}
              value={String(pick?.["feature_set_hash"] ?? DASH).slice(0, 16)}
            />
            <KeyValue
              label={t("intel.detail.cutoff")}
              value={bogotaDateTime(String(pick?.["data_cutoff_ts"] ?? ""))}
            />
          </Section>
          <Section title={t("intel.detail.calibrator")}>
            {cal ? (
              <>
                <KeyValue
                  label={t("intel.detail.method")}
                  value={`${String(cal["method"])} #${String(cal["id"])} (${String(x["calibrator_role"] ?? "")})`}
                />
                <KeyValue label={t("intel.detail.params")} value={JSON.stringify(cal["params"])} />
                <KeyValue
                  label={t("intel.detail.gate")}
                  value={String(((cal["gate"] ?? {}) as Record<string, unknown>)["calibrated"])}
                />
              </>
            ) : (
              <Note>{DASH}</Note>
            )}
          </Section>
          <Section title={t("intel.detail.outcome")}>
            {outcome ? (
              <>
                <KeyValue label={t("intel.cols.result")} value={String(outcome["result_status"])} />
                <KeyValue label={t("intel.detail.pnl")} value={fixed(outcome["profit_flat"], 2)} />
                <KeyValue label={t("intel.cols.clv")} value={fmtSignedPct(num(outcome["clv"]))} />
              </>
            ) : (
              <Note>{t("intel.detail.pending")}</Note>
            )}
          </Section>
          {pm ? (
            <Section title={t("intel.detail.postmortem")}>
              <KeyValue label={t("intel.detail.verdict")} value={String(pm["verdict"])} />
              <KeyValue label={t("intel.detail.quality")} value={String(pm["decision_quality"])} />
              <ul className="list-disc space-y-1 pl-4 text-xs">
                {((pm["causes"] ?? []) as Array<Record<string, unknown>>).map((c, i) => (
                  <li key={i}>{String(c["text"])}</li>
                ))}
              </ul>
              <Note>
                {String(((pm["answers"] ?? {}) as Record<string, unknown>)["aprendizaje"] ?? "")}
              </Note>
            </Section>
          ) : null}
          <Section title={t("intel.detail.history")}>
            <TableShell compact>
              <THead>
                <TH>{t("intel.cols.checkpoint")}</TH>
                <TH>{t("intel.cols.state")}</TH>
                <TH align="right">{t("intel.cols.odds")}</TH>
                <TH align="right">{t("intel.cols.evCal")}</TH>
              </THead>
              <tbody>
                {d.history.map((h) => (
                  <TRow key={String(h["id"])}>
                    <TD>
                      {String(h["checkpoint"])}{" "}
                      <span className="text-caption text-muted-foreground">
                        {bogotaDateTime(String(h["known_at"]))}
                      </span>
                    </TD>
                    <TD>
                      <StateBadge state={String(h["state"]) as IntelState} />
                    </TD>
                    <TD align="right">{fmtOdds(num(h["odds"]))}</TD>
                    <TD align="right">{fmtSignedPct(num(h["ev_cal"]))}</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          </Section>
        </div>
      </div>
    </Panel>
  );
}

// ── the match dossier ────────────────────────────────────────────────────────

function pair(a: unknown, b: unknown, digits = 2): string {
  return `${fixed(a, digits)} / ${fixed(b, digits)}`;
}

function teamRows(tb: IntelTeamProfile | undefined): Array<[string, string]> {
  const a: IntelTeamBlock = tb?.all ?? { n: 0 };
  return [
    ["results", tb?.results ?? DASH],
    ["goals", pair(a.goals_for, a.goals_against)],
    ["xg", pair(a.xg_for, a.xg_against)],
    ["shots", pair(a.shots, a.shots_against, 1)],
    ["sot", pair(a.sot, a.sot_against, 1)],
    ["corners", pair(a.corners, a.corners_against, 1)],
    ["fouls", pair(a.fouls, a.fouls_against, 1)],
    ["cards", fixed(a.cards, 1)],
    ["offsides", fixed(a.offsides, 1)],
    [
      "possession",
      a.possession === null || a.possession === undefined ? DASH : `${fixed(a.possession, 1)} %`,
    ],
    ["penalties", `${a.penalties_for ?? DASH} / ${a.penalties_against ?? DASH}`],
    ["cleanSheets", `${a.clean_sheets ?? DASH} / ${a.n}`],
    ["btts", `${a.btts ?? DASH} / ${a.n}`],
    ["over", `${a.over_2_5 ?? DASH} / ${a.n}`],
    ["streak", `${tb?.streaks?.unbeaten ?? DASH} / ${tb?.streaks?.winless ?? DASH}`],
    [
      "scoreline",
      `${tb?.scoreline?.scored_first ?? DASH} / ${tb?.scoreline?.leads_lost ?? DASH} / ${tb?.scoreline?.comebacks ?? DASH}`,
    ],
    ["opponents", fixed(tb?.opponents?.mean_elo, 0)],
  ];
}

function PlayersTable({ players }: { players: IntelPlayer[] }) {
  if (!players.length) return <Note>{DASH}</Note>;
  return (
    <TableShell compact>
      <THead>
        <TH>{t("intel.match.player.name")}</TH>
        <TH align="right">{t("intel.match.player.starts")}</TH>
        <TH align="right">{t("intel.match.player.minutes")}</TH>
        <TH align="right">{t("intel.match.player.goals")}</TH>
        <TH align="right">{t("intel.match.player.assists")}</TH>
        <TH align="right">{t("intel.match.player.load")}</TH>
      </THead>
      <tbody>
        {players.map((p) => (
          <TRow key={p.id}>
            <TD className="max-w-[10rem] break-words">
              {p.name}
              {p.reported_out ? (
                <span className="ml-1 text-caption text-negative">
                  ({t("intel.match.player.out")})
                </span>
              ) : null}
            </TD>
            <TD align="right">{p.starts}</TD>
            <TD align="right">{localInt(p.minutes)}</TD>
            <TD align="right">{p.goals}</TD>
            <TD align="right">{p.assists}</TD>
            <TD align="right">{localInt(p.minutes_14d)}</TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

function MatchView({
  fixture,
  setFixture,
  onOpen,
}: {
  fixture: string;
  setFixture: (f: string) => void;
  onOpen: (id: number) => void;
}) {
  const [draft, setDraft] = useState(fixture);
  const q = useLiveQuery(live.intelDossier(fixture));
  const d = q.data?.data;
  return (
    <div className="space-y-4" data-testid="intel-match">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setFixture(draft.trim());
        }}
      >
        <label className="flex flex-col gap-1 text-caption uppercase tracking-wider text-subtle-foreground">
          {t("intel.match.fixture")}
          <input
            value={draft}
            inputMode="numeric"
            onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
            className="h-8 w-40 min-h-11 rounded-md border border-border bg-card px-2 text-xs sm:min-h-8"
          />
        </label>
        <button type="submit" className="tap-y h-8 rounded-md border border-border px-3 text-xs">
          {t("intel.match.load")}
        </button>
      </form>
      {!fixture ? <Note>{t("intel.match.hint")}</Note> : null}
      {fixture ? <Loading q={q} /> : null}
      {d ? (
        <>
          <PageHeader
            title={`${d.fixture.home} - ${d.fixture.away}`}
            description={`${d.fixture.competition} · ${bogotaDateTime(d.fixture.kickoff_at)}`}
          />
          {!d.dossier && !d.narrative ? <Note>{t("intel.match.empty")}</Note> : null}
          {d.narrative ? (
            <Panel
              title={t("intel.match.narrative")}
              subtitle={
                d.narrative_engine === "llm"
                  ? t("intel.match.engineLlm")
                  : t("intel.match.engineRules")
              }
            >
              <div className="space-y-3">
                {d.narrative.map((s) => (
                  <div key={s.key}>
                    <SubTitle>{s.title}</SubTitle>
                    <p className="mt-1 text-sm leading-relaxed">{s.text ?? DASH}</p>
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
          {d.dossier ? (
            <>
              <Panel title={t("intel.match.teams")}>
                <TableShell compact>
                  <THead>
                    <TH>&nbsp;</TH>
                    <TH align="right">{d.fixture.home}</TH>
                    <TH align="right">{d.fixture.away}</TH>
                  </THead>
                  <tbody>
                    {teamRows(d.dossier.teams.home).map(([k, v], i) => (
                      <TRow key={k}>
                        <TD className="text-xs text-muted-foreground">
                          {t(`intel.match.row.${k}`)}
                        </TD>
                        <TD align="right">{v}</TD>
                        <TD align="right">{teamRows(d.dossier?.teams.away)[i]?.[1] ?? DASH}</TD>
                      </TRow>
                    ))}
                    <TRow>
                      <TD className="text-xs text-muted-foreground">{t("intel.match.coach")}</TD>
                      <TD align="right">
                        {d.dossier.teams.home.coach?.name ?? DASH} ·{" "}
                        {d.dossier.teams.home.coach?.main_formation ?? DASH}
                      </TD>
                      <TD align="right">
                        {d.dossier.teams.away.coach?.name ?? DASH} ·{" "}
                        {d.dossier.teams.away.coach?.main_formation ?? DASH}
                      </TD>
                    </TRow>
                    <TRow>
                      <TD className="text-xs text-muted-foreground">{t("intel.match.rotation")}</TD>
                      <TD align="right">
                        {fixed(d.dossier.teams.home.coach?.rotation_avg_changes, 1)}
                      </TD>
                      <TD align="right">
                        {fixed(d.dossier.teams.away.coach?.rotation_avg_changes, 1)}
                      </TD>
                    </TRow>
                    <TRow>
                      <TD className="text-xs text-muted-foreground">{t("intel.match.firstSub")}</TD>
                      <TD align="right">
                        {fixed(d.dossier.teams.home.coach?.first_sub_minute, 0)}
                      </TD>
                      <TD align="right">
                        {fixed(d.dossier.teams.away.coach?.first_sub_minute, 0)}
                      </TD>
                    </TRow>
                  </tbody>
                </TableShell>
              </Panel>
              <div className="grid gap-4 lg:grid-cols-3">
                <Panel title={t("intel.match.referee")}>
                  <KeyValue
                    label={t("intel.match.referee")}
                    value={String(d.dossier.referee["name"] ?? DASH)}
                  />
                  <KeyValue
                    label={t("intel.match.matches")}
                    value={String(d.dossier.referee["matches"] ?? 0)}
                  />
                  <KeyValue
                    label={t("intel.match.cardsPerMatch")}
                    value={fixed(d.dossier.referee["cards_per_match"], 2)}
                  />
                  <KeyValue
                    label={t("intel.match.foulsPerMatch")}
                    value={fixed(d.dossier.referee["fouls_per_match"], 1)}
                  />
                  <KeyValue
                    label={t("intel.match.pensPerMatch")}
                    value={fixed(d.dossier.referee["penalties_per_match"], 2)}
                  />
                  <KeyValue
                    label={t("intel.match.cardsHomeAway")}
                    value={pair(
                      d.dossier.referee["cards_home_per_match"],
                      d.dossier.referee["cards_away_per_match"],
                    )}
                  />
                </Panel>
                <Panel title={t("intel.match.contextTitle")}>
                  {(["derby", "cup", "knockout", "final", "friendly"] as const).map((k) => (
                    <KeyValue
                      key={k}
                      label={t(`intel.match.${k}`)}
                      value={d.dossier?.context[k] ? t("intel.match.yes") : t("intel.match.no")}
                    />
                  ))}
                  {d.dossier.context["second_leg"] ? (
                    <KeyValue
                      label={t("intel.match.secondLeg")}
                      value={JSON.stringify(d.dossier.context["second_leg"])}
                    />
                  ) : null}
                </Panel>
                <Panel title={t("intel.match.h2h")}>
                  <KeyValue label="n" value={String(d.dossier.h2h.n)} />
                  <KeyValue label={t("intel.match.relevance")} value={d.dossier.h2h.relevance} />
                  <Note>{d.dossier.h2h.note}</Note>
                </Panel>
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <Panel title={`${t("intel.match.players")} · ${d.fixture.home}`}>
                  <PlayersTable players={d.dossier.players.home} />
                </Panel>
                <Panel title={`${t("intel.match.players")} · ${d.fixture.away}`}>
                  <PlayersTable players={d.dossier.players.away} />
                </Panel>
              </div>
            </>
          ) : null}
          <Panel title={t("intel.match.decisions")}>
            {d.decisions.length ? (
              <TableShell compact>
                <THead>
                  <TH>{t("intel.cols.selection")}</TH>
                  <TH align="right">{t("intel.cols.odds")}</TH>
                  <TH align="right">{t("intel.cols.pCal")}</TH>
                  <TH align="right">{t("intel.cols.evCal")}</TH>
                  <TH>{t("intel.cols.state")}</TH>
                </THead>
                <tbody>
                  {d.decisions.map((x) => (
                    <TRow key={String(x["id"])} onClick={() => onOpen(Number(x["id"]))}>
                      <TD>
                        {selectionText(
                          String(x["market_key"]),
                          String(x["selection"]),
                          num(x["line"]),
                        )}
                      </TD>
                      <TD align="right">{fmtOdds(num(x["odds"]))}</TD>
                      <TD align="right">{fmtPct(num(x["p_cal"]))}</TD>
                      <TD align="right">{fmtSignedPct(num(x["ev_cal"]))}</TD>
                      <TD>
                        <StateBadge state={String(x["state"]) as IntelState} />
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            ) : (
              <Note>{DASH}</Note>
            )}
          </Panel>
        </>
      ) : null}
    </div>
  );
}

// ── calibration ──────────────────────────────────────────────────────────────

function CalibrationView() {
  const q = useLiveQuery(live.intelCalibration);
  const d = q.data?.data;
  if (!d) return <Loading q={q} />;
  const gates = d.gates as Record<string, Record<string, unknown> | number>;
  return (
    <div className="space-y-4" data-testid="intel-calibration">
      <Panel title={t("intel.calibration.champions")}>
        <CalibrationTable rows={d.champions} />
      </Panel>
      <Panel title={t("intel.calibration.gates")}>
        <pre className="overflow-x-auto whitespace-pre-wrap break-words text-caption">
          {JSON.stringify(gates, null, 2)}
        </pre>
      </Panel>
      <Panel title={t("intel.calibration.promotions")} bodyClassName="p-0">
        <TableShell>
          <THead>
            <TH>{t("intel.calibration.since")}</TH>
            <TH>{t("intel.cols.model")}</TH>
            <TH>{t("intel.calibration.role")}</TH>
            <TH>{t("intel.calibration.reason")}</TH>
          </THead>
          <tbody>
            {d.promotions.slice(0, 60).map((p) => (
              <TRow key={String(p["id"])}>
                <TD>{bogotaDateTime(String(p["at"]))}</TD>
                <TD>
                  {String(p["entity"])} · {String(p["market_key"])}/{String(p["model_name"])}
                </TD>
                <TD>{String(p["to_role"])}</TD>
                <TD className="max-w-[28rem] break-words text-xs">{String(p["reason"])}</TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>
      <Panel title={t("intel.calibration.evaluations")} bodyClassName="p-0">
        <TableShell>
          <THead>
            <TH>{t("intel.calibration.day")}</TH>
            <TH>{t("intel.cols.model")}</TH>
            <TH align="right">{t("intel.calibration.n")}</TH>
            <TH align="right">{t("intel.calibration.loglossCal")}</TH>
            <TH align="right">{t("intel.calibration.loglossRaw")}</TH>
            <TH align="right">{t("intel.calibration.loglossMarket")}</TH>
            <TH align="right">{t("intel.calibration.ece")}</TH>
            <TH align="right">{t("intel.calibration.ruleClv")}</TH>
          </THead>
          <tbody>
            {d.evaluations.slice(0, 120).map((e, i) => (
              <TRow key={i}>
                <TD>{String(e["day"])}</TD>
                <TD>
                  {String(e["market_key"])}/{String(e["model_name"])} ({String(e["method"])})
                </TD>
                <TD align="right">{String(e["n"])}</TD>
                <TD align="right">{fixed(e["logloss_cal"], 4)}</TD>
                <TD align="right">{fixed(e["logloss_raw"], 4)}</TD>
                <TD align="right">{fixed(e["logloss_market"], 4)}</TD>
                <TD align="right">{fixed(e["ece_cal"], 3)}</TD>
                <TD align="right">{fmtSignedPct(num(e["rule_clv"]))}</TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>
    </div>
  );
}

// ── memory ───────────────────────────────────────────────────────────────────

function MemoryView() {
  const [type, setType] = useState<string>("team");
  const [search, setSearch] = useState("");
  const q = useLiveQuery(
    live.intelMemory({ entity_type: type || undefined, q: search || undefined }),
  );
  const items = q.data?.data?.items ?? [];
  return (
    <div className="space-y-3" data-testid="intel-memory">
      <div className="flex flex-wrap items-end gap-3">
        <SelectFilter
          label={t("intel.memory.type")}
          value={type}
          onChange={setType}
          options={ENTITY_TYPES.map((x) => ({ value: x, label: t(`intel.memory.types.${x}`) }))}
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
      <Note>{t("intel.memory.streakNote")}</Note>
      <Loading q={q} />
      {q.data && items.length === 0 ? <Note>{t("intel.memory.empty")}</Note> : null}
      {items.length ? (
        <Panel bodyClassName="p-0">
          <TableShell>
            <THead>
              <TH>{t("intel.memory.type")}</TH>
              <TH>{t("intel.memory.aspect")}</TH>
              <TH>{t("intel.memory.asOf")}</TH>
              <TH align="right">{t("intel.memory.decisions")}</TH>
              <TH align="right">{t("intel.memory.record")}</TH>
              <TH align="right">{t("intel.memory.clv")}</TH>
              <TH>{t("intel.memory.last10")}</TH>
              <TH>{t("intel.memory.detail")}</TH>
            </THead>
            <tbody>
              {items.map((m) => {
                const s = m.stats as Record<string, unknown>;
                const detail =
                  m.entity_type === "referee"
                    ? t("intel.memory.refereeLine", {
                        cards: fixed(s["cards_per_match"], 2),
                        fouls: fixed(s["fouls_per_match"], 1),
                      })
                    : m.entity_type === "coach"
                      ? `${String(s["wins"] ?? 0)}G ${String(s["draws"] ?? 0)}E ${String(s["losses"] ?? 0)}P · ${Object.keys(
                          (s["formations"] ?? {}) as Record<string, number>,
                        )
                          .slice(0, 2)
                          .join(", ")}`
                      : m.entity_type === "player"
                        ? `${String(s["started_anyway"] ?? 0)}/${String(s["reported_out"] ?? 0)}`
                        : DASH;
                return (
                  <TRow key={`${m.entity_type}-${m.entity_id}-${m.aspect}`}>
                    <TD className="max-w-[12rem] break-words">{m.entity_name ?? m.entity_id}</TD>
                    <TD>{m.aspect}</TD>
                    <TD>{m.as_of_day}</TD>
                    <TD align="right">
                      {String(s["decisions"] ?? s["matches"] ?? s["reported_out"] ?? DASH)}
                    </TD>
                    <TD align="right">
                      {s["wins"] !== undefined
                        ? `${String(s["wins"])} / ${String(s["losses"] ?? 0)} / ${String(s["voids"] ?? 0)}`
                        : DASH}
                    </TD>
                    <TD align="right">{fmtSignedPct(num(s["clv_mean"]))}</TD>
                    <TD className="font-mono text-caption">
                      {Array.isArray(s["last10"]) ? (s["last10"] as string[]).join("") : DASH}
                    </TD>
                    <TD className="text-xs">{detail}</TD>
                  </TRow>
                );
              })}
            </tbody>
          </TableShell>
        </Panel>
      ) : null}
    </div>
  );
}

// ── markets ──────────────────────────────────────────────────────────────────

function MarketsView() {
  const q = useLiveQuery(live.intelMarkets);
  const d = q.data?.data;
  if (!d) return <Loading q={q} />;
  return (
    <div className="space-y-3" data-testid="intel-markets">
      <Note>{t("intel.markets.never")}</Note>
      {!d.run ? <Note>{t("intel.markets.empty")}</Note> : null}
      <div className="flex flex-wrap gap-2">
        {Object.entries(d.by_status).map(([k, v]) => (
          <StatusBadge
            key={k}
            tone={k === "ACTIVE" ? "positive" : k === "RESEARCH" ? "info" : "neutral"}
          >
            {translateOr(`intel.markets.status.${k}`, k)} {v}
          </StatusBadge>
        ))}
      </div>
      {d.items.length ? (
        <Panel bodyClassName="p-0">
          <TableShell>
            <THead>
              <TH>#</TH>
              <TH>{t("intel.markets.market")}</TH>
              <TH>{t("intel.cols.state")}</TH>
              <TH align="right">{t("intel.markets.fixtures")}</TH>
              <TH align="right">{t("intel.markets.books")}</TH>
              {CRITERIA.map((c) => (
                <TH key={c} align="center" className="text-caption">
                  {t(`intel.markets.criteria.${c}`)}
                </TH>
              ))}
              <TH>{t("intel.markets.proposal")}</TH>
            </THead>
            <tbody>
              {d.items.map((m) => (
                <TRow key={m.provider_bet_id}>
                  <TD>{m.provider_bet_id}</TD>
                  <TD className="max-w-[12rem] break-words">{m.name}</TD>
                  <TD>
                    <StatusBadge
                      tone={
                        m.status === "ACTIVE"
                          ? "positive"
                          : m.status === "RESEARCH"
                            ? "info"
                            : "neutral"
                      }
                      dot={false}
                    >
                      {translateOr(`intel.markets.status.${m.status}`, m.status)}
                    </StatusBadge>
                  </TD>
                  <TD align="right">{String(m.metrics["fixtures"] ?? DASH)}</TD>
                  <TD align="right">{String(m.metrics["median_books"] ?? DASH)}</TD>
                  {CRITERIA.map((c) => (
                    <TD key={c} align="center">
                      {m.criteria[c]?.ok ? "✓" : "·"}
                    </TD>
                  ))}
                  <TD className="max-w-[20rem] break-words text-xs">{m.proposal ?? DASH}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Panel>
      ) : null}
    </div>
  );
}

// ── costs, runs and the leakage audit ────────────────────────────────────────

function CostsView() {
  const q = useLiveQuery(live.intelCosts);
  const r = useLiveQuery(live.intelRuns);
  const c = q.data?.data;
  const runs = r.data?.data;
  const projection = (c?.projection ?? {}) as Record<string, unknown>;
  const budget = (c?.budget ?? {}) as Record<string, unknown>;
  return (
    <div className="space-y-4" data-testid="intel-costs">
      {c ? (
        <Panel title={t("intel.tabs.costs")}>
          <StatGrid className="lg:grid-cols-4">
            <Stat label={t("intel.costs.perMatch")} value={usd(c.per_match_usd)} />
            <Stat label={t("intel.costs.perCandidate")} value={usd(c.per_candidate_usd)} />
            <Stat label={t("intel.costs.perPick")} value={usd(c.per_pick_usd)} />
            <Stat label={t("intel.costs.perResearch")} value={usd(c.per_research_usd)} />
            <Stat label={t("intel.costs.perPostmortem")} value={usd(c.per_postmortem_usd)} />
            <Stat label={t("intel.costs.perDay")} value={usd(c.per_day_usd)} />
            <Stat label={t("intel.costs.budget")} value={usd(c.monthly_budget_usd)} />
            <Stat label={t("intel.costs.spentMonth")} value={usd(num(budget["spent_month_usd"]))} />
            <Stat
              label={t("intel.costs.projection")}
              value={usd(num(projection["projected_month_usd"]))}
            />
          </StatGrid>
          <div className="mt-3 text-xs">
            {t("intel.costs.alerts")}:{" "}
            {c.alerts && c.alerts.length
              ? c.alerts.map((a) => `${a.threshold} %`).join(", ")
              : t("intel.costs.noAlerts")}
          </div>
        </Panel>
      ) : (
        <Loading q={q} />
      )}
      {runs ? (
        <>
          <Panel title={t("intel.costs.audit")} bodyClassName="p-0">
            {runs.leakage_audit.length === 0 ? (
              <div className="p-4">
                <Note>{t("intel.costs.auditEmpty")}</Note>
              </div>
            ) : (
              <TableShell compact>
                <THead>
                  <TH>{t("intel.costs.rule")}</TH>
                  <TH align="right">{t("intel.costs.checked")}</TH>
                  <TH align="right">{t("intel.costs.violations")}</TH>
                  <TH>{t("intel.calibration.day")}</TH>
                </THead>
                <tbody>
                  {runs.leakage_audit.map((a) => (
                    <TRow key={a.rule}>
                      <TD>{a.rule}</TD>
                      <TD align="right">{localInt(a.n_checked)}</TD>
                      <TD align="right" className={a.n_violations ? "text-negative" : ""}>
                        {localInt(a.n_violations)}
                      </TD>
                      <TD>{a.day}</TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            )}
          </Panel>
          <Panel title={t("intel.costs.runs")} bodyClassName="p-0">
            <TableShell>
              <THead>
                <TH>{t("intel.costs.job")}</TH>
                <TH>{t("intel.costs.started")}</TH>
                <TH align="right">{t("intel.costs.duration")}</TH>
                <TH>{t("intel.costs.status")}</TH>
                <TH>{t("intel.costs.errors")}</TH>
              </THead>
              <tbody>
                {runs.items.map((x) => (
                  <TRow key={x.id}>
                    <TD>{x.job}</TD>
                    <TD>{bogotaDateTime(x.started_at)}</TD>
                    <TD align="right">{durationMs(x.duration_ms)}</TD>
                    <TD>
                      <StatusBadge
                        tone={
                          x.status === "ok"
                            ? "positive"
                            : x.status === "running"
                              ? "info"
                              : x.status === "skipped"
                                ? "neutral"
                                : "warning"
                        }
                        dot={false}
                      >
                        {x.status}
                      </StatusBadge>
                    </TD>
                    <TD className="max-w-[24rem] break-words text-xs">
                      {x.errors.length ? x.errors.join(" | ") : t("intel.costs.none")}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          </Panel>
        </>
      ) : (
        <Loading q={r} />
      )}
    </div>
  );
}

// ── the page ─────────────────────────────────────────────────────────────────

export function IntelligenceLive() {
  const [tab, setTab] = useState<Tab>("day");
  const [open, setOpen] = useState<number>(0);
  const [fixture, setFixture] = useState<string>("");
  const openDecision = (id: number) => {
    if (id > 0) setOpen(id);
  };
  const toMatch = (f: number) => {
    setFixture(String(f));
    setTab("match");
  };
  return (
    <div className="space-y-4" data-testid="intel-page">
      <PageHeader
        title={t("admin.pages.intelligence.title")}
        description={t("admin.pages.intelligence.description")}
      />
      <div
        className="flex flex-wrap items-center gap-2 rounded-md border border-primary/25 bg-primary/8 px-3 py-2 text-xs"
        data-testid="intel-shadow-line"
      >
        <StatusBadge tone="brand">SHADOW</StatusBadge>
        <span className="min-w-0 text-foreground/85">{t("intel.shadowLine")}</span>
      </div>
      <SegmentedTabs
        tabs={TABS}
        value={tab}
        onChange={setTab}
        label={t("intel.tabsLabel")}
        format={(x) => t(`intel.tabs.${x}`)}
      />
      {open > 0 ? <DecisionDetail id={open} onClose={() => setOpen(0)} onMatch={toMatch} /> : null}
      {tab === "day" ? <DayView onOpen={openDecision} /> : null}
      {tab === "decisions" ? <DecisionsView onOpen={openDecision} /> : null}
      {tab === "match" ? (
        <MatchView fixture={fixture} setFixture={setFixture} onOpen={openDecision} />
      ) : null}
      {tab === "calibration" ? <CalibrationView /> : null}
      {tab === "memory" ? <MemoryView /> : null}
      {tab === "markets" ? <MarketsView /> : null}
      {tab === "costs" ? <CostsView /> : null}
    </div>
  );
}

/**
 * POR ENTIDAD Y TEMA (Operación → Trabajo IA, plan IA, phase 2): what research v2 does and has done, in the words of the plan - one answer per entity
 * and topic, the class of each source, how fresh an answer is and how often it was reused instead of searched again - beside the week of comparison
 * with v1 and the gate that decides whether v2 may replace it. The switch comes first (what the owner asked, what the cycle does with it), then the
 * gate and the comparison, then the evidence they stand on: the freshness of each topic, the answers kept, the claims by class of source and by
 * state, each day of the cycle, and the pages read. Reading only: nothing here searches, calls a model, writes a claim or changes a switch.
 */
import { t, translateOr } from "@/lib/i18n";
import { DASH, localInt } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, SectionView } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  AnswerRow,
  ClaimBreakdown,
  EntityResearchOverview,
  GateCheckRow,
  PageCache,
  ResearchClaims,
  ResearchComparison,
  ResearchDay,
  ResearchFreshness,
  ResearchGateRow,
  ResearchGateView,
  ResearchSwitch,
  TopicRow,
} from "@/lib/api/v1/types_ai_research";
import { Block, Fact, Framed, Note, Notice, Stat, StatGrid } from "./AiBits";
import { bogotaDateTime, dayShort, usd } from "./aiModel";
import { orderedCounts } from "./agentsModel";
import {
  CLAIM_STATUSES,
  CLASS_TONE,
  EXTRACTOR_STATUSES,
  SERIOUS,
  STATUS_TONE,
  SWITCH_TONE,
  answerKey,
  attention,
  checkTone,
  dayTotals,
  detailPairs,
  entityName,
  figureText,
  freshShare,
  hoursText,
  markKey,
  missedLine,
  pctText,
  previewFigures,
  reuseShare,
  silentClasses,
  statusCells,
  switchState,
  tierCounts,
  usedStatuses,
  verdictKey,
  verdictTone,
} from "./topicsModel";

const share = (x: number | null): string => (x === null ? DASH : `${Math.round(x * 100)} %`);
const when = (iso: string | null): string => (iso ? bogotaDateTime(iso) : DASH);

// ── what to look at ──────────────────────────────────────────────────────────

/** What the owner should look at, most serious first - or, honestly, that there is nothing. */
function AttentionLine({ o }: { o: EntityResearchOverview }) {
  const items = attention(o);
  if (items.length === 0) {
    return (
      <div
        className="flex flex-wrap items-center gap-2 rounded-md border border-positive/30 bg-positive-soft px-3 py-2 text-xs"
        data-testid="topics-attention"
      >
        <StatusBadge tone="positive">{t("ai.topics.attention.title")}</StatusBadge>
        <span className="min-w-0 text-foreground/85">{t("ai.topics.attention.none")}</span>
      </div>
    );
  }
  const serious = items.some((i) => SERIOUS.includes(i.code));
  return (
    <Notice
      tone={serious ? "negative" : "warning"}
      testId="topics-attention"
      title={t("ai.topics.attention.title")}
    >
      {items.map((i) => (
        <li key={i.code}>{t(`ai.topics.attention.${i.code}`, { n: i.n })}</li>
      ))}
    </Notice>
  );
}

// ── the switch ───────────────────────────────────────────────────────────────

function GateRowLine({ r }: { r: ResearchGateRow }) {
  return (
    <TRow>
      <TD className="whitespace-nowrap text-xs">{bogotaDateTime(r.at)}</TD>
      <TD>
        <StatusBadge tone={r.passed ? "positive" : "negative"} dot={false}>
          {r.passed ? t("ai.topics.switch.history.passed") : t("ai.topics.switch.history.failed")}
        </StatusBadge>
      </TD>
      <TD className="text-xs">{r.decided_by}</TD>
      <TD className="numeric text-xs">{r.code_version ?? DASH}</TD>
      <TD className="numeric text-caption text-muted-foreground">{r.evidence_hash.slice(0, 12)}</TD>
    </TRow>
  );
}

function SwitchPanel({ s }: { s: ResearchSwitch }) {
  const state = switchState(s);
  const gateText =
    s.gate_at === null
      ? t("ai.topics.switch.gateState.never")
      : t(`ai.topics.switch.gateState.${s.gate_passed ? "passed" : "failed"}`, {
          date: bogotaDateTime(s.gate_at),
        });
  return (
    <Panel
      title={t("ai.topics.switch.title")}
      subtitle={t("ai.topics.switch.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <StatGrid testId="topics-switch">
        <Stat label={t("ai.topics.switch.asked")} value={s.asked} />
        <Stat
          label={t("ai.topics.switch.mode")}
          value={s.mode}
          tone={state === "held" ? "warning" : s.mode === "on" ? "positive" : "default"}
        />
        <Stat
          label={t("ai.topics.switch.typed")}
          value={
            s.typed_visible ? t("ai.topics.switch.typedVisible") : t("ai.topics.switch.typedHidden")
          }
          tone={s.typed_visible ? "positive" : "muted"}
        />
        <Stat
          label={t("ai.topics.switch.gate")}
          value={gateText}
          tone={s.gate_at === null ? "muted" : s.gate_passed ? "positive" : "negative"}
        />
      </StatGrid>
      <div className="flex flex-wrap items-center gap-2" data-testid="topics-switch-state">
        <StatusBadge tone={SWITCH_TONE[state]} dot={false}>
          {t(`ai.topics.switch.state.${state}`)}
        </StatusBadge>
        <Note>{s.why}</Note>
      </div>
      <Block title={t("ai.topics.switch.history.title")} hint={t("ai.topics.switch.history.hint")}>
        {s.history.length === 0 ? (
          <Note>{t("ai.topics.switch.history.empty")}</Note>
        ) : (
          <Framed>
            <TableShell compact>
              <THead>
                <TH>{t("ai.topics.switch.history.col.when")}</TH>
                <TH>{t("ai.topics.switch.history.col.verdict")}</TH>
                <TH>{t("ai.topics.switch.history.col.by")}</TH>
                <TH>{t("ai.topics.switch.history.col.version")}</TH>
                <TH>{t("ai.topics.switch.history.col.hash")}</TH>
              </THead>
              <tbody>
                {s.history.map((r) => (
                  <GateRowLine key={r.id} r={r} />
                ))}
              </tbody>
            </TableShell>
          </Framed>
        )}
      </Block>
    </Panel>
  );
}

// ── the gate ─────────────────────────────────────────────────────────────────

function CheckRow({ c }: { c: GateCheckRow }) {
  const pairs = detailPairs(c.detail);
  return (
    <TRow>
      <TD className="max-w-[22rem]">
        <div className="font-medium">{translateOr(`ai.topics.gate.check.${c.id}`, c.id)}</div>
        <div className="mt-0.5 text-caption text-muted-foreground">{c.title}</div>
      </TD>
      <TD>
        <StatusBadge tone={checkTone(c.ok)} dot={false}>
          {t(`ai.topics.gate.mark.${markKey(c.ok)}`)}
        </StatusBadge>
      </TD>
      <TD className="max-w-[26rem] text-xs">
        {pairs.length === 0 ? (
          <span className="text-muted-foreground">{DASH}</span>
        ) : (
          <ul className="space-y-0.5">
            {pairs.map(([k, v]) => (
              <li key={k} className="break-words">
                <span className="text-muted-foreground">{k}</span>{" "}
                <span className="numeric">{v}</span>
              </li>
            ))}
          </ul>
        )}
      </TD>
      <TD className="numeric text-xs">{c.revert ?? DASH}</TD>
    </TRow>
  );
}

function GateBody({ g }: { g: ResearchGateView }) {
  const key = verdictKey(g.verdict);
  const w = g.window;
  const figures = previewFigures(g.preview);
  return (
    <div className="space-y-4" data-testid="topics-gate">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={verdictTone(g.verdict)} dot={false}>
          {key === "unknown" ? g.verdict : t(`ai.topics.gate.verdict.${key}`)}
        </StatusBadge>
        <span className="text-xs text-muted-foreground">
          {t("ai.topics.gate.evaluatedAt", { at: bogotaDateTime(g.at) })}
        </span>
      </div>
      <div data-testid="topics-gate-window">
        <Fact
          label={t("ai.topics.gate.window.days")}
          value={t("ai.topics.gate.window.daysOf", { n: w.stable_complete_days, total: w.days })}
        />
        <Fact
          label={t("ai.topics.gate.window.range")}
          value={`${dayShort(w.first)} – ${dayShort(w.last)}`}
        />
        <Fact
          label={t("ai.topics.gate.window.since")}
          value={w.anchor ? dayShort(w.anchor) : DASH}
        />
        <Fact label={t("ai.topics.gate.window.eligible")} value={dayShort(w.eligible_on)} />
        <Fact label={t("ai.topics.gate.window.anchoredBy")} value={w.anchored_by} />
      </div>
      {g.pending.length > 0 ? (
        <Notice
          tone="warning"
          testId="topics-gate-pending"
          title={t("ai.topics.gate.pendingTitle")}
        >
          {g.pending.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </Notice>
      ) : null}
      {g.checks.length > 0 ? (
        <Framed>
          <TableShell>
            <THead>
              <TH>{t("ai.topics.gate.col.check")}</TH>
              <TH>{t("ai.topics.gate.col.result")}</TH>
              <TH>{t("ai.topics.gate.col.detail")}</TH>
              <TH>{t("ai.topics.gate.col.revert")}</TH>
            </THead>
            <tbody>
              {g.checks.map((c) => (
                <CheckRow key={c.id} c={c} />
              ))}
            </tbody>
          </TableShell>
        </Framed>
      ) : null}
      {g.consequence ? (
        <Notice
          tone="negative"
          testId="topics-gate-consequence"
          title={t("ai.topics.gate.consequenceTitle")}
        >
          <li>{g.consequence}</li>
        </Notice>
      ) : null}
      {figures.length > 0 ? (
        <Block title={t("ai.topics.gate.preview.title")} hint={t("ai.topics.gate.preview.hint")}>
          <div data-testid="topics-gate-preview">
            {figures.map((f) => (
              <Fact
                key={`${f.group}.${f.key}`}
                label={translateOr(`ai.topics.gate.preview.figure.${f.key}`, f.key)}
                value={f.key.endsWith("_pct") ? pctText(f.value) : figureText(f.value)}
              />
            ))}
          </div>
        </Block>
      ) : null}
      <Note>{t("ai.topics.gate.recordNote")}</Note>
    </div>
  );
}

function GatePanel({ section }: { section: EntityResearchOverview["gate"] }) {
  return (
    <Panel
      title={t("ai.topics.gate.title")}
      subtitle={t("ai.topics.gate.subtitle")}
      bodyClassName="p-4"
    >
      <SectionView section={section}>
        {(g) => (g === null ? <Note>{t("ai.topics.gate.none")}</Note> : <GateBody g={g} />)}
      </SectionView>
    </Panel>
  );
}

// ── v1 against research v2 ───────────────────────────────────────────────────

function ComparisonBody({ c }: { c: ResearchComparison }) {
  const statuses = orderedCounts(c.extractor_by_status, EXTRACTOR_STATUSES);
  return (
    <div className="space-y-4" data-testid="topics-comparison">
      <StatGrid testId="topics-comparison-stats">
        <Stat
          label={t("ai.topics.comparison.stat.passes")}
          value={localInt(c.passes_compared)}
          hint={t("ai.topics.comparison.stat.passesHint", {
            n: c.passes_in_shadow,
            failed: c.passes_v2_failed,
            cut: c.passes_v2_cut_short,
          })}
        />
        <Stat label={t("ai.topics.comparison.stat.searchesV1")} value={localInt(c.searches_v1)} />
        <Stat
          label={t("ai.topics.comparison.stat.searchesV2")}
          value={localInt(c.searches_v2_alone)}
          hint={t("ai.topics.comparison.stat.searchesV2Hint")}
        />
        <Stat
          label={t("ai.topics.comparison.stat.saved")}
          value={localInt(c.saved)}
          hint={pctText(c.saved_pct)}
          tone={c.saved > 0 ? "positive" : c.saved < 0 ? "negative" : "default"}
        />
        <Stat
          label={t("ai.topics.comparison.stat.reuse")}
          value={pctText(c.reuse_pct)}
          hint={t("ai.topics.comparison.stat.reuseHint")}
        />
        <Stat
          label={t("ai.topics.comparison.stat.coverage")}
          value={pctText(c.coverage_pct)}
          hint={t("ai.topics.comparison.stat.coverageHint", {
            found: c.found_by_v2,
            facts: c.facts_v1,
          })}
        />
        <Stat
          label={t("ai.topics.comparison.stat.players")}
          value={pctText(c.coverage_players_pct)}
          hint={t("ai.topics.comparison.stat.playersHint")}
        />
        <Stat
          label={t("ai.topics.comparison.stat.perMatch")}
          value={`${figureText(c.facts_per_match_v1)} · ${figureText(c.facts_per_match_v2)}`}
          hint={t("ai.topics.comparison.stat.perMatchHint", { n: c.fixtures })}
        />
        <Stat
          label={t("ai.topics.comparison.stat.exaV1")}
          value={usd(c.exa_v1_usd)}
          hint={t("ai.topics.comparison.stat.exaSearches", { n: c.exa_v1_searches })}
        />
        <Stat
          label={t("ai.topics.comparison.stat.exaV2")}
          value={usd(c.exa_v2_usd)}
          hint={t("ai.topics.comparison.stat.exaSearches", { n: c.exa_v2_searches })}
        />
        <Stat
          label={t("ai.topics.comparison.stat.extractor")}
          value={localInt(c.extractor_calls)}
          hint={statuses.map(([k, n]) => `${k} ${localInt(n)}`).join(" · ") || undefined}
        />
        <Stat
          label={t("ai.topics.comparison.stat.invalid")}
          value={pctText(c.extractor_invalid_pct)}
          hint={t("ai.topics.comparison.stat.invalidHint")}
        />
      </StatGrid>
      <Block
        title={t("ai.topics.comparison.missed.title")}
        hint={t("ai.topics.comparison.missed.hint")}
      >
        {c.missed_examples.length === 0 ? (
          <Note>{t("ai.topics.comparison.missed.none")}</Note>
        ) : (
          <ul className="space-y-1 text-xs" data-testid="topics-missed">
            {c.missed_examples.map((m) => (
              <li key={missedLine(m)} className="numeric break-words">
                {missedLine(m)}
              </li>
            ))}
          </ul>
        )}
      </Block>
    </div>
  );
}

function ComparisonPanel({ section }: { section: EntityResearchOverview["comparison"] }) {
  const range = section.data
    ? t("ai.topics.comparison.range", {
        first: dayShort(section.data.first),
        last: dayShort(section.data.last),
      })
    : "";
  return (
    <Panel
      title={t("ai.topics.comparison.title")}
      subtitle={`${t("ai.topics.comparison.subtitle")} ${range}`.trim()}
      bodyClassName="p-4"
    >
      <SectionView section={section}>
        {(c) =>
          c === null ? <Note>{t("ai.topics.comparison.none")}</Note> : <ComparisonBody c={c} />
        }
      </SectionView>
    </Panel>
  );
}

// ── the cache: what each topic keeps ─────────────────────────────────────────

function TopicLine({ r }: { r: TopicRow }) {
  const fresh = freshShare(r);
  return (
    <TRow>
      <TD>
        <div className="font-medium">
          {translateOr(`ai.topics.freshness.topic.${r.topic}`, r.topic)}
        </div>
        <div className="mt-0.5 text-caption text-muted-foreground">{r.label}</div>
      </TD>
      <TD className="text-xs">{translateOr(`ai.topics.entity.${r.entity}`, r.entity)}</TD>
      <TD className="numeric text-xs">{r.levels.join(" · ")}</TD>
      <TD className="numeric whitespace-nowrap text-xs">
        {hoursText(r.early_hours)} / {hoursText(r.late_hours)}
      </TD>
      <TD align="right">{localInt(r.entries)}</TD>
      <TD align="right">
        {localInt(r.fresh)}
        {fresh === null ? null : (
          <span className="ml-1 text-caption text-muted-foreground">{share(fresh)}</span>
        )}
      </TD>
      <TD align="right">{localInt(r.expired)}</TD>
      <TD align="right">{localInt(r.reuses)}</TD>
      <TD className="whitespace-nowrap text-xs">{when(r.newest_at)}</TD>
      <TD className="whitespace-nowrap text-xs">{when(r.last_reuse_at)}</TD>
    </TRow>
  );
}

function FreshnessPanel({ f }: { f: ResearchFreshness }) {
  const kept = f.topics.reduce((sum, r) => sum + r.entries, 0);
  return (
    <Panel
      title={t("ai.topics.freshness.title")}
      subtitle={t("ai.topics.freshness.subtitle")}
      bodyClassName="space-y-3 p-4"
    >
      <Framed>
        <TableShell>
          <THead>
            <TH>{t("ai.topics.freshness.col.topic")}</TH>
            <TH>{t("ai.topics.freshness.col.entity")}</TH>
            <TH>{t("ai.topics.freshness.col.levels")}</TH>
            <TH>{t("ai.topics.freshness.col.rule")}</TH>
            <TH align="right">{t("ai.topics.freshness.col.entries")}</TH>
            <TH align="right">{t("ai.topics.freshness.col.fresh")}</TH>
            <TH align="right">{t("ai.topics.freshness.col.expired")}</TH>
            <TH align="right">{t("ai.topics.freshness.col.reuses")}</TH>
            <TH>{t("ai.topics.freshness.col.newest")}</TH>
            <TH>{t("ai.topics.freshness.col.lastReuse")}</TH>
          </THead>
          <tbody>
            {f.topics.map((r) => (
              <TopicLine key={r.topic} r={r} />
            ))}
          </tbody>
        </TableShell>
      </Framed>
      <Note>{t("ai.topics.freshness.window", { n: f.late_window_hours })}</Note>
      {kept === 0 ? <Note>{t("ai.topics.freshness.empty")}</Note> : null}
      {f.unreadable > 0 ? (
        <Note className="text-warning">
          {t("ai.topics.freshness.unreadable", { n: f.unreadable })}
        </Note>
      ) : null}
    </Panel>
  );
}

// ── the answers kept ─────────────────────────────────────────────────────────

function AnswerLine({ a }: { a: AnswerRow }) {
  const tiers = tierCounts(a);
  return (
    <TRow>
      <TD className="max-w-[18rem]">
        <div className="font-medium break-words">{entityName(a)}</div>
        <div className="mt-0.5 text-caption text-muted-foreground">
          {translateOr(`ai.topics.entity.${a.kind}`, a.kind)}
          {a.kickoff_at ? ` · ${bogotaDateTime(a.kickoff_at)}` : ""}
        </div>
      </TD>
      <TD className="text-xs">{translateOr(`ai.topics.freshness.topic.${a.topic}`, a.topic)}</TD>
      <TD align="right">{a.level === null ? DASH : localInt(a.level)}</TD>
      <TD align="right">{a.results === null ? DASH : localInt(a.results)}</TD>
      <TD>
        {a.standing === null ? (
          <span className="text-muted-foreground">{DASH}</span>
        ) : (
          <StatusBadge tone={a.standing ? "positive" : "warning"} dot={false}>
            {t(`ai.topics.answers.standing.${a.standing ? "yes" : "no"}`)}
          </StatusBadge>
        )}
      </TD>
      <TD className="max-w-[16rem] text-xs">
        {tiers.length === 0 ? (
          <span className="text-muted-foreground">{DASH}</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {tiers.map(([tier, n]) => (
              <StatusBadge key={tier} tone="neutral" dot={false}>
                {translateOr(`ai.topics.answers.tier.${tier}`, tier)} · {localInt(n)}
              </StatusBadge>
            ))}
          </div>
        )}
      </TD>
      <TD className="whitespace-nowrap text-xs">{bogotaDateTime(a.fetched_at)}</TD>
      <TD>
        <StatusBadge tone={a.fresh ? "positive" : "neutral"} dot={false}>
          {t(`ai.topics.answers.fresh.${a.fresh ? "yes" : "no"}`)}
        </StatusBadge>
        <div className="mt-0.5 whitespace-nowrap text-caption text-muted-foreground">
          {t("ai.topics.answers.until", { at: bogotaDateTime(a.expires_at) })}
        </div>
      </TD>
      <TD align="right">{localInt(a.reuses)}</TD>
      <TD align="right">
        {localInt(a.claims)}
        <span className="ml-1 text-caption text-muted-foreground">
          {t("ai.topics.answers.claimsFresh", { n: a.claims_fresh })}
        </span>
      </TD>
    </TRow>
  );
}

function AnswersPanel({ answers, days }: { answers: AnswerRow[]; days: number }) {
  return (
    <Panel
      title={t("ai.topics.answers.title")}
      subtitle={t("ai.topics.answers.subtitle", { days })}
      bodyClassName="space-y-3 p-4"
    >
      {answers.length === 0 ? (
        <Note>{t("ai.topics.answers.empty")}</Note>
      ) : (
        <Framed>
          <TableShell>
            <THead>
              <TH>{t("ai.topics.answers.col.entity")}</TH>
              <TH>{t("ai.topics.answers.col.topic")}</TH>
              <TH align="right">{t("ai.topics.answers.col.level")}</TH>
              <TH align="right">{t("ai.topics.answers.col.results")}</TH>
              <TH>{t("ai.topics.answers.col.standing")}</TH>
              <TH>{t("ai.topics.answers.col.tiers")}</TH>
              <TH>{t("ai.topics.answers.col.fetched")}</TH>
              <TH>{t("ai.topics.answers.col.state")}</TH>
              <TH align="right">{t("ai.topics.answers.col.reuses")}</TH>
              <TH align="right">{t("ai.topics.answers.col.claims")}</TH>
            </THead>
            <tbody>
              {answers.map((a) => (
                <AnswerLine key={answerKey(a)} a={a} />
              ))}
            </tbody>
          </TableShell>
        </Framed>
      )}
    </Panel>
  );
}

// ── the claims ───────────────────────────────────────────────────────────────

function BreakdownTable({
  rows,
  statuses,
  word,
  testId,
}: {
  rows: ClaimBreakdown[];
  statuses: string[];
  word: "class" | "type";
  testId: string;
}) {
  return (
    <Framed>
      <TableShell compact>
        <THead>
          <TH>{t(`ai.topics.claims.col.${word}`)}</TH>
          <TH align="right">{t("ai.topics.claims.col.total")}</TH>
          <TH align="right">{t("ai.topics.claims.col.fresh")}</TH>
          {statuses.map((s) => (
            <TH key={s} align="right">
              {translateOr(`ai.topics.claims.status.${s}`, s)}
            </TH>
          ))}
        </THead>
        <tbody data-testid={testId}>
          {rows.map((r) => {
            const cells = new Map(statusCells(r));
            return (
              <TRow key={r.key}>
                <TD>
                  <span className="font-medium">
                    {translateOr(`ai.topics.claims.${word}.${r.key}`, r.key)}
                  </span>
                  {word === "class" ? (
                    <StatusBadge
                      tone={CLASS_TONE[r.key] ?? "neutral"}
                      dot={false}
                      className="ml-2 align-middle"
                    >
                      {r.key}
                    </StatusBadge>
                  ) : null}
                </TD>
                <TD align="right" className={r.total === 0 ? "text-muted-foreground" : ""}>
                  {localInt(r.total)}
                </TD>
                <TD align="right">{localInt(r.fresh)}</TD>
                {statuses.map((s) => (
                  <TD key={s} align="right" className={cells.get(s) ? "" : "text-muted-foreground"}>
                    {localInt(cells.get(s) ?? 0)}
                  </TD>
                ))}
              </TRow>
            );
          })}
        </tbody>
      </TableShell>
    </Framed>
  );
}

function ClaimsPanel({ c }: { c: ResearchClaims }) {
  const statuses = usedStatuses([...c.by_class, ...c.by_type]);
  const silent = silentClasses(c.by_class);
  return (
    <Panel
      title={t("ai.topics.claims.title")}
      subtitle={t("ai.topics.claims.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <StatGrid testId="topics-claims-stats">
        <Stat label={t("ai.topics.claims.stat.total")} value={localInt(c.total)} />
        <Stat label={t("ai.topics.claims.stat.fresh")} value={localInt(c.fresh)} />
        <Stat
          label={t("ai.topics.claims.stat.entity")}
          value={localInt(c.entity_scoped)}
          hint={t("ai.topics.claims.stat.entityHint")}
        />
        <Stat label={t("ai.topics.claims.stat.match")} value={localInt(c.match_scoped)} />
        <Stat
          label={t("ai.topics.claims.stat.flagged")}
          value={localInt(c.flagged)}
          hint={t("ai.topics.claims.stat.flaggedHint")}
          tone={c.flagged > 0 ? "warning" : "default"}
        />
      </StatGrid>
      {c.total === 0 ? (
        <Note>{t("ai.topics.claims.empty")}</Note>
      ) : (
        <div className="flex flex-wrap gap-2" data-testid="topics-claims-status">
          {orderedCounts(c.by_status, CLAIM_STATUSES).map(([status, n]) => (
            <StatusBadge key={status} tone={STATUS_TONE[status] ?? "neutral"} dot={false}>
              {translateOr(`ai.topics.claims.status.${status}`, status)} · {localInt(n)}
            </StatusBadge>
          ))}
        </div>
      )}
      <Block title={t("ai.topics.claims.byClass")} hint={t("ai.topics.claims.byClassHint")}>
        <BreakdownTable
          rows={c.by_class}
          statuses={statuses}
          word="class"
          testId="topics-claims-by-class"
        />
        {silent.length > 0 && c.total > 0 ? (
          <Note>
            {t("ai.topics.claims.silent", {
              list: silent.map((k) => translateOr(`ai.topics.claims.class.${k}`, k)).join(", "),
            })}
          </Note>
        ) : null}
      </Block>
      <Block title={t("ai.topics.claims.byType")}>
        <BreakdownTable
          rows={c.by_type}
          statuses={statuses}
          word="type"
          testId="topics-claims-by-type"
        />
      </Block>
    </Panel>
  );
}

// ── the days ─────────────────────────────────────────────────────────────────

function DayLine({ d }: { d: ResearchDay }) {
  const reuse = reuseShare(d);
  return (
    <TRow>
      <TD className="whitespace-nowrap">{dayShort(d.day)}</TD>
      <TD align="right">{localInt(d.passes)}</TD>
      <TD align="right">{localInt(d.passes_v2)}</TD>
      <TD align="right" className={d.passes_failed > 0 ? "text-negative" : ""}>
        {localInt(d.passes_failed)}
      </TD>
      <TD align="right" className={d.passes_cut > 0 ? "text-warning" : ""}>
        {localInt(d.passes_cut)}
      </TD>
      <TD align="right">{localInt(d.searches)}</TD>
      <TD align="right">{localInt(d.demand)}</TD>
      <TD align="right">{localInt(d.paid)}</TD>
      <TD align="right">{localInt(d.shared)}</TD>
      <TD align="right">{localInt(d.reused)}</TD>
      <TD align="right">{share(reuse)}</TD>
      <TD align="right">
        {localInt(d.pages)}
        <span className="ml-1 text-caption text-muted-foreground">
          {t("ai.topics.days.known", { n: d.pages_known })}
        </span>
      </TD>
      <TD align="right">
        {localInt(d.claims)}
        <span className="ml-1 text-caption text-muted-foreground">
          {t("ai.topics.days.new", { n: d.claims_new })}
        </span>
      </TD>
      <TD align="right">{usd(d.exa_v1_usd)}</TD>
      <TD align="right">{usd(d.exa_v2_usd)}</TD>
    </TRow>
  );
}

function DaysPanel({ days }: { days: ResearchDay[] }) {
  const total = dayTotals(days);
  return (
    <Panel
      title={t("ai.topics.days.title")}
      subtitle={t("ai.topics.days.subtitle")}
      bodyClassName="space-y-3 p-4"
    >
      <Framed>
        <TableShell>
          <THead>
            <TH>{t("ai.topics.days.col.day")}</TH>
            <TH align="right">{t("ai.topics.days.col.passes")}</TH>
            <TH align="right">{t("ai.topics.days.col.v2")}</TH>
            <TH align="right">{t("ai.topics.days.col.failed")}</TH>
            <TH align="right">{t("ai.topics.days.col.cut")}</TH>
            <TH align="right">{t("ai.topics.days.col.searches")}</TH>
            <TH align="right">{t("ai.topics.days.col.demand")}</TH>
            <TH align="right">{t("ai.topics.days.col.paid")}</TH>
            <TH align="right">{t("ai.topics.days.col.shared")}</TH>
            <TH align="right">{t("ai.topics.days.col.reused")}</TH>
            <TH align="right">{t("ai.topics.days.col.reuse")}</TH>
            <TH align="right">{t("ai.topics.days.col.pages")}</TH>
            <TH align="right">{t("ai.topics.days.col.claims")}</TH>
            <TH align="right">{t("ai.topics.days.col.exaV1")}</TH>
            <TH align="right">{t("ai.topics.days.col.exaV2")}</TH>
          </THead>
          <tbody data-testid="topics-days">
            {days.map((d) => (
              <DayLine key={d.day} d={d} />
            ))}
            <TRow className="font-medium">
              <TD>{t("ai.topics.days.total")}</TD>
              <TD align="right">{localInt(total.passes)}</TD>
              <TD align="right">{localInt(total.passes_v2)}</TD>
              <TD align="right">{localInt(total.passes_failed)}</TD>
              <TD align="right">{localInt(total.passes_cut)}</TD>
              <TD align="right">{localInt(total.searches)}</TD>
              <TD align="right">{localInt(total.demand)}</TD>
              <TD align="right">{localInt(total.paid)}</TD>
              <TD align="right">{localInt(total.shared)}</TD>
              <TD align="right">{localInt(total.reused)}</TD>
              <TD align="right">{share(reuseShare(total))}</TD>
              <TD align="right">{localInt(total.pages)}</TD>
              <TD align="right">{localInt(total.claims)}</TD>
              <TD align="right">{usd(total.exa_v1_usd)}</TD>
              <TD align="right">{usd(total.exa_v2_usd)}</TD>
            </TRow>
          </tbody>
        </TableShell>
      </Framed>
      <Note>{t("ai.topics.days.hint")}</Note>
    </Panel>
  );
}

// ── the pages ────────────────────────────────────────────────────────────────

function PagesPanel({ p }: { p: PageCache }) {
  return (
    <Panel
      title={t("ai.topics.pages.title")}
      subtitle={t("ai.topics.pages.subtitle")}
      bodyClassName="p-4"
    >
      <StatGrid testId="topics-pages">
        <Stat label={t("ai.topics.pages.stat.remembered")} value={localInt(p.remembered)} />
        <Stat label={t("ai.topics.pages.stat.fresh")} value={localInt(p.fresh)} />
        <Stat label={t("ai.topics.pages.stat.reuses")} value={localInt(p.reuses)} />
        <Stat label={t("ai.topics.pages.stat.read")} value={localInt(p.read)} />
        <Stat label={t("ai.topics.pages.stat.known")} value={localInt(p.known)} />
        <Stat
          label={t("ai.topics.pages.stat.unread")}
          value={localInt(p.unread)}
          hint={t("ai.topics.pages.stat.unreadHint")}
        />
        <Stat
          label={t("ai.topics.pages.stat.flagged")}
          value={localInt(p.flagged)}
          hint={t("ai.topics.pages.stat.flaggedHint")}
          tone={p.flagged > 0 ? "warning" : "default"}
        />
      </StatGrid>
    </Panel>
  );
}

// ── the tab ──────────────────────────────────────────────────────────────────

/** Everything the view shows, given the figures: the part of the view that needs no server. */
export function TopicsBody({ o }: { o: EntityResearchOverview }) {
  return (
    <div className="space-y-4" data-testid="topics-body">
      <AttentionLine o={o} />
      <SwitchPanel s={o.switch} />
      <GatePanel section={o.gate} />
      <ComparisonPanel section={o.comparison} />
      <FreshnessPanel f={o.freshness} />
      <AnswersPanel answers={o.answers} days={o.days} />
      <ClaimsPanel c={o.claims} />
      <DaysPanel days={o.per_day} />
      <PagesPanel p={o.pages} />
    </div>
  );
}

/** POR ENTIDAD Y TEMA: a view of the AI work of Operación. */
export function TopicsView() {
  const q = useLiveQuery(live.aiResearchEntities());
  const o = q.data?.data ?? null;
  return (
    <div className="space-y-4" data-testid="operation-topics">
      <Note>{t("ai.topics.intro")}</Note>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {o ? <TopicsBody o={o} /> : q.isLoading ? <TableSkeleton rows={6} cols={5} /> : null}
    </div>
  );
}

/**
 * ATRIBUCIÓN (Aprendizaje > Atribución, plan IA phase 5): which agent, in which version, was right or wrong about each settled selection of the shadow
 * - computed by the server from codes, never by a model -, the share of matches with attributions against the plan's bar for Gate B, hits and misses
 * per agent and version, the post-mortems with what each agent did and the reviewer's narrative, and the hypotheses the Learning Analyst proposed per
 * version with the ids of the attributions they cite. Reading only: it changes no pick, rule, model or hypothesis, and it never says a gate passed.
 */
import { t, translateOr } from "@/lib/i18n";
import { DASH, localInt, localPct } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  AttributedHypothesis,
  AttributionLine,
  AttributionOverview,
  PostmortemAttribution,
} from "@/lib/api/v1/types_ai_attribution";
import { Block, Fact, Framed, Note, Stat, StatGrid } from "./AiBits";
import { bogotaDateTime } from "./aiModel";
import { citedIds, coverageState, outcomeTone, sortedClasses } from "./attributionModel";

const pct = (x: number | null) => (x === null ? DASH : localPct(x, 1));
const klass = (c: string) => translateOr(`ai.attribution.class.${c}`, c);

function Switches({ d }: { d: AttributionOverview }) {
  const s = d.switches;
  return (
    <Block title={t("ai.attribution.switches.title")} hint={t("ai.attribution.switches.hint")}>
      <StatGrid testId="attribution-switches">
        <Stat
          label={t("ai.attribution.switches.reviewer")}
          value={t(s.pm_reviewer ? "ai.attribution.switches.on" : "ai.attribution.switches.off")}
          hint={`${s.reviewer_version} · ${s.attribution_version}`}
          tone={s.pm_reviewer ? "positive" : "default"}
        />
        <Stat
          label={t("ai.attribution.switches.analyst")}
          value={t(
            s.learning_analyst ? "ai.attribution.switches.on" : "ai.attribution.switches.off",
          )}
          hint={s.analyst_version}
          tone={s.learning_analyst ? "positive" : "default"}
        />
      </StatGrid>
    </Block>
  );
}

function CoverageBlock({ d }: { d: AttributionOverview }) {
  const c = d.coverage;
  const state = coverageState(c);
  return (
    <Block
      title={t("ai.attribution.coverage.title", { days: d.days })}
      hint={t("ai.attribution.coverage.hint", { bar: localPct(c.bar, 0) })}
    >
      <StatGrid testId="attribution-coverage">
        <Stat
          label={t("ai.attribution.coverage.matches")}
          value={pct(c.match_share)}
          hint={t("ai.attribution.coverage.of", { n: c.attributed_matches, total: c.matches })}
          tone={state === "reached" ? "positive" : state === "below" ? "warning" : "default"}
        />
        <Stat
          label={t("ai.attribution.coverage.selections")}
          value={pct(c.selection_share)}
          hint={t("ai.attribution.coverage.of", {
            n: c.attributed_selections,
            total: c.selections,
          })}
        />
        <Stat label={t("ai.attribution.coverage.bar")} value={localPct(c.bar, 0)} />
      </StatGrid>
      <div className="text-xs text-muted-foreground" data-testid="attribution-coverage-state">
        {t(`ai.attribution.coverage.state.${state}`)}
      </div>
    </Block>
  );
}

function Scoreboard({ d }: { d: AttributionOverview }) {
  return (
    <Block title={t("ai.attribution.score.title")} hint={t("ai.attribution.score.hint")}>
      {d.scoreboard.length === 0 ? (
        <Note>{t("ai.attribution.score.empty")}</Note>
      ) : (
        <Framed>
          <TableShell>
            <THead>
              <TH>{t("ai.attribution.col.agent")}</TH>
              <TH>{t("ai.attribution.col.engine")}</TH>
              <TH align="right">{t("ai.attribution.col.hits")}</TH>
              <TH align="right">{t("ai.attribution.col.misses")}</TH>
              <TH align="right">{t("ai.attribution.col.voids")}</TH>
              <TH align="right">{t("ai.attribution.col.rate")}</TH>
            </THead>
            <tbody>
              {d.scoreboard.map((r) => (
                <TRow key={`${r.engine}-${r.agent}-${r.agent_version}`} data-testid="score-row">
                  <TD>
                    <span className="font-medium">{r.agent}</span>{" "}
                    <span className="numeric text-caption text-muted-foreground">
                      {r.agent_version}
                    </span>
                  </TD>
                  <TD className="numeric">{r.engine}</TD>
                  <TD align="right">{localInt(r.hits)}</TD>
                  <TD align="right">{localInt(r.misses)}</TD>
                  <TD align="right">{localInt(r.voids)}</TD>
                  <TD align="right">{pct(r.hit_rate)}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Framed>
      )}
    </Block>
  );
}

function Classes({ d }: { d: AttributionOverview }) {
  if (d.classes.length === 0) return null;
  return (
    <Block title={t("ai.attribution.classes.title")} hint={t("ai.attribution.classes.hint")}>
      <Framed>
        <TableShell>
          <THead>
            <TH>{t("ai.attribution.col.agent")}</TH>
            <TH>{t("ai.attribution.col.class")}</TH>
            <TH align="right">{t("ai.attribution.col.n")}</TH>
            <TH align="right">{t("ai.attribution.col.refined")}</TH>
          </THead>
          <tbody>
            {sortedClasses(d.classes).map((r) => (
              <TRow key={`${r.agent}-${r.agent_version}-${r.error_class}`} data-testid="class-row">
                <TD>
                  {r.agent} <span className="numeric text-caption">{r.agent_version}</span>
                </TD>
                <TD>{klass(r.error_class)}</TD>
                <TD align="right">{localInt(r.n)}</TD>
                <TD align="right">{localInt(r.refined)}</TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Framed>
    </Block>
  );
}

function LineRow({ l }: { l: AttributionLine }) {
  return (
    <TRow data-testid="attribution-line">
      <TD>
        {l.agent}{" "}
        <span className="numeric text-caption text-muted-foreground">{l.agent_version}</span>
        <div className="numeric text-caption text-muted-foreground">{l.engine}</div>
      </TD>
      <TD>{translateOr(`ai.attribution.signal.${l.signal}`, l.signal)}</TD>
      <TD>{translateOr(`ai.attribution.stance.${l.stance}`, l.stance)}</TD>
      <TD>
        <StatusBadge tone={outcomeTone(l.outcome)} dot={false}>
          {t(`ai.attribution.outcome.${l.outcome}`)}
        </StatusBadge>
      </TD>
      <TD>
        {l.outcome === "MISS" ? klass(l.error_class) : DASH}
        {l.refined_class ? (
          <div className="text-caption text-muted-foreground">
            {t("ai.attribution.refined", { klass: klass(l.refined_class) })}
          </div>
        ) : null}
      </TD>
      <TD>
        {l.toward_close === null
          ? DASH
          : t(l.toward_close ? "ai.attribution.close.toward" : "ai.attribution.close.away")}
      </TD>
    </TRow>
  );
}

function PostmortemCard({ p }: { p: PostmortemAttribution }) {
  return (
    <div
      className="space-y-2 rounded-md border border-border px-3 py-2"
      data-testid={`attribution-pm-${p.postmortem_id}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">{p.match}</span>
        <span className="text-xs text-muted-foreground">{bogotaDateTime(p.kickoff_at)}</span>
        <span className="numeric text-xs">
          {p.market_key} · {p.selection}
          {p.line !== 0 ? ` ${p.line}` : ""}
        </span>
        <StatusBadge tone="neutral" dot={false}>
          {translateOr(`ai.attribution.settled.${p.settled}`, p.settled)}
        </StatusBadge>
      </div>
      <div className="flex flex-wrap gap-x-4 text-xs text-muted-foreground">
        <span>
          {t("ai.attribution.clv")}: {p.clv === null ? DASH : localPct(p.clv, 2, true)}
        </span>
        <span>
          {t("ai.attribution.calibration")}:{" "}
          {p.calibration
            ? translateOr(`ai.attribution.calib.${p.calibration}`, p.calibration)
            : DASH}
        </span>
      </div>
      <Framed>
        <TableShell>
          <THead>
            <TH>{t("ai.attribution.col.agent")}</TH>
            <TH>{t("ai.attribution.col.signal")}</TH>
            <TH>{t("ai.attribution.col.stance")}</TH>
            <TH>{t("ai.attribution.col.outcome")}</TH>
            <TH>{t("ai.attribution.col.class")}</TH>
            <TH>{t("ai.attribution.col.close")}</TH>
          </THead>
          <tbody>
            {p.lines.map((l) => (
              <LineRow key={`${l.engine}-${l.agent}-${l.signal}`} l={l} />
            ))}
          </tbody>
        </TableShell>
      </Framed>
      {p.narrative ? (
        <div className="text-xs" data-testid="attribution-narrative">
          <div className="font-medium">{t("ai.attribution.narrative")}</div>
          <p className="mt-0.5 whitespace-pre-wrap text-foreground/85">{p.narrative}</p>
        </div>
      ) : null}
    </div>
  );
}

function HypothesisCard({ h }: { h: AttributedHypothesis }) {
  const experiment = h.experiment ? Object.entries(h.experiment) : [];
  return (
    <div
      className="space-y-1 rounded-md border border-border px-3 py-2"
      data-testid={`attribution-hypothesis-${h.id}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone="brand" dot={false}>
          {h.agent} · {h.agent_version}
        </StatusBadge>
        <StatusBadge tone="neutral" dot={false}>
          {translateOr(`ai.attribution.hstatus.${h.status}`, h.status)}
        </StatusBadge>
        <span className="font-medium">{h.title}</span>
      </div>
      <p className="text-xs text-foreground/85">{h.hypothesis}</p>
      <p className="text-xs text-muted-foreground">{h.rationale}</p>
      <Fact
        label={t("ai.attribution.cites", { n: h.attribution_ids.length })}
        value={h.attribution_ids.length > 0 ? citedIds(h.attribution_ids) : DASH}
      />
      {h.week_from ? <Fact label={t("ai.attribution.week")} value={h.week_from} /> : null}
      {experiment.length > 0 ? (
        <div data-testid="attribution-experiment">
          <div className="text-xs font-medium">{t("ai.attribution.experiment")}</div>
          {experiment.map(([k, v]) => (
            <Fact key={k} label={k} value={typeof v === "string" ? v : JSON.stringify(v)} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** Everything the panel shows, given the figures: the part that needs no server. */
export function AttributionBody({ d }: { d: AttributionOverview }) {
  return (
    <div className="space-y-4" data-testid="attribution-body">
      <Switches d={d} />
      <CoverageBlock d={d} />
      <Scoreboard d={d} />
      <Classes d={d} />
      <Block
        title={t("ai.attribution.postmortems.title")}
        hint={t("ai.attribution.postmortems.hint")}
      >
        {d.postmortems.length === 0 ? (
          <Note>{t("ai.attribution.postmortems.empty")}</Note>
        ) : (
          <div className="space-y-2">
            {d.postmortems.map((p) => (
              <PostmortemCard key={p.postmortem_id} p={p} />
            ))}
          </div>
        )}
      </Block>
      <Block
        title={t("ai.attribution.hypotheses.title")}
        hint={t("ai.attribution.hypotheses.hint")}
      >
        {d.hypothesis_counts.length > 0 ? (
          <Framed>
            <TableShell>
              <THead>
                <TH>{t("ai.attribution.col.agent")}</TH>
                <TH align="right">{t("ai.attribution.col.proposed")}</TH>
                <TH align="right">{t("ai.attribution.col.accepted")}</TH>
                <TH align="right">{t("ai.attribution.col.rejected")}</TH>
                <TH align="right">{t("ai.attribution.col.other")}</TH>
              </THead>
              <tbody>
                {d.hypothesis_counts.map((c) => (
                  <TRow key={`${c.agent}-${c.agent_version}`} data-testid="hypothesis-count">
                    <TD>
                      {c.agent} <span className="numeric text-caption">{c.agent_version}</span>
                    </TD>
                    <TD align="right">{localInt(c.proposed)}</TD>
                    <TD align="right">{localInt(c.accepted)}</TD>
                    <TD align="right">{localInt(c.rejected)}</TD>
                    <TD align="right">{localInt(c.other)}</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          </Framed>
        ) : null}
        {d.hypotheses.length === 0 ? (
          <Note>{t("ai.attribution.hypotheses.empty")}</Note>
        ) : (
          <div className="space-y-2">
            {d.hypotheses.map((h) => (
              <HypothesisCard key={h.id} h={h} />
            ))}
          </div>
        )}
      </Block>
    </div>
  );
}

/** ATRIBUCIÓN: the panel of Aprendizaje > Atribución. */
export function AttributionPanel() {
  const q = useLiveQuery(live.aiAttribution());
  const d = q.data?.data ?? null;
  return (
    <Panel
      title={t("ai.attribution.title")}
      subtitle={t("ai.attribution.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <div data-testid="attribution">
        <Note>{t("ai.attribution.intro")}</Note>
        {q.isError ? <ApiErrorNotice error={q.error} /> : null}
        {d ? <AttributionBody d={d} /> : q.isLoading ? <TableSkeleton rows={5} cols={6} /> : null}
      </div>
    </Panel>
  );
}

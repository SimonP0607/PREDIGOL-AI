/**
 * LAS FAMILIAS EN SHADOW (plan F10.17 and F11.11), a tab of Aprendizaje: what corners, cards, yellow cards and the goals of the halves decide
 * when they are only being measured. Their decisions are not picks (`decision-fam-v1`: the state reaches INVESTIGACION at most, the stake is
 * zero), so this is the one place they are read:
 *
 *   EL CICLO      the four steps of the worker (decide, settle, post-mortem, remember), when each last worked and what it reported
 *   FAMILIAS      one card per family: how many selections, how many the filters refused, how many are settled, how they ended and which
 *                 rule grades them
 *   LA ÚLTIMA     the last word of each model on each market of each match, with the rule that grades it, what became of it and what the
 *   PALABRA       post-mortem found; a row opens the decision in full
 *   MEMORIA       what the families remember: the post-mortems added up by family, market, competition and referee
 *
 * Reading only. A family's probability is its model's own number, not calibrated, and nothing here is offered to a user.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import {
  DASH,
  fmtLine,
  fmtOdds,
  fmtPct,
  fmtSignedPct,
  fmtSignedPp,
  localFixed,
  localInt,
} from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  FamiliesCard,
  FamiliesItem,
  FamiliesMemoryRow,
  FamiliesRule,
  FamiliesStepRun,
  IntelFamilies,
} from "@/lib/api/v1/types_families";
import { Choice, Fact, Note, Stat, StatGrid, SubTitle, Toolbar } from "./AiBits";
import { bogotaDateTime } from "./aiModel";
import { DecisionDetail } from "./IntelligenceLive";
import {
  FAMILY_CODES,
  STEPS,
  WINDOWS,
  familyName,
  marketText,
  modeHelp,
  modeName,
  modeTone,
  msText,
  pickText,
  qualityName,
  reasonsShown,
  resultName,
  resultTone,
  ruleNote,
  ruleText,
  stateName,
  stateTone,
  statusName,
  stepFacts,
  stepName,
  stepTone,
  verdictHint,
  verdictName,
  verdictTone,
} from "./familiesText";

const STATES = ["INVESTIGACION", "RECHAZADO"] as const;
const DEFAULT_DAYS = 14;

// ── the cycle ────────────────────────────────────────────────────────────────────────────────────────────────────────────

function StepBox({ step, run }: { step: string; run: FamiliesStepRun | undefined }) {
  const facts = run ? stepFacts(step, run.result) : [];
  return (
    <div
      className="min-w-0 space-y-1.5 rounded-md border border-border bg-card p-3"
      data-testid={`families-step-${step}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{stepName(step)}</span>
        {run ? (
          <StatusBadge tone={stepTone(run.status)}>{statusName(run.status)}</StatusBadge>
        ) : null}
      </div>
      {run ? (
        <>
          <p className="text-caption text-subtle-foreground">
            {t("families.step.lastRun", { when: bogotaDateTime(run.started_at) })}
            {run.ms !== null ? ` · ${msText(run.ms)}` : ""}
          </p>
          <div>
            {facts.map((fact) => (
              <Fact key={fact.key} label={fact.label} value={fact.value} />
            ))}
          </div>
          {run.error ? (
            <p
              className="break-words text-caption text-negative"
              data-testid={`families-error-${step}`}
            >
              {t("families.step.error", { error: run.error })}
            </p>
          ) : null}
        </>
      ) : (
        <p className="text-caption text-subtle-foreground">{t("families.step.never")}</p>
      )}
    </div>
  );
}

function Cycle({ d }: { d: IntelFamilies }) {
  const byStep = new Map<string, FamiliesStepRun>(d.steps.map((s) => [s.step, s]));
  const help = modeHelp(d.mode);
  return (
    <section className="space-y-2" data-testid="families-cycle">
      <div className="flex flex-wrap items-center gap-2">
        <SubTitle>{t("families.cycle.title")}</SubTitle>
        <span data-testid="families-mode">
          <StatusBadge tone={modeTone(d.mode)}>{modeName(d.mode)}</StatusBadge>
        </span>
      </div>
      <Note>{t("families.cycle.help")}</Note>
      {help ? (
        <div data-testid="families-mode-help">
          <Note>{help}</Note>
        </div>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((step) => (
          <StepBox key={step} step={step} run={byStep.get(step)} />
        ))}
      </div>
      <Note>{t("families.versions", { ...d.versions })}</Note>
    </section>
  );
}

// ── one card per family ──────────────────────────────────────────────────────────────────────────────────────────────────

/** A count as a badge: "Ganada 12". */
function Counted({ tone, label, n }: { tone: BadgeTone; label: string; n: number }) {
  return (
    <StatusBadge tone={tone} dot={false}>
      {`${label} ${localInt(n)}`}
    </StatusBadge>
  );
}

function entries<T extends string>(counts: Partial<Record<T, number>>): Array<[T, number]> {
  return (Object.entries(counts) as Array<[T, number | undefined]>)
    .filter((entry): entry is [T, number] => (entry[1] ?? 0) > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** The newest snapshot of what a family remembers, as lines. */
function MemorySummary({ memory }: { memory: FamiliesMemoryRow }) {
  const all = memory.stats.all;
  return (
    <div data-testid="families-card-memory">
      <Fact label={t("families.memory.cols.n")} value={localInt(all.n)} />
      <Fact
        label={`${t("families.memory.cols.hit")} / ${t("families.memory.cols.claimed")}`}
        value={`${fmtPct(all.hit)} / ${fmtPct(all.claimed)}`}
      />
      <Fact label={t("families.memory.cols.clv")} value={fmtSignedPct(all.clv_mean, 2)} />
      <Fact label={t("families.memory.cols.roi")} value={fmtSignedPct(all.roi)} />
      <Fact
        label={t("families.memory.cols.confidence")}
        value={memory.confidence === null ? DASH : fmtPct(memory.confidence, 0)}
      />
      <p className="mt-1 text-caption text-subtle-foreground">
        {t("families.memory.asOf", { day: memory.as_of_day })}
      </p>
    </div>
  );
}

function FamilyCard({ card, rules }: { card: FamiliesCard; rules: Record<string, FamiliesRule> }) {
  const results = entries(card.results);
  const verdicts = entries(card.verdicts);
  const empty = card.selections + card.rejected === 0;
  return (
    <div
      className="min-w-0 space-y-3 rounded-md border border-border bg-card p-3"
      data-testid={`families-card-${card.family}`}
    >
      <h3 className="text-sm font-medium">{familyName(card.family)}</h3>
      <StatGrid className="sm:grid-cols-4 lg:grid-cols-4">
        <Stat
          label={t("families.card.selections")}
          value={localInt(card.selections)}
          hint={t("families.card.selectionsHint")}
        />
        <Stat
          label={t("families.card.rejected")}
          value={localInt(card.rejected)}
          hint={t("families.card.rejectedHint")}
        />
        <Stat label={t("families.card.settled")} value={localInt(card.settled)} />
        <Stat label={t("families.card.open")} value={localInt(card.open)} />
      </StatGrid>
      {empty ? <Note>{t("families.card.none")}</Note> : null}
      {results.length ? (
        <div className="space-y-1" data-testid="families-card-results">
          <SubTitle>{t("families.card.results")}</SubTitle>
          <div className="flex flex-wrap gap-1.5">
            {results.map(([result, n]) => (
              <Counted key={result} tone={resultTone(result)} label={resultName(result)} n={n} />
            ))}
          </div>
        </div>
      ) : null}
      {verdicts.length ? (
        <div className="space-y-1" data-testid="families-card-verdicts">
          <SubTitle>{t("families.card.verdicts")}</SubTitle>
          <div className="flex flex-wrap gap-1.5">
            {verdicts.map(([verdict, n]) => (
              <span key={verdict} title={verdictHint(verdict)}>
                <Counted tone={verdictTone(verdict)} label={verdictName(verdict)} n={n} />
              </span>
            ))}
          </div>
        </div>
      ) : null}
      <div className="space-y-1" data-testid="families-card-rules">
        <SubTitle>{t("families.card.rules")}</SubTitle>
        <ul className="space-y-1.5">
          {card.rules.map((key) => {
            const rule = rules[key];
            if (!rule) return null;
            const note = ruleNote(rule);
            return (
              <li key={key} className="text-xs">
                <span className="mr-1.5 font-mono text-caption text-subtle-foreground">{key}</span>
                {ruleText(rule)}
                {note ? <span className="text-subtle-foreground"> {note}</span> : null}
              </li>
            );
          })}
        </ul>
      </div>
      <div className="space-y-1">
        <SubTitle>{t("families.card.memory")}</SubTitle>
        {card.memory ? (
          <MemorySummary memory={card.memory} />
        ) : (
          <Note>{t("families.card.noMemory")}</Note>
        )}
      </div>
    </div>
  );
}

function Cards({ d }: { d: IntelFamilies }) {
  return (
    <section className="grid gap-3 lg:grid-cols-2" data-testid="families-cards">
      {d.families.map((card) => (
        <FamilyCard key={card.family} card={card} rules={d.rules} />
      ))}
    </section>
  );
}

// ── the last word of each family ─────────────────────────────────────────────────────────────────────────────────────────

function OutcomeCell({ x }: { x: FamiliesItem }) {
  const o = x.outcome;
  if (!o) {
    return (
      <StatusBadge tone="neutral" dot={false}>
        {t("families.items.open")}
      </StatusBadge>
    );
  }
  const figures = [
    o.profit_flat === null
      ? null
      : t("families.outcome.profit", { profit: fmtLine(o.profit_flat, true) }),
    o.clv === null ? null : t("families.outcome.clv", { clv: fmtSignedPct(o.clv) }),
  ].filter((figure) => figure !== null);
  return (
    <div className="space-y-0.5">
      <StatusBadge tone={resultTone(o.result)}>{resultName(o.result)}</StatusBadge>
      {figures.length ? (
        <div className="numeric text-caption text-muted-foreground">{figures.join(" · ")}</div>
      ) : null}
    </div>
  );
}

/** How many causes a row lists before it says "+N more" (all of them are in the decision's detail). */
const CAUSES_SHOWN = 2;

function PostmortemCell({ x }: { x: FamiliesItem }) {
  const p = x.postmortem;
  if (!p)
    return <span className="text-caption text-subtle-foreground">{t("families.pm.none")}</span>;
  const margin =
    p.margin === null
      ? ""
      : ` ${t("families.outcome.margin", { margin: fmtLine(p.margin, true) })}`;
  return (
    <div className="max-w-[18rem] space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <span title={verdictHint(p.verdict)}>
          <StatusBadge tone={verdictTone(p.verdict)}>{verdictName(p.verdict)}</StatusBadge>
        </span>
        <span className="text-caption text-muted-foreground">{qualityName(p.quality)}</span>
      </div>
      {p.actual !== null ? (
        <div className="numeric text-caption">
          {t("families.outcome.count", { actual: fmtLine(p.actual) })}
          {margin}
        </div>
      ) : null}
      {p.causes.slice(0, CAUSES_SHOWN).map((cause) => (
        <div key={cause} className="break-words text-caption text-muted-foreground">
          {cause}
        </div>
      ))}
      {p.causes.length > CAUSES_SHOWN ? (
        <div className="text-caption text-subtle-foreground">
          {t("families.pm.more", { count: p.causes.length - CAUSES_SHOWN })}
        </div>
      ) : null}
    </div>
  );
}

function ItemRow({
  x,
  rules,
  selected,
  onOpen,
}: {
  x: FamiliesItem;
  rules: Record<string, FamiliesRule>;
  selected: boolean;
  onOpen: ((id: number) => void) | undefined;
}) {
  const rule = x.rule === null ? undefined : rules[x.rule];
  const reasons = reasonsShown(x.reasons);
  return (
    <TRow selected={selected} {...(onOpen ? { onClick: () => onOpen(x.id) } : {})}>
      <TD className="max-w-[14rem] align-top">
        <div className="break-words text-sm">{x.match}</div>
        <div className="text-caption text-muted-foreground">
          {x.competition} · {bogotaDateTime(x.kickoff_at)} · {x.checkpoint}
        </div>
      </TD>
      <TD className="max-w-[16rem] align-top">
        <div className="text-caption text-muted-foreground" title={x.market_key}>
          {marketText(x.market_key)}
        </div>
        <div className="break-words text-sm font-medium">
          {pickText(x.market_key, x.selection, x.line, { home: x.home, away: x.away })}
        </div>
        <div className="text-caption text-subtle-foreground">
          {familyName(x.family)}
          {x.revisions > 1 ? ` · ${t("families.items.revisions", { count: x.revisions })}` : ""}
        </div>
      </TD>
      <TD align="right" className="numeric align-top">
        {fmtOdds(x.odds)}
      </TD>
      <TD align="right" className="numeric align-top">
        {fmtPct(x.p_model)}
      </TD>
      <TD align="right" className="numeric align-top">
        {fmtPct(x.p_market)}
      </TD>
      <TD align="right" className="numeric align-top">
        {fmtSignedPct(x.ev_raw)}
      </TD>
      <TD className="align-top">
        <StatusBadge tone={stateTone(x.state)}>{stateName(x.state)}</StatusBadge>
        {reasons.length ? (
          <div className="mt-1 max-w-[12rem] text-caption text-muted-foreground">
            {reasons.join(" · ")}
          </div>
        ) : null}
      </TD>
      <TD className="align-top text-xs">
        {rule ? (
          <span className="font-mono" title={ruleText(rule)}>
            {rule.key}
          </span>
        ) : (
          <span className="text-subtle-foreground">{t("families.items.noRule")}</span>
        )}
      </TD>
      <TD className="align-top">
        <OutcomeCell x={x} />
      </TD>
      <TD className="align-top">
        <PostmortemCell x={x} />
      </TD>
    </TRow>
  );
}

function Items({
  d,
  openId,
  onOpen,
}: {
  d: IntelFamilies;
  openId: number;
  onOpen: ((id: number) => void) | undefined;
}) {
  return (
    <section className="space-y-2" data-testid="families-items">
      <SubTitle>{t("families.items.title")}</SubTitle>
      <Note>{t("families.items.help")}</Note>
      <Note>
        {t("families.items.shown", {
          shown: localInt(d.items.length),
          total: localInt(d.total),
          days: localInt(d.window.days),
        })}
      </Note>
      {d.items.length === 0 ? (
        <div data-testid="families-items-empty">
          <Note>{t("families.items.empty")}</Note>
        </div>
      ) : (
        <TableShell>
          <THead>
            <TH>{t("families.cols.match")}</TH>
            <TH>{t("families.cols.market")}</TH>
            <TH align="right">{t("families.cols.odds")}</TH>
            <TH align="right" title={t("families.cols.pModelHint")}>
              {t("families.cols.pModel")}
            </TH>
            <TH align="right" title={t("families.cols.pMarketHint")}>
              {t("families.cols.pMarket")}
            </TH>
            <TH align="right" title={t("families.cols.evHint")}>
              {t("families.cols.ev")}
            </TH>
            <TH>{t("families.cols.state")}</TH>
            <TH>{t("families.cols.rule")}</TH>
            <TH>{t("families.cols.outcome")}</TH>
            <TH>{t("families.cols.postmortem")}</TH>
          </THead>
          <tbody>
            {d.items.map((x) => (
              <ItemRow
                key={x.id}
                x={x}
                rules={d.rules}
                selected={x.id === openId}
                onOpen={onOpen}
              />
            ))}
          </tbody>
        </TableShell>
      )}
    </section>
  );
}

// ── what they remember ───────────────────────────────────────────────────────────────────────────────────────────────────

function entityName(m: FamiliesMemoryRow): string {
  if (m.entity_type === "family") return familyName(m.entity_key);
  if (m.entity_type === "market") return marketText(m.entity_key);
  return m.entity_name ?? m.entity_key;
}

function MemoryRow({ m }: { m: FamiliesMemoryRow }) {
  const all = m.stats.all;
  const recent = m.stats.recent;
  const delta = m.delta["hit"];
  return (
    <TRow>
      <TD className="max-w-[18rem]">
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge tone="neutral" dot={false}>
            {t(`families.memory.type.${m.entity_type}`)}
          </StatusBadge>
          <span className="break-words text-sm" title={m.entity_key}>
            {entityName(m)}
          </span>
        </div>
        <div className="text-caption text-subtle-foreground">
          {t("families.memory.asOf", { day: m.as_of_day })}
        </div>
      </TD>
      <TD align="right" className="numeric">
        {localInt(all.n)}
      </TD>
      <TD align="right" className="numeric">
        {fmtPct(all.hit)}
      </TD>
      <TD align="right" className="numeric">
        {fmtPct(all.claimed)}
      </TD>
      <TD align="right" className="numeric">
        {fmtSignedPp(all.gap)}
      </TD>
      <TD align="right" className="numeric">
        {all.z === null ? DASH : localFixed(all.z, 2)}
      </TD>
      <TD align="right" className="numeric">
        {fmtSignedPct(all.clv_mean, 2)}
      </TD>
      <TD align="right" className="numeric">
        {fmtSignedPct(all.roi)}
      </TD>
      <TD align="right" className="numeric">
        {m.confidence === null ? DASH : fmtPct(m.confidence, 0)}
      </TD>
      <TD className="numeric whitespace-nowrap text-xs">
        {recent.n === 0 ? DASH : `${localInt(recent.n)} · ${fmtSignedPp(delta)}`}
      </TD>
    </TRow>
  );
}

function Memory({ d }: { d: IntelFamilies }) {
  const days = d.memory[0]?.stats.recent_days ?? 28;
  return (
    <section className="space-y-2" data-testid="families-memory">
      <SubTitle>{t("families.memory.title")}</SubTitle>
      <Note>{t("families.memory.help")}</Note>
      {d.memory.length === 0 ? (
        <div data-testid="families-memory-empty">
          <Note>{t("families.memory.empty")}</Note>
        </div>
      ) : (
        <TableShell>
          <THead>
            <TH>{t("families.memory.entity")}</TH>
            <TH align="right">{t("families.memory.cols.n")}</TH>
            <TH align="right">{t("families.memory.cols.hit")}</TH>
            <TH align="right">{t("families.memory.cols.claimed")}</TH>
            <TH align="right">{t("families.memory.cols.gap")}</TH>
            <TH align="right">{t("families.memory.cols.z")}</TH>
            <TH align="right">{t("families.memory.cols.clv")}</TH>
            <TH align="right">{t("families.memory.cols.roi")}</TH>
            <TH align="right">{t("families.memory.cols.confidence")}</TH>
            <TH>{t("families.memory.cols.recent", { days: localInt(days) })}</TH>
          </THead>
          <tbody>
            {d.memory.map((m) => (
              <MemoryRow key={`${m.entity_type}:${m.entity_key}`} m={m} />
            ))}
          </tbody>
        </TableShell>
      )}
    </section>
  );
}

// ── the tab ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

/** The whole tab from data already in hand (so it renders, and is tested, without a network). */
export function FamiliesBody({
  d,
  openId = 0,
  onOpen,
}: {
  d: IntelFamilies;
  /** The decision whose detail is open, to mark its row. */
  openId?: number;
  /** Opening a row; without it the rows are plain. */
  onOpen?: ((id: number) => void) | undefined;
}) {
  return (
    <div className="space-y-6" data-testid="families">
      <Note>{t("families.explain")}</Note>
      <Cycle d={d} />
      <Cards d={d} />
      <Items d={d} openId={openId} onOpen={onOpen} />
      <Memory d={d} />
    </div>
  );
}

export function FamiliesPanel() {
  const [family, setFamily] = useState("");
  const [state, setState] = useState("");
  const [days, setDays] = useState<number>(DEFAULT_DAYS);
  const [open, setOpen] = useState(0);
  const navigate = useNavigate();
  const detail = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // A row far down a long table opens its detail above it: bring the detail into view.
    if (open > 0) detail.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [open]);
  const q = useLiveQuery(
    live.intelFamilies({ family: family || undefined, state: state || undefined, days }),
  );
  const d = q.data?.data;
  return (
    <div className="space-y-4" data-testid="families-tab">
      {open > 0 ? (
        <div ref={detail}>
          <DecisionDetail
            id={open}
            onClose={() => setOpen(0)}
            onMatch={(fixture) =>
              void navigate({ to: "/matches/$fixtureId", params: { fixtureId: String(fixture) } })
            }
          />
        </div>
      ) : null}
      <Panel title={t("families.title")} subtitle={t("families.subtitle")}>
        <div className="space-y-4">
          <Toolbar>
            <Choice label={t("families.filters.family")} value={family} onChange={setFamily}>
              <option value="">{t("families.filters.all")}</option>
              {FAMILY_CODES.map((code) => (
                <option key={code} value={code}>
                  {familyName(code)}
                </option>
              ))}
            </Choice>
            <Choice label={t("families.filters.state")} value={state} onChange={setState}>
              <option value="">{t("families.filters.allStates")}</option>
              {STATES.map((code) => (
                <option key={code} value={code}>
                  {stateName(code)}
                </option>
              ))}
            </Choice>
            <Choice
              label={t("families.filters.days")}
              value={String(days)}
              onChange={(value) => setDays(Number(value))}
            >
              {WINDOWS.map((n) => (
                <option key={n} value={String(n)}>
                  {t("families.filters.daysOption", { count: n })}
                </option>
              ))}
            </Choice>
          </Toolbar>
          {d ? (
            <FamiliesBody d={d} openId={open} onOpen={setOpen} />
          ) : q.error ? (
            <ApiErrorNotice error={q.error} />
          ) : q.isLoading ? (
            <TableSkeleton rows={6} cols={6} />
          ) : null}
        </div>
      </Panel>
    </div>
  );
}

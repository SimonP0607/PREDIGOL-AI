/**
 * The context blocks of a match's dossier in the Admin Console (plan F6): the weighted head-to-head, what the match
 * does to its table and its tie, the observable tactics of each side and the status of every context factor. All of
 * it is DESCRIPTION - the AI reads it, the owner reads it, and no model, pick or settlement does until a person
 * validates a factor with an experiment (the registry at the bottom says which have been). Nothing here is shown to
 * users.
 */
import type { ReactNode } from "react";
import { t } from "@/lib/i18n";
import { Panel, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { live } from "@/lib/api/v1/queries";
import type {
  IntelFactorRow,
  IntelFactorsBlock,
  IntelFactorStatus,
  IntelH2hBlock,
  IntelScenariosBlock,
  IntelTacticsBlock,
} from "@/lib/api/v1/types_intel";
import { Fact, Note, SubTitle } from "./AiBits";
import { bogotaDateTime } from "./aiModel";
import {
  DASH,
  factorLines,
  factorName,
  factorStatus,
  h2hView,
  tableView,
  tacticsRows,
  tieView,
} from "./intelMatch";

/** DESCRIPTIVE (grey) or VALIDATED (green): the two things a context factor can be. */
export function FactorBadge({ status }: { status: IntelFactorStatus }) {
  return (
    <StatusBadge tone={status === "VALIDATED" ? "positive" : "neutral"} dot={false}>
      {t(`intel.match.factors.status.${status}`)}
    </StatusBadge>
  );
}

// ── the two sides, one against the other ─────────────────────────────────────

/** One line of a comparison: what is being compared and what each of the two columns has for it. */
interface CompareLine {
  key: string;
  label: ReactNode;
  first: ReactNode;
  second: ReactNode;
}

/** The label column and the two compared ones, once the panel is wide enough for them to sit side by side. */
const COMPARE_COLUMNS = "@xl:grid-cols-[10rem_minmax(0,1fr)_minmax(0,1fr)]";

/**
 * Two columns set against each other - the two sides of the match, or what a factor was and is. In a wide panel it is
 * a grid (what is compared, the first column, the second) under a header that names them; in a narrow one (a phone)
 * each line stacks and names its column beside its figure, so none waits beyond the edge of a scrolling table. What
 * decides is the panel's own width (a container query), not the screen's: the same panel is narrow in a side column
 * and wide on a page of its own. A screen reader hears the name of the column at every width: the header is for the
 * eyes, the name inside each cell is for the ears.
 */
function CompareRows({
  heads,
  labelHead = "",
  lines,
}: {
  heads: readonly [string, string];
  /** What the first column is (a factor, say); blank when it is evident. */
  labelHead?: string;
  lines: readonly CompareLine[];
}) {
  return (
    <div className="@container">
      <div
        aria-hidden
        className={`hidden gap-x-4 border-b border-border px-3 py-2 text-label font-semibold text-subtle-foreground @xl:grid ${COMPARE_COLUMNS}`}
      >
        <span className="break-words">{labelHead}</span>
        <span className="break-words">{heads[0]}</span>
        <span className="break-words">{heads[1]}</span>
      </div>
      <dl>
        {lines.map((l) => (
          <div
            key={l.key}
            className={`grid items-baseline gap-x-4 gap-y-1 border-b border-border/60 px-3 py-2.5 text-sm last:border-0 ${COMPARE_COLUMNS}`}
          >
            <dt className="text-xs text-muted-foreground">{l.label}</dt>
            <CompareCell head={heads[0]}>{l.first}</CompareCell>
            <CompareCell head={heads[1]}>{l.second}</CompareCell>
          </div>
        ))}
      </dl>
    </div>
  );
}

function CompareCell({ head, children }: { head: string; children: ReactNode }) {
  return (
    <dd className="flex min-w-0 items-baseline gap-2 @xl:block">
      <span className="w-24 shrink-0 break-words text-caption text-subtle-foreground @xl:sr-only">
        {head}
      </span>
      <span className="min-w-0 flex-1 break-words">{children}</span>
    </dd>
  );
}

// ── the weighted head-to-head ────────────────────────────────────────────────

export function H2hPanel({
  block,
  home,
  away,
}: {
  block: IntelH2hBlock;
  home: string;
  away: string;
}) {
  const v = h2hView(block);
  return (
    <Panel
      title={t("intel.match.h2hw.title")}
      subtitle={t("intel.match.h2hw.subtitle", { home, away })}
      actions={<FactorBadge status={factorStatus(block.status)} />}
    >
      <div className="space-y-3" data-testid="intel-h2h-weighted">
        <div className="grid gap-x-8 sm:grid-cols-2">
          <div>
            <Fact label={t("intel.match.h2hw.n")} value={v.n} />
            <Fact label={t("intel.match.nEffective")} value={v.nEffective} />
            <Fact label={t("intel.match.relevance")} value={v.relevance} />
            <Fact label={t("intel.match.h2hw.last")} value={v.lastAgo} />
            <Fact label={t("intel.match.h2hw.oldest")} value={v.oldestAgo} />
          </div>
          <div>
            <Fact label={t("intel.match.h2hw.record", { home })} value={v.record ?? DASH} />
            <Fact label={t("intel.match.h2hw.sameVenue", { home })} value={v.sameVenue ?? DASH} />
            <Fact label={t("intel.match.h2hw.weighted", { home })} value={v.weighted ?? DASH} />
            <Fact label={t("intel.match.h2hw.goals", { home })} value={v.goalsPerMeeting ?? DASH} />
            <Fact label={t("intel.match.h2hw.coaches")} value={v.coaches ?? DASH} />
          </div>
        </div>
        {v.meetings.length ? (
          <TableShell>
            <THead>
              <TH>{t("intel.match.h2hw.col.when")}</TH>
              <TH>{t("intel.match.h2hw.col.competition")}</TH>
              <TH align="right">{t("intel.match.h2hw.col.score")}</TH>
              <TH>{t("intel.match.h2hw.col.ground")}</TH>
              <TH>{t("intel.match.h2hw.col.scope")}</TH>
              <TH>{t("intel.match.h2hw.col.coaches")}</TH>
              <TH align="right">{t("intel.match.h2hw.col.weight")}</TH>
              <TH align="right">{t("intel.match.h2hw.col.share")}</TH>
            </THead>
            <tbody>
              {v.meetings.map((m) => (
                <TRow key={m.id}>
                  <TD className="whitespace-nowrap">{m.age}</TD>
                  <TD className="max-w-[12rem] break-words">{m.competition}</TD>
                  <TD align="right" className="whitespace-nowrap">
                    {m.score}
                    {m.afterExtraTime ? ` (${t("intel.match.h2hw.aet")})` : ""}
                  </TD>
                  <TD className="text-xs">{m.ground}</TD>
                  <TD className="text-xs">{m.scope}</TD>
                  <TD className="text-xs">{m.coaches}</TD>
                  <TD align="right">{m.weight}</TD>
                  <TD align="right">{m.share}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        ) : (
          <Note>{t("intel.match.h2hw.empty")}</Note>
        )}
        <Note>{v.note}</Note>
        {v.weightsNote ? <Note>{v.weightsNote}</Note> : null}
      </div>
    </Panel>
  );
}

// ── the match's effect on its table and its tie ──────────────────────────────

/** What a tie says of each side, in the order it is read: the margins that put it ahead, level and behind, and its limit. */
const TIE_LINES = ["ahead", "level", "behind", "limit"] as const;

export function ScenariosPanel({
  block,
  home,
  away,
}: {
  block: IntelScenariosBlock;
  home: string;
  away: string;
}) {
  const table = block.table ? tableView(block.table) : null;
  const tie = block.tie ? tieView(block.tie) : null;
  return (
    <Panel
      title={t("intel.match.scen.title")}
      subtitle={t("intel.match.scen.subtitle")}
      actions={<FactorBadge status={factorStatus(block.status)} />}
    >
      <div className="space-y-4" data-testid="intel-scenarios">
        {table ? (
          <div className="space-y-2">
            <SubTitle>
              {table.group
                ? `${t("intel.match.scen.tableTitle")} · ${table.group}`
                : t("intel.match.scen.tableTitle")}
            </SubTitle>
            {table.unavailable ? (
              <Note>{t("intel.match.scen.unavailable")}</Note>
            ) : (
              <>
                <CompareRows
                  heads={[home, away]}
                  lines={[
                    {
                      key: "today",
                      label: t("intel.match.scen.today"),
                      first: table.home ?? DASH,
                      second: table.away ?? DASH,
                    },
                    ...table.rows.map((r) => ({
                      key: r.result,
                      label: t(`intel.match.scen.result.${r.result}`),
                      first: r.home,
                      second: r.away,
                    })),
                  ]}
                />
                {table.snapshotAt ? (
                  <Note>
                    {t("intel.match.scen.snapshot", { when: bogotaDateTime(table.snapshotAt) })}
                  </Note>
                ) : null}
              </>
            )}
          </div>
        ) : null}
        {tie ? (
          <div className="space-y-2" data-testid="intel-tie">
            <SubTitle>{`${t("intel.match.scen.tieTitle")} · ${tie.kindLabel}`}</SubTitle>
            {tie.before ? <Fact label={t("intel.match.scen.before")} value={tie.before} /> : null}
            {tie.series ? <Fact label={t("intel.match.scen.series")} value={tie.series} /> : null}
            {tie.note ? <Note>{tie.note}</Note> : null}
            {tie.sides.length ? (
              <>
                <CompareRows
                  heads={[home, away]}
                  lines={TIE_LINES.map((k) => ({
                    key: k,
                    label: t(`intel.match.scen.tie.${k}`),
                    first: tie.sides.find((s) => s.side === "home")?.[k] ?? DASH,
                    second: tie.sides.find((s) => s.side === "away")?.[k] ?? DASH,
                  }))}
                />
                {tie.margin ? <Note>{tie.margin}</Note> : null}
              </>
            ) : null}
          </div>
        ) : null}
        <Note>{block.note}</Note>
      </div>
    </Panel>
  );
}

// ── observable tactics ───────────────────────────────────────────────────────

export function TacticsPanel({
  block,
  home,
  away,
}: {
  block: IntelTacticsBlock;
  home: string;
  away: string;
}) {
  const rows = tacticsRows(block.home, block.away);
  return (
    <Panel
      title={t("intel.match.tactics.title")}
      subtitle={t("intel.match.tactics.subtitle")}
      actions={<FactorBadge status={factorStatus(block.status)} />}
    >
      <div className="space-y-3" data-testid="intel-tactics">
        <CompareRows
          heads={[home, away]}
          lines={rows.map((r) => ({
            key: r.key,
            label: t(`intel.match.tactics.row.${r.key}`),
            first: r.home,
            second: r.away,
          }))}
        />
        <Note>{block.note}</Note>
      </div>
    </Panel>
  );
}

// ── the status of each context factor ────────────────────────────────────────

/** The factors of a packet beside the registry as it stands: the hook's data goes in, the page comes out. */
export function FactorsPanel({ block }: { block: IntelFactorsBlock }) {
  const registry = useLiveQuery(live.intelFactors);
  return (
    <FactorsBody
      block={block}
      registry={registry.data?.data?.factors}
      loaded={registry.data !== undefined}
    />
  );
}

export function FactorsBody({
  block,
  registry,
  loaded,
}: {
  block: IntelFactorsBlock;
  /** The registry today; undefined while it loads or when it could not be read. */
  registry: readonly IntelFactorRow[] | undefined;
  loaded: boolean;
}) {
  const lines = factorLines(block, registry);
  const decisions = (registry ?? [])
    .flatMap((f) => f.decisions.map((d) => ({ ...d, factor: f.key, label: f.label })))
    .sort((a, b) => b.id - a.id);
  return (
    <Panel title={t("intel.match.factors.title")} subtitle={t("intel.match.factors.subtitle")}>
      <div className="space-y-3" data-testid="intel-factors">
        {block.error ? <WarningBanner>{t("intel.match.factors.error")}</WarningBanner> : null}
        <CompareRows
          heads={[t("intel.match.factors.col.packet"), t("intel.match.factors.col.today")]}
          labelHead={t("intel.match.factors.col.factor")}
          lines={lines.map((l) => ({
            key: l.key,
            label: <span className="text-sm text-foreground">{l.name}</span>,
            first: (
              <span className="flex flex-wrap items-center gap-1.5">
                <FactorBadge status={l.packet} />
                {l.experiment ? (
                  <span className="text-caption text-subtle-foreground">
                    {t("intel.match.factors.experiment", { name: l.experiment })}
                  </span>
                ) : null}
              </span>
            ),
            second: l.today ? (
              <span className="flex flex-wrap items-center gap-1.5">
                <FactorBadge status={l.today} />
                {l.changed ? (
                  <span className="text-caption text-warning">
                    {t("intel.match.factors.changed")}
                  </span>
                ) : null}
              </span>
            ) : (
              DASH
            ),
          }))}
        />
        {decisions.length ? (
          <div className="space-y-1.5" data-testid="intel-factor-decisions">
            <SubTitle>{t("intel.match.factors.decisions")}</SubTitle>
            <ul className="space-y-1.5 text-xs">
              {decisions.map((d) => (
                <li key={d.id} className="rounded-md border border-border bg-card px-3 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <FactorBadge status={d.status} />
                    <span className="font-medium">{factorName(d.factor, d.label)}</span>
                    <span className="text-subtle-foreground">
                      {bogotaDateTime(d.decided_at)} · {d.who ?? d.decided_by} · {d.version}
                    </span>
                    {d.experiment ? (
                      <span className="text-subtle-foreground">
                        {t("intel.match.factors.experiment", { name: d.experiment })}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 break-words text-foreground/85">{d.reason}</p>
                </li>
              ))}
            </ul>
          </div>
        ) : loaded ? (
          <Note>{t("intel.match.factors.noDecisions")}</Note>
        ) : null}
        <Note>{block.note}</Note>
      </div>
    </Panel>
  );
}

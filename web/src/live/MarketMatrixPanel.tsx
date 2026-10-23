/**
 * The matrix of markets by family (plan F9) in the Admin Console, under "Mercados": for each kind of bet, whether the
 * provider offers it, how many matches carry a price and how many carry the figure that would settle it, whether a model
 * exists and the verdict those facts earn (LISTO, PARCIAL, POR INVESTIGAR, NO VIABLE). Reading only - it shows the
 * newest matrix the weekly job stored and asks the provider nothing. A figure the matrix could not make arrives as null
 * and is shown as a dash, never as zero.
 */
import { getLocale, t, translateOr } from "@/lib/i18n";
import { localFixed, localInt, localPct } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  IntelMarketMatrix,
  IntelMatrixCoverage,
  IntelMatrixRow,
  IntelMatrixSummary,
} from "@/lib/api/v1/types_intel";
import { Note, Stat, StatGrid, SubTitle } from "./AiBits";
import { bogotaDateTime } from "./aiModel";

const DASH = "—";
const COLUMNS = 7;
/** The competitions listed under the table: those with the most finished matches. */
const TOP_COMPETITIONS = 15;
const INVESTIGATE = "POR INVESTIGAR";

/** The server's verdicts are Spanish phrases; the catalogs are keyed by a one-word slug. */
const VERDICT_KEY: Record<string, string> = {
  LISTO: "ready",
  PARCIAL: "partial",
  [INVESTIGATE]: "investigate",
  "NO VIABLE": "notViable",
};

const VERDICT_TONE: Record<string, BadgeTone> = {
  LISTO: "positive",
  PARCIAL: "info",
  [INVESTIGATE]: "warning",
  "NO VIABLE": "neutral",
};

const VERDICTS = Object.keys(VERDICT_KEY);

/** A count: a whole number, or a dash when the matrix could not make it. */
function count(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : localInt(v);
}

/** A share the server sends as a fraction of 1: "97,9 %", or a dash. */
function share(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : localPct(v, 1);
}

/** A median of whole numbers is a whole number or a half: 8, 4,5. */
function houses(v: number | null | undefined): string {
  if (v === null || v === undefined) return DASH;
  return Number.isInteger(v) ? localInt(v) : localFixed(v, 1);
}

function when(iso: string | null | undefined): string {
  return iso ? bogotaDateTime(iso) : DASH;
}

function verdictText(verdict: string): string {
  return translateOr(`intel.markets.matrix.verdict.${VERDICT_KEY[verdict] ?? verdict}`, verdict);
}

function reasonText(reason: string): string {
  return reason ? translateOr(`intel.markets.matrix.reason.${reason}`, reason) : DASH;
}

function priorityText(priority: string): string {
  return translateOr(`intel.markets.matrix.priority.${priority}`, priority);
}

function labelOf(row: IntelMatrixRow): string {
  return getLocale() === "en" && row.label_en ? row.label_en : row.label;
}

interface MatrixGroup {
  letter: string;
  name: string;
  rows: IntelMatrixRow[];
}

/** The rows under their group letter, A to Z, each group keeping the order the server gave its rows. */
function groupRows(d: IntelMarketMatrix): MatrixGroup[] {
  const byLetter = new Map<string, IntelMatrixRow[]>();
  for (const row of d.rows) {
    const rows = byLetter.get(row.group);
    if (rows) rows.push(row);
    else byLetter.set(row.group, [row]);
  }
  return [...byLetter.keys()].sort().map((letter) => ({
    letter,
    name: translateOr(`intel.markets.matrix.group.${letter}`, d.groups[letter] ?? ""),
    rows: byLetter.get(letter) ?? [],
  }));
}

/** How many rows earned each verdict - the four of the plan always, even at zero, then any other the server sends. */
function tally(rows: IntelMatrixRow[]): Array<[string, number]> {
  const counts = new Map<string, number>(VERDICTS.map((verdict) => [verdict, 0]));
  for (const row of rows) counts.set(row.verdict, (counts.get(row.verdict) ?? 0) + 1);
  return [...counts.entries()];
}

/** A labelled figure on one line, inside a table cell. */
function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 whitespace-nowrap">
      <span className="text-caption text-subtle-foreground">{label}</span>
      <span className="numeric text-xs">{value}</span>
    </div>
  );
}

/**
 * The price of a kind of bet. A row the price clock does not store (no extracted bet) and that no discovery run has
 * seen has nothing to measure: one dash, not three zeros. A discovery figure is an estimate and says so.
 */
function PriceCell({ price }: { price: IntelMatrixRow["price"] }) {
  const estimated = price.source === "discovery";
  if (!estimated && price.extracted === 0) return <span>{DASH}</span>;
  return (
    <>
      <Figure label={t("intel.markets.matrix.price.fixtures")} value={count(price.fixtures)} />
      <Figure label={t("intel.markets.matrix.price.houses")} value={houses(price.houses_median)} />
      <Figure label={t("intel.markets.matrix.price.coverage")} value={share(price.coverage)} />
      {estimated ? (
        <div
          className="text-caption italic text-subtle-foreground"
          title={t("intel.markets.matrix.estimatedHint")}
        >
          {t("intel.markets.matrix.estimated")}
        </div>
      ) : null}
    </>
  );
}

function ResultsCell({ results }: { results: IntelMatrixRow["results"] }) {
  if (!results) return <span>{DASH}</span>;
  return (
    <>
      <Figure label={t("intel.markets.matrix.results.matches")} value={count(results.n_window)} />
      <Figure label={t("intel.markets.matrix.results.share")} value={share(results.pct)} />
    </>
  );
}

function ModelCell({ model }: { model: IntelMatrixRow["model"] }) {
  if (!model.enabled) return <span>{DASH}</span>;
  const edge = model.edge ?? "unknown";
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <StatusBadge tone="brand" dot={false}>
        {t("intel.markets.matrix.model.enabled")}
      </StatusBadge>
      <span
        className={cn(
          "text-caption",
          model.edge === "VALIDATED" ? "text-positive" : "text-subtle-foreground",
        )}
      >
        {translateOr(`intel.markets.matrix.model.edge.${edge}`, edge)}
      </span>
    </div>
  );
}

/** A `<tr>` of its own, not the shared TRow: that one takes no test id. The cells are the shared ones. */
function MatrixRow({ row }: { row: IntelMatrixRow }) {
  return (
    <tr
      className="border-b border-border/60 align-top last:border-0"
      data-testid={`intel-market-matrix-row-${row.key}`}
    >
      <TD className="max-w-[22rem] break-words">
        <div className={cn("flex items-baseline gap-1.5", row.parent ? "pl-4" : null)}>
          {row.parent ? (
            <span aria-hidden className="text-subtle-foreground">
              ↳
            </span>
          ) : null}
          <span title={row.key}>{labelOf(row)}</span>
        </div>
      </TD>
      <TD>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge tone={VERDICT_TONE[row.verdict] ?? "neutral"} dot={false}>
            {verdictText(row.verdict)}
          </StatusBadge>
          {row.verdict === INVESTIGATE && row.priority ? (
            <span className="text-xs text-muted-foreground">{priorityText(row.priority)}</span>
          ) : null}
        </div>
      </TD>
      <TD className="max-w-[20rem] break-words text-xs">
        {reasonText(row.reason)}
        {row.curated ? (
          <span
            className="ml-1 text-caption text-subtle-foreground"
            title={t("intel.markets.matrix.curatedHint")}
          >
            ({t("intel.markets.matrix.curated")})
          </span>
        ) : null}
      </TD>
      <TD align="right" className="numeric whitespace-nowrap text-xs">
        {`${localInt(row.extracted_bets.length)} / ${localInt(row.bets.length)}`}
      </TD>
      <TD>
        <PriceCell price={row.price} />
      </TD>
      <TD>
        <ResultsCell results={row.results} />
      </TD>
      <TD>
        <ModelCell model={row.model} />
      </TD>
    </tr>
  );
}

/** The sub-title that opens a group of rows: "A · Resultado". */
function GroupHeader({ title }: { title: string }) {
  return (
    <tr className="border-b border-border bg-elevated/40">
      <td colSpan={COLUMNS} className="px-3 py-1.5">
        <SubTitle>{title}</SubTitle>
      </td>
    </tr>
  );
}

function CardsNote({ cards }: { cards: IntelMatrixSummary["cards"] }) {
  const events = cards.matches_with_events;
  if (!(events > 0)) return null;
  const sensitive = cards.convention_sensitive_pct;
  const equal = cards.events_equal_statistics_pct;
  return (
    <div className="space-y-1" data-testid="intel-market-matrix-cards">
      <SubTitle>{t("intel.markets.matrix.cards.title")}</SubTitle>
      {sensitive !== null ? (
        <Note>
          {t("intel.markets.matrix.cards.convention", {
            pct: share(sensitive),
            matches: localInt(events),
          })}
        </Note>
      ) : null}
      {equal !== null ? (
        <Note>
          {t("intel.markets.matrix.cards.statistics", {
            pct: share(equal),
            compared: localInt(cards.events_vs_statistics_compared),
          })}
        </Note>
      ) : null}
    </div>
  );
}

function CompetitionsTable({ coverage }: { coverage: IntelMatrixCoverage }) {
  const top = [...coverage.competitions]
    .sort((a, b) => b.finished - a.finished || a.competition_id - b.competition_id)
    .slice(0, TOP_COMPETITIONS);
  if (top.length === 0) return null;
  return (
    <div className="space-y-2" data-testid="intel-market-matrix-competitions">
      <SubTitle>{t("intel.markets.matrix.competitions.title")}</SubTitle>
      <Note>
        {t("intel.markets.matrix.competitions.help", {
          n: localInt(top.length),
          finished: count(coverage.totals.finished),
          priced: count(coverage.totals.priced),
        })}
      </Note>
      <TableShell compact>
        <THead>
          <TH>{t("intel.markets.matrix.competitions.name")}</TH>
          <TH align="right">
            {t("intel.markets.matrix.competitions.finished", {
              days: count(coverage.results_days),
            })}
          </TH>
          <TH align="right">
            {t("intel.markets.matrix.competitions.priced", { days: count(coverage.price_days) })}
          </TH>
        </THead>
        <tbody>
          {top.map((c) => (
            <TRow key={c.competition_id}>
              <TD>
                <div>{c.name ?? `#${c.competition_id}`}</div>
                {c.country ? (
                  <div className="text-caption text-subtle-foreground">{c.country}</div>
                ) : null}
              </TD>
              <TD align="right" className="numeric">
                {count(c.finished)}
              </TD>
              <TD align="right" className="numeric">
                {count(c.priced)}
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </div>
  );
}

/** The whole panel from data already in hand (so it renders, and is tested, without a network). */
export function MarketMatrixBody({ d }: { d: IntelMarketMatrix }) {
  const run = d.run;
  return (
    <div className="space-y-4" data-testid="intel-market-matrix">
      <Note>{t("intel.markets.matrix.explain")}</Note>
      {run ? (
        <MatrixBody d={d} run={run} />
      ) : (
        <div data-testid="intel-market-matrix-empty">
          <Note>{t("intel.markets.matrix.empty")}</Note>
        </div>
      )}
    </div>
  );
}

function MatrixBody({
  d,
  run,
}: {
  d: IntelMarketMatrix;
  run: NonNullable<IntelMarketMatrix["run"]>;
}) {
  const summary = d.summary;
  const groups = groupRows(d);
  const priceDays = d.coverage?.price_days ?? run.window_days;
  return (
    <>
      <StatGrid className="sm:grid-cols-2 lg:grid-cols-4" testId="intel-market-matrix-stats">
        <Stat
          label={t("intel.markets.matrix.generated")}
          value={when(run.generated_at)}
          hint={t("intel.markets.matrix.generatedHint", {
            version: run.matrix_version,
            taxonomy: run.taxonomy_version,
          })}
        />
        <Stat
          label={t("intel.markets.matrix.keys")}
          value={count(d.keys.keys)}
          hint={t("intel.markets.matrix.keysHint", {
            followed: count(d.keys.followed),
            modelled: count(d.keys.modelled),
          })}
        />
        <Stat
          label={t("intel.markets.matrix.rules")}
          value={count(d.rules.rules)}
          hint={t("intel.markets.matrix.rulesHint", { n: count(d.rules.can_grade) })}
        />
        <Stat
          label={t("intel.markets.matrix.definitions")}
          value={count(summary?.definitions)}
          hint={
            summary
              ? t("intel.markets.matrix.definitionsHint", {
                  extracted: count(summary.extracted),
                  withRule: count(summary.with_rule),
                })
              : undefined
          }
        />
      </StatGrid>

      {run.matrix_version !== d.current_version ? (
        <Note>
          {t("intel.markets.matrix.stale", {
            version: run.matrix_version,
            current: d.current_version,
          })}
        </Note>
      ) : null}

      <div className="space-y-2">
        <div
          className="flex flex-wrap items-center gap-2"
          data-testid="intel-market-matrix-verdicts"
        >
          {tally(d.rows).map(([verdict, n]) => (
            <StatusBadge key={verdict} tone={VERDICT_TONE[verdict] ?? "neutral"}>
              {`${verdictText(verdict)} ${localInt(n)}`}
            </StatusBadge>
          ))}
        </div>
        <Note>{t("intel.markets.matrix.legend")}</Note>
      </div>

      {d.rows.length ? (
        <div className="space-y-2">
          <Note>
            {t("intel.markets.matrix.howToRead", {
              price: count(priceDays),
              results: count(d.coverage?.results_days),
            })}
          </Note>
          <TableShell>
            <THead>
              <TH>{t("intel.markets.matrix.cols.market")}</TH>
              <TH>{t("intel.markets.matrix.cols.verdict")}</TH>
              <TH>{t("intel.markets.matrix.cols.reason")}</TH>
              <TH align="right">{t("intel.markets.matrix.cols.bets")}</TH>
              <TH>{t("intel.markets.matrix.cols.price")}</TH>
              <TH>{t("intel.markets.matrix.cols.results")}</TH>
              <TH>{t("intel.markets.matrix.cols.model")}</TH>
            </THead>
            {groups.map((g) => (
              <tbody key={g.letter} data-testid={`intel-market-matrix-group-${g.letter}`}>
                <GroupHeader title={g.name ? `${g.letter} · ${g.name}` : g.letter} />
                {g.rows.map((row) => (
                  <MatrixRow key={row.key} row={row} />
                ))}
              </tbody>
            ))}
          </TableShell>
        </div>
      ) : null}

      {summary ? <CardsNote cards={summary.cards} /> : null}
      {d.coverage ? <CompetitionsTable coverage={d.coverage} /> : null}
    </>
  );
}

export function MarketMatrixPanel() {
  const q = useLiveQuery(live.intelMarketMatrix);
  const d = q.data?.data;
  return (
    <Panel title={t("intel.markets.matrix.title")} subtitle={t("intel.markets.matrix.subtitle")}>
      {d ? (
        <MarketMatrixBody d={d} />
      ) : q.error ? (
        <ApiErrorNotice error={q.error} />
      ) : q.isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : null}
    </Panel>
  );
}

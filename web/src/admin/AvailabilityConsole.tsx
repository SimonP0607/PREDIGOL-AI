/**
 * The owner's console of the availability matrix (plan PM, PM-02-08, lámina I11; UX-174): the level of each family per competition,
 * the cells of one competition with their sample and date, the last week of changes, the shadow's discrepancies and the seven states
 * of one match. Read-only, on C-16's private matrix (`/admin/availability/matrix`) and the match route; built with the console's
 * primitives (`Panel`, `MetricCard`, the table, `StatusBadge`, the filters) and the states of PM-14-01. Shown only with
 * `FBI_AVAILABILITY` on (the tab of /admin/competitions).
 */
import { useMemo, useState, type FormEvent } from "react";
import { Check, Eye, EyeOff, X } from "lucide-react";
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
import {
  FilterBar,
  SearchFilter,
  SegmentedTabs,
  SelectFilter,
  ToggleFilter,
} from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, StatusNotice } from "@/components/system/LiveState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { live } from "@/lib/api/v1/queries";
import type {
  AvailabilityPrivate,
  CoverageLevel,
  LevelCellPrivate,
  MarketAvailability,
  MarketCellPrivate,
  MatchAvailability,
} from "@/lib/api/v1/types_availability";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import { int } from "@/lib/format";
import { localFixed } from "@/lib/i18n/format";
import { utcDate, utcDateTime } from "@/live/format";
import { PrivateBand } from "@/product/shared/intelligence/Pieces";
import { UnavailableNotes } from "@/product/shared/Unavailable";
import {
  AVAILABILITY_STEPS,
  blockUnavailable,
  cellUnavailable,
  marketSteps,
  marketUnavailable,
  type StepResult,
} from "@/product/shared/availabilityState";
import { t } from "@/product/shared/availabilityText";
import {
  FAMILIES,
  LEVELS,
  NO_FILTER,
  changeRows,
  countries,
  filterRows,
  matrixFigures,
  matrixRow,
  type MatrixFilter,
  type MatrixRow,
  type PrivateCompetition,
} from "./availabilityMatrix";

const LEVEL_TONE: Record<CoverageLevel, BadgeTone> = {
  A: "positive",
  B: "brand",
  C: "warning",
  D: "negative",
  MI: "neutral",
};

/** A level as a tag: its letter always written (the colour never says it alone) and its meaning for a screen reader and a tap. */
export function LevelBadge({ level }: { level: CoverageLevel }) {
  return (
    <span title={t(`availability.level.${level}`)}>
      <StatusBadge tone={LEVEL_TONE[level]} dot={false} className="numeric min-w-8 justify-center">
        <span aria-hidden>{level}</span>
        <span className="sr-only">
          {t("availability.level.label", {
            level,
            meaning: t(`availability.level.${level}`),
          })}
        </span>
      </StatusBadge>
    </span>
  );
}

function StepCell({ result }: { result: StepResult }) {
  if (result === "sin_evaluar")
    return (
      <span className="text-caption text-subtle-foreground">
        {t("availability.result.sin_evaluar")}
      </span>
    );
  const yes = result === "si";
  const Icon = yes ? Check : X;
  return (
    <span
      className={
        yes
          ? "inline-flex items-center gap-1 text-positive"
          : "inline-flex items-center gap-1 text-negative"
      }
    >
      <Icon aria-hidden className="h-3.5 w-3.5" />
      <span className="text-xs font-semibold">{t(`availability.result.${result}`)}</span>
    </span>
  );
}

function reasonText(reason: string): string {
  return t(`availability.reason.${reason}`);
}

function keyText(kind: "datum" | "market", key: string): string {
  return t(`availability.${kind}.${key}`);
}

function Figures({ matrix }: { matrix: AvailabilityPrivate }) {
  const f = matrixFigures(matrix);
  const share = f.totalCells > 0 ? Math.round((f.visibleCells / f.totalCells) * 100) : 0;
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="availability-figures">
      <MetricCard
        label={t("availability.console.kpi.competitions")}
        value={int(f.competitions)}
        hint={t("availability.console.kpi.competitionsHint", { n: int(f.levelA) })}
      />
      <MetricCard
        label={t("availability.console.kpi.visible")}
        value={t("availability.console.kpi.visibleValue", {
          v: int(f.visibleCells),
          t: int(f.totalCells),
        })}
        hint={t("availability.console.kpi.visibleHint")}
        footer={
          <div className="h-1.5 overflow-hidden rounded-full bg-foreground/[0.08]" aria-hidden>
            <div className="h-full rounded-full bg-primary" style={{ width: `${share}%` }} />
          </div>
        }
      />
      <MetricCard
        label={t("availability.console.kpi.blocker")}
        value={
          f.topReason ? reasonText(f.topReason.reason) : t("availability.console.kpi.blockerNone")
        }
        {...(f.topReason
          ? { hint: t("availability.console.kpi.blockerHint", { n: int(f.topReason.cells) }) }
          : {})}
      />
      <MetricCard
        label={t("availability.console.kpi.changes")}
        value={int(f.changes)}
        hint={t("availability.console.kpi.changesHint", { up: int(f.up), down: int(f.down) })}
      />
    </div>
  );
}

function MatrixTable({
  rows,
  total,
  selected,
  onSelect,
}: {
  rows: MatrixRow[];
  total: number;
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <Panel
      title={t("availability.console.matrix.title")}
      subtitle={`${t("availability.console.matrix.subtitle")} ${t("availability.console.matrix.shown", { shown: int(rows.length), total: int(total) })}`}
      bodyClassName=""
    >
      {rows.length === 0 ? (
        <StatusNotice status="empty" reason={t("availability.console.matrix.empty")} />
      ) : (
        <LimitedRows rows={rows} step={50}>
          {(shown) => (
            <TableShell>
              <THead>
                <TH>{t("availability.console.matrix.competition")}</TH>
                <TH align="center">{t("availability.console.matrix.summary")}</TH>
                {FAMILIES.map((f) => (
                  <TH key={f} align="center">
                    {t(`availability.family.${f}`)}
                  </TH>
                ))}
                <TH align="right">{t("availability.console.matrix.sample")}</TH>
                <TH>{t("availability.console.matrix.measured")}</TH>
              </THead>
              <tbody>
                {shown.map((r) => (
                  <TRow
                    key={r.id}
                    onClick={() => onSelect(r.id)}
                    selected={selected === r.id}
                    data-testid="availability-row"
                  >
                    <TD>
                      <div className="text-sm font-semibold">{r.name}</div>
                      <div className="text-caption text-subtle-foreground">{r.country ?? "—"}</div>
                    </TD>
                    <TD align="center">
                      <LevelBadge level={r.summary} />
                    </TD>
                    {FAMILIES.map((f) => {
                      const level = r.families[f];
                      return (
                        <TD key={f} align="center">
                          {level ? (
                            <LevelBadge level={level} />
                          ) : (
                            <span className="text-caption text-subtle-foreground">—</span>
                          )}
                        </TD>
                      );
                    })}
                    <TD align="right" className="numeric text-xs">
                      {t("availability.console.matrix.matches", { n: int(r.sample) })}
                    </TD>
                    <TD className="numeric whitespace-nowrap text-xs text-muted-foreground">
                      {utcDate(r.measuredAt)}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </LimitedRows>
      )}
    </Panel>
  );
}

function CellRows({
  kind,
  cells,
}: {
  kind: "datum" | "market";
  cells: Array<LevelCellPrivate | MarketCellPrivate>;
}) {
  return (
    <>
      {cells.map((c) => {
        const state = cellUnavailable(c);
        return (
          <TRow key={`${kind}-${c.key}`}>
            <TD className="text-sm">{keyText(kind, c.key)}</TD>
            <TD align="center">
              <LevelBadge level={c.level} />
            </TD>
            <TD align="right" className="numeric text-xs">
              {int(c.with_data)} / {int(c.n)}
            </TD>
            <TD align="right" className="numeric text-xs">
              {isMissing(c.pct) ? "—" : `${localFixed(c.pct, 1)} %`}
            </TD>
            <TD className="text-xs text-muted-foreground">
              {reasonText(c.reason)}
              {c.provisional ? ` · ${t("availability.console.detail.provisional")}` : ""}
            </TD>
            <TD>
              {state ? (
                <StatusBadge tone="neutral" dot={false}>
                  <EyeOff aria-hidden className="h-3.5 w-3.5" />
                  {t(`availability.kind.${state.kind}`)}
                </StatusBadge>
              ) : (
                <StatusBadge tone="positive" dot={false}>
                  <Eye aria-hidden className="h-3.5 w-3.5" />
                  {t("availability.console.detail.visible")}
                </StatusBadge>
              )}
            </TD>
            <TD className="numeric whitespace-nowrap text-xs text-muted-foreground">
              {utcDateTime(c.measured_at)}
            </TD>
          </TRow>
        );
      })}
    </>
  );
}

function CompetitionDetail({ competition }: { competition: PrivateCompetition | null }) {
  const row = competition ? matrixRow(competition) : null;
  const season = row?.season ?? null;
  if (!competition || !season) {
    return (
      <Panel title={t("availability.console.detail.pick")}>
        <p className="text-small text-muted-foreground">
          {t("availability.console.detail.subtitle")}
        </p>
      </Panel>
    );
  }
  const header = (label: string) => (
    <TRow>
      <TD colSpan={7} className="bg-elevated/60 text-label text-subtle-foreground">
        {label}
      </TD>
    </TRow>
  );
  return (
    <Panel
      title={t("availability.console.detail.title", {
        name: competition.name,
        season: season.season,
      })}
      subtitle={t("availability.console.detail.subtitle")}
      actions={<LevelBadge level={season.summary} />}
      bodyClassName=""
    >
      <TableShell>
        <THead>
          <TH>{t("availability.console.detail.key")}</TH>
          <TH align="center">{t("availability.console.detail.level")}</TH>
          <TH align="right">{t("availability.console.detail.sample")}</TH>
          <TH align="right">{t("availability.console.detail.pct")}</TH>
          <TH>{t("availability.console.detail.reason")}</TH>
          <TH>{t("availability.console.detail.inApp")}</TH>
          <TH>{t("availability.console.detail.measured")}</TH>
        </THead>
        <tbody>
          {header(t("availability.console.detail.data"))}
          <CellRows kind="datum" cells={season.data} />
          {header(t("availability.console.detail.markets"))}
          <CellRows kind="market" cells={season.markets} />
        </tbody>
      </TableShell>
      <p className="border-t border-border/70 px-4 py-3 text-caption text-muted-foreground">
        {t("availability.console.detail.note")}
      </p>
    </Panel>
  );
}

function ChangesPanel({ matrix }: { matrix: AvailabilityPrivate }) {
  const rows = changeRows(matrix);
  return (
    <Panel
      title={t("availability.console.changes.title")}
      subtitle={t("availability.console.changes.subtitle")}
      bodyClassName=""
    >
      {rows.length === 0 ? (
        <StatusNotice status="empty" reason={t("availability.console.changes.empty")} />
      ) : (
        <LimitedRows rows={rows} step={25}>
          {(shown) => (
            <TableShell>
              <THead>
                <TH>{t("availability.console.changes.when")}</TH>
                <TH>{t("availability.console.changes.competition")}</TH>
                <TH>{t("availability.console.changes.key")}</TH>
                <TH align="center">{t("availability.console.changes.from")}</TH>
                <TH align="center">{t("availability.console.changes.to")}</TH>
                <TH>{t("availability.console.changes.reason")}</TH>
                <TH align="right">{t("availability.console.changes.n")}</TH>
              </THead>
              <tbody>
                {shown.map((c, i) => (
                  <TRow key={`${c.competition_season_id}-${c.kind}-${c.key}-${c.changed_at}-${i}`}>
                    <TD className="numeric whitespace-nowrap text-xs text-muted-foreground">
                      {utcDateTime(c.changed_at)}
                    </TD>
                    <TD className="text-sm">
                      {c.competition ??
                        t("availability.console.changes.unknown", { id: c.competition_season_id })}
                      {c.season ? (
                        <span className="text-caption text-subtle-foreground"> · {c.season}</span>
                      ) : null}
                    </TD>
                    <TD className="text-xs">
                      {keyText(c.kind === "market" ? "market" : "datum", c.key)}
                    </TD>
                    <TD align="center">
                      {isMissing(c.old_level) ? (
                        <span className="text-caption text-subtle-foreground">—</span>
                      ) : (
                        <LevelBadge level={c.old_level} />
                      )}
                    </TD>
                    <TD align="center">
                      <LevelBadge level={c.new_level} />
                    </TD>
                    <TD className="text-xs text-muted-foreground">
                      {t(`availability.change.${c.reason}`)}
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {isMissing(c.n) ? "—" : int(c.n)}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </LimitedRows>
      )}
    </Panel>
  );
}

function ShadowPanel({ matrix }: { matrix: AvailabilityPrivate }) {
  const rows = matrix.discrepancies.items;
  const shows = (b: boolean) =>
    t(b ? "availability.console.shadow.yes" : "availability.console.shadow.no");
  return (
    <Panel
      title={t("availability.console.shadow.title")}
      subtitle={t("availability.console.shadow.subtitle")}
      bodyClassName=""
    >
      {rows.length === 0 ? (
        <StatusNotice status="empty" reason={t("availability.console.shadow.empty")} />
      ) : (
        <LimitedRows rows={rows} step={25}>
          {(shown) => (
            <TableShell>
              <THead>
                <TH>{t("availability.console.shadow.day")}</TH>
                <TH align="right">{t("availability.console.shadow.fixture")}</TH>
                <TH>{t("availability.console.shadow.module")}</TH>
                <TH>{t("availability.console.shadow.key")}</TH>
                <TH>{t("availability.console.shadow.shown")}</TH>
                <TH>{t("availability.console.shadow.matrix")}</TH>
                <TH>{t("availability.console.shadow.reason")}</TH>
              </THead>
              <tbody>
                {shown.map((d, i) => (
                  <TRow key={`${d.day}-${d.fixture_id}-${d.module}-${d.key}-${i}`}>
                    <TD className="numeric whitespace-nowrap text-xs text-muted-foreground">
                      {d.day}
                    </TD>
                    <TD align="right" className="numeric text-xs">
                      {d.fixture_id}
                    </TD>
                    <TD className="text-xs">{d.module}</TD>
                    <TD className="break-all text-xs">{d.key}</TD>
                    <TD className="text-xs">{shows(d.shown)}</TD>
                    <TD className="text-xs">{shows(d.matrix)}</TD>
                    <TD className="text-xs text-muted-foreground">{d.reason}</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </LimitedRows>
      )}
    </Panel>
  );
}

function MarketStateRow({ market }: { market: MarketAvailability }) {
  const steps = marketSteps(market);
  const state = marketUnavailable(market);
  return (
    <TRow>
      <TD className="break-all text-xs font-semibold">{market.key}</TD>
      {AVAILABILITY_STEPS.map((s) => (
        <TD key={s} align="center">
          <StepCell result={steps[s]} />
        </TD>
      ))}
      <TD>
        {state ? (
          <StatusBadge tone="neutral" dot={false}>
            <EyeOff aria-hidden className="h-3.5 w-3.5" />
            {t(`availability.kind.${state.kind}`)}
          </StatusBadge>
        ) : (
          <StatusBadge tone="positive" dot={false}>
            <Eye aria-hidden className="h-3.5 w-3.5" />
            {t("availability.console.detail.visible")}
          </StatusBadge>
        )}
      </TD>
    </TRow>
  );
}

/** The seven states of one match (the bottom of I11), and the one note a reader would get for its blocks (PM-14-01). */
export function MatchStates({ match }: { match: MatchAvailability }) {
  const entries = match.blocks.map((b) => ({
    subject: keyText("datum", b.key).toLowerCase(),
    state: blockUnavailable(b),
  }));
  return (
    <div className="space-y-3">
      <TableShell>
        <THead>
          <TH>{t("availability.console.match.market")}</TH>
          {AVAILABILITY_STEPS.map((s, i) => (
            <TH key={s} align="center">
              {`${i + 1} · ${t(`availability.step.${s}`)}`}
            </TH>
          ))}
          <TH>{t("availability.console.detail.inApp")}</TH>
        </THead>
        <tbody>
          {match.markets.map((m) => (
            <MarketStateRow key={m.key} market={m} />
          ))}
        </tbody>
      </TableShell>
      <div className="space-y-2 px-4 pb-4">
        <p className="text-label text-subtle-foreground">
          {t("availability.console.match.blocks")}
        </p>
        {entries.some((e) => e.state) ? (
          <UnavailableNotes entries={entries} />
        ) : (
          <p className="text-small text-muted-foreground">
            {t("availability.console.match.allVisible")}
          </p>
        )}
      </div>
    </div>
  );
}

function MatchPanel() {
  const [draft, setDraft] = useState("");
  const [id, setId] = useState<string | null>(null);
  const q = useQuery({ ...live.matchAvailability(id ?? ""), enabled: id !== null });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const value = draft.trim();
    setId(/^\d+$/.test(value) ? value : null);
  };
  const match = q.data?.data.match;
  return (
    <Panel
      title={t("availability.console.match.title")}
      subtitle={t("availability.console.match.subtitle")}
      bodyClassName=""
    >
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2 px-4 pt-4 pb-3">
        <label
          className="flex flex-col gap-1 text-xs text-muted-foreground"
          htmlFor="availability-fixture"
        >
          {t("availability.console.match.label")}
          <Input
            id="availability-fixture"
            inputMode="numeric"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-40"
          />
        </label>
        <Button type="submit" variant="secondary" size="sm">
          {t("availability.console.match.go")}
        </Button>
      </form>
      {id === null ? (
        <p className="px-4 pb-4 text-small text-muted-foreground">
          {t("availability.console.match.empty")}
        </p>
      ) : q.isLoading ? (
        <TableSkeleton rows={4} cols={9} />
      ) : q.isError ? (
        <div className="px-4 pb-4">
          <ApiErrorNotice error={q.error} />
        </div>
      ) : match && !isMissing(match) ? (
        <MatchStates match={match} />
      ) : null}
    </Panel>
  );
}

export function AvailabilityConsoleView({ matrix }: { matrix: AvailabilityPrivate }) {
  const competitions = matrix.competitions as PrivateCompetition[];
  const all = useMemo(() => competitions.map(matrixRow), [competitions]);
  const [filter, setFilter] = useState<MatrixFilter>(NO_FILTER);
  const [selected, setSelected] = useState<number | null>(null);
  const rows = filterRows(all, filter);
  const chosen = competitions.find((c) => c.competition_id === selected) ?? null;
  const levelTabs = ["all", ...LEVELS] as const;
  return (
    <div className="space-y-4">
      <Figures matrix={matrix} />
      {all.length === 0 ? (
        <Panel>
          <StatusNotice status="empty" reason={t("availability.console.matrix.none")} />
        </Panel>
      ) : (
        <>
          <FilterBar>
            <SearchFilter
              value={filter.term}
              onChange={(term) => setFilter({ ...filter, term })}
              placeholder={t("availability.console.matrix.search")}
              label={t("availability.console.matrix.search")}
            />
            <SegmentedTabs
              label={t("availability.console.matrix.level")}
              tabs={levelTabs}
              value={filter.level}
              onChange={(level) => setFilter({ ...filter, level })}
              format={(l) => (l === "all" ? t("availability.console.matrix.levelAll") : l)}
              className="w-auto"
            />
            <SelectFilter
              label={t("availability.console.matrix.country")}
              value={filter.country}
              options={[
                { value: "", label: t("availability.console.matrix.countryAll") },
                ...countries(all).map((c) => ({ value: c, label: c })),
              ]}
              onChange={(country) => setFilter({ ...filter, country })}
            />
            <ToggleFilter
              label={t("availability.console.matrix.blockedOnly")}
              checked={filter.blockedOnly}
              onChange={(blockedOnly) => setFilter({ ...filter, blockedOnly })}
            />
          </FilterBar>
          <MatrixTable rows={rows} total={all.length} selected={selected} onSelect={setSelected} />
          <CompetitionDetail competition={chosen} />
        </>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <ChangesPanel matrix={matrix} />
        <ShadowPanel matrix={matrix} />
      </div>
      <MatchPanel />
    </div>
  );
}

/** The tab: the private matrix, with its loading and error states. */
export function AvailabilityConsole() {
  const q = useLiveQuery(live.adminAvailability);
  return (
    <div className="space-y-4" data-testid="availability-console">
      <PageHeader
        title={t("availability.console.title")}
        description={t("availability.console.description")}
      />
      <PrivateBand>{t("availability.console.private")}</PrivateBand>
      {q.isLoading ? (
        <TableSkeleton rows={8} cols={10} />
      ) : q.isError ? (
        <ApiErrorNotice error={q.error} />
      ) : q.data ? (
        <AvailabilityConsoleView matrix={q.data.data} />
      ) : null}
    </div>
  );
}

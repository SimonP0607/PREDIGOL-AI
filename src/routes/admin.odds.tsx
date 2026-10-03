import { useMemo, useState } from "react";
import { DATA_MODE } from "@/lib/api/mode";
import { DemoRegion } from "@/components/system/DataSources";
import { OddsLive } from "@/live/MarketLive";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState, Panel, WarningBanner } from "@/components/primitives/Panel";
import {
  CardRow,
  SortableTH,
  TableShell,
  TableSkeleton,
  TD,
  TH,
  THead,
  TRow,
} from "@/components/primitives/DataTable";
import { EVIndicator, EdgeIndicator, Numeric, OddsCell } from "@/components/primitives/Indicators";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { FreshnessBadge } from "@/components/system/Freshness";
import { MetricLabel } from "@/components/system/InfoTip";
import { FilterBar, NumberFilter, SegmentedTabs, SelectFilter } from "@/components/system/Filters";
import { ChartContainer, LineMovementChart } from "@/components/analytics/Charts";
import { fixtureQueries, queries } from "@/lib/api/resources";
import { fixtures } from "@/mock/data";
import { EMPTY, num, odds as fmtOdds, pct, timeOf } from "@/lib/format";
import { useSortable } from "@/hooks/useSortable";
import type { ValueRow } from "@/types/domain";

export const Route = createFileRoute("/admin/odds")({
  head: () => ({
    meta: [
      { title: "Odds Intelligence — Football Intelligence" },
      {
        name: "description",
        content:
          "Price capture, consensus construction and market movement across tracked bookmakers.",
      },
      { property: "og:title", content: "Odds Intelligence — Football Intelligence" },
      {
        property: "og:description",
        content: "Price capture, overround removal, movement and near-close snapshots.",
      },
    ],
  }),
  component: RouteComponent,
});

function RouteComponent() {
  if (DATA_MODE === "mock") {
    return (
      <DemoRegion>
        <OddsPage />
      </DemoRegion>
    );
  }
  return <OddsLive />;
}

const tabs = [
  "Value Scanner",
  "Odds Explorer",
  "Line Movement",
  "Market Consensus",
  "Near-Close",
] as const;
type Tab = (typeof tabs)[number];

function OddsPage() {
  const [tab, setTab] = useState<Tab>("Value Scanner");
  const [fixtureId, setFixtureId] = useState(fixtures[0]!.id);

  const fixtureOptions = fixtures.map((f) => ({
    value: f.id,
    label: `${f.home.code}–${f.away.code} · ${f.competition.shortCode} ${timeOf(f.kickoff)}`,
  }));

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Operations" }, { label: "Odds Intelligence" }]}
        title="Odds Intelligence"
        description="Raw prices turned into a comparable market view: overround removal, consensus, dispersion and movement between snapshots."
      />

      <WarningBanner>
        Near-close data is not yet validated as official closing prices. Nothing on this page may be
        reported as closing line value.
      </WarningBanner>

      <SegmentedTabs tabs={tabs} value={tab} onChange={setTab} label="Odds intelligence sections" />

      {tab === "Value Scanner" ? <ValueScanner /> : null}
      {tab !== "Value Scanner" ? (
        <FilterBar>
          <SelectFilter
            label="Fixture"
            value={fixtureId}
            onChange={setFixtureId}
            options={fixtureOptions}
            className="w-full sm:w-72"
          />
        </FilterBar>
      ) : null}
      {tab === "Odds Explorer" ? <OddsExplorer fixtureId={fixtureId} /> : null}
      {tab === "Line Movement" ? <LineMovement fixtureId={fixtureId} /> : null}
      {tab === "Market Consensus" ? <MarketConsensus fixtureId={fixtureId} /> : null}
      {tab === "Near-Close" ? <NearClose /> : null}
    </div>
  );
}

type ValueSortKey = "edge" | "ev" | "kickoff" | "bestOdds";

function ValueScanner() {
  const navigate = useNavigate();
  const value = useQuery(queries.valueScanner);
  const [market, setMarket] = useState("all");
  const [minEdge, setMinEdge] = useState(0);
  const [freshness, setFreshness] = useState("all");

  const rows = useMemo(
    () =>
      (value.data ?? []).filter((r) => {
        if (market !== "all" && r.market !== market) return false;
        if (r.edge * 100 < minEdge) return false;
        if (freshness !== "all" && r.freshness !== freshness) return false;
        return true;
      }),
    [value.data, market, minEdge, freshness],
  );

  const { sorted, sort, toggle } = useSortable<ValueRow, ValueSortKey>(
    rows,
    {
      edge: (r) => r.edge,
      ev: (r) => r.ev,
      kickoff: (r) => r.kickoff,
      bestOdds: (r) => r.bestOdds,
    },
    { key: "edge", direction: "desc" },
  );

  return (
    <div className="space-y-4">
      <FilterBar
        onReset={() => {
          setMarket("all");
          setMinEdge(0);
          setFreshness("all");
        }}
        meta={
          <span className="numeric text-caption text-subtle-foreground">
            {sorted.length} candidates
          </span>
        }
      >
        <SelectFilter
          label="Market"
          value={market}
          onChange={setMarket}
          options={[
            { value: "all", label: "All markets" },
            { value: "1x2", label: "1X2" },
            { value: "ou_2_5", label: "Over / Under 2.5" },
            { value: "btts", label: "BTTS" },
            { value: "double_chance", label: "Double Chance" },
          ]}
        />
        <SelectFilter
          label="Freshness"
          value={freshness}
          onChange={setFreshness}
          options={[
            { value: "all", label: "Any" },
            { value: "fresh", label: "Fresh" },
            { value: "aging", label: "Aging" },
            { value: "stale", label: "Stale" },
          ]}
        />
        <NumberFilter
          label="Min edge"
          value={minEdge}
          onChange={setMinEdge}
          min={0}
          max={8}
          step={0.5}
          className="w-40"
        />
      </FilterBar>

      <Panel
        title="Value Scanner"
        subtitle="Gaps between model probability and overround-removed consensus. A gap is not a recommendation."
        bodyClassName=""
      >
        {value.isLoading ? (
          <TableSkeleton rows={6} cols={8} />
        ) : sorted.length === 0 ? (
          <EmptyState
            title="No candidates above this threshold"
            description="Lower the minimum edge or widen the market filter. Empty is a valid result: most fixtures carry no measurable gap."
          />
        ) : (
          <>
            <div className="hidden lg:block">
              <TableShell>
                <THead>
                  <TH>Fixture</TH>
                  <TH>Market</TH>
                  <TH>Selection</TH>
                  <TH align="right">
                    <MetricLabel term="modelProbability">Model</MetricLabel>
                  </TH>
                  <TH align="right">
                    <MetricLabel term="marketProbability">Market</MetricLabel>
                  </TH>
                  <TH align="right">
                    <MetricLabel term="fairOdds">Fair</MetricLabel>
                  </TH>
                  <SortableTH
                    align="right"
                    active={sort.key === "bestOdds"}
                    direction={sort.direction}
                    onClick={() => toggle("bestOdds")}
                  >
                    Best
                  </SortableTH>
                  <SortableTH
                    align="right"
                    active={sort.key === "edge"}
                    direction={sort.direction}
                    onClick={() => toggle("edge")}
                  >
                    Edge
                  </SortableTH>
                  <SortableTH
                    align="right"
                    active={sort.key === "ev"}
                    direction={sort.direction}
                    onClick={() => toggle("ev")}
                  >
                    EV
                  </SortableTH>
                  <TH>Freshness</TH>
                </THead>
                <tbody>
                  {sorted.map((r) => (
                    <TRow
                      key={r.id}
                      onClick={() =>
                        navigate({ to: "/matches/$fixtureId", params: { fixtureId: r.fixtureId } })
                      }
                    >
                      <TD>
                        <div className="text-sm">{r.fixtureLabel}</div>
                        <div className="text-caption text-subtle-foreground">
                          {r.competitionCode} · {timeOf(r.kickoff)} UTC
                        </div>
                      </TD>
                      <TD className="text-xs text-muted-foreground">{r.marketLabel}</TD>
                      <TD className="text-xs">{r.selection}</TD>
                      <TD align="right">
                        <Numeric>{pct(r.modelProbability)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric muted>{pct(r.marketProbability)}</Numeric>
                      </TD>
                      <TD align="right">
                        <OddsCell value={r.fairOdds} fair />
                      </TD>
                      <TD align="right">
                        <OddsCell value={r.bestOdds} bookmaker={r.bookmaker} />
                      </TD>
                      <TD align="right">
                        <EdgeIndicator value={r.edge} />
                      </TD>
                      <TD align="right">
                        <EVIndicator value={r.ev} />
                      </TD>
                      <TD>
                        <FreshnessBadge freshness={r.freshness} />
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            </div>
            <div className="lg:hidden">
              {sorted.map((r) => (
                <CardRow
                  key={r.id}
                  onClick={() =>
                    navigate({ to: "/matches/$fixtureId", params: { fixtureId: r.fixtureId } })
                  }
                  title={r.fixtureLabel}
                  subtitle={`${r.marketLabel} · ${r.selection}`}
                  badges={<FreshnessBadge freshness={r.freshness} />}
                  fields={[
                    { label: "Model", value: pct(r.modelProbability) },
                    { label: "Market", value: pct(r.marketProbability) },
                    { label: "Fair", value: fmtOdds(r.fairOdds) },
                    { label: "Best", value: `${fmtOdds(r.bestOdds)} ${r.bookmaker}` },
                    { label: "Edge", value: <EdgeIndicator value={r.edge} /> },
                    { label: "EV", value: <EVIndicator value={r.ev} /> },
                  ]}
                />
              ))}
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}

function OddsExplorer({ fixtureId }: { fixtureId: string }) {
  const board = useQuery(fixtureQueries.oddsBoard(fixtureId));
  const selections = ["Home", "Draw", "Away"];
  const rows = board.data ?? [];
  const books = Array.from(new Set(rows.map((r) => r.bookmaker)));

  return (
    <Panel
      title="Odds Explorer"
      subtitle="Every captured price per bookmaker and selection, with the capture timestamp behind it."
      bodyClassName=""
    >
      {board.isLoading ? (
        <TableSkeleton rows={6} cols={5} />
      ) : (
        <TableShell>
          <THead>
            <TH>Bookmaker</TH>
            {selections.map((s) => (
              <TH key={s} align="right">
                {s}
              </TH>
            ))}
            <TH align="right">
              <MetricLabel term="overround">Overround</MetricLabel>
            </TH>
            <TH>Captured</TH>
            <TH>Freshness</TH>
          </THead>
          <tbody>
            {books.map((book) => {
              const bookRows = rows.filter((r) => r.bookmaker === book);
              const overround = bookRows.reduce((a, r) => a + r.impliedProbability, 0);
              const first = bookRows[0];
              return (
                <TRow key={book}>
                  <TD className="text-sm">{book}</TD>
                  {selections.map((s) => {
                    const cell = bookRows.find((r) => r.selection === s);
                    return (
                      <TD key={s} align="right">
                        <Numeric>{fmtOdds(cell?.odds ?? null)}</Numeric>
                        <div className="text-caption text-subtle-foreground">
                          {cell ? pct(cell.impliedProbability, 1) : EMPTY}
                        </div>
                      </TD>
                    );
                  })}
                  <TD align="right">
                    <Numeric>{num(overround, 4)}</Numeric>
                  </TD>
                  <TD>
                    <Numeric muted>{first ? timeOf(first.capturedAt) : EMPTY}</Numeric>
                  </TD>
                  <TD>{first ? <FreshnessBadge freshness={first.freshness} /> : EMPTY}</TD>
                </TRow>
              );
            })}
          </tbody>
        </TableShell>
      )}
    </Panel>
  );
}

function LineMovement({ fixtureId }: { fixtureId: string }) {
  const movement = useQuery(fixtureQueries.movement(fixtureId));
  const series = movement.data ?? [];
  if (movement.isLoading)
    return (
      <Panel>
        <TableSkeleton rows={4} cols={3} />
      </Panel>
    );
  return (
    <div className="space-y-4">
      <ChartContainer
        title="Line Movement — Home price"
        subtitle="Path between captured snapshots. The last capture is not a closing price."
        demo
        height={260}
      >
        <LineMovementChart series={series} />
      </ChartContainer>
      <Panel title="Snapshot deltas" bodyClassName="">
        <TableShell>
          <THead>
            <TH>Source</TH>
            <TH align="right">Open</TH>
            <TH align="right">Latest</TH>
            <TH align="right">Delta</TH>
            <TH align="right">Snapshots</TH>
          </THead>
          <tbody>
            {series.map((s) => {
              const open = s.points[0]?.odds ?? null;
              const last = s.points[s.points.length - 1]?.odds ?? null;
              const delta = open !== null && last !== null ? last - open : null;
              return (
                <TRow key={s.bookmaker}>
                  <TD className="text-sm">{s.bookmaker}</TD>
                  <TD align="right">
                    <Numeric muted>{fmtOdds(open)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{fmtOdds(last)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric className={delta && delta < 0 ? "text-negative" : "text-positive"}>
                      {delta === null ? EMPTY : `${delta > 0 ? "+" : ""}${delta.toFixed(2)}`}
                    </Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric muted>{s.points.length}</Numeric>
                  </TD>
                </TRow>
              );
            })}
          </tbody>
        </TableShell>
      </Panel>
    </div>
  );
}

function MarketConsensus({ fixtureId }: { fixtureId: string }) {
  const consensus = useQuery(fixtureQueries.consensus(fixtureId));
  const rows = consensus.data ?? [];
  return (
    <Panel
      title="Market Consensus"
      subtitle="Overround-removed consensus probability, best available price and dispersion across tracked books."
      bodyClassName=""
    >
      {consensus.isLoading ? (
        <TableSkeleton rows={3} cols={6} />
      ) : (
        <TableShell>
          <THead>
            <TH>Market</TH>
            <TH>Selection</TH>
            <TH align="right">
              <MetricLabel term="marketProbability">Market probability</MetricLabel>
            </TH>
            <TH align="right">
              <MetricLabel term="bestOdds">Best odds</MetricLabel>
            </TH>
            <TH align="right">Median</TH>
            <TH align="right">Books</TH>
            <TH align="right">
              <MetricLabel term="overround">Overround</MetricLabel>
            </TH>
            <TH>Captured</TH>
          </THead>
          <tbody>
            {rows.map((r) => (
              <TRow key={`${r.market}-${r.selection}`}>
                <TD className="text-xs text-muted-foreground">{r.marketLabel}</TD>
                <TD className="text-sm">{r.selection}</TD>
                <TD align="right">
                  <Numeric>{pct(r.marketProbability)}</Numeric>
                </TD>
                <TD align="right">
                  <OddsCell value={r.bestOdds} bookmaker={r.bestBookmaker} />
                </TD>
                <TD align="right">
                  <Numeric muted>{fmtOdds(r.medianOdds)}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric muted>{r.bookmakerCount}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric>{num(r.overround, 4)}</Numeric>
                </TD>
                <TD>
                  <div className="flex items-center gap-2">
                    <Numeric muted>{timeOf(r.capturedAt)}</Numeric>
                    <FreshnessBadge freshness={r.freshness} />
                  </div>
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      )}
    </Panel>
  );
}

function NearClose() {
  const nearClose = useQuery(queries.nearClose);
  const rows = nearClose.data ?? [];
  return (
    <Panel
      title="Near-Close Snapshots"
      subtitle="Captures taken at T-12m. These are near-close references, never closing prices."
      actions={<StatusBadge tone="warning">Pending validation</StatusBadge>}
      bodyClassName=""
    >
      {nearClose.isLoading ? (
        <TableSkeleton rows={4} cols={6} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No near-close captures recorded"
          description="Snapshots appear once the capture worker runs inside the T-12m window."
        />
      ) : (
        <TableShell>
          <THead>
            <TH>Fixture</TH>
            <TH>Market</TH>
            <TH>Selection</TH>
            <TH align="right">Snapshot</TH>
            <TH align="right">Latest</TH>
            <TH align="right">Delta</TH>
            <TH align="right">T-minus</TH>
            <TH>
              <MetricLabel term="pickLineValue">Pick line value</MetricLabel>
            </TH>
          </THead>
          <tbody>
            {rows.map((r, i) => (
              <TRow key={`${r.fixtureId}-${r.market}-${i}`}>
                <TD>
                  <Link
                    to="/matches/$fixtureId"
                    params={{ fixtureId: r.fixtureId }}
                    className="text-sm text-primary hover:underline"
                  >
                    {r.fixtureLabel}
                  </Link>
                </TD>
                <TD className="text-xs text-muted-foreground">{r.marketLabel}</TD>
                <TD className="text-xs">{r.selection}</TD>
                <TD align="right">
                  <Numeric>{fmtOdds(r.snapshotOdds)}</Numeric>
                  <div className="text-caption text-subtle-foreground">{timeOf(r.capturedAt)}</div>
                </TD>
                <TD align="right">
                  <Numeric muted>{fmtOdds(r.latestOdds)}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric className={r.delta < 0 ? "text-negative" : "text-positive"}>
                    {`${r.delta > 0 ? "+" : ""}${r.delta.toFixed(2)}`}
                  </Numeric>
                </TD>
                <TD align="right">
                  <Numeric muted>{r.minutesToKickoff}m</Numeric>
                </TD>
                <TD>
                  <span className="text-caption text-subtle-foreground">
                    {r.validated ? "Available" : "Pending validation"}
                  </span>
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      )}
    </Panel>
  );
}

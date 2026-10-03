import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, MetricCard, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { SegmentedTabs } from "@/components/system/Filters";
import { MetricLabel } from "@/components/system/InfoTip";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, SectionView, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { MarketQuote, OddsSeries, PerformanceSlice } from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { dec, decPct, relative, utcDate, utcDateTime } from "./format";
import { bookLabel, seasonLabel } from "./labels";
import { FixtureLink, StatusGroupBadge } from "./shared";

/* ------------------------------------------------------------------------ */
/* Odds explorer                                                            */
/* ------------------------------------------------------------------------ */

const oddsTabs = ["Board", "Movement", "Near-close", "Consensus"] as const;
type OddsTab = (typeof oddsTabs)[number];

const pageTabs = ["Captured by us", "Historical market"] as const;
type PageTab = (typeof pageTabs)[number];

export function OddsLive() {
  const [page, setPage] = useState<PageTab>("Captured by us");
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Market" }, { label: "Odds" }]}
        title="Odds"
        description="Two sources, never mixed: the prices this platform captured itself, with their capture time, and a second source's historical prices in that source's own terms."
      />
      <SegmentedTabs label="Odds source" tabs={pageTabs} value={page} onChange={setPage} />
      {page === "Captured by us" ? <CapturedOdds /> : <HistoricalMarketLive />}
    </div>
  );
}

function CapturedOdds() {
  const list = useLiveQuery(live.odds);
  const [selected, setSelected] = useState<number | null>(null);
  const fixtures = list.data?.data ?? [];
  const active = selected ?? fixtures[0]?.id ?? null;

  return (
    <div className="space-y-4">
      <Panel
        title="Fixtures with captured prices"
        subtitle="Implied probabilities are raw (1/odds); de-vigged probabilities appear only in the consensus."
        bodyClassName=""
      >
        {list.isLoading ? (
          <TableSkeleton rows={3} cols={5} />
        ) : list.isError ? (
          <div className="p-4">
            <ApiErrorNotice error={list.error} />
          </div>
        ) : list.data && list.data.status !== "ok" ? (
          <StatusNotice status={list.data.status} reason={list.data.reason} />
        ) : (
          <TableShell>
            <THead>
              <TH>Kick-off</TH>
              <TH>Fixture</TH>
              <TH>Status</TH>
              <TH align="right">Snapshots</TH>
              <TH align="right">Bookmakers</TH>
              <TH align="right">Markets</TH>
              <TH>Last capture</TH>
            </THead>
            <tbody>
              {fixtures.map((m) => (
                <TRow key={m.id} onClick={() => setSelected(m.id)} selected={active === m.id}>
                  <TD>
                    <Numeric>{utcDateTime(m.kickoff_at)}</Numeric>
                  </TD>
                  <TD>
                    <FixtureLink match={m} />
                  </TD>
                  <TD>
                    <StatusGroupBadge match={m} />
                  </TD>
                  <TD align="right">
                    <Numeric>{int(m.odds.snapshots)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{int(m.odds.bookmakers)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{int(m.odds.markets)}</Numeric>
                  </TD>
                  <TD>
                    <Numeric muted>{relative(m.odds.last_captured_at)}</Numeric>
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>
      {active !== null ? <FixtureOddsPanel id={active} /> : null}
    </div>
  );
}

function bestPrices(quotes: MarketQuote[]) {
  const best = new Map<string, MarketQuote>();
  for (const q of quotes) {
    const k = `${q.market_key}|${q.selection}|${q.line}`;
    const cur = best.get(k);
    if (!cur || Number(q.odds_decimal) > Number(cur.odds_decimal)) best.set(k, q);
  }
  return [...best.values()];
}

function FixtureOddsPanel({ id }: { id: number }) {
  const [tab, setTab] = useState<OddsTab>("Board");
  const q = useLiveQuery(live.fixtureOdds(String(id)));
  const best = useMemo(
    () => (q.data?.data.board.status === "ok" ? bestPrices(q.data.data.board.data) : []),
    [q.data],
  );
  if (q.isLoading)
    return (
      <Panel title="Fixture odds">
        <TableSkeleton rows={5} cols={5} />
      </Panel>
    );
  if (q.isError || !q.data) return <ApiErrorNotice error={q.error} />;
  const d = q.data.data;
  return (
    <div className="space-y-3">
      <SegmentedTabs label="Odds sections" tabs={oddsTabs} value={tab} onChange={setTab} />
      {tab === "Board" ? (
        <Panel
          title={`${d.match.home.name} v ${d.match.away.name}`}
          subtitle="Latest price per bookmaker, and the best available per selection"
          bodyClassName=""
        >
          <SectionView section={d.board}>
            {(quotes) => (
              <>
                <TableShell>
                  <THead>
                    <TH>Market</TH>
                    <TH>Selection</TH>
                    <TH align="right">Best odds</TH>
                    <TH>At</TH>
                    <TH align="right">Implied (raw)</TH>
                  </THead>
                  <tbody>
                    {best.map((b) => (
                      <TRow key={`${b.market_key}-${b.selection}-${b.line}`}>
                        <TD className="text-xs">{b.market_key}</TD>
                        <TD className="text-sm">{b.selection}</TD>
                        <TD align="right">
                          <Numeric>{dec(b.odds_decimal)}</Numeric>
                        </TD>
                        <TD className="text-xs text-muted-foreground">{b.bookmaker}</TD>
                        <TD align="right">
                          <Numeric muted>{decPct(b.implied_probability)}</Numeric>
                        </TD>
                      </TRow>
                    ))}
                  </tbody>
                </TableShell>
                <p className="border-t border-border px-4 py-2 text-caption text-subtle-foreground">
                  {quotes.length} latest quotes from{" "}
                  {new Set(quotes.map((x) => x.bookmaker_id)).size} bookmakers.
                </p>
              </>
            )}
          </SectionView>
        </Panel>
      ) : null}
      {tab === "Movement" ? (
        <Panel
          title="Line movement"
          subtitle="First and last captured price per bookmaker and selection"
          bodyClassName=""
        >
          <SectionView section={d.series}>
            {(series) => <MovementTable series={series} />}
          </SectionView>
        </Panel>
      ) : null}
      {tab === "Near-close" ? (
        <Panel
          title="Near-close"
          subtitle="The capture closest to kick-off our cadence allowed. Not a closing line until validated."
          bodyClassName=""
        >
          <SectionView section={d.near_close}>
            {(rows) => (
              <TableShell>
                <THead>
                  <TH>Bookmaker</TH>
                  <TH>Market</TH>
                  <TH>Selection</TH>
                  <TH align="right">Odds</TH>
                  <TH>Captured</TH>
                  <TH>Validated close</TH>
                </THead>
                <tbody>
                  {rows.map((r) => (
                    <TRow key={`${r.bookmaker}-${r.market_key}-${r.selection}-${r.line}`}>
                      <TD className="text-xs">{r.bookmaker}</TD>
                      <TD className="text-xs">{r.market_key}</TD>
                      <TD className="text-sm">{r.selection}</TD>
                      <TD align="right">
                        <Numeric>{dec(r.odds_decimal)}</Numeric>
                      </TD>
                      <TD>
                        <span className="numeric text-xs">T-{r.minutes_to_ko} min</span>
                      </TD>
                      <TD>
                        {r.is_validated_close ? (
                          <StatusBadge tone="positive">
                            {r.close_validation_method ?? "yes"}
                          </StatusBadge>
                        ) : (
                          <StatusBadge tone="neutral">no</StatusBadge>
                        )}
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            )}
          </SectionView>
        </Panel>
      ) : null}
      {tab === "Consensus" ? (
        <Panel
          title="Market consensus"
          subtitle="De-vigged probability across bookmakers"
          bodyClassName=""
        >
          <SectionView section={d.consensus}>
            {(rows) => (
              <TableShell>
                <THead>
                  <TH>Market</TH>
                  <TH>Selection</TH>
                  <TH>Method</TH>
                  <TH align="right">Fair probability</TH>
                  <TH align="right">Overround</TH>
                  <TH align="right">Books</TH>
                </THead>
                <tbody>
                  {rows.map((r) => (
                    <TRow key={`${r.market_key}-${r.selection}-${r.line}-${r.devig_method}`}>
                      <TD className="text-xs">{r.market_key}</TD>
                      <TD className="text-sm">{r.selection}</TD>
                      <TD className="text-xs">{r.devig_method}</TD>
                      <TD align="right">
                        <Numeric>{decPct(r.p_fair)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric muted>{decPct(r.overround, 2)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric>{r.n_bookmakers}</Numeric>
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            )}
          </SectionView>
        </Panel>
      ) : null}
    </div>
  );
}

function MovementTable({ series }: { series: OddsSeries[] }) {
  return (
    <TableShell>
      <THead>
        <TH>Bookmaker</TH>
        <TH>Market</TH>
        <TH>Selection</TH>
        <TH align="right">First</TH>
        <TH align="right">Last</TH>
        <TH align="right">Change</TH>
        <TH align="right">Captures</TH>
      </THead>
      <tbody>
        {series.map((s) => {
          const first = s.points[0];
          const last = s.points[s.points.length - 1];
          const change =
            first && last ? Number(last.odds_decimal) - Number(first.odds_decimal) : null;
          return (
            <TRow key={`${s.bookmaker_id}-${s.market_key}-${s.selection}-${s.line}`}>
              <TD className="text-xs">{s.bookmaker}</TD>
              <TD className="text-xs">{s.market_key}</TD>
              <TD className="text-sm">{s.selection}</TD>
              <TD align="right">
                <Numeric>
                  {first ? `${dec(first.odds_decimal)} · T-${first.minutes_to_ko}` : null}
                </Numeric>
              </TD>
              <TD align="right">
                <Numeric>
                  {last ? `${dec(last.odds_decimal)} · T-${last.minutes_to_ko}` : null}
                </Numeric>
              </TD>
              <TD align="right">
                <Numeric
                  className={
                    change === null || change === 0
                      ? ""
                      : change > 0
                        ? "text-positive"
                        : "text-negative"
                  }
                >
                  {change === null ? null : `${change > 0 ? "+" : ""}${change.toFixed(2)}`}
                </Numeric>
              </TD>
              <TD align="right">
                <Numeric>{s.points.length}</Numeric>
              </TD>
            </TRow>
          );
        })}
      </tbody>
    </TableShell>
  );
}

function HistoricalMarketLive() {
  const q = useLiveQuery(live.oddsIntelligence);
  const d = q.data?.data;
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (!d) return <TableSkeleton rows={6} cols={6} />;
  return (
    <div className="space-y-4">
      <WarningBanner tone="info">{d.note}</WarningBanner>
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard
          label="Fixtures with historical prices"
          value={int(d.fixtures_with_prices)}
          hint={`Seasons ${d.seasons.map((y) => seasonLabel(y)).join(", ") || "—"} · ${d.source}`}
        />
        <MetricCard
          label="Captured by us"
          value={d.live.status === "ok" ? int(d.live.data["snapshots"] ?? 0) : "0"}
          hint={d.live.status === "ok" ? "snapshots" : (d.live.reason ?? "")}
          tone={d.live.status === "ok" ? "default" : "muted"}
        />
        <MetricCard
          label="Live consensus"
          value={int(d.live.data["consensus_fixtures"] ?? 0)}
          hint="fixtures with a de-vigged consensus from our captures"
          tone="muted"
        />
      </div>
      <Panel
        title="Bookmaker margins"
        subtitle="Overround per book and price kind: the sum of 1/odds across a market. Best-price share counts how often a named book had the top 1X2 price (ties count for each)."
        bodyClassName=""
      >
        <SectionView section={d.margins}>
          {(rows) => (
            <TableShell>
              <THead>
                <TH>Book</TH>
                <TH>Market</TH>
                <TH>Kind</TH>
                <TH align="right">Fixtures</TH>
                <TH align="right">
                  <MetricLabel term="overround">Mean overround</MetricLabel>
                </TH>
                <TH align="right">Median</TH>
                <TH align="right">Best 1X2 price</TH>
              </THead>
              <tbody>
                {rows.map((r) => (
                  <TRow key={`${r.bookmaker_code}-${r.market_key}-${r.price_kind}`}>
                    <TD className="text-sm">{bookLabel(r.bookmaker_code)}</TD>
                    <TD className="text-xs text-muted-foreground">
                      {r.market_key === "OU" ? "Over/Under 2.5" : r.market_key}
                    </TD>
                    <TD className="text-xs text-muted-foreground">
                      {r.price_kind === "pre_closing" ? "pre-closing" : r.price_kind}
                    </TD>
                    <TD align="right">
                      <Numeric>{int(r.fixtures)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{dec(r.mean_overround, 4)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric muted>{dec(r.median_overround, 4)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Nullable
                        value={decPct(r.best_price_share)}
                        reason={
                          r.bookmaker_code === "AVG"
                            ? "An average is not a price anyone offered."
                            : "Only computed for 1X2."
                        }
                        className="numeric"
                      />
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </SectionView>
      </Panel>
      <Panel
        title="Pre-closing → closing"
        subtitle="Pinnacle, de-vigged with Shin. How far the price moved between the source's two collections, and which of the two predicted the result better."
        bodyClassName=""
      >
        <SectionView section={d.movement}>
          {(rows) => (
            <TableShell>
              <THead>
                <TH>Competition</TH>
                <TH>Season</TH>
                <TH align="right">Fixtures</TH>
                <TH align="right">Mean |Δ p(home)|</TH>
                <TH align="right">Favourite shortened</TH>
                <TH align="right">
                  <MetricLabel term="logLoss">Pre-closing log loss</MetricLabel>
                </TH>
                <TH align="right">Closing log loss</TH>
              </THead>
              <tbody>
                {rows.map((r) => {
                  const better = Number(r.closing_logloss) < Number(r.pre_closing_logloss);
                  return (
                    <TRow key={`${r.competition_id}-${r.season}`}>
                      <TD className="text-sm">{r.competition}</TD>
                      <TD className="numeric text-xs">{seasonLabel(r.season)}</TD>
                      <TD align="right">
                        <Numeric>{int(r.fixtures)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric>{decPct(r.mean_abs_home_shift, 2)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric>{decPct(r.favourite_shortened_share)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric muted>{dec(r.pre_closing_logloss, 4)}</Numeric>
                      </TD>
                      <TD align="right">
                        <span className={better ? "numeric text-positive" : "numeric"}>
                          {dec(r.closing_logloss, 4)}
                        </span>
                      </TD>
                    </TRow>
                  );
                })}
              </tbody>
            </TableShell>
          )}
        </SectionView>
        <p className="border-t border-border px-4 py-2.5 text-caption text-muted-foreground">
          The source collects pre-closing prices on Friday or Tuesday afternoons; neither kind has
          an exact timestamp, so this is movement between two labelled collections, not a line
          history.
        </p>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Picks and performance                                                    */
/* ------------------------------------------------------------------------ */

export function PerformanceLive() {
  const q = useLiveQuery(live.performance);
  const d = q.data?.data;
  const reason = q.data?.reason ?? null;
  const cards: Array<[string, string | null]> = [
    ["P&L (units)", dec(d?.profit_units)],
    ["ROI", d?.roi_pct ? `${dec(d.roi_pct)}%` : null],
    ["Hit rate", d?.hit_rate ? `${dec(d.hit_rate)}%` : null],
    ["Staked (units)", dec(d?.staked_units)],
  ];
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Research" }, { label: "Performance" }]}
        title="Performance"
        description="Shadow picks settled at the price that was captured when the pick was made. No money was staked: this measures whether the models' edge was real, nothing else."
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(([label, value]) => (
          <div key={label} className="surface-panel px-4 py-3">
            <div className="text-label text-subtle-foreground">{label}</div>
            <div className="mt-1.5 numeric-lg">
              <Nullable value={value} reason={reason ?? "Not computable yet."} />
            </div>
          </div>
        ))}
      </div>
      <Panel title="Sample">
        <KeyValue label="Settled picks" value={int(d?.settled ?? null)} />
        <KeyValue label="Pending picks" value={int(d?.pending ?? null)} />
        {q.data ? (
          <StatusNotice status={q.data.status} reason={q.data.reason} compact className="mt-2" />
        ) : null}
        {d ? <p className="mt-2 text-caption text-subtle-foreground">{d.note}</p> : null}
      </Panel>
      {d && d.slices?.length ? <PerformanceSlices slices={d.slices} /> : null}
    </div>
  );
}

const SLICE_TITLE: Record<PerformanceSlice["dimension"], string> = {
  market: "By market",
  model: "By model",
  rule: "By decision rule",
  month: "By month of kick-off",
  odds_band: "By price band",
};

function PerformanceSlices({ slices }: { slices: PerformanceSlice[] }) {
  const dims = ["model", "market", "rule", "odds_band", "month"] as const;
  return (
    <div className="space-y-4">
      <p className="text-caption text-muted-foreground">
        ± is a 95% interval on the ROI from the spread of bet results (shown from 30 bets). An
        interval that contains 0 means the result is not distinguishable from luck. &ldquo;Model
        expected&rdquo; is what the model&apos;s own EV promised for the same bets.
      </p>
      <div className="grid gap-4 xl:grid-cols-2">
        {dims.map((dim) => {
          const rows = slices.filter((s) => s.dimension === dim);
          if (!rows.length) return null;
          return (
            <Panel key={dim} title={SLICE_TITLE[dim]} bodyClassName="">
              <TableShell compact>
                <THead>
                  <TH>{dim === "odds_band" ? "Odds" : dim}</TH>
                  <TH align="right">Bets</TH>
                  <TH align="right">Hit</TH>
                  <TH align="right">P&amp;L</TH>
                  <TH align="right">ROI</TH>
                  <TH align="right">Model expected</TH>
                </THead>
                <tbody>
                  {rows.map((r) => {
                    const roi = r.roi_pct === null ? null : Number(r.roi_pct);
                    return (
                      <TRow key={`${dim}-${r.key}`}>
                        <TD className="text-sm">{r.key}</TD>
                        <TD align="right">
                          <Numeric className="text-xs">{r.settled}</Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric muted className="text-xs">
                            {r.hit_rate !== null ? `${dec(r.hit_rate, 1)}%` : "—"}
                          </Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric className="text-xs">{dec(r.profit_units, 2) ?? "—"}</Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric
                            className={
                              roi === null
                                ? "text-xs"
                                : roi > 0
                                  ? "text-xs text-positive"
                                  : "text-xs text-negative"
                            }
                          >
                            {roi === null ? "—" : `${dec(r.roi_pct, 1)}%`}
                            {r.roi_ci95_pct !== null ? (
                              <span className="text-subtle-foreground">
                                {" "}
                                ±{dec(r.roi_ci95_pct, 0)}
                              </span>
                            ) : null}
                          </Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric muted className="text-xs">
                            {dec(r.expected_profit_units, 2) ?? "—"}
                          </Numeric>
                        </TD>
                      </TRow>
                    );
                  })}
                </tbody>
              </TableShell>
            </Panel>
          );
        })}
      </div>
    </div>
  );
}

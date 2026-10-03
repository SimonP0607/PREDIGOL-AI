/**
 * Live Intelligence: every tracked match in play, refreshed every 15 seconds.
 * Two feeds, kept apart and labelled: the fixture feed (score, minute, events,
 * statistics) and the odds feed (in-play prices). A match nobody quotes in play
 * still shows - it just says "no in-play prices".
 */
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricCard, Panel } from "@/components/primitives/Panel";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { LiveMatch, LiveQuote } from "@/lib/api/v1/types_center";
import { cn } from "@/lib/utils";
import { dec, relative } from "./format";
import { StatComparison } from "./MatchCenterExtra";
import { minuteText } from "./liveText";

function MainOdds({ quotes }: { quotes: LiveQuote[] }) {
  const x12 = ["Home", "Draw", "Away"].map((s) =>
    quotes.find((q) => q.market_key === "1X2" && q.selection === s),
  );
  const ou = quotes.filter((q) => q.market_key === "OU");
  const overs = ou.filter((q) => q.selection === "Over");
  const line = overs.length ? overs[0]!.line : null;
  const over = overs[0];
  const under = ou.find((q) => q.selection === "Under" && q.line === line);
  const cell = (q: LiveQuote | undefined, label: string) => (
    <div className="flex flex-col items-center rounded border border-border px-2 py-1">
      <span className="text-caption text-subtle-foreground">{label}</span>
      <span
        className={cn("numeric text-sm", q?.suspended ? "text-warning line-through" : "")}
        title={q?.suspended ? "Suspended" : q?.odds === null ? "Withdrawn" : undefined}
      >
        {q ? (dec(q.odds, 2) ?? "—") : "—"}
      </span>
    </div>
  );
  if (!quotes.length) {
    return <p className="text-caption text-subtle-foreground">No in-play prices for this match.</p>;
  }
  return (
    <div className="grid grid-cols-5 gap-1.5">
      {cell(x12[0], "1")}
      {cell(x12[1], "X")}
      {cell(x12[2], "2")}
      {cell(over, line ? `O ${dec(line, 1)}` : "Over")}
      {cell(under, line ? `U ${dec(line, 1)}` : "Under")}
    </div>
  );
}

function MatchCard({ m }: { m: LiveMatch }) {
  const goals = m.events.filter((e) => e.type === "Goal" && e.detail !== "Missed Penalty");
  const reds = m.events.filter((e) => e.type === "Card" && e.detail !== "Yellow Card");
  return (
    <Panel bodyClassName="p-0" className="h-full">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <span className="min-w-0 truncate text-caption text-muted-foreground">
          {m.competition}
          {m.country ? ` · ${m.country}` : ""}
        </span>
        <div className="flex shrink-0 items-center gap-1.5">
          {m.data_status === "stale" ? (
            <StatusBadge tone="warning">
              stale {Math.round(m.state_age_seconds / 60)} min
            </StatusBadge>
          ) : null}
          <StatusBadge tone="brand">
            {m.status === "HT" ? "HT" : minuteText(m.elapsed, m.extra)}
          </StatusBadge>
        </div>
      </div>
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(m.fixture_id) }}
        className="block px-3 py-3 hover:bg-muted/40"
      >
        <div className="grid grid-cols-[1fr_auto] items-center gap-2 text-sm">
          <span className="truncate font-medium">{m.home.name}</span>
          <span className="numeric text-lg">{m.goals_home ?? "?"}</span>
          <span className="truncate font-medium">{m.away.name}</span>
          <span className="numeric text-lg">{m.goals_away ?? "?"}</span>
        </div>
        {goals.length || reds.length ? (
          <ul className="mt-2 space-y-0.5 text-caption text-muted-foreground">
            {[...goals, ...reds]
              .sort((a, b) => a.minute - b.minute)
              .map((e) => (
                <li key={e.seq} className={cn(e.side === "away" ? "text-right" : "")}>
                  <span className={e.type === "Card" ? "text-negative" : "text-positive"}>
                    {e.type === "Card" ? "■" : "●"}
                  </span>{" "}
                  {minuteText(e.minute, e.extra_minute)} {e.player ?? "?"}
                </li>
              ))}
          </ul>
        ) : null}
      </Link>
      {m.statistics.length ? (
        <div className="border-t border-border px-3 py-2">
          <StatComparison
            lines={m.statistics}
            sides={{ home: m.home.name, away: m.away.name }}
            rows={[
              { key: "possession_pct", label: "Possession", pct: true },
              { key: "expected_goals", label: "xG", decimals: 2 },
              { key: "shots_on_target", label: "Shots on target" },
              { key: "corners", label: "Corners" },
            ]}
          />
        </div>
      ) : null}
      <div className="border-t border-border px-3 py-2">
        <MainOdds quotes={m.main_odds} />
        <div className="mt-1.5 flex flex-wrap justify-between gap-1 text-caption text-subtle-foreground">
          <span>
            state: {m.state_source === "fixture_feed" ? "fixture feed" : "odds feed"} ·{" "}
            {relative(m.state_at)}
          </span>
          {m.markets_offered !== null ? (
            <span>
              {m.markets_offered} markets · {m.values_suspended ?? 0} suspended
            </span>
          ) : (
            <span>not priced in play</span>
          )}
        </div>
      </div>
    </Panel>
  );
}

export function LiveBoardLive() {
  const q = useLiveQuery(live.liveBoard);
  const board = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Operations" }, { label: "Live" }]}
        title="Live"
        description="Tracked matches in play. Refreshed every 15 seconds from the API; the worker follows each match every minute and captures in-play prices every 30 seconds."
        actions={
          q.dataUpdatedAt ? (
            <span className="text-caption text-subtle-foreground">
              updated {relative(new Date(q.dataUpdatedAt).toISOString())}
            </span>
          ) : null
        }
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={4} cols={4} /> : null}
      {board ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard label="Matches in play" value={String(board.matches.length)} />
            <MetricCard
              label="Followed by fixture feed"
              value={String(board.followed_by_fixture_feed)}
              hint="score, minute, events, statistics"
            />
            <MetricCard
              label="Priced in play"
              value={String(board.priced_by_odds_feed)}
              hint="odds feed, last 5 min"
            />
            <MetricCard
              label="Last in-play price"
              value={board.last_odds_feed_at ? relative(board.last_odds_feed_at) : null}
              hint={
                board.last_fixture_feed_at
                  ? `fixture feed ${relative(board.last_fixture_feed_at)}`
                  : "fixture feed: never"
              }
            />
          </div>
          {q.data && q.data.status !== "ok" ? (
            <Panel>
              <StatusNotice status={q.data.status} reason={q.data.reason} />
            </Panel>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {board.matches.map((m) => (
                <MatchCard key={m.fixture_id} m={m} />
              ))}
            </div>
          )}
          <p className="text-caption text-subtle-foreground">
            <Numeric muted className="text-caption">
              In-play prices
            </Numeric>{" "}
            are a separate series from pre-match prices and are never used for pre-match
            backtesting.
          </p>
        </>
      ) : null}
    </div>
  );
}

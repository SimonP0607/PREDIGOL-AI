import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { Numeric } from "@/components/primitives/Indicators";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { FilterBar, SearchFilter, SegmentedTabs, SelectFilter } from "@/components/system/Filters";
import { DateNav, formatDay } from "@/components/football/DateNav";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { MatchQuery } from "@/lib/api/v1/client";
import { int } from "@/lib/format";
import { isoDay, relative, utcDateTime } from "./format";
import { FixtureLink, ScoreText, StatusGroupBadge } from "./shared";
import { minuteText } from "./liveText";

const tabs = ["All", "Scheduled", "Live", "Finished", "Postponed"] as const;
type Tab = (typeof tabs)[number];
const views = ["By day", "All stored"] as const;
type View = (typeof views)[number];
const PAGE = 50;

export function MatchesLive() {
  const today = isoDay(new Date());
  const [view, setView] = useState<View>("By day");
  const [day, setDay] = useState(today);
  const [tab, setTab] = useState<Tab>("All");
  const [competition, setCompetition] = useState("all");
  const [term, setTerm] = useState("");
  const [pages, setPages] = useState(1);

  const competitions = useLiveQuery(live.competitions);
  const query: MatchQuery = {
    order: view === "By day" ? "asc" : "desc",
    limit: PAGE * pages,
    ...(view === "By day" ? { date_from: day, date_to: day } : {}),
    ...(tab !== "All" ? { status: tab.toLowerCase() } : {}),
    ...(competition !== "all" ? { competition_id: Number(competition) } : {}),
  };
  const matches = useLiveQuery(live.matches(query));
  // Score and minute of matches in play come from the live follow, not the result row.
  const board = useLiveQuery(live.liveBoard);
  const inPlay = useMemo(
    () => new Map((board.data?.data.matches ?? []).map((m) => [m.fixture_id, m])),
    [board.data],
  );

  const rows = useMemo(() => {
    const all = matches.data?.data ?? [];
    const q = term.trim().toLowerCase();
    if (!q) return all;
    return all.filter((m) =>
      `${m.home.name} ${m.away.name} ${m.competition.name} ${m.round ?? ""}`
        .toLowerCase()
        .includes(q),
    );
  }, [matches.data, term]);

  const withFixtures = (competitions.data?.data ?? []).filter((c) => c.fixtures > 0);
  const total = matches.data?.meta.total ?? null;
  const awaiting = rows.filter((m) => m.awaiting_result).length;

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Football" }, { label: "Matches" }]}
        title="Matches"
        description="Every fixture the ingestion layer has stored, with its score, status and what the capturer has seen for it."
      />

      <div className="flex flex-wrap items-center gap-2">
        <SegmentedTabs
          label="View"
          tabs={views}
          value={view}
          onChange={(v) => {
            setView(v);
            setPages(1);
          }}
          className="w-auto"
        />
        {view === "By day" ? (
          <DateNav
            value={day}
            today={today}
            onChange={(d) => {
              setDay(d);
              setPages(1);
            }}
          />
        ) : null}
      </div>

      <FilterBar>
        <SegmentedTabs
          label="Status"
          tabs={tabs}
          value={tab}
          onChange={(t) => {
            setTab(t);
            setPages(1);
          }}
          className="w-auto"
        />
        <SelectFilter
          label="Competition"
          value={competition}
          onChange={(v) => {
            setCompetition(v);
            setPages(1);
          }}
          options={[
            { value: "all", label: "All competitions" },
            ...withFixtures.map((c) => ({ value: String(c.id), label: c.name })),
          ]}
        />
        <SearchFilter
          value={term}
          onChange={setTerm}
          placeholder="Team, competition, round"
          label="Filter loaded rows"
        />
      </FilterBar>

      <Panel
        title={view === "By day" ? formatDay(day) : "Stored fixtures"}
        subtitle={
          total === null
            ? "Loading…"
            : `${int(total)} fixture(s) match · showing ${rows.length}${awaiting ? ` · ${awaiting} awaiting a result` : ""}`
        }
        bodyClassName=""
      >
        {matches.isLoading ? (
          <TableSkeleton rows={6} cols={7} />
        ) : matches.isError ? (
          <div className="p-4">
            <ApiErrorNotice error={matches.error} />
          </div>
        ) : matches.data && matches.data.status !== "ok" ? (
          <StatusNotice status={matches.data.status} reason={matches.data.reason} />
        ) : rows.length === 0 ? (
          <StatusNotice status="empty" reason="No loaded fixture matches this text filter." />
        ) : (
          <TableShell>
            <THead>
              <TH>Kick-off</TH>
              <TH>Competition</TH>
              <TH>Fixture</TH>
              <TH align="center">Score</TH>
              <TH>Status</TH>
              <TH align="right" title="Pre-match price snapshots captured">
                Prices
              </TH>
              <TH align="right">Books</TH>
              <TH>Last capture</TH>
            </THead>
            <tbody>
              {rows.map((m) => (
                <TRow key={m.id}>
                  <TD className="whitespace-nowrap">
                    <Numeric className="text-xs">
                      {view === "By day"
                        ? utcDateTime(m.kickoff_at).split(" ").slice(-2).join(" ")
                        : utcDateTime(m.kickoff_at)}
                    </Numeric>
                  </TD>
                  <TD className="max-w-[11rem]">
                    <div className="truncate text-xs" title={m.competition.name}>
                      {m.competition.name}
                    </div>
                    <div className="truncate text-caption text-subtle-foreground">
                      {m.round ?? `season ${m.competition.season}`}
                    </div>
                  </TD>
                  <TD className="max-w-[20rem]">
                    <FixtureLink match={m} />
                  </TD>
                  <TD align="center">
                    {inPlay.get(m.id) && !m.score ? (
                      <span
                        className="numeric font-medium text-primary"
                        title="Live score from the match follow"
                      >
                        {inPlay.get(m.id)!.goals_home ?? "?"}–{inPlay.get(m.id)!.goals_away ?? "?"}
                      </span>
                    ) : (
                      <ScoreText score={m.score} />
                    )}
                  </TD>
                  <TD className="whitespace-nowrap">
                    {inPlay.get(m.id) ? (
                      <StatusBadge tone="brand">
                        {inPlay.get(m.id)!.status === "HT"
                          ? "half time"
                          : `live ${minuteText(inPlay.get(m.id)!.elapsed, inPlay.get(m.id)!.extra)}`}
                      </StatusBadge>
                    ) : (
                      <StatusGroupBadge match={m} />
                    )}
                  </TD>
                  <TD align="right">
                    <Numeric muted={m.odds.snapshots === 0}>{int(m.odds.snapshots)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric muted={m.odds.bookmakers === 0}>{int(m.odds.bookmakers)}</Numeric>
                  </TD>
                  <TD>
                    <Nullable
                      value={m.odds.last_captured_at ? relative(m.odds.last_captured_at) : null}
                      reason="No odds snapshot has been captured for this fixture."
                      className="numeric text-xs"
                    />
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
        {total !== null && (matches.data?.data.length ?? 0) < total ? (
          <div className="border-t border-border p-3 text-center">
            <button
              type="button"
              onClick={() => setPages((p) => p + 1)}
              className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-elevated focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              Load {Math.min(PAGE, total - (matches.data?.data.length ?? 0))} more
            </button>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}

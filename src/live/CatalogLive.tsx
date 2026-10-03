import { useEffect, useState } from "react";
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { FilterBar, SearchFilter, SegmentedTabs } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, SectionView, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import { int } from "@/lib/format";
import { utcDate, utcDateTime } from "./format";
import { FixtureLink, ScoreText, StatusGroupBadge } from "./shared";

const scopes = ["Tracked", "With fixtures", "All known"] as const;
type Scope = (typeof scopes)[number];

export function CompetitionsLive() {
  const [scope, setScope] = useState<Scope>("With fixtures");
  const [term, setTerm] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const list = useLiveQuery(live.competitions);

  const all = list.data?.data ?? [];
  const q = term.trim().toLowerCase();
  const rows = all.filter((c) => {
    if (scope === "Tracked" && !c.is_tracked) return false;
    if (scope === "With fixtures" && c.fixtures === 0) return false;
    return !q || `${c.name} ${c.country ?? ""}`.toLowerCase().includes(q);
  });

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Football" }, { label: "Competitions" }]}
        title="Competitions"
        description="The catalogue the system knows, which competitions it tracks, and how deep the stored history goes."
      />
      <FilterBar>
        <SegmentedTabs
          label="Scope"
          tabs={scopes}
          value={scope}
          onChange={setScope}
          className="w-auto"
        />
        <SearchFilter
          value={term}
          onChange={setTerm}
          placeholder="Name or country"
          label="Filter"
        />
      </FilterBar>
      <div className="grid gap-4 xl:grid-cols-5">
        <Panel
          title="Catalogue"
          subtitle={
            list.data ? `${rows.length} shown · ${int(list.data.meta.total)} known` : "Loading…"
          }
          className="xl:col-span-3"
          bodyClassName=""
        >
          {list.isLoading ? (
            <TableSkeleton rows={6} cols={5} />
          ) : list.isError ? (
            <div className="p-4">
              <ApiErrorNotice error={list.error} />
            </div>
          ) : rows.length === 0 ? (
            <StatusNotice status="empty" reason="No competition in this scope." />
          ) : (
            <TableShell>
              <THead>
                <TH>Competition</TH>
                <TH>Type</TH>
                <TH align="right">Seasons</TH>
                <TH align="right">Fixtures</TH>
                <TH align="right">Teams</TH>
                <TH>Tracking</TH>
              </THead>
              <tbody>
                {rows.map((c) => (
                  <TRow key={c.id} onClick={() => setSelected(c.id)} selected={selected === c.id}>
                    <TD>
                      <div className="text-sm">{c.name}</div>
                      <div className="text-caption text-subtle-foreground">
                        {c.country ?? "International"}
                      </div>
                    </TD>
                    <TD className="text-xs text-muted-foreground">
                      {c.competition_type.replaceAll("_", " ")}
                    </TD>
                    <TD align="right">
                      <Numeric>{int(c.seasons)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric muted={c.fixtures === 0}>{int(c.fixtures)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric muted={c.teams === 0}>{int(c.teams)}</Numeric>
                    </TD>
                    <TD>
                      {c.is_tracked ? (
                        <StatusBadge tone="positive">tracked</StatusBadge>
                      ) : (
                        <StatusBadge tone="neutral">catalogue</StatusBadge>
                      )}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>
        <div className="xl:col-span-2">
          {selected === null ? (
            <Panel title="Details">
              <StatusNotice
                status="empty"
                reason="Select a competition to see its seasons and teams."
              />
            </Panel>
          ) : (
            <CompetitionDetailPanel id={selected} />
          )}
        </div>
      </div>
    </div>
  );
}

function CompetitionDetailPanel({ id }: { id: number }) {
  const q = useLiveQuery(live.competition(String(id)));
  if (q.isLoading)
    return (
      <Panel title="Details">
        <TableSkeleton rows={4} cols={3} />
      </Panel>
    );
  if (q.isError || !q.data)
    return (
      <Panel title="Details">
        <ApiErrorNotice error={q.error} />
      </Panel>
    );
  const { competition: c, seasons, teams } = q.data.data;
  return (
    <div className="space-y-4">
      <Panel
        title={c.name}
        subtitle={`${c.country ?? "International"} · provider league ${c.provider_league_id}`}
      >
        <KeyValue label="Tracked" value={c.is_tracked ? "yes" : "no"} />
        <KeyValue
          label="Current season"
          value={
            <Nullable
              value={c.current_season === null ? null : String(c.current_season)}
              reason="No season is marked current."
            />
          }
        />
        <KeyValue
          label="Tier"
          value={
            <Nullable
              value={c.tier === null ? null : String(c.tier)}
              reason="Tier not set in the catalogue."
            />
          }
        />
      </Panel>
      <Panel
        title="Seasons"
        subtitle="Stored fixtures and how many have a recorded result"
        bodyClassName=""
      >
        {seasons.length === 0 ? (
          <StatusNotice
            status="empty"
            reason="No season of this competition is stored."
            compact
            className="p-4"
          />
        ) : (
          <TableShell className="min-w-0">
            <THead>
              <TH>Season</TH>
              <TH align="right">Fixtures</TH>
              <TH align="right">Finished</TH>
              <TH align="right">With result</TH>
              <TH>Odds</TH>
            </THead>
            <tbody>
              {seasons.map((s) => (
                <TRow key={s.id}>
                  <TD>
                    <Numeric>{s.season}</Numeric>
                    {s.is_current ? (
                      <span className="ml-1.5 text-caption text-primary">current</span>
                    ) : null}
                  </TD>
                  <TD align="right">
                    <Numeric>{int(s.fixtures)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{int(s.finished)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric className={s.with_results < s.finished ? "text-warning" : ""}>
                      {int(s.with_results)}
                    </Numeric>
                  </TD>
                  <TD>
                    {s.has_odds ? (
                      <StatusBadge tone="info">covered</StatusBadge>
                    ) : (
                      <span className="text-caption text-subtle-foreground">no</span>
                    )}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>
      <Panel title="Teams" subtitle="Teams appearing in stored fixtures">
        {teams.length === 0 ? (
          <StatusNotice
            status="empty"
            reason="No fixture of this competition is stored, so no team is known."
            compact
          />
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {teams.map((t) => (
              <li key={t.id} className="rounded border border-border px-2 py-0.5 text-xs">
                {t.name}
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <StandingsPanel competitionId={id} />
    </div>
  );
}

export function TeamsLive() {
  const [term, setTerm] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  // Searched on the server: 8,000+ teams, and only the first 200 are listed without a search.
  const q = useDebounced(term.trim(), 250);
  const list = useLiveQuery(q.length >= 2 ? live.teamSearch(q) : live.teams);
  const rows = list.data?.data ?? [];
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Football" }, { label: "Teams" }]}
        title="Teams"
        description="Teams that appear in stored fixtures. Records count recorded results only: a match without a score is unknown, not a draw."
      />
      <FilterBar>
        <SearchFilter value={term} onChange={setTerm} placeholder="Team name" label="Filter" />
      </FilterBar>
      <div className="grid gap-4 xl:grid-cols-5">
        <Panel
          title="Teams"
          subtitle={
            list.data
              ? `${rows.length} shown${q.length >= 2 ? ` for “${q}”` : " · type 2+ letters to search all teams"}`
              : "Loading…"
          }
          className="xl:col-span-2"
          bodyClassName=""
        >
          {list.isLoading ? (
            <TableSkeleton rows={8} cols={3} />
          ) : list.isError ? (
            <div className="p-4">
              <ApiErrorNotice error={list.error} />
            </div>
          ) : list.data && list.data.status !== "ok" ? (
            <StatusNotice status={list.data.status} reason={list.data.reason} />
          ) : (
            <TableShell className="min-w-0">
              <THead>
                <TH>Team</TH>
                <TH align="right">Fixtures</TH>
                <TH align="right">Results</TH>
              </THead>
              <tbody>
                {rows.map((t) => (
                  <TRow key={t.id} onClick={() => setSelected(t.id)} selected={selected === t.id}>
                    <TD className="text-sm">{t.name}</TD>
                    <TD align="right">
                      <Numeric>{int(t.fixtures)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric muted={t.results === 0}>{int(t.results)}</Numeric>
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>
        <div className="xl:col-span-3">
          {selected === null ? (
            <Panel title="Team">
              <StatusNotice status="empty" reason="Select a team to see its record and fixtures." />
            </Panel>
          ) : (
            <TeamDetailPanel id={selected} />
          )}
        </div>
      </div>
    </div>
  );
}

function TeamDetailPanel({ id }: { id: number }) {
  const q = useLiveQuery(live.team(String(id)));
  if (q.isLoading)
    return (
      <Panel title="Team">
        <TableSkeleton rows={4} cols={3} />
      </Panel>
    );
  if (q.isError || !q.data)
    return (
      <Panel title="Team">
        <ApiErrorNotice error={q.error} />
      </Panel>
    );
  const d = q.data.data;
  return (
    <div className="space-y-4">
      <Panel
        title={d.team.name}
        subtitle={`provider team ${d.team.provider_team_id}${d.venue ? ` · ${d.venue.name}` : ""}`}
      >
        <SectionView section={d.record}>
          {(r) =>
            r ? (
              <div className="grid grid-cols-3 gap-2 text-center sm:grid-cols-6">
                {(
                  [
                    ["Played", r.played],
                    ["Won", r.won],
                    ["Drawn", r.drawn],
                    ["Lost", r.lost],
                    ["For", r.goals_for],
                    ["Against", r.goals_against],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k} className="rounded border border-border px-2 py-1.5">
                    <div className="text-caption text-subtle-foreground">{k}</div>
                    <div className="numeric text-base">{v}</div>
                  </div>
                ))}
              </div>
            ) : null
          }
        </SectionView>
      </Panel>
      <SquadPanel teamId={id} />
      {(["recent", "upcoming"] as const).map((k) => (
        <Panel
          key={k}
          title={k === "recent" ? "Recent fixtures" : "Upcoming fixtures"}
          bodyClassName=""
        >
          {d[k].length === 0 ? (
            <StatusNotice
              status="empty"
              reason={k === "recent" ? "No past fixture stored." : "No upcoming fixture stored."}
              compact
              className="p-4"
            />
          ) : (
            <TableShell className="min-w-0">
              <THead>
                <TH>Date</TH>
                <TH>Fixture</TH>
                <TH align="center">Score</TH>
                <TH>Status</TH>
              </THead>
              <tbody>
                {d[k].map((m) => (
                  <TRow key={m.id}>
                    <TD>
                      <Numeric>
                        {k === "recent" ? utcDate(m.kickoff_at) : utcDateTime(m.kickoff_at)}
                      </Numeric>
                    </TD>
                    <TD>
                      <FixtureLink match={m} />
                    </TD>
                    <TD align="center">
                      <ScoreText score={m.score} />
                    </TD>
                    <TD>
                      <StatusGroupBadge match={m} />
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>
      ))}
    </div>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Players with a stored appearance for this team in the last 400 days, by minutes. */
function SquadPanel({ teamId }: { teamId: number }) {
  const q = useLiveQuery(live.players({ team_id: teamId }));
  const rows = (q.data?.data ?? []).slice(0, 30);
  return (
    <Panel
      title="Squad"
      subtitle="Players with a stored appearance in the last 400 days, by minutes"
      bodyClassName=""
    >
      {q.isLoading ? (
        <TableSkeleton rows={4} cols={5} />
      ) : q.isError ? (
        <div className="p-4">
          <ApiErrorNotice error={q.error} />
        </div>
      ) : q.data && q.data.status !== "ok" ? (
        <StatusNotice status={q.data.status} reason={q.data.reason} compact className="p-4" />
      ) : (
        <TableShell className="min-w-0" compact>
          <THead>
            <TH>Player</TH>
            <TH>Pos</TH>
            <TH align="right">Apps</TH>
            <TH align="right">Min</TH>
            <TH align="right">G</TH>
            <TH align="right">A</TH>
          </THead>
          <tbody>
            {rows.map((p) => (
              <TRow key={p.id}>
                <TD className="text-sm">
                  <Link
                    to="/players/$playerId"
                    params={{ playerId: String(p.id) }}
                    className="hover:text-primary"
                  >
                    {p.name}
                  </Link>
                </TD>
                <TD className="text-xs text-muted-foreground">{p.position ?? "—"}</TD>
                <TD align="right">
                  <Numeric className="text-xs">{p.apps}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric muted className="text-xs">
                    {p.minutes ?? "—"}
                  </Numeric>
                </TD>
                <TD align="right">
                  <Numeric className="text-xs">{p.goals ?? "—"}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric className="text-xs">{p.assists ?? "—"}</Numeric>
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      )}
    </Panel>
  );
}

/** The latest league table stored for the competition, refreshed every 12 h by the worker. */
function StandingsPanel({ competitionId }: { competitionId: number }) {
  const q = useLiveQuery(live.standings(String(competitionId)));
  const t = q.data?.data ?? null;
  return (
    <Panel
      title="League table"
      subtitle={t ? `${t.season} · snapshot ${utcDateTime(t.snapshot_at)}` : "Latest stored table"}
      bodyClassName=""
    >
      {q.isLoading ? (
        <TableSkeleton rows={6} cols={6} />
      ) : q.isError ? (
        <div className="p-4">
          <ApiErrorNotice error={q.error} />
        </div>
      ) : !t ? (
        <StatusNotice
          status={q.data?.status ?? "empty"}
          reason={q.data?.reason ?? null}
          compact
          className="p-4"
        />
      ) : (
        <TableShell className="min-w-0" compact>
          <THead>
            <TH align="right">#</TH>
            <TH>Team</TH>
            <TH align="right">P</TH>
            <TH align="right">W-D-L</TH>
            <TH align="right">GD</TH>
            <TH align="right">Pts</TH>
            <TH>Form</TH>
          </THead>
          <tbody>
            {t.rows.map((r, i) => (
              <TRow key={`${r.group ?? ""}-${r.team_id}`}>
                <TD align="right">
                  <Numeric className="text-xs">{r.rank}</Numeric>
                </TD>
                <TD className="text-sm">
                  {r.team}
                  {r.group &&
                  (i === 0 || t.rows[i - 1]?.group !== r.group) &&
                  t.rows.some((x) => x.group !== r.group) ? (
                    <div className="text-caption text-subtle-foreground">{r.group}</div>
                  ) : null}
                </TD>
                <TD align="right">
                  <Numeric muted className="text-xs">
                    {r.played}
                  </Numeric>
                </TD>
                <TD align="right">
                  <Numeric className="text-xs">
                    {r.wins}-{r.draws}-{r.losses}
                  </Numeric>
                </TD>
                <TD align="right">
                  <Numeric className="text-xs">{r.goals_for - r.goals_against}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric>{r.points}</Numeric>
                </TD>
                <TD className="numeric text-caption text-muted-foreground">{r.form ?? "—"}</TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      )}
    </Panel>
  );
}

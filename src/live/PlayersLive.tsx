/** Players: search, a team's squad, the most productive of the last 30 days, and a profile. */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { Numeric } from "@/components/primitives/Indicators";
import { SearchFilter } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, SectionView, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { PlayerSummary } from "@/lib/api/v1/types_center";
import { dec, utcDate } from "./format";

function age(birth: string | null): string | null {
  if (!birth) return null;
  const b = new Date(birth);
  const n = new Date();
  let a = n.getUTCFullYear() - b.getUTCFullYear();
  if (
    n.getUTCMonth() < b.getUTCMonth() ||
    (n.getUTCMonth() === b.getUTCMonth() && n.getUTCDate() < b.getUTCDate())
  )
    a--;
  return String(a);
}

function PlayersTable({ rows }: { rows: PlayerSummary[] }) {
  return (
    <TableShell>
      <THead>
        <TH>Player</TH>
        <TH>Team (latest)</TH>
        <TH>Pos</TH>
        <TH align="right">Age</TH>
        <TH align="right" title="Appearances with statistics in the window">
          Apps
        </TH>
        <TH align="right">Min</TH>
        <TH align="right">G</TH>
        <TH align="right">A</TH>
        <TH align="right">Rating</TH>
        <TH>Last played</TH>
      </THead>
      <tbody>
        {rows.map((p) => (
          <TRow key={p.id}>
            <TD className="text-sm">
              <Link
                to="/admin/players/$playerId"
                params={{ playerId: String(p.id) }}
                className="hover:text-primary"
              >
                {p.name}
              </Link>
              <div className="text-caption text-subtle-foreground">
                {p.nationality ?? "nationality not reported"}
              </div>
            </TD>
            <TD className="text-xs">
              {p.team_id ? (
                <span className="text-muted-foreground">{p.team}</span>
              ) : (
                <Nullable value={null} reason="No appearance with statistics in the window." />
              )}
            </TD>
            <TD className="text-xs text-muted-foreground">{p.position ?? "—"}</TD>
            <TD align="right">
              <Numeric muted className="text-xs">
                <Nullable value={age(p.birth_date)} reason="Birth date not reported." />
              </Numeric>
            </TD>
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
            <TD align="right">
              <Numeric className="text-xs">
                <Nullable value={dec(p.avg_rating, 2)} reason="No rated appearance." />
              </Numeric>
            </TD>
            <TD className="text-xs text-muted-foreground">
              {p.last_played ? utcDate(p.last_played) : "—"}
            </TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

export function PlayersLive() {
  const [q, setQ] = useState("");
  const term = q.trim().length >= 3 ? q.trim() : "";
  const query = useLiveQuery(live.players({ q: term || undefined }));
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Football" }, { label: "Players" }]}
        title="Players"
        description="Players from line-ups and match statistics. Without a search: the most productive players of the last 30 days. Figures cover the last 400 days."
      />
      <div className="max-w-sm">
        <SearchFilter
          label="Player search"
          value={q}
          onChange={setQ}
          placeholder="Search a player (3+ letters)…"
        />
      </div>
      <Panel
        title={term ? `Players matching “${term}”` : "Most productive, last 30 days"}
        subtitle={
          term ? "Ordered by appearances in the last 400 days." : "Ordered by goals, then rating."
        }
        bodyClassName=""
      >
        {query.isLoading ? (
          <TableSkeleton rows={8} cols={8} />
        ) : query.isError ? (
          <div className="p-4">
            <ApiErrorNotice error={query.error} />
          </div>
        ) : query.data ? (
          query.data.status === "ok" ? (
            <PlayersTable rows={query.data.data} />
          ) : (
            <StatusNotice status={query.data.status} reason={query.data.reason} />
          )
        ) : null}
      </Panel>
    </div>
  );
}

export function PlayerLive({ playerId }: { playerId: string }) {
  const q = useLiveQuery(live.player(playerId));
  if (q.isLoading) return <TableSkeleton rows={8} cols={6} />;
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  const d = q.data?.data;
  if (!q.data || !d) {
    return (
      <div className="space-y-4">
        <PageHeader
          breadcrumb={[{ label: "Players", to: "/admin/players" }]}
          title="Player not found"
        />
        {q.data ? <StatusNotice status={q.data.status} reason={q.data.reason} /> : null}
      </div>
    );
  }
  const p = d.player;
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Players", to: "/admin/players" }, { label: p.name }]}
        title={p.name}
        description={[p.position, p.nationality, p.team].filter(Boolean).join(" · ") || undefined}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Profile">
          <KeyValue
            label="Full name"
            value={[d.firstname, d.lastname].filter(Boolean).join(" ") || "—"}
          />
          <KeyValue
            label="Born"
            value={p.birth_date ? `${p.birth_date} (age ${age(p.birth_date)})` : "—"}
          />
          <KeyValue label="Nationality" value={p.nationality ?? "—"} />
          <KeyValue label="Position" value={p.position ?? "—"} />
          <KeyValue label="Height" value={d.height_cm ? `${d.height_cm} cm` : "—"} />
          <KeyValue label="Weight" value={d.weight_kg ? `${d.weight_kg} kg` : "—"} />
          <KeyValue label="Latest team" value={p.team ?? "—"} />
          <KeyValue label="Provider id" value={p.provider_player_id} />
        </Panel>
        <Panel title="Last 400 days" className="lg:col-span-2">
          <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
            <KeyValue label="Appearances" value={p.apps} />
            <KeyValue label="Minutes" value={p.minutes ?? "—"} />
            <KeyValue label="Goals" value={p.goals ?? "—"} />
            <KeyValue label="Assists" value={p.assists ?? "—"} />
            <KeyValue label="Avg rating" value={dec(p.avg_rating, 2) ?? "—"} />
            <KeyValue label="Last played" value={p.last_played ? utcDate(p.last_played) : "—"} />
          </div>
        </Panel>
      </div>
      <Panel title="By competition and season" bodyClassName="">
        <SectionView section={d.seasons}>
          {(rows) => (
            <TableShell>
              <THead>
                <TH>Season</TH>
                <TH>Competition</TH>
                <TH>Team</TH>
                <TH align="right">Apps</TH>
                <TH align="right">Starts</TH>
                <TH align="right">Min</TH>
                <TH align="right">G</TH>
                <TH align="right">A</TH>
                <TH align="right">Y</TH>
                <TH align="right">R</TH>
                <TH align="right">Rating</TH>
              </THead>
              <tbody>
                {rows.map((s) => (
                  <TRow key={`${s.season}-${s.competition}`}>
                    <TD>
                      <Numeric className="text-xs">{s.season}</Numeric>
                    </TD>
                    <TD className="text-sm">{s.competition}</TD>
                    <TD className="text-xs text-muted-foreground">{s.team ?? "—"}</TD>
                    {[
                      s.apps,
                      s.starts,
                      s.minutes,
                      s.goals,
                      s.assists,
                      s.yellow_cards,
                      s.red_cards,
                    ].map((v, i) => (
                      <TD key={i} align="right">
                        <Numeric className="text-xs" muted={!v}>
                          {v ?? "—"}
                        </Numeric>
                      </TD>
                    ))}
                    <TD align="right">
                      <Numeric className="text-xs">{dec(s.avg_rating, 2) ?? "—"}</Numeric>
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </SectionView>
      </Panel>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Recent matches" className="lg:col-span-2" bodyClassName="">
          <SectionView section={d.matches}>
            {(rows) => (
              <TableShell>
                <THead>
                  <TH>Date</TH>
                  <TH>Match</TH>
                  <TH align="right">Min</TH>
                  <TH align="right">G</TH>
                  <TH align="right">A</TH>
                  <TH align="right">Rating</TH>
                </THead>
                <tbody>
                  {rows.map((m) => (
                    <TRow key={m.fixture_id}>
                      <TD className="text-xs text-muted-foreground">{utcDate(m.kickoff_at)}</TD>
                      <TD className="text-sm">
                        <Link
                          to="/matches/$fixtureId"
                          params={{ fixtureId: String(m.fixture_id) }}
                          className="hover:text-primary"
                        >
                          {m.team ?? "?"} v {m.opponent ?? "?"}
                        </Link>
                        <div className="text-caption text-subtle-foreground">
                          {m.competition}
                          {m.substitute ? " · came on" : ""}
                        </div>
                      </TD>
                      <TD align="right">
                        <Numeric className="text-xs">{m.minutes ?? "—"}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric className="text-xs">{m.goals ?? "—"}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric className="text-xs">{m.assists ?? "—"}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric className="text-xs">{dec(m.rating, 1) ?? "—"}</Numeric>
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            )}
          </SectionView>
        </Panel>
        <Panel title="Injuries and suspensions" bodyClassName="">
          <SectionView section={d.absences}>
            {(rows) => (
              <ul className="divide-y divide-border/60 text-xs">
                {rows.map((a, i) => (
                  <li key={i} className="px-4 py-2">
                    <div className="font-medium">{a.type ?? "Absence"}</div>
                    <div className="text-muted-foreground">
                      {a.reason ?? "no reason given"}
                      {a.kickoff_at ? ` · ${utcDate(a.kickoff_at)}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionView>
        </Panel>
      </div>
    </div>
  );
}

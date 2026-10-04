/** Players: search, a team's squad, the most productive of the last 30 days, and a profile. */
import { t } from "@/lib/i18n";
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
import { PlayerPhoto, TeamName } from "@/components/football/Logos";
import { dec, utcDate } from "./format";
import { PlayerReferencePanels } from "./ReferenceData";

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
        <TH>{t("catalog.columns.player")}</TH>
        <TH>{t("catalog.players.list.headers.team")}</TH>
        <TH>{t("catalog.columns.position")}</TH>
        <TH align="right">{t("catalog.players.list.headers.age")}</TH>
        <TH align="right" title={t("catalog.players.list.appsTitle")}>
          {t("catalog.columns.apps")}
        </TH>
        <TH align="right">{t("catalog.columns.minutes")}</TH>
        <TH align="right">{t("catalog.columns.goals")}</TH>
        <TH align="right">{t("catalog.columns.assists")}</TH>
        <TH align="right">{t("catalog.columns.rating")}</TH>
        <TH>{t("catalog.players.list.headers.lastPlayed")}</TH>
      </THead>
      <tbody>
        {rows.map((p) => (
          <TRow key={p.id}>
            <TD className="text-sm">
              <div className="flex items-center gap-2">
                <PlayerPhoto src={p.photo_url} name={p.name} size={28} />
                <div className="min-w-0">
                  <Link
                    to="/admin/players/$playerId"
                    params={{ playerId: String(p.id) }}
                    className="hover:text-primary"
                  >
                    {p.name}
                  </Link>
                  <div className="text-caption text-subtle-foreground">
                    {p.nationality ?? t("catalog.players.list.noNationality")}
                  </div>
                </div>
              </div>
            </TD>
            <TD className="text-xs">
              {p.team_id && p.team ? (
                <TeamName
                  name={p.team}
                  logo={p.team_logo}
                  size={16}
                  className="text-muted-foreground"
                />
              ) : (
                <Nullable value={null} reason={t("catalog.players.list.noTeam")} />
              )}
              {p.national_team ? (
                <TeamName
                  name={p.national_team}
                  logo={p.national_team_logo}
                  size={14}
                  className="mt-0.5 text-caption text-subtle-foreground"
                />
              ) : null}
            </TD>
            <TD className="text-xs text-muted-foreground">{p.position ?? "—"}</TD>
            <TD align="right">
              <Numeric muted className="text-xs">
                <Nullable
                  value={age(p.birth_date)}
                  reason={t("catalog.players.list.noBirthDate")}
                />
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
                <Nullable
                  value={dec(p.avg_rating, 2)}
                  reason={t("catalog.players.list.noRating")}
                />
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
        title={t("admin.pages.players.title")}
        description={t("admin.pages.players.description")}
      />
      <div className="max-w-sm">
        <SearchFilter
          label={t("catalog.players.search.label")}
          value={q}
          onChange={setQ}
          placeholder={t("catalog.players.search.placeholder")}
        />
      </div>
      <Panel
        title={term ? t("catalog.players.list.matching", { term }) : t("catalog.players.list.top")}
        subtitle={
          term ? t("catalog.players.list.byAppearances") : t("catalog.players.list.byGoals")
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
          breadcrumb={[{ label: t("admin.nav.players"), to: "/admin/players" }]}
          title={t("catalog.players.detail.notFound")}
        />
        {q.data ? <StatusNotice status={q.data.status} reason={q.data.reason} /> : null}
      </div>
    );
  }
  const p = d.player;
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: t("admin.nav.players"), to: "/admin/players" }, { label: p.name }]}
        title={p.name}
        description={[p.position, p.nationality, p.team].filter(Boolean).join(" · ") || undefined}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title={t("catalog.players.detail.profile.title")}>
          <div className="mb-3 flex items-center gap-3">
            <PlayerPhoto src={p.photo_url} name={p.name} size={72} />
            <div className="min-w-0 space-y-1 text-xs">
              {p.team ? <TeamName name={p.team} logo={p.team_logo} size={18} /> : null}
              {p.national_team ? (
                <TeamName name={p.national_team} logo={p.national_team_logo} size={18} />
              ) : null}
            </div>
          </div>
          <KeyValue
            label={t("catalog.players.detail.profile.fullName")}
            value={[d.firstname, d.lastname].filter(Boolean).join(" ") || "—"}
          />
          <KeyValue
            label={t("catalog.players.detail.profile.born")}
            value={
              p.birth_date
                ? t("catalog.players.detail.profile.bornValue", {
                    date: p.birth_date,
                    age: age(p.birth_date),
                  })
                : "—"
            }
          />
          <KeyValue
            label={t("catalog.players.detail.profile.nationality")}
            value={p.nationality ?? "—"}
          />
          <KeyValue
            label={t("catalog.players.detail.profile.position")}
            value={p.position ?? "—"}
          />
          <KeyValue
            label={t("catalog.players.detail.profile.height")}
            value={d.height_cm ? `${d.height_cm} cm` : "—"}
          />
          <KeyValue
            label={t("catalog.players.detail.profile.weight")}
            value={d.weight_kg ? `${d.weight_kg} kg` : "—"}
          />
          <KeyValue
            label={t("catalog.players.detail.profile.club")}
            value={
              p.team
                ? p.club_source === "squad"
                  ? t("catalog.players.detail.profile.clubFromSquad", { team: p.team })
                  : t("catalog.players.detail.profile.clubFromApps", { team: p.team })
                : "—"
            }
          />
          <KeyValue
            label={t("catalog.players.detail.profile.nationalTeam")}
            value={p.national_team ?? "—"}
          />
          <KeyValue
            label={t("catalog.players.detail.profile.lastAppearance")}
            value={p.last_team ?? "—"}
          />
          <KeyValue
            label={t("catalog.players.detail.profile.providerId")}
            value={p.provider_player_id}
          />
        </Panel>
        <Panel title={t("catalog.players.detail.totals.title")} className="lg:col-span-2">
          <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
            <KeyValue label={t("catalog.players.detail.totals.appearances")} value={p.apps} />
            <KeyValue label={t("catalog.players.detail.totals.minutes")} value={p.minutes ?? "—"} />
            <KeyValue label={t("catalog.players.detail.totals.goals")} value={p.goals ?? "—"} />
            <KeyValue label={t("catalog.players.detail.totals.assists")} value={p.assists ?? "—"} />
            <KeyValue
              label={t("catalog.players.detail.totals.avgRating")}
              value={dec(p.avg_rating, 2) ?? "—"}
            />
            <KeyValue
              label={t("catalog.players.detail.totals.lastPlayed")}
              value={p.last_played ? utcDate(p.last_played) : "—"}
            />
          </div>
        </Panel>
      </div>
      <Panel title={t("catalog.players.detail.seasons.title")} bodyClassName="">
        <SectionView section={d.seasons}>
          {(rows) => (
            <TableShell>
              <THead>
                <TH>{t("catalog.players.detail.seasons.headers.season")}</TH>
                <TH>{t("catalog.players.detail.seasons.headers.competition")}</TH>
                <TH>{t("catalog.players.detail.seasons.headers.team")}</TH>
                <TH align="right">{t("catalog.columns.apps")}</TH>
                <TH align="right">{t("catalog.columns.starts")}</TH>
                <TH align="right">{t("catalog.columns.minutes")}</TH>
                <TH align="right">{t("catalog.columns.goals")}</TH>
                <TH align="right">{t("catalog.columns.assists")}</TH>
                <TH align="right">{t("catalog.columns.yellowCards")}</TH>
                <TH align="right">{t("catalog.columns.redCards")}</TH>
                <TH align="right">{t("catalog.columns.rating")}</TH>
              </THead>
              <tbody>
                {rows.map((s) => (
                  <TRow key={`${s.season}-${s.competition}-${s.team ?? ""}`}>
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
        <Panel
          title={t("catalog.players.detail.matches.title")}
          className="lg:col-span-2"
          bodyClassName=""
        >
          <SectionView section={d.matches}>
            {(rows) => (
              <TableShell>
                <THead>
                  <TH>{t("catalog.players.detail.matches.headers.date")}</TH>
                  <TH>{t("catalog.players.detail.matches.headers.match")}</TH>
                  <TH align="right">{t("catalog.columns.minutes")}</TH>
                  <TH align="right">{t("catalog.columns.goals")}</TH>
                  <TH align="right">{t("catalog.columns.assists")}</TH>
                  <TH align="right">{t("catalog.columns.rating")}</TH>
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
                          {t("catalog.players.detail.matches.versus", {
                            team: m.team ?? "?",
                            opponent: m.opponent ?? "?",
                          })}
                        </Link>
                        <div className="text-caption text-subtle-foreground">
                          {m.competition}
                          {m.substitute ? ` · ${t("catalog.players.detail.matches.cameOn")}` : ""}
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
        <Panel title={t("catalog.players.detail.absences.title")} bodyClassName="">
          <SectionView section={d.absences}>
            {(rows) => (
              <ul className="divide-y divide-border/60 text-xs">
                {rows.map((a, i) => (
                  <li key={i} className="px-4 py-2">
                    <div className="font-medium">
                      {a.type ?? t("catalog.players.detail.absences.absence")}
                    </div>
                    <div className="text-muted-foreground">
                      {a.reason ?? t("catalog.players.detail.absences.noReason")}
                      {a.kickoff_at ? ` · ${utcDate(a.kickoff_at)}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionView>
        </Panel>
      </div>
      <PlayerReferencePanels d={d} />
    </div>
  );
}

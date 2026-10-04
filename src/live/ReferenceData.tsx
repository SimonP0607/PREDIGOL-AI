/**
 * The provider's reference lists, each with where it comes from: a player's transfers, periods out and
 * trophies; a competition's top scorers, assists and cards and its round calendar. "Not read yet" and
 * "the provider lists nothing" are different messages (the API says which).
 */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { CalendarDays, Database } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD } from "@/components/primitives/DataTable";
import { Numeric } from "@/components/primitives/Indicators";
import { SegmentedTabs } from "@/components/system/Filters";
import { SectionView } from "@/components/system/LiveState";
import { PlayerPhoto, TeamName } from "@/components/football/Logos";
import type {
  CompetitionReference,
  LeaderList,
  LeaderListName,
  PlayerDetail,
  Provenance,
  SeasonRound,
} from "@/lib/api/v1/types_center";
import { leaderFigure, ratingCountsUnrated, roundSpan } from "@/product/shared/reference";
import { dec, shortHash, utcDate, utcDateTime } from "./format";

/** "API-Football /transfers · payload 1a2b3c4d5e6f · fetched 4 Oct 2026 18:30 UTC · asked 4 Oct ..." */
export function ProvenanceNote({
  p,
  className,
}: {
  p: Provenance | null | undefined;
  className?: string;
}) {
  if (!p) return null;
  const parts = [p.source];
  if (p.payload_hash)
    parts.push(t("catalog.reference.payload", { hash: shortHash(p.payload_hash) }));
  if (p.observed_at) parts.push(t("catalog.reference.fetched", { at: utcDateTime(p.observed_at) }));
  if (p.checked_at) parts.push(t("catalog.reference.asked", { at: utcDateTime(p.checked_at) }));
  return (
    <p
      className={cn("flex items-start gap-1.5 text-caption text-subtle-foreground", className)}
      data-testid="provenance"
    >
      <Database aria-hidden className="mt-px h-3 w-3 shrink-0" />
      <span>{parts.join(" · ")}</span>
    </p>
  );
}

export function PlayerReferencePanels({ d }: { d: PlayerDetail }) {
  const prov = d.provenance ?? {};
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Panel title={t("catalog.reference.transfers.title")} bodyClassName="">
        {d.transfers ? (
          <SectionView section={d.transfers}>
            {(rows) => (
              <ul className="divide-y divide-border/60 text-xs" data-testid="player-transfers">
                {rows.map((x, i) => (
                  <li key={i} className="px-4 py-2">
                    <div className="font-medium">
                      {x.team_out ?? "?"} → {x.team_in ?? "?"}
                    </div>
                    <div className="text-muted-foreground">
                      {x.transfer_date ? utcDate(x.transfer_date) : "—"}
                      {x.type ? ` · ${x.type}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionView>
        ) : null}
        <ProvenanceNote p={prov["transfers"]} className="px-4 pb-3 pt-2" />
      </Panel>
      <Panel title={t("catalog.reference.sidelined.title")} bodyClassName="">
        {d.sidelined ? (
          <SectionView section={d.sidelined}>
            {(rows) => (
              <ul className="divide-y divide-border/60 text-xs" data-testid="player-sidelined">
                {rows.map((x, i) => (
                  <li key={i} className="px-4 py-2">
                    <div className="font-medium">
                      {x.type ?? t("catalog.reference.sidelined.out")}
                    </div>
                    <div className="text-muted-foreground">
                      {x.start ? utcDate(x.start) : "?"} –{" "}
                      {x.end ? utcDate(x.end) : t("catalog.reference.open")}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionView>
        ) : null}
        <ProvenanceNote p={prov["sidelined"]} className="px-4 pb-3 pt-2" />
      </Panel>
      <Panel title={t("catalog.reference.trophies.title")} bodyClassName="">
        {d.trophies ? (
          <SectionView section={d.trophies}>
            {(rows) => (
              <ul className="divide-y divide-border/60 text-xs" data-testid="player-trophies">
                {rows.map((x, i) => (
                  <li key={i} className="px-4 py-2">
                    <div className="font-medium">
                      {x.league ?? "?"}
                      {x.season ? ` ${x.season}` : ""}
                    </div>
                    <div className="text-muted-foreground">
                      {x.place ?? "—"}
                      {x.country ? ` · ${x.country}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SectionView>
        ) : null}
        <ProvenanceNote p={prov["trophies"]} className="px-4 pb-3 pt-2" />
      </Panel>
    </div>
  );
}

const LISTS: readonly LeaderListName[] = [
  "topscorers",
  "topassists",
  "topyellowcards",
  "topredcards",
];

export function LeadersPanel({ data }: { data: CompetitionReference }) {
  const available = data.leaders.status === "ok" ? data.leaders.data : [];
  const kinds = LISTS.filter((k) => available.some((l) => l.kind === k));
  const [kind, setKind] = useState<LeaderListName>(kinds[0] ?? "topscorers");
  const list = available.find((l) => l.kind === kind) ?? available[0];
  return (
    <Panel
      title={t("catalog.reference.leaders.title")}
      subtitle={t("catalog.reference.leaders.description")}
      bodyClassName=""
    >
      <SectionView section={data.leaders}>
        {() => (
          <div className="space-y-2">
            {kinds.length > 1 ? (
              <div className="px-4 pt-3">
                <SegmentedTabs
                  tabs={kinds}
                  value={kind}
                  onChange={setKind}
                  label={t("catalog.reference.leaders.title")}
                  format={(k) => t(`catalog.reference.leaders.${k}`)}
                />
              </div>
            ) : null}
            {list ? (
              <>
                <TableShell compact>
                  <THead>
                    <TH align="right">#</TH>
                    <TH>{t("catalog.columns.player")}</TH>
                    <TH>{t("catalog.players.list.headers.team")}</TH>
                    <TH align="right">{t("catalog.columns.apps")}</TH>
                    <TH align="right">{t(`catalog.reference.leaders.figure.${list.kind}`)}</TH>
                    <TH align="right" title={t("catalog.reference.leaders.ratingTitle")}>
                      {t("catalog.columns.ratingShort")}
                    </TH>
                  </THead>
                  <tbody data-testid="leaders">
                    {list.rows.map((r) => (
                      <TRow key={`${r.rank}-${r.provider_player_id}`}>
                        <TD align="right">
                          <Numeric className="text-xs">{r.rank}</Numeric>
                        </TD>
                        <TD>
                          <span className="flex items-center gap-2">
                            <PlayerPhoto src={r.photo_url} name={r.name ?? "?"} size={24} />
                            {r.player_id ? (
                              <Link
                                to="/admin/players/$playerId"
                                params={{ playerId: String(r.player_id) }}
                                className="text-sm hover:text-primary"
                              >
                                {r.name ?? "?"}
                              </Link>
                            ) : (
                              <span className="text-sm">{r.name ?? "?"}</span>
                            )}
                          </span>
                        </TD>
                        <TD>
                          {r.team ? (
                            <TeamName
                              name={r.team}
                              logo={r.team_logo}
                              size={16}
                              className="max-w-[9rem]"
                            />
                          ) : (
                            "—"
                          )}
                        </TD>
                        <TD align="right">
                          <Numeric className="text-xs">{r.appearances ?? "—"}</Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric className="text-xs font-semibold">
                            {leaderFigure(list.kind, r) ?? "—"}
                          </Numeric>
                        </TD>
                        <TD align="right">
                          <span
                            title={
                              ratingCountsUnrated(r)
                                ? t("catalog.reference.leaders.unrated", {
                                    count: r.unrated_matches,
                                  })
                                : undefined
                            }
                          >
                            <Numeric className="text-xs">
                              {dec(r.rating, 2) ?? "—"}
                              {ratingCountsUnrated(r) ? "*" : ""}
                            </Numeric>
                          </span>
                        </TD>
                      </TRow>
                    ))}
                  </tbody>
                </TableShell>
                {list.rows.some(ratingCountsUnrated) ? (
                  <p
                    className="px-4 text-[11px] text-muted-foreground"
                    data-testid="leaders-unrated"
                  >
                    {t("catalog.reference.leaders.unratedNote")}
                  </p>
                ) : null}
                <ProvenanceNote p={list.provenance} className="px-4 pb-3" />
              </>
            ) : null}
          </div>
        )}
      </SectionView>
    </Panel>
  );
}

function roundDates(r: SeasonRound): string {
  const span = roundSpan(r);
  if (!span) return "—";
  return span[0] === span[1] ? utcDate(span[0]) : `${utcDate(span[0])} – ${utcDate(span[1])}`;
}

export function RoundsPanel({ data }: { data: CompetitionReference }) {
  return (
    <Panel
      title={t("catalog.reference.rounds.title")}
      subtitle={
        data.current_rounds.length
          ? t("catalog.reference.rounds.current", { rounds: data.current_rounds.join(", ") })
          : t("catalog.reference.rounds.description")
      }
      bodyClassName=""
    >
      <SectionView section={data.rounds}>
        {(rounds) => (
          <>
            <ol
              className="max-h-80 divide-y divide-border/60 overflow-y-auto text-xs"
              data-testid="rounds"
            >
              {rounds.map((r) => (
                <li
                  key={r.ordinal}
                  className={cn(
                    "flex items-center justify-between gap-3 px-4 py-1.5",
                    r.is_current && "bg-primary/5",
                  )}
                  aria-current={r.is_current ? "step" : undefined}
                >
                  <span
                    className={cn(
                      "flex items-center gap-1.5",
                      r.is_current && "font-semibold text-primary",
                    )}
                  >
                    {r.is_current ? <CalendarDays aria-hidden className="h-3.5 w-3.5" /> : null}
                    {r.round}
                  </span>
                  <span className="text-muted-foreground">{roundDates(r)}</span>
                </li>
              ))}
            </ol>
            <ProvenanceNote p={data.rounds_provenance} className="px-4 pb-3 pt-2" />
          </>
        )}
      </SectionView>
    </Panel>
  );
}

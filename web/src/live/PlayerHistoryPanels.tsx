/** A player's history (plan F3): where he has played over time, and what he has done with his senior national team. */
import { Link } from "@tanstack/react-router";
import { Panel } from "@/components/primitives/Panel";
import { TableShell, TD, TH, THead, TRow } from "@/components/primitives/DataTable";
import { SectionView } from "@/components/system/LiveState";
import type { PlayerDetail } from "@/lib/api/v1/types_center";
import { t } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { utcDate } from "./format";
import { capRecord, capRole, capScore, isCurrent } from "./playerHistory";

export function PlayerHistoryPanels({ d }: { d: PlayerDetail }) {
  if (!d.club_history && !d.national_caps) return null;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {d.club_history ? (
        <Panel
          title={t("catalog.players.detail.history.title")}
          subtitle={t("catalog.players.detail.history.subtitle")}
          bodyClassName=""
        >
          <SectionView section={d.club_history}>
            {(rows) => (
              <TableShell>
                <THead>
                  <TH>{t("catalog.players.detail.history.headers.club")}</TH>
                  <TH>{t("catalog.players.detail.history.headers.from")}</TH>
                  <TH>{t("catalog.players.detail.history.headers.to")}</TH>
                  <TH align="right">{t("catalog.players.detail.history.headers.matches")}</TH>
                  <TH>{t("catalog.players.detail.history.headers.lastEvidence")}</TH>
                </THead>
                <tbody data-testid="player-club-history">
                  {rows.map((s) => (
                    <TRow key={`${s.provider_team_id}:${s.valid_from ?? "?"}`}>
                      <TD className="text-sm">
                        {s.team ?? `#${s.provider_team_id}`}
                        <div className="text-caption text-subtle-foreground">
                          {t(`catalog.players.detail.history.source.${s.source}`)}
                          {s.via ? ` · ${s.via}` : ""}
                        </div>
                      </TD>
                      <TD className="text-xs text-muted-foreground">
                        {s.valid_from
                          ? utcDate(s.valid_from)
                          : t("catalog.players.detail.history.unknownStart")}
                      </TD>
                      <TD className="text-xs text-muted-foreground">
                        {isCurrent(s)
                          ? t("catalog.players.detail.history.stillThere")
                          : utcDate(s.valid_to)}
                      </TD>
                      <TD align="right" className="text-xs tabular-nums">
                        {localInt(s.matches)}
                      </TD>
                      <TD className="text-xs text-muted-foreground">{utcDate(s.last_evidence)}</TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            )}
          </SectionView>
        </Panel>
      ) : null}
      {d.national_caps ? (
        <Panel
          title={t("catalog.players.detail.history.caps.title")}
          subtitle={t("catalog.players.detail.history.caps.subtitle")}
          bodyClassName=""
        >
          <SectionView section={d.national_caps}>
            {(rows) => {
              const record = capRecord(rows);
              return (
                <>
                  <div
                    className="px-4 py-2 text-xs text-muted-foreground"
                    data-testid="player-caps-summary"
                  >
                    {t("catalog.players.detail.history.caps.summary", {
                      caps: localInt(record.caps),
                      starts: localInt(record.starts),
                      minutes: localInt(record.minutes),
                      waiting: localInt(record.waiting),
                    })}
                  </div>
                  <TableShell>
                    <THead>
                      <TH>{t("catalog.players.detail.history.caps.headers.date")}</TH>
                      <TH>{t("catalog.players.detail.history.caps.headers.team")}</TH>
                      <TH>{t("catalog.players.detail.history.caps.headers.opponent")}</TH>
                      <TH>{t("catalog.players.detail.history.caps.headers.role")}</TH>
                      <TH align="right">
                        {t("catalog.players.detail.history.caps.headers.minutes")}
                      </TH>
                    </THead>
                    <tbody data-testid="player-national-caps">
                      {rows.map((c) => (
                        <TRow key={c.fixture_id}>
                          <TD className="text-xs text-muted-foreground">{utcDate(c.kickoff_at)}</TD>
                          <TD className="text-sm">{c.team}</TD>
                          <TD className="text-sm">
                            <Link
                              to="/matches/$fixtureId"
                              params={{ fixtureId: String(c.fixture_id) }}
                              className="hover:text-primary"
                            >
                              {c.opponent ?? "?"}
                            </Link>
                            <div className="text-caption text-subtle-foreground">
                              {[c.competition, capScore(c)].filter(Boolean).join(" · ")}
                            </div>
                          </TD>
                          <TD className="text-xs">
                            {t(`catalog.players.detail.history.caps.role.${capRole(c)}`)}
                          </TD>
                          <TD align="right" className="text-xs tabular-nums">
                            {c.minutes === null ? "—" : localInt(c.minutes)}
                          </TD>
                        </TRow>
                      ))}
                    </tbody>
                  </TableShell>
                </>
              );
            }}
          </SectionView>
        </Panel>
      ) : null}
    </div>
  );
}

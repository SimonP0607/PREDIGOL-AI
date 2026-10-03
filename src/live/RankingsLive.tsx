/**
 * Rankings, live: the Elo ratings the models actually read, from the stored
 * rating history. A rating built from fewer than ten matches is marked
 * provisional - it is still mostly the starting value every newcomer gets.
 */
import { t } from "@/lib/i18n";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { SelectFilter } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, SectionView } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import { int } from "@/lib/format";
import { utcDate, utcDateTime } from "./format";

export function RankingsLive() {
  const comps = useLiveQuery(live.competitions);
  const options = (comps.data?.data ?? []).filter((c) => c.fixtures > 0);
  // By id: several competitions share a name ("Premier League", "Super Cup").
  const choices = [
    { value: "all", label: "All competitions" },
    ...[...options]
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((c) => ({
        value: String(c.id),
        label: `${c.name}${c.country ? ` (${c.country})` : ""}`,
      })),
  ];
  const [scope, setScope] = useState("all");
  const selected = options.find((c) => String(c.id) === scope);
  const q = useLiveQuery(live.rankings(selected?.id));
  const d = q.data;
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.rankings.title")}
        description={t("admin.pages.rankings.description")}
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      <div className="max-w-sm">
        <SelectFilter label="Competition" value={scope} options={choices} onChange={setScope} />
      </div>
      <Panel
        title="Elo"
        subtitle={
          d?.data
            ? `${d.data.parameters} · ${d.data.elo_version}, computed ${utcDateTime(d.data.computed_at)}`
            : "World Football Elo"
        }
        bodyClassName=""
      >
        {!d ? (
          <TableSkeleton rows={8} cols={6} />
        ) : (
          <SectionView section={{ status: d.status, data: d.data, reason: d.reason }}>
            {(r) =>
              r ? (
                <TableShell>
                  <THead>
                    <TH align="right">#</TH>
                    <TH>Team</TH>
                    <TH align="right">Rating</TH>
                    <TH align="right">Last 5</TH>
                    <TH align="right">Rated matches</TH>
                    <TH>Last match</TH>
                  </THead>
                  <tbody>
                    {r.rows.map((row) => (
                      <TRow key={row.team_id}>
                        <TD align="right">
                          <Numeric muted>{row.rank}</Numeric>
                        </TD>
                        <TD>
                          <div className="flex items-center gap-2 text-sm">
                            {row.team}
                            {row.provisional ? (
                              <StatusBadge tone="warning">provisional</StatusBadge>
                            ) : null}
                          </div>
                        </TD>
                        <TD align="right">
                          <Numeric>{row.rating.toFixed(0)}</Numeric>
                        </TD>
                        <TD align="right">
                          {row.change_last5 === null ? (
                            <span
                              className="text-subtle-foreground"
                              title="Fewer than five rated matches."
                            >
                              —
                            </span>
                          ) : (
                            <span
                              className={
                                row.change_last5 >= 0
                                  ? "numeric text-positive"
                                  : "numeric text-negative"
                              }
                            >
                              {row.change_last5 >= 0 ? "+" : "−"}
                              {Math.abs(row.change_last5).toFixed(0)}
                            </span>
                          )}
                        </TD>
                        <TD align="right">
                          <Numeric muted>{int(row.matches)}</Numeric>
                        </TD>
                        <TD>
                          <span className="numeric text-xs">{utcDate(row.last_match_at)}</span>
                          <div className="text-caption text-subtle-foreground">
                            {row.last_competition}
                          </div>
                        </TD>
                      </TRow>
                    ))}
                  </tbody>
                </TableShell>
              ) : null
            }
          </SectionView>
        )}
      </Panel>
    </div>
  );
}

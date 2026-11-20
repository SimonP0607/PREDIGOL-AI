/**
 * The tables of a season the provider does not give (lámina I07): the reclasificación, the relegation table by average and the
 * international places, computed by PrediGol from the results and the competition's regulation (BE-075, served by BE-082 behind
 * `FBI_COMPETITION_TABLES`). Each table says whether it is final, provisional or still open, and what the regulation leaves open;
 * a place that depends on a champion not known yet says so instead of being guessed.
 *
 * `children` is where the calculator «¿Qué pasa si…?» (PM-09-03) goes, under the tables, behind its own switch.
 */
import { useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { Info } from "lucide-react";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { Segmented } from "@/components/ui/segmented";
import { TeamName } from "@/components/football/Logos";
import type {
  PlaceState,
  SeasonTable,
  SeasonTables,
  SeasonTableRow,
  SeasonTeam,
  ZoneState,
} from "@/lib/api/v1/types_season_tables";
import { cn } from "@/lib/utils";
import { t } from "./text";

const ZONE_TONE: Record<ZoneState, BadgeTone> = {
  definitivo: "positive",
  provisional: "info",
  condicional: "neutral",
  empate_abierto: "warning",
};

const PLACE_TONE: Record<PlaceState, BadgeTone> = {
  calculado: "positive",
  provisional: "info",
  pendiente: "neutral",
  no_calculado: "neutral",
};

/** A view of the block: one table, or the places a table gives. */
export interface TableView {
  key: string;
  label: string;
  table: SeasonTable;
  places: boolean;
}

export function tableViews(data: SeasonTables): TableView[] {
  const order = (x: SeasonTable): number =>
    x.key === "reclasificacion" ? 0 : x.kind === "average" ? 1 : 2;
  const main = data.tables.filter((x) => x.key === "reclasificacion" || x.kind === "average");
  const views: TableView[] = [...main]
    .sort((a, b) => order(a) - order(b))
    .map((x) => ({ key: x.key, label: x.name, table: x, places: false }));
  for (const x of main)
    if (x.places.length > 0)
      views.push({
        key: `${x.key}:places`,
        label: t("competitions.tables.places"),
        table: x,
        places: true,
      });
  return views;
}

/** «Libertadores», «Descenso» or nothing: the zone a row is in today. */
export function zoneOf(
  table: SeasonTable,
  row: SeasonTableRow,
): SeasonTable["zones"][number] | null {
  return table.zones.find((z) => z.positions.includes(row.position)) ?? null;
}

export function TeamCell({ team }: { team: SeasonTeam }) {
  const name = <TeamName name={team.name} logo={team.logo_url} size={18} wrap />;
  return team.team_id !== null ? (
    <Link
      to="/teams/$teamId"
      params={{ teamId: String(team.team_id) }}
      className="hover:text-primary hover:underline"
    >
      {name}
    </Link>
  ) : (
    name
  );
}

function ZoneTag({ table, row }: { table: SeasonTable; row: SeasonTableRow }) {
  const zone = zoneOf(table, row);
  if (!zone)
    return (
      <span className="text-caption text-subtle-foreground">{t("competitions.tables.noZone")}</span>
    );
  return (
    <span title={zone.note ?? undefined}>
      <StatusBadge tone={ZONE_TONE[zone.state]} dot={false}>
        {t(`competitions.tables.zone.${zone.kind === "relegation" ? "relegation" : "continental"}`)}
        <span className="sr-only"> · {t(`competitions.tables.zoneState.${zone.state}`)}</span>
      </StatusBadge>
    </span>
  );
}

function Rows({
  table,
  highlight,
}: {
  table: SeasonTable;
  highlight?: ReadonlySet<number> | undefined;
}) {
  const average = table.kind === "average";
  return (
    <table className="w-full table-fixed text-sm" data-testid={`season-table-${table.key}`}>
      <caption className="sr-only">{table.name}</caption>
      <thead>
        <tr className="text-left text-caption text-subtle-foreground">
          <th scope="col" className="w-8 pb-1.5 font-medium">
            #
          </th>
          <th scope="col" className="pb-1.5 font-medium">
            {t("competitions.tables.team")}
          </th>
          <th scope="col" className="w-10 pb-1.5 text-right font-medium">
            <abbr title={t("competitions.tables.playedLong")} className="no-underline">
              {t("competitions.tables.played")}
            </abbr>
          </th>
          <th scope="col" className="w-12 pb-1.5 text-right font-medium">
            <abbr title={t("competitions.tables.pointsLong")} className="no-underline">
              {t("competitions.tables.points")}
            </abbr>
          </th>
          {average ? (
            <th scope="col" className="w-16 pb-1.5 text-right font-medium">
              <abbr title={t("competitions.tables.averageLong")} className="no-underline">
                {t("competitions.tables.average")}
              </abbr>
            </th>
          ) : null}
          <th scope="col" className="w-28 pb-1.5 pl-2 font-medium">
            {t("competitions.tables.zoneToday")}
          </th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border/60">
        {table.rows.map((r) => (
          <tr
            key={r.team.provider_team_id}
            className={cn(highlight?.has(r.team.provider_team_id) && "bg-primary/8 font-semibold")}
          >
            <td className="numeric py-2 text-muted-foreground">{r.position}</td>
            <td className="py-2 pr-2">
              <TeamCell team={r.team} />
              {r.shared_with.length > 0 ? (
                <span className="block text-caption text-warning">
                  {t("competitions.tables.tied")}
                </span>
              ) : null}
            </td>
            <td className="numeric py-2 text-right text-muted-foreground">{r.played}</td>
            <td className="numeric py-2 text-right font-semibold">{r.points}</td>
            {average ? <td className="numeric py-2 text-right">{r.average_3_cut ?? "—"}</td> : null}
            <td className="py-2 pl-2">
              <ZoneTag table={table} row={r} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Places({ table }: { table: SeasonTable }) {
  const byCompetition = new Map<string, SeasonTable["places"]>();
  for (const p of table.places)
    byCompetition.set(p.competition, [...(byCompetition.get(p.competition) ?? []), p]);
  return (
    <div className="space-y-4" data-testid="season-places">
      {[...byCompetition.entries()].map(([competition, places]) => (
        <section key={competition} aria-label={competition} className="space-y-1.5">
          <h3 className="text-sm font-semibold">
            {competition}
            {places[0]?.article ? (
              <span className="ml-1 text-caption font-normal text-subtle-foreground">
                ({places[0].article})
              </span>
            ) : null}
          </h3>
          <ul className="divide-y divide-border/60">
            {places.map((p) => (
              <li
                key={p.slot}
                className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 py-1.5"
              >
                <span className="w-24 shrink-0 text-caption text-muted-foreground">{p.slot}</span>
                <span className="min-w-0 flex-1 text-sm">
                  {p.team ? (
                    <TeamCell team={p.team} />
                  ) : (
                    <span className="text-muted-foreground">
                      {p.source === "table_rank"
                        ? t("competitions.tables.placeByRank")
                        : t(`competitions.tables.placeOf.${p.source}`, { of: p.of ?? "" })}
                    </span>
                  )}
                </span>
                <StatusBadge tone={PLACE_TONE[p.state]} dot={false}>
                  {t(`competitions.tables.placeState.${p.state}`)}
                </StatusBadge>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Notes({ data, table }: { data: SeasonTables; table: SeasonTable }) {
  const notes: string[] = [];
  notes.push(
    table.complete
      ? t("competitions.tables.complete")
      : t("competitions.tables.pending", { n: table.pending_matches }),
  );
  if (table.kind === "average") notes.push(t("competitions.tables.averageNote"));
  if (table.unverified_decisions > 0)
    notes.push(t("competitions.tables.unverified", { n: table.unverified_decisions }));
  notes.push(t("competitions.tables.source", { version: data.rules_version }));
  return (
    <ul className="space-y-1 text-caption text-muted-foreground" data-testid="season-table-notes">
      {notes.map((n) => (
        <li key={n} className="flex items-start gap-1.5">
          <Info aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{n}</span>
        </li>
      ))}
    </ul>
  );
}

export function SeasonTablesBlock({
  data,
  children,
  view: controlled,
  onView,
  highlight,
}: {
  data: SeasonTables;
  children?: ReactNode;
  /** The view chosen, when the parent keeps it (the calculator redraws the same table). */
  view?: string | undefined;
  onView?: ((key: string) => void) | undefined;
  highlight?: ReadonlySet<number> | undefined;
}) {
  const views = tableViews(data);
  const [own, setOwn] = useState(views[0]?.key ?? "");
  const key = controlled ?? own;
  const chosen = views.find((v) => v.key === key) ?? views[0];
  if (!chosen) return null;
  const choose = (k: string) => (onView ? onView(k) : setOwn(k));
  return (
    <section
      aria-labelledby="season-tables-title"
      className="space-y-3"
      data-testid="season-tables"
    >
      <h2 id="season-tables-title" className="text-title">
        {t("competitions.tables.title")}
      </h2>
      {views.length > 1 ? (
        <div className="-mx-1 overflow-x-auto px-1 [scrollbar-width:none]">
          <Segmented<string>
            full={false}
            className="min-w-max"
            value={chosen.key}
            onChange={choose}
            label={t("competitions.tables.choose")}
            testId="season-tables-views"
            options={views.map((v) => ({ value: v.key, label: v.label }))}
          />
        </div>
      ) : null}
      {chosen.places ? (
        <Places table={chosen.table} />
      ) : (
        <Rows table={chosen.table} highlight={highlight} />
      )}
      <Notes data={data} table={chosen.table} />
      {children}
    </section>
  );
}

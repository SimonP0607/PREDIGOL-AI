/**
 * «¿Qué pasa si…?» (plan PM, PM-09-03; UX-181; lámina I07, M05): under the season tables, the reader chooses the result of the
 * matches still to be played that the table counts and sees the table of their scenario, who enters and who leaves each zone, and
 * which clubs are left level (the regulation decides those). Computed in the browser by `whatIf.ts`; nothing is estimated and no
 * figure is a forecast: the block is labelled as the reader's own calculation, and every number in it is points or a quotient.
 *
 * Shown only while `FBI_WHAT_IF` is on (the owner's signature of publication, DM-14) and the season tables are served.
 */
import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Calculator, Check, RotateCcw } from "lucide-react";
import type { SeasonTable, SeasonTables, SeasonTeam } from "@/lib/api/v1/types_season_tables";
import { formatKickoff } from "@/lib/time";
import { cn } from "@/lib/utils";
import { TeamCell } from "./SeasonTables";
import { applyChoices, zoneShifts, type Choice, type WhatIfLine } from "./scenario";
import { t } from "./text";

const CHOICES: readonly Choice[] = ["home", "draw", "away"];
/** The matches offered at once: the next rounds (a calendar of 40 rows would not be read). */
const MAX_MATCHES = 12;

function ChoiceRow({
  home,
  away,
  value,
  onChange,
  label,
}: {
  home: string;
  away: string;
  value: Choice | undefined;
  onChange: (c: Choice | undefined) => void;
  label: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="grid grid-cols-3 gap-1 rounded-full bg-elevated p-1"
    >
      {CHOICES.map((c) => {
        const on = value === c;
        return (
          <button
            key={c}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? undefined : c)}
            className={cn(
              "inline-flex min-h-11 items-center justify-center gap-1 rounded-full px-2 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              on ? "bg-primary-soft text-primary" : "text-foreground-soft hover:bg-card",
            )}
            title={c === "home" ? home : c === "away" ? away : undefined}
          >
            {on ? <Check aria-hidden className="h-4 w-4" /> : null}
            {t(`competitions.whatIf.choice.${c}`)}
          </button>
        );
      })}
    </div>
  );
}

function Movement({ line }: { line: WhatIfLine }) {
  const d = line.before - line.position;
  if (d === 0) return <span className="sr-only">{t("competitions.whatIf.same")}</span>;
  const up = d > 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-caption",
        up ? "text-positive" : "text-negative",
      )}
    >
      {up ? (
        <ArrowUp aria-hidden className="h-3.5 w-3.5" />
      ) : (
        <ArrowDown aria-hidden className="h-3.5 w-3.5" />
      )}
      <span>
        {t(up ? "competitions.whatIf.up" : "competitions.whatIf.down", { n: Math.abs(d) })}
      </span>
    </span>
  );
}

function quotient(line: WhatIfLine): string {
  if (line.played === 0) return "—";
  const cut = Math.trunc((line.points / line.played) * 1000) / 1000;
  return cut.toFixed(3);
}

export function WhatIf({ data, table }: { data: SeasonTables; table: SeasonTable }) {
  const matches = useMemo(
    () => data.remaining.filter((m) => m.tables.includes(table.key)).slice(0, MAX_MATCHES),
    [data.remaining, table.key],
  );
  const [choices, setChoices] = useState<Record<string, Choice | undefined>>({});
  const teams = useMemo(() => {
    const out = new Map<number, SeasonTeam>();
    for (const r of table.rows) out.set(r.team.provider_team_id, r.team);
    return out;
  }, [table.rows]);
  if (matches.length === 0) return null;
  const rows = table.rows.map((r) => ({
    team: r.team.provider_team_id,
    played: r.played,
    points: r.points,
    counts_now: r.window.length === 0 || r.window.includes(data.season),
  }));
  const lines = applyChoices(
    table.kind,
    rows,
    matches.map((m) => [m.home.provider_team_id, m.away.provider_team_id] as const),
    choices,
    data.points,
  );
  const chosen = Object.values(choices).filter(Boolean).length;
  const shifts = zoneShifts(
    table.zones,
    rows.map((r) => r.team),
    lines.map((l) => l.team),
  );
  const name = (id: number) => teams.get(id)?.name ?? `#${id}`;
  const tied = lines.filter((l) => l.tied);
  return (
    <section
      aria-labelledby="what-if-title"
      className="space-y-3 border-t border-border pt-4"
      data-testid="what-if"
    >
      <h3 id="what-if-title" className="flex items-center gap-2 text-title">
        <Calculator aria-hidden className="h-5 w-5 text-subtle-foreground" />
        {t("competitions.whatIf.title")}
      </h3>
      <p className="text-small text-muted-foreground">{t("competitions.whatIf.intro")}</p>
      <ul className="space-y-3">
        {matches.map((m, i) => {
          const label = `${m.home.name} – ${m.away.name}`;
          return (
            <li key={m.provider_fixture_id} className="space-y-1.5">
              <p className="text-sm font-semibold">
                {label}
                {m.kickoff_at ? (
                  <span className="ml-2 text-caption font-normal text-muted-foreground">
                    {formatKickoff(m.kickoff_at)}
                  </span>
                ) : null}
              </p>
              <ChoiceRow
                home={m.home.name}
                away={m.away.name}
                label={label}
                value={choices[String(i)]}
                onChange={(c) => setChoices((s) => ({ ...s, [String(i)]: c }))}
              />
            </li>
          );
        })}
      </ul>
      <p className="text-caption text-muted-foreground">{t("competitions.whatIf.unchosen")}</p>
      {chosen > 0 ? (
        <div
          className="space-y-3 rounded-field border border-primary/30 bg-primary/5 p-3"
          aria-live="polite"
        >
          <p className="text-overline text-primary">{t("competitions.whatIf.yourScenario")}</p>
          {shifts.length > 0 ? (
            <ul className="space-y-1 text-small" data-testid="what-if-shifts">
              {shifts.map((s) => {
                const zone = table.zones[s.zone];
                const what = t(
                  `competitions.tables.zone.${zone?.kind === "relegation" ? "relegation" : "continental"}`,
                );
                return (
                  <li key={s.zone}>
                    {s.entered.length > 0
                      ? t("competitions.whatIf.enters", {
                          teams: s.entered.map(name).join(", "),
                          zone: what,
                        })
                      : null}{" "}
                    {s.left.length > 0
                      ? t("competitions.whatIf.leaves", {
                          teams: s.left.map(name).join(", "),
                          zone: what,
                        })
                      : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-small">{t("competitions.whatIf.noShift")}</p>
          )}
          {tied.length > 0 ? (
            <p className="text-small text-warning" data-testid="what-if-tied">
              {t("competitions.whatIf.tied", { teams: tied.map((l) => name(l.team)).join(", ") })}
            </p>
          ) : null}
          <table className="w-full table-fixed text-sm" data-testid="what-if-table">
            <caption className="sr-only">{t("competitions.whatIf.yourScenario")}</caption>
            <thead>
              <tr className="text-left text-caption text-subtle-foreground">
                <th scope="col" className="w-8 pb-1 font-medium">
                  #
                </th>
                <th scope="col" className="pb-1 font-medium">
                  {t("competitions.tables.team")}
                </th>
                <th scope="col" className="w-10 pb-1 text-right font-medium">
                  {t("competitions.tables.played")}
                </th>
                <th scope="col" className="w-12 pb-1 text-right font-medium">
                  {t("competitions.tables.points")}
                </th>
                {table.kind === "average" ? (
                  <th scope="col" className="w-16 pb-1 text-right font-medium">
                    {t("competitions.tables.average")}
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {lines.map((l) => {
                const team = teams.get(l.team);
                return (
                  <tr key={l.team} className={cn(l.before !== l.position && "font-semibold")}>
                    <td className="numeric py-1.5 text-muted-foreground">{l.position}</td>
                    <td className="py-1.5 pr-2">
                      {team ? <TeamCell team={team} /> : `#${l.team}`} <Movement line={l} />
                    </td>
                    <td className="numeric py-1.5 text-right text-muted-foreground">{l.played}</td>
                    <td className="numeric py-1.5 text-right">{l.points}</td>
                    {table.kind === "average" ? (
                      <td className="numeric py-1.5 text-right">{quotient(l)}</td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
          <button
            type="button"
            onClick={() => setChoices({})}
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full border border-border bg-card text-sm font-semibold hover:border-border-strong"
          >
            <RotateCcw aria-hidden className="h-4 w-4" />
            {t("competitions.whatIf.clear")}
          </button>
        </div>
      ) : null}
      <p className="text-caption text-muted-foreground" data-testid="what-if-disclaimer">
        {t("competitions.whatIf.disclaimer")}
      </p>
    </section>
  );
}

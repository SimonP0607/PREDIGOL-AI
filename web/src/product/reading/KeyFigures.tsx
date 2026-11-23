/**
 * AP-P07 (a): the Análisis opens with its key figures - for each side the position, the points to its zone, the form in
 * coloured chips, the xG for and against and the days of rest - and «Cómo quedaría la tabla» (if one side wins, if they
 * draw, if the other wins). Everything is read from the facts the reading already carries (`keyFigures`): nothing is
 * calculated or written here, and a figure the reading lacks leaves its row out.
 */
import { useId, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { hasKey, t } from "@/lib/i18n";
import { localFixed } from "@/lib/i18n/format";
import {
  keyFigures,
  type FormLetter,
  type KeyFigures as Figures,
  type SideFigures,
  type TableScenario,
} from "./figuresModel";
import type { MatchReading } from "@/lib/api/v1/types_reading";

const CHIP: Record<FormLetter, string> = {
  W: "border-positive/40 bg-positive-soft text-positive",
  D: "border-border bg-elevated text-muted-foreground",
  L: "border-negative/40 bg-negative-soft text-negative",
};

function FormChips({ letters }: { letters: FormLetter[] }) {
  return (
    <span className="inline-flex flex-wrap justify-center gap-1">
      {letters.map((l, i) => (
        <span
          key={i}
          className={cn(
            "inline-flex h-6 min-w-6 items-center justify-center rounded-md border px-1 text-caption font-semibold",
            CHIP[l],
          )}
        >
          {t(`match.facts.formLetters.${l}`)}
        </span>
      ))}
    </span>
  );
}

function zoneName(zone: string): string {
  const key = `match.facts.zone.${zone}`;
  return hasKey(key) ? t(key) : zone;
}

function days(d: number): string {
  return t("match.keyFigures.days", { count: d, days: localFixed(d, d % 1 === 0 ? 0 : 1) });
}

interface Row {
  key: string;
  label: string;
  home: ReactNode;
  away: ReactNode;
}

function rows(h: SideFigures, a: SideFigures): Row[] {
  const out: Row[] = [];
  const dash = t("match.keyFigures.none");
  const add = (key: string, label: string, home: ReactNode | null, away: ReactNode | null) => {
    if (home === null && away === null) return;
    out.push({ key, label, home: home ?? dash, away: away ?? dash });
  };
  const rank = (s: SideFigures) =>
    s.rank === null ? null : t("match.keyFigures.rankValue", { rank: s.rank });
  add("rank", t("match.keyFigures.rank"), rank(h), rank(a));
  const gap = (s: SideFigures) =>
    s.gap
      ? t(s.gap.direction === "up" ? "match.keyFigures.gapUp" : "match.keyFigures.gapDown", {
          count: s.gap.points,
          zone: zoneName(s.gap.zone),
        })
      : null;
  add("gap", t("match.keyFigures.gap"), gap(h), gap(a));
  const form = (s: SideFigures) =>
    s.form ? (
      <span className="flex flex-col items-center gap-0.5">
        <FormChips letters={s.form.letters} />
        <span className="text-micro font-normal text-subtle-foreground">
          {t("match.keyFigures.formLast", { count: s.form.matches })}
        </span>
      </span>
    ) : null;
  add("form", t("match.keyFigures.form"), form(h), form(a));
  const xg = (s: SideFigures) =>
    s.xg ? `${localFixed(s.xg.for, 2)} / ${localFixed(s.xg.against, 2)}` : null;
  add("xg", t("match.keyFigures.xg"), xg(h), xg(a));
  const rest = (s: SideFigures) =>
    s.rest
      ? s.rest.atMost
        ? t("match.keyFigures.restAtMost", { days: days(s.rest.days) })
        : days(s.rest.days)
      : null;
  add("rest", t("match.keyFigures.rest"), rest(h), rest(a));
  return out;
}

function Names({ f }: { f: Figures }) {
  return (
    <div className="grid grid-cols-[1fr_minmax(0,1.1fr)_1fr] items-end gap-x-2 pb-1.5 text-xs font-semibold">
      <span className="min-w-0 break-words">{f.home.team}</span>
      <span aria-hidden />
      <span className="min-w-0 break-words text-right">{f.away.team}</span>
    </div>
  );
}

function scenarioLabel(s: TableScenario, f: Figures): string {
  if (s.result === "draw") return t("match.keyFigures.ifDraw");
  return t(s.result === "home_win" ? "match.keyFigures.ifHomeWin" : "match.keyFigures.ifAwayWin", {
    team: s.result === "home_win" ? f.home.team : f.away.team,
  });
}

function placesText(p: { best: number; worst: number }): string {
  return p.best === p.worst
    ? t("match.facts.places.one", { best: p.best })
    : t("match.facts.places.range", { best: p.best, worst: p.worst });
}

function pointsPlaces(points: number, p: { best: number; worst: number } | null): string {
  return p ? t("match.keyFigures.pointsPlaces", { points, places: placesText(p) }) : `${points}`;
}

export function KeyFiguresView({
  reading,
  teams,
}: {
  reading: MatchReading;
  teams?: { home: string; away: string } | undefined;
}) {
  const figures = keyFigures(reading, teams);
  const titleId = useId();
  const tableId = useId();
  if (!figures) return null;
  const list = rows(figures.home, figures.away);
  return (
    <div className="space-y-3" data-testid="key-figures">
      {list.length ? (
        <section aria-labelledby={titleId} className="space-y-1.5">
          <h3
            id={titleId}
            className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground"
          >
            {t("match.keyFigures.title")}
          </h3>
          <div className="rounded-lg border border-border/70 bg-elevated/40 px-3 py-2">
            <Names f={figures} />
            <dl>
              {list.map((r) => (
                <div
                  key={r.key}
                  data-testid={`key-figure-${r.key}`}
                  className="grid min-h-11 grid-cols-[1fr_minmax(0,1.1fr)_1fr] items-center gap-x-2 border-t border-border/60 py-1.5"
                >
                  <dd className="numeric min-w-0 break-words text-sm font-semibold">{r.home}</dd>
                  <dt className="min-w-0 break-words text-center text-caption text-subtle-foreground">
                    {r.label}
                  </dt>
                  <dd className="numeric min-w-0 break-words text-right text-sm font-semibold">
                    <span className="inline-block text-right">{r.away}</span>
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </section>
      ) : null}
      {figures.table.length ? (
        <section aria-labelledby={tableId} className="space-y-1.5" data-testid="key-figures-table">
          <h3
            id={tableId}
            className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground"
          >
            {t("match.keyFigures.tableTitle")}
          </h3>
          <div className="overflow-x-auto rounded-lg border border-border/70 bg-elevated/40">
            <table className="w-full min-w-[20rem] text-left text-sm">
              <thead>
                <tr className="text-caption text-subtle-foreground">
                  <th scope="col" className="px-3 py-1.5 font-medium">
                    <span className="sr-only">{t("match.keyFigures.tableTitle")}</span>
                  </th>
                  <th scope="col" className="px-2 py-1.5 font-medium">
                    {figures.home.team}
                  </th>
                  <th scope="col" className="px-3 py-1.5 font-medium">
                    {figures.away.team}
                  </th>
                </tr>
              </thead>
              <tbody>
                {figures.table.map((s) => (
                  <tr key={s.result} data-result={s.result} className="border-t border-border/60">
                    <th scope="row" className="min-h-11 px-3 py-2 text-sm font-semibold">
                      {scenarioLabel(s, figures)}
                    </th>
                    <td className="numeric px-2 py-2">
                      {pointsPlaces(s.homePoints, s.homePlaces)}
                    </td>
                    <td className="numeric px-3 py-2">
                      {pointsPlaces(s.awayPoints, s.awayPlaces)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      <p className="text-caption text-subtle-foreground">{t("match.keyFigures.note")}</p>
    </div>
  );
}

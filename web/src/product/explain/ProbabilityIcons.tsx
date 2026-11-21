/**
 * «Probabilidad en iconos» and «Mito o dato» (plan PM, PM-10-07, OP-45; lámina I09 «M08»; UX-182): the result forecast of the
 * «Pronóstico PrediGol» block counted in 100 icons, with the sentence «dicho al revés», the warning that it is not a certainty and a
 * few short myths and facts about probability. It explains the figure the bars already show and computes none (`iconArray.ts`);
 * nothing here is written by a model. Shown only behind `FBI_PROB_ICONS` (off by default) and only for a calibrated and authorised
 * result forecast (`iconsAllowed`); the bars stay the default view.
 *
 * Shapes as well as colours (circle, square, triangle), so that the three results are told apart without colour; the grid is one
 * image with its sentence for a screen reader, and the legend below says the same in text.
 */
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { ICONS_PER_ROW, ICON_SIDES, iconCells, type IconCounts, type IconSide } from "./iconArray";
import { t } from "./probIconsText";

export type ForecastViewMode = "bars" | "icons";

const SIDE_CLASS: Record<IconSide, string> = {
  home: "text-primary",
  draw: "text-muted-foreground",
  away: "text-foreground",
};

/** One icon centred in a 10 × 10 cell of the grid's 100 × 100 box. */
function Shape({ side, x, y }: { side: IconSide; x: number; y: number }) {
  const cx = x * 10 + 5;
  const cy = y * 10 + 5;
  if (side === "home") return <circle cx={cx} cy={cy} r={3.6} fill="currentColor" />;
  if (side === "draw") {
    return (
      <rect
        x={cx - 3}
        y={cy - 3}
        width={6}
        height={6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.2}
      />
    );
  }
  return (
    <polygon
      points={`${cx},${cy - 3.6} ${cx + 3.8},${cy + 3.2} ${cx - 3.8},${cy + 3.2}`}
      fill="currentColor"
    />
  );
}

/** A small icon of one side, for the legend. */
function LegendShape({ side }: { side: IconSide }) {
  return (
    <svg aria-hidden viewBox="0 0 10 10" className={cn("h-5 w-5 shrink-0", SIDE_CLASS[side])}>
      <Shape side={side} x={0} y={0} />
    </svg>
  );
}

/** «Barras | Iconos»: two buttons, the pressed one is the view shown. */
export function ForecastViewToggle({
  mode,
  onChange,
}: {
  mode: ForecastViewMode;
  onChange: (mode: ForecastViewMode) => void;
}) {
  const options: ForecastViewMode[] = ["bars", "icons"];
  return (
    <div
      role="group"
      aria-label={t("probicons.view.label")}
      data-testid="forecast-view-toggle"
      className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-elevated/40 p-1"
    >
      {options.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={mode === option}
          data-testid={`forecast-view-${option}`}
          onClick={() => onChange(option)}
          className={cn(
            "tap-y relative min-h-9 rounded-md px-3 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            mode === option
              ? "bg-primary/15 text-foreground ring-1 ring-primary/50"
              : "text-muted-foreground hover:bg-elevated",
          )}
        >
          {t(`probicons.view.${option}`)}
        </button>
      ))}
    </div>
  );
}

const MYTHS: readonly { id: string; verdict: "myth" | "fact" }[] = [
  { id: "streak", verdict: "myth" },
  { id: "likely", verdict: "myth" },
  { id: "judge", verdict: "fact" },
  { id: "calibrated", verdict: "myth" },
];

/** «Mito o dato»: four short statements about probability, folded away; fixed words, no figure. */
export function MythOrFact() {
  return (
    <details
      data-testid="myth-or-fact"
      className="rounded-lg border border-border/70 bg-card/60 px-3 py-2"
    >
      <summary className="tap-y relative cursor-pointer text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {t("probicons.myth.title")}
      </summary>
      <ul className="mt-2 space-y-2.5">
        {MYTHS.map((m) => (
          <li key={m.id} data-testid="myth-item" data-myth={m.id} data-verdict={m.verdict}>
            <p className="text-sm font-medium">{t(`probicons.myth.${m.id}.claim`)}</p>
            <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
              <span
                className={cn(
                  "mr-1.5 inline-flex rounded-full border px-2 py-0.5 text-micro font-semibold",
                  m.verdict === "fact"
                    ? "border-positive/40 bg-positive-soft text-positive"
                    : "border-border-strong bg-elevated text-foreground",
                )}
              >
                {t(`probicons.myth.${m.verdict}`)}
              </span>
              {t(`probicons.myth.${m.id}.why`)}
            </p>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The 100 icons, their legend, the sentence «dicho al revés» and the warning; `counts` from `iconCounts`. */
export function ProbabilityIcons({
  counts,
  home,
  away,
  figure,
}: {
  counts: IconCounts;
  home: string;
  away: string;
  /** The home side's figure as the bars show it, with its interval: «56 %, entre 48 % y 63 %». */
  figure: string;
}) {
  const cells = iconCells(counts);
  const team: Record<IconSide, string> = { home, draw: "", away };
  return (
    <div
      data-testid="prob-icons"
      data-home={counts.home}
      data-draw={counts.draw}
      data-away={counts.away}
      data-adjusted={counts.adjusted ? "true" : "false"}
      className="space-y-3"
    >
      <p className="font-display text-sm font-semibold">{t("probicons.lead")}</p>
      <svg
        role="img"
        aria-label={t("probicons.grid", {
          home: counts.home,
          draw: counts.draw,
          away: counts.away,
          homeTeam: home,
          awayTeam: away,
        })}
        viewBox="0 0 100 100"
        data-testid="prob-icons-grid"
        className="mx-auto block w-full max-w-[18rem]"
      >
        {cells.map((side, i) => (
          <g key={i} className={SIDE_CLASS[side]} data-side={side}>
            <Shape side={side} x={i % ICONS_PER_ROW} y={Math.floor(i / ICONS_PER_ROW)} />
          </g>
        ))}
      </svg>
      <ul className="space-y-1.5" data-testid="prob-icons-legend">
        {ICON_SIDES.map((side) => (
          <li key={side} data-side={side} className="flex items-center gap-3">
            <LegendShape side={side} />
            <span className="numeric w-9 shrink-0 text-xl font-bold leading-none">
              {counts[side]}
            </span>
            <span className="min-w-0 break-words text-sm text-muted-foreground">
              {t(`probicons.legend.${side}`, { team: team[side] })}
            </span>
          </li>
        ))}
      </ul>
      <p className="border-t border-border/70 pt-2 text-sm" data-testid="prob-icons-reverse">
        {t("probicons.reverse", { team: home, n: 100 - counts.home })}
      </p>
      <div className="flex gap-2 rounded-lg border border-border/70 px-3 py-2 text-sm leading-relaxed">
        <Info aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <p>
          <strong className="font-semibold">{t("probicons.notCertainTitle")}</strong>{" "}
          <span className="text-muted-foreground">{t("probicons.notCertain")}</span>
        </p>
      </div>
      {counts.adjusted ? (
        <p
          className="text-caption leading-snug text-subtle-foreground"
          data-testid="prob-icons-adjusted"
        >
          {t("probicons.adjusted")}
        </p>
      ) : null}
      <p className="text-caption leading-snug text-subtle-foreground">
        {t("probicons.same", { figure })}
      </p>
      <MythOrFact />
    </div>
  );
}

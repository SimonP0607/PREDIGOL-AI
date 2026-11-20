/**
 * Who was ahead, minute by minute, over the 90 minutes: the bar of «Cómo fue el marcador» (Postpartido, plan F7) and of «Estado del
 * marcador» in Estadísticas (plan PM, PM-10-02, lámina I01 «M04»; FE-006). One drawing for both: the segments in the order they
 * happened (or the three totals when the goals do not give the count), the goals as dots and who led for how long underneath.
 */
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import type { Sides } from "./intelligence";
import { storyLegend, trackPercent, type LeadState, type StoryDrawing } from "./knowledge";

const LEAD_TONE: Record<LeadState, string> = {
  home: "bg-primary",
  level: "bg-muted-foreground/25",
  away: "bg-info",
};

export function StoryBar({ drawing, sides }: { drawing: StoryDrawing; sides: Sides }) {
  const legend = storyLegend(drawing.minutes, sides);
  const label = t("match.knowledge.story.aria", {
    summary: legend.map((l) => `${l.text} ${l.span}`).join(", "),
  });
  return (
    <div className="space-y-1.5">
      <div
        role="img"
        aria-label={label}
        data-testid="knowledge-bar"
        data-kind={drawing.kind}
        className="relative h-3 overflow-hidden rounded-full bg-muted/70"
      >
        {drawing.segments.map((s) => (
          <span
            key={`${s.from}-${s.state}`}
            data-state={s.state}
            className={cn("absolute inset-y-0", LEAD_TONE[s.state])}
            style={{
              left: `${trackPercent(s.from)}%`,
              width: `${Math.round((trackPercent(s.to) - trackPercent(s.from)) * 100) / 100}%`,
            }}
          />
        ))}
      </div>
      {drawing.kind === "timeline" ? (
        <div aria-hidden className="relative h-2.5">
          {drawing.ticks.map((g, i) => (
            <span
              key={`${g.minute}-${g.side}-${i}`}
              data-testid="knowledge-goal"
              data-side={g.side}
              className={cn(
                "absolute top-0 h-2.5 w-2.5 -translate-x-1/2 rounded-full ring-2 ring-card",
                g.side === "home" ? "bg-primary" : "bg-info",
              )}
              style={{ left: `${trackPercent(g.minute)}%` }}
            />
          ))}
        </div>
      ) : null}
      <div
        aria-hidden
        className="numeric flex justify-between text-micro leading-none text-subtle-foreground"
      >
        <span>0&apos;</span>
        <span>45&apos;</span>
        <span>90&apos;</span>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-xs">
        {legend.map((l) => (
          <li key={l.state} data-state={l.state} className="flex min-w-0 items-center gap-1.5">
            <span
              aria-hidden
              className={cn("inline-block h-2 w-2 shrink-0 rounded-full", LEAD_TONE[l.state])}
            />
            <span className="min-w-0 break-words">{l.text}</span>
            <span className="numeric shrink-0 whitespace-nowrap text-muted-foreground">
              {l.span}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

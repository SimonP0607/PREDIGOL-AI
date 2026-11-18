/**
 * Goals by interval in mirror (plan EA, catalogue n.º 2; V2·6): goals for above the axis, against below, the league's mean of each
 * bin marked in grey, 45+ and 90+ their own bins. Each bin opens the list of its goals (match and minute). SVG, with the numbers in
 * a table for a screen reader.
 */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import type { GoalIntervals, GoalRef } from "@/lib/api/v1/types_stats";
import { cn } from "@/lib/utils";
import { num } from "./format";

const W = 340;
const H = 150;
const MID = 75;
const PAD = 14;

function minuteText(g: GoalRef): string {
  return g.extra_minute ? `${g.minute}+${g.extra_minute}'` : `${g.minute}'`;
}

export function MirrorBins({ intervals, testId }: { intervals: GoalIntervals; testId?: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const bins = intervals.bins;
  const n = Math.max(1, intervals.matches);
  const max = Math.max(
    1,
    ...bins.flatMap((b) => [b.goals_for, b.goals_against, b.league_for * n, b.league_against * n]),
  );
  const slot = (W - PAD * 2) / bins.length;
  const bw = slot * 0.62;
  const scale = (MID - 12) / max;
  const chosen = bins.find((b) => b.label === open);
  return (
    <div data-testid={testId}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={t("stats.intervalsTitle")}
      >
        <line x1={PAD} x2={W - PAD} y1={MID} y2={MID} stroke="var(--color-border-strong)" />
        {bins.map((b, i) => {
          const cx = PAD + slot * i + slot / 2;
          const up = b.goals_for * scale;
          const down = b.goals_against * scale;
          return (
            <g key={b.label}>
              <rect
                x={cx - bw / 2}
                y={MID - up}
                width={bw}
                height={Math.max(up, 0.5)}
                rx={3}
                fill="var(--color-primary)"
              />
              <rect
                x={cx - bw / 2}
                y={MID}
                width={bw}
                height={Math.max(down, 0.5)}
                rx={3}
                fill="var(--color-negative)"
                opacity={0.85}
              />
              <line
                x1={cx - bw / 2 - 2}
                x2={cx + bw / 2 + 2}
                y1={MID - b.league_for * n * scale}
                y2={MID - b.league_for * n * scale}
                stroke="var(--color-foreground-soft)"
                strokeWidth={1.5}
                opacity={0.7}
              />
              <line
                x1={cx - bw / 2 - 2}
                x2={cx + bw / 2 + 2}
                y1={MID + b.league_against * n * scale}
                y2={MID + b.league_against * n * scale}
                stroke="var(--color-foreground-soft)"
                strokeWidth={1.5}
                opacity={0.7}
              />
              <text
                x={cx}
                y={MID - up - 3}
                textAnchor="middle"
                fontSize="9"
                fill="var(--color-foreground-soft)"
              >
                {b.goals_for}
              </text>
              <text
                x={cx}
                y={MID + down + 10}
                textAnchor="middle"
                fontSize="9"
                fill="var(--color-foreground-soft)"
              >
                {b.goals_against}
              </text>
              <text
                x={cx}
                y={H - 2}
                textAnchor="middle"
                fontSize="8.5"
                fill="var(--color-subtle-foreground)"
              >
                {b.label}
              </text>
            </g>
          );
        })}
      </svg>
      <div
        className="mt-2 flex flex-wrap gap-1.5"
        role="group"
        aria-label={t("stats.intervalsTitle")}
      >
        {bins.map((b) => (
          <button
            key={b.label}
            type="button"
            aria-pressed={open === b.label}
            onClick={() => setOpen(open === b.label ? null : b.label)}
            className={cn(
              "inline-flex min-h-11 items-center rounded-lg border px-2.5 text-caption",
              open === b.label
                ? "border-primary text-primary"
                : "border-border bg-elevated text-foreground-soft",
            )}
          >
            {t("stats.intervalsTotal", { label: b.label, n: b.goals_for + b.goals_against })}
          </button>
        ))}
      </div>
      {chosen ? (
        <div className="mt-2 rounded-xl bg-elevated p-3 text-caption" data-testid="interval-goals">
          <p className="mb-1 font-semibold">{t("stats.intervalsGoals", { label: chosen.label })}</p>
          <ul className="grid gap-1 sm:grid-cols-2">
            {chosen.goals_for_list.map((g, i) => (
              <li key={`f${i}`} className="text-positive">
                <Link
                  to="/matches/$fixtureId"
                  params={{ fixtureId: String(g.fixture_id) }}
                  className="hover:underline"
                >
                  + {minuteText(g)}
                </Link>
              </li>
            ))}
            {chosen.goals_against_list.map((g, i) => (
              <li key={`a${i}`} className="text-negative">
                <Link
                  to="/matches/$fixtureId"
                  params={{ fixtureId: String(g.fixture_id) }}
                  className="hover:underline"
                >
                  − {minuteText(g)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <table className="sr-only">
        <caption>{t("stats.intervalsTitle")}</caption>
        <tbody>
          {bins.map((b) => (
            <tr key={b.label}>
              <th scope="row">{b.label}</th>
              <td>{b.goals_for}</td>
              <td>{b.goals_against}</td>
              <td>{num(b.league_for * n, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

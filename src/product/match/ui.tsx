/** Small building blocks of the Match Center: blocks, honest notes, bars, chips and icons. */
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, Clock3 } from "lucide-react";
import type { DataStatus, Section } from "@/lib/api/v1/types";
import type { MatchCenter } from "@/lib/api/v1/types_center";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { formatDate } from "@/lib/time";
import type { PriceFreshness } from "@/lib/api/v1/types_product";
import { TeamName } from "@/components/football/Logos";
import { Freshness } from "@/product/shared/Bits";
import { sectionCodeText } from "@/components/system/LiveState";
import { Card, ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { CenterState } from "./context";
import { fmtDecimal, fmtStat, type FormChip, type ResultLetter, type StatRow } from "./model";

/** A card with a small heading row. */
export function Block({
  title,
  icon,
  right,
  children,
  className,
  bodyClassName,
  premium = false,
  level = 2,
}: {
  title: ReactNode;
  icon?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string | undefined;
  bodyClassName?: string | undefined;
  premium?: boolean;
  /** 3 inside a titled group. */
  level?: 2 | 3;
}) {
  const Heading = level === 3 ? "h3" : "h2";
  return (
    <Card className={cn("min-w-0", className)} premium={premium}>
      <div className="flex min-h-11 items-center justify-between gap-3 px-4 pt-3">
        <Heading className="flex min-w-0 items-center gap-2 font-display text-[0.95rem] font-semibold tracking-tight">
          {icon ? (
            <span aria-hidden className="shrink-0 text-muted-foreground [&>svg]:h-4 [&>svg]:w-4">
              {icon}
            </span>
          ) : null}
          <span className="min-w-0 truncate">{title}</span>
        </Heading>
        {right ? <div className="flex shrink-0 items-center gap-2">{right}</div> : null}
      </div>
      <div className={cn("px-4 pb-4 pt-2", bodyClassName)}>{children}</div>
    </Card>
  );
}

/** The honest one-liner for a block with nothing to show. */
export function SectionNote({
  status,
  children,
  className,
}: {
  status?: DataStatus | null | undefined;
  children?: ReactNode;
  className?: string | undefined;
}) {
  return (
    <p
      data-empty-state
      className={cn(
        "flex items-center gap-2 rounded-lg border border-dashed border-border-strong/70 px-3 py-2.5 text-xs text-muted-foreground",
        className,
      )}
    >
      <Clock3 aria-hidden className="h-3.5 w-3.5 shrink-0 text-subtle-foreground" />
      <span>
        {children ??
          (status === "not_available" ? t("match.note.notAvailable") : t("match.note.noData"))}
      </span>
    </p>
  );
}

/**
 * One section of the match detail: loading, error, nothing yet, or the data. The API's
 * own reason is never shown here (it is English and technical); its code is, in the
 * reader's language (common.sectionCode), and the admin tab has the reason itself.
 */
export function CenterSection<T>({
  center,
  pick,
  children,
  empty,
  skeleton,
}: {
  center: CenterState;
  pick: (c: MatchCenter) => Section<T>;
  children: (data: T) => ReactNode;
  empty?: ((status: DataStatus, code: string | null) => ReactNode) | undefined;
  skeleton?: ReactNode;
}) {
  if (center.loading) return <>{skeleton ?? <SkeletonBlock className="h-24" />}</>;
  if (center.error) {
    return <ErrorState error={center.error} onRetry={center.retry} className="py-5" />;
  }
  const none = (status: DataStatus, code: string | null = null) =>
    empty ? (
      <>{empty(status, code)}</>
    ) : (
      <SectionNote status={status}>{sectionCodeText(code) ?? undefined}</SectionNote>
    );
  if (!center.data) return none(center.status ?? "not_available");
  const section = pick(center.data);
  if (section.status !== "ok") return none(section.status, section.code ?? null);
  if (Array.isArray(section.data) && section.data.length === 0) {
    return none("empty", section.code ?? null);
  }
  return <>{children(section.data)}</>;
}

/** A player's name; a link to the player's research page for the admin only. */
export function PlayerName({
  name,
  id,
  admin,
  className,
}: {
  name: string | null;
  id: number | null;
  admin: boolean;
  className?: string | undefined;
}) {
  const label = name ?? t("match.events.unknownPlayer");
  if (admin && id !== null && name) {
    return (
      <Link
        to="/admin/players/$playerId"
        params={{ playerId: String(id) }}
        className={cn("hover:text-primary hover:underline", className)}
      >
        {label}
      </Link>
    );
  }
  return <span className={className}>{label}</span>;
}

/** Text button that moves somewhere (another tab, all lines). */
export function MoreButton({
  onClick,
  children,
  expanded,
  className,
}: {
  onClick: () => void;
  children: ReactNode;
  /** Present for a show more / show less toggle. */
  expanded?: boolean | undefined;
  className?: string | undefined;
}) {
  const Icon = expanded === undefined ? ChevronRight : ChevronDown;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={expanded}
      className={cn(
        "inline-flex min-h-9 items-center gap-0.5 rounded-md px-1 text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        className,
      )}
    >
      {children}
      <Icon
        aria-hidden
        className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")}
      />
    </button>
  );
}

const RESULT_TONE: Record<ResultLetter, string> = {
  W: "bg-positive-soft text-positive",
  D: "bg-muted text-muted-foreground",
  L: "bg-negative-soft text-negative",
};

function chipTitle(c: FormChip): string {
  const head = t(`match.form.long.${c.result}`);
  if (!c.opponent) return head;
  const score =
    c.goalsFor !== null && c.goalsAgainst !== null ? `${c.goalsFor}–${c.goalsAgainst}` : "";
  return t("match.form.chipTitle", {
    result: head,
    date: c.at ? formatDate(c.at) : "",
    opponent: c.opponent,
    venue: c.venue ? t(`match.form.venue.${c.venue}`) : "",
    score,
  });
}

/** W/D/L chips, oldest first: the newest result is the last (outlined) one. */
export function FormChips({
  chips,
  className,
}: {
  chips: readonly FormChip[];
  className?: string | undefined;
}) {
  if (chips.length === 0) return <span className="text-caption text-subtle-foreground">—</span>;
  const label = t("match.form.aria", {
    results: chips.map((c) => t(`match.form.long.${c.result}`)).join(", "),
  });
  return (
    <ol className={cn("flex items-center gap-1", className)} aria-label={label}>
      {chips.map((c, i) => (
        <li key={`${c.fixtureId ?? "f"}-${i}`} title={chipTitle(c)}>
          <span
            aria-hidden
            className={cn(
              "numeric flex h-6 w-6 items-center justify-center rounded-md text-[0.7rem] font-bold",
              RESULT_TONE[c.result],
              i === chips.length - 1 && "ring-1 ring-inset ring-foreground/35",
            )}
          >
            {t(`match.form.short.${c.result}`)}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Home colour on the left, away colour on the right: the key to every comparison bar. */
export function TeamsLegend({
  home,
  away,
  className,
}: {
  home: { name: string; logo_url?: string | null | undefined };
  away: { name: string; logo_url?: string | null | undefined };
  className?: string | undefined;
}) {
  return (
    <div className={cn("flex items-center justify-between gap-3 text-xs", className)}>
      <span className="flex min-w-0 items-center gap-2">
        <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-primary" />
        <TeamName name={home.name} logo={home.logo_url} size={18} strong className="min-w-0" />
      </span>
      <span className="flex min-w-0 items-center gap-2">
        <TeamName
          name={away.name}
          logo={away.logo_url}
          size={18}
          strong
          reverse
          className="min-w-0"
        />
        <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-info" />
      </span>
    </div>
  );
}

/** Home against away, one row per figure; the larger side of each pair is emphasised. */
export function StatBars({
  rows,
  className,
}: {
  rows: readonly StatRow[];
  className?: string | undefined;
}) {
  return (
    <ul className={cn("space-y-3.5", className)}>
      {rows.map((r) => {
        const h = r.home ?? 0;
        const a = r.away ?? 0;
        const max = Math.max(h, a);
        const hPct = max > 0 ? (h / max) * 100 : 0;
        const aPct = max > 0 ? (a / max) * 100 : 0;
        const lead = h === a ? null : h > a ? "home" : "away";
        const label = t(`match.stats.label.${r.key}`);
        return (
          <li key={r.key} data-stat={r.key}>
            <div className="flex items-baseline justify-between gap-2">
              <span
                className={cn(
                  "numeric w-14 shrink-0 text-sm",
                  lead === "home" ? "font-semibold text-foreground" : "text-muted-foreground",
                )}
              >
                {fmtStat(r.home, r.format)}
              </span>
              <span className="min-w-0 truncate text-center text-xs text-muted-foreground">
                {label}
              </span>
              <span
                className={cn(
                  "numeric w-14 shrink-0 text-right text-sm",
                  lead === "away" ? "font-semibold text-foreground" : "text-muted-foreground",
                )}
              >
                {fmtStat(r.away, r.format)}
              </span>
            </div>
            <div aria-hidden className="mt-1.5 flex gap-1">
              <div className="flex h-1.5 flex-1 justify-end overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full",
                    lead === "away" ? "bg-primary/45" : "bg-primary",
                  )}
                  style={{ width: `${hPct}%` }}
                />
              </div>
              <div className="flex h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn("h-full rounded-full", lead === "home" ? "bg-info/45" : "bg-info")}
                  style={{ width: `${aPct}%` }}
                />
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** A football, drawn in the current colour. */
export function BallIcon({ className }: { className?: string | undefined }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      className={cn("h-4 w-4 shrink-0", className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="9.25" />
      <path d="M12 7.7l3.5 2.5-1.3 4.1H9.8l-1.3-4.1z" fill="currentColor" stroke="none" />
      <path d="M12 7.7V3M15.5 10.2l4.3-1.5M14.2 14.3l2.7 3.7M9.8 14.3L7.1 18M8.5 10.2L4.2 8.7" />
    </svg>
  );
}

/** A booking: yellow, red, or the second yellow that becomes red. */
export function CardIcon({
  tone,
  className,
}: {
  tone: "yellow" | "red" | "second";
  className?: string | undefined;
}) {
  if (tone === "second") {
    return (
      <span aria-hidden className={cn("relative inline-block h-4 w-3.5 shrink-0", className)}>
        <span className="absolute left-0 top-0 h-3.5 w-2.5 rounded-[2px] bg-warning" />
        <span className="absolute bottom-0 right-0 h-3.5 w-2.5 rounded-[2px] bg-negative ring-1 ring-card" />
      </span>
    );
  }
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-3.5 w-2.5 shrink-0 rounded-[2px]",
        tone === "yellow" ? "bg-warning" : "bg-negative",
        className,
      )}
    />
  );
}

/** A player's 0-10 match rating; the best one of the match carries the gold edge. */
export function RatingBadge({
  value,
  top = false,
  className,
}: {
  value: number;
  top?: boolean;
  className?: string | undefined;
}) {
  const tone =
    value >= 8
      ? "bg-positive text-primary-foreground"
      : value >= 7
        ? "bg-positive-soft text-positive"
        : value >= 6
          ? "bg-elevated text-foreground"
          : "bg-warning-soft text-warning";
  return (
    <span
      title={t("match.players.rating")}
      className={cn(
        "numeric inline-flex min-w-[2.4rem] items-center justify-center rounded-md px-1.5 py-0.5 text-xs font-semibold",
        top ? "gold-ring border bg-gold-soft text-gold-strong" : tone,
        className,
      )}
    >
      {fmtDecimal(value, 1)}
    </span>
  );
}

/** The two halves of the comparison bars' colour key, as small dots. */
export function SideDot({ side }: { side: "home" | "away" }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        side === "home" ? "bg-primary" : "bg-info",
      )}
    />
  );
}

/** "hace 2 min" with its dot, at caption size whatever the shared badge's own classes resolve to. */
export function FreshnessLabel({
  at,
  level,
}: {
  at: string | null | undefined;
  level: PriceFreshness;
}) {
  return (
    <span className="text-caption">
      <Freshness at={at} level={level} />
    </span>
  );
}

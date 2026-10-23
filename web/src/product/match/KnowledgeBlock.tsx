/**
 * POSTPARTIDO (plan F7) - what happened in a finished match, put together once the provider had had its last look at it:
 * how the score went (who was ahead, minute by minute), what the market expected against what happened, the best of the
 * match, the formations and the changes, and how far all of it can be trusted ("Completo" only where the result, the
 * statistics, the events and the players all came with trustworthy data; what could not be confirmed is listed).
 *
 * Everything here is a fact of a match that is over. There is no pick, no forecast and no recommendation in it, and no price
 * to take: the market is read as the probability its bookmakers gave. Whether users see this block at all is the owner's
 * decision (the API answers `not_available` until then, and the block renders nothing for them). The Admin Console's
 * preview sees it with, folded away, the row as PrediGol stored it: its nine layers (the decision layer's picks and the
 * post-mortems among them), the provider's last prices and the chain of rebuilds.
 */
import { useId, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { CircleCheck, History } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtPct } from "@/lib/i18n/format";
import { formatDateTime, formatRelative } from "@/lib/time";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type {
  AfterMatch,
  KnowledgeCompleteness,
  MatchKnowledge,
} from "@/lib/api/v1/types_knowledge";
import { ShadowBadge } from "@/product/shared/Bits";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import { barPercent } from "./forecast";
import type { Sides } from "./intelligence";
import {
  KNOWLEDGE_ID,
  bestPlayers,
  closingNote,
  completenessLabel,
  completenessNote,
  doubtTexts,
  finalReads,
  happenedNote,
  headlineText,
  headlines,
  knowledgeScreen,
  lineups,
  marketHeading,
  marketReads,
  marketSelectionText,
  noKnowledgeText,
  playerFigures,
  shortHash,
  storedLayers,
  storyDrawing,
  storyFacts,
  storyLegend,
  storyOf,
  storyUntold,
  substitutionText,
  tieText,
  trackPercent,
  type KnowledgeLoad,
  type LeadState,
  type MarketRead,
  type PlayerLine,
  type SideLineup,
  type StoryDrawing,
} from "./knowledge";
import { PlayerName, RatingBadge, SideDot } from "./ui";

const CALM_TAG = "border-border-strong bg-elevated text-muted-foreground";
const POSITIVE_TAG = "border-positive/40 bg-positive-soft text-positive";
const WARNING_TAG = "border-warning/40 bg-warning-soft text-warning";
const COMPLETENESS_TONE: Record<KnowledgeCompleteness, string> = {
  complete: POSITIVE_TAG,
  partial: WARNING_TAG,
  minimal: CALM_TAG,
};

const LEAD_TONE: Record<LeadState, string> = {
  home: "bg-primary",
  level: "bg-muted-foreground/25",
  away: "bg-info",
};

function Tag({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold leading-tight",
        tone,
      )}
    >
      {children}
    </span>
  );
}

/** A titled part of the block: the story, the market, the players, the formations. */
function Part({
  testId,
  title,
  subtitle,
  children,
}: {
  testId: string;
  title: string;
  subtitle?: string | undefined;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section
      data-testid={testId}
      aria-labelledby={id}
      className="min-w-0 space-y-3 rounded-lg border border-border/70 bg-elevated/30 p-3"
    >
      <header>
        <h3 id={id} className="text-sm font-semibold">
          {title}
        </h3>
        {subtitle ? <p className="mt-0.5 text-caption text-muted-foreground">{subtitle}</p> : null}
      </header>
      {children}
    </section>
  );
}

// ── how the score went ──────────────────────────────────────────────────────

function StoryBar({ drawing, sides }: { drawing: StoryDrawing; sides: Sides }) {
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
        className="numeric flex justify-between text-[0.65rem] leading-none text-subtle-foreground"
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

function StoryPart({ after, sides }: { after: AfterMatch; sides: Sides }) {
  const story = storyOf(after);
  if (!story) {
    if (!storyUntold(after)) return null;
    return (
      <Part testId="knowledge-story" title={t("match.knowledge.story.title")}>
        <p data-testid="knowledge-story-untold" className="text-sm text-muted-foreground">
          {t("match.knowledge.story.notTold")}
        </p>
      </Part>
    );
  }
  const drawing = storyDrawing(story, after.events.data?.goals ?? []);
  const facts = storyFacts(story, sides);
  return (
    <Part
      testId="knowledge-story"
      title={t("match.knowledge.story.title")}
      subtitle={t("match.knowledge.story.subtitle")}
    >
      <StoryBar drawing={drawing} sides={sides} />
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {facts.map((f) => (
          <div
            key={f.key}
            data-fact={f.key}
            className="min-w-0 rounded-lg border border-border bg-card/60 px-3 py-2"
          >
            <dt className="break-words text-caption leading-tight text-muted-foreground">
              {f.label}
            </dt>
            <dd className="mt-0.5 break-words text-sm font-semibold">{f.value}</dd>
          </div>
        ))}
      </dl>
    </Part>
  );
}

// ── what the market expected ────────────────────────────────────────────────

function MarketView({ read, sides }: { read: MarketRead; sides: Sides }) {
  const happened = happenedNote(read);
  const closing = closingNote(read);
  return (
    <div
      data-testid="knowledge-market"
      data-market={read.market}
      className="min-w-0 space-y-3 border-t border-border/60 pt-3 first:border-t-0 first:pt-0"
    >
      <h4 className="min-w-0 break-words text-sm font-semibold">{marketHeading(read)}</h4>
      <ul className="space-y-3">
        {read.rows.map((row) => (
          <li
            key={row.selection}
            data-testid="knowledge-selection"
            data-selection={row.selection}
            data-happened={row.happened ? "true" : "false"}
            className="min-w-0"
          >
            <div className="flex items-baseline justify-between gap-3">
              <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                <span className="min-w-0 break-words">
                  {marketSelectionText(read, row.selection, sides)}
                </span>
                {row.happened ? (
                  <Tag tone={POSITIVE_TAG}>
                    <CircleCheck aria-hidden className="h-3 w-3" />
                    {t("match.knowledge.market.happened")}
                  </Tag>
                ) : null}
              </span>
              <span className="numeric shrink-0 text-base font-semibold">
                {fmtPct(row.close, 0)}
              </span>
            </div>
            <div aria-hidden className="relative mt-1.5 h-2 rounded-full bg-muted/70">
              <div
                className={cn(
                  "absolute inset-y-0 left-0 rounded-full",
                  row.happened ? "bg-positive" : "bg-primary/55",
                )}
                style={{ width: `${barPercent(row.close)}%` }}
              />
              {row.open !== null ? (
                <span
                  className="absolute top-1/2 h-3.5 w-px -translate-y-1/2 bg-foreground/60"
                  style={{ left: `${barPercent(row.open)}%` }}
                />
              ) : null}
            </div>
            <p className="numeric mt-1 text-caption text-muted-foreground">
              {row.open === null
                ? t("match.knowledge.market.openedNone")
                : t("match.knowledge.market.opened", { p: fmtPct(row.open, 0) })}
            </p>
          </li>
        ))}
      </ul>
      {happened ? (
        <p data-testid="knowledge-happened" className="text-xs leading-snug">
          {happened}
        </p>
      ) : null}
      {closing ? (
        <p
          data-testid="knowledge-closing"
          className="text-caption leading-snug text-subtle-foreground"
        >
          {closing}
        </p>
      ) : null}
    </div>
  );
}

function MarketPart({ after, sides }: { after: AfterMatch; sides: Sides }) {
  const reads = marketReads(after);
  if (reads.length === 0) return null;
  return (
    <Part
      testId="knowledge-markets"
      title={t("match.knowledge.market.title")}
      subtitle={t("match.knowledge.market.subtitle")}
    >
      <div className="space-y-3">
        {reads.map((r) => (
          <MarketView key={r.market} read={r} sides={sides} />
        ))}
      </div>
    </Part>
  );
}

// ── the best of the match ───────────────────────────────────────────────────

function PlayerRow({ player, admin }: { player: PlayerLine; admin: boolean }) {
  const figures = playerFigures(player);
  return (
    <li
      data-testid="knowledge-player"
      data-best={player.best ? "true" : "false"}
      className="flex min-w-0 items-center gap-2.5"
    >
      {player.rating !== null ? (
        <RatingBadge value={player.rating} top={player.best} />
      ) : (
        <span className="numeric inline-flex min-w-[2.4rem] justify-center text-xs text-subtle-foreground">
          —
        </span>
      )}
      <div className="min-w-0">
        <p className="break-words text-sm font-medium">
          <PlayerName name={player.name} id={player.id} admin={admin} />
        </p>
        {figures.length ? (
          <p className="numeric text-caption text-muted-foreground">{figures.join(" · ")}</p>
        ) : null}
      </div>
    </li>
  );
}

function PlayersPart({ after, sides, admin }: { after: AfterMatch; sides: Sides; admin: boolean }) {
  const best = bestPlayers(after);
  if (!best) return null;
  return (
    <Part
      testId="knowledge-players"
      title={t("match.knowledge.players.title")}
      subtitle={t("match.knowledge.players.subtitle")}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {(["home", "away"] as const).map((side) =>
          best[side].length ? (
            <div key={side} data-side={side} className="min-w-0 space-y-2">
              <p className="flex items-center gap-2 text-xs font-semibold">
                <SideDot side={side} />
                <span className="min-w-0 break-words">{sides[side]}</span>
              </p>
              <ul className="space-y-2">
                {best[side].map((p) => (
                  <PlayerRow key={p.id} player={p} admin={admin} />
                ))}
              </ul>
            </div>
          ) : null,
        )}
      </div>
    </Part>
  );
}

// ── the formations and the changes ──────────────────────────────────────────

function LineupSide({
  side,
  name,
  lineup,
  eventsKnown,
}: {
  side: "home" | "away";
  name: string;
  lineup: SideLineup | null;
  /** Without the list of events a side that shows no change may have made some: it is not said to have made none. */
  eventsKnown: boolean;
}) {
  return (
    <div data-testid="knowledge-lineup" data-side={side} className="min-w-0 space-y-1.5">
      <p className="flex items-center gap-2 text-xs font-semibold">
        <SideDot side={side} />
        <span className="min-w-0 break-words">{name}</span>
      </p>
      <p className="numeric text-sm">
        {lineup?.formation
          ? t("match.knowledge.tactics.formation", { formation: lineup.formation })
          : t("match.knowledge.tactics.noFormation")}
      </p>
      {lineup && lineup.subs.length ? (
        <>
          <p className="text-caption text-muted-foreground">
            {t("match.knowledge.tactics.subs", { count: lineup.subs.length })}
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {lineup.subs.map((s, i) => (
              <li
                key={`${s.minute}-${i}`}
                className="numeric rounded-md border border-border/70 bg-card/60 px-1.5 py-0.5 text-caption"
              >
                {substitutionText(s)}
              </li>
            ))}
          </ul>
        </>
      ) : eventsKnown ? (
        <p className="text-caption text-muted-foreground">{t("match.knowledge.tactics.noSubs")}</p>
      ) : null}
    </div>
  );
}

function LineupsPart({ after, sides }: { after: AfterMatch; sides: Sides }) {
  const both = lineups(after);
  if (!both) return null;
  const eventsKnown = after.events.data !== null;
  return (
    <Part testId="knowledge-lineups" title={t("match.knowledge.tactics.title")}>
      <div className="grid gap-4 sm:grid-cols-2">
        <LineupSide side="home" name={sides.home} lineup={both.home} eventsKnown={eventsKnown} />
        <LineupSide side="away" name={sides.away} lineup={both.away} eventsKnown={eventsKnown} />
      </div>
    </Part>
  );
}

// ── how far it can be trusted ───────────────────────────────────────────────

function Quality({ after }: { after: AfterMatch }) {
  const doubts = doubtTexts(after);
  return (
    <div
      data-testid="knowledge-quality"
      data-completeness={after.completeness}
      className="space-y-2"
    >
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Tag tone={COMPLETENESS_TONE[after.completeness]}>
          {completenessLabel(after.completeness)}
        </Tag>
        <span className="min-w-0 text-caption leading-snug text-muted-foreground">
          {completenessNote(after.completeness)}
        </span>
      </p>
      {doubts.length ? (
        <div data-testid="knowledge-doubts" className="space-y-1">
          <p className="text-caption font-semibold text-muted-foreground">
            {t("match.knowledge.quality.doubtsTitle")}
          </p>
          <ul className="list-disc space-y-0.5 pl-4 text-caption leading-snug text-muted-foreground">
            {doubts.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-caption text-subtle-foreground">
        {t("match.knowledge.updated", { when: formatRelative(after.known_at) })}
      </p>
    </div>
  );
}

// ── the preview's own detail: the row as stored ─────────────────────────────

/** Folded away: the summary is what the block says; the rest is for knowing how PrediGol keeps it. */
function AdminDetails({ data, after }: { data: MatchKnowledge; after: AfterMatch }) {
  const stored = data.stored;
  if (!stored) return null;
  const layers = storedLayers(stored);
  const finals = finalReads(after);
  return (
    <details
      data-testid="knowledge-admin"
      className="rounded-lg border border-info/30 bg-info-soft/30 px-3 py-2"
    >
      <summary className="cursor-pointer text-xs font-semibold text-info focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
        {t("match.knowledge.admin.detailsTitle")}
      </summary>
      <div className="mt-2 space-y-3 text-caption">
        <p className="numeric break-words text-muted-foreground">
          {t("match.knowledge.admin.build", { id: stored.id })} ·{" "}
          {stored.supersedes === null
            ? t("match.knowledge.admin.first")
            : t("match.knowledge.admin.replaces", { id: stored.supersedes })}{" "}
          ·{" "}
          {t("match.knowledge.admin.hashes", {
            inputs: shortHash(stored.inputs_hash),
            content: shortHash(stored.content_hash),
          })}
        </p>
        <div className="space-y-1.5">
          <h4 className="font-semibold text-muted-foreground">
            {t("match.knowledge.admin.layersTitle")}
          </h4>
          <p className="text-subtle-foreground">{t("match.knowledge.admin.ownLayers")}</p>
          <ul className="space-y-1.5">
            {layers.map((l) => (
              <li
                key={l.name}
                data-testid="knowledge-stored-layer"
                data-layer={l.name}
                className="min-w-0 rounded-md border border-border/60 bg-card/60 px-2.5 py-1.5"
              >
                <p className="numeric flex flex-wrap items-baseline gap-x-3 break-words">
                  <span className="font-semibold">{l.name}</span>
                  <span>{l.status}</span>
                  {l.knownAt ? (
                    <span className="text-muted-foreground">{formatDateTime(l.knownAt)}</span>
                  ) : null}
                  {l.notes.length ? (
                    <span className="text-muted-foreground">
                      {t("match.knowledge.admin.notes")}: {l.notes.join(", ")}
                    </span>
                  ) : null}
                </p>
                {l.json ? (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-info">
                      {t("match.knowledge.admin.showData")}
                    </summary>
                    <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/50 p-2 text-[0.7rem] leading-snug">
                      {l.json}
                    </pre>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
        {finals.length ? (
          <div data-testid="knowledge-finals" className="space-y-1.5">
            <h4 className="font-semibold text-muted-foreground">
              {t("match.knowledge.admin.finalTitle")}
            </h4>
            <ul className="space-y-1">
              {finals.map((f) => (
                <li key={f.market} className="numeric break-words">
                  <span className="font-semibold">
                    {f.market}
                    {f.line !== null ? ` ${f.line}` : ""}
                  </span>{" "}
                  {t("match.knowledge.admin.finalLine", {
                    odds: f.odds,
                    count: f.books,
                    before: f.before,
                  })}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="space-y-1.5">
          <h4 className="font-semibold text-muted-foreground">
            {t("match.knowledge.admin.chainTitle")}
          </h4>
          <ol data-testid="knowledge-chain" className="numeric space-y-0.5">
            {stored.chain.map((c) => (
              <li key={c.id} className="break-words">
                {t("match.knowledge.admin.chainLine", {
                  id: c.id,
                  built: formatDateTime(c.built_at),
                  completeness: c.completeness,
                  hash: shortHash(c.content_hash),
                })}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </details>
  );
}

// ── the block ───────────────────────────────────────────────────────────────

function Body({
  data,
  after,
  sides,
  preview,
  admin,
}: {
  data: MatchKnowledge;
  after: AfterMatch;
  sides: Sides;
  preview: boolean;
  admin: boolean;
}) {
  const tags = headlines(after);
  const result = after.result.data;
  const tie = result ? tieText(result) : null;
  return (
    <>
      {tags.length ? (
        <ul data-testid="knowledge-tags" className="flex flex-wrap gap-1.5">
          {tags.map((h) => (
            <li key={h.key} data-tag={h.key}>
              <Tag tone={h.key === "corrected" ? WARNING_TAG : CALM_TAG}>
                {headlineText(h, sides)}
              </Tag>
            </li>
          ))}
        </ul>
      ) : null}
      {tie ? (
        <p data-testid="knowledge-tie" className="numeric text-sm font-medium">
          {tie}
        </p>
      ) : null}
      <StoryPart after={after} sides={sides} />
      <MarketPart after={after} sides={sides} />
      <PlayersPart after={after} sides={sides} admin={admin} />
      <LineupsPart after={after} sides={sides} />
      <Quality after={after} />
      {preview ? <AdminDetails data={data} after={after} /> : null}
    </>
  );
}

/**
 * The block from an answer of the API. Apart from the query so that it can be rendered from a fixture: `preview` is the
 * Admin Console's shadow preview, the only view that sees the row as stored; `admin` adds links to the players.
 */
export function KnowledgeView({
  load,
  home,
  away,
  preview,
  admin = false,
}: {
  load: KnowledgeLoad;
  home: string;
  away: string;
  preview: boolean;
  admin?: boolean;
}) {
  const titleId = useId();
  const screen = knowledgeScreen(load, preview);
  if (screen.kind === "nothing") return null;
  const sides: Sides = { home, away };
  return (
    <section
      id={KNOWLEDGE_ID}
      aria-labelledby={titleId}
      data-testid="knowledge-block"
      data-screen={screen.kind}
      data-preview={preview ? "true" : "false"}
      className={cn(
        "min-w-0 scroll-mt-20 rounded-xl border border-border bg-card",
        preview && "border-info/40",
      )}
    >
      <header className="flex items-start justify-between gap-3 px-4 pt-3.5">
        <div className="min-w-0">
          <h2
            id={titleId}
            className="flex items-center gap-2 font-display text-[0.95rem] font-bold uppercase tracking-[0.08em]"
          >
            <History aria-hidden className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 break-words">{t("match.knowledge.title")}</span>
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("match.knowledge.subtitle")}</p>
        </div>
        {preview ? <ShadowBadge compact /> : null}
      </header>
      <div className="space-y-3 px-4 pb-4 pt-3">
        {screen.kind === "loading" ? <SkeletonBlock className="h-40" /> : null}
        {screen.kind === "error" ? (
          <ErrorState error={screen.error} onRetry={screen.retry} className="py-5" />
        ) : null}
        {screen.kind === "none" ? (
          <p
            className="text-sm text-muted-foreground"
            data-empty-state
            data-testid="knowledge-none"
          >
            {noKnowledgeText(screen.code)}
          </p>
        ) : null}
        {screen.kind === "knowledge" ? (
          <Body
            data={screen.data}
            after={screen.after}
            sides={sides}
            preview={preview}
            admin={admin}
          />
        ) : null}
      </div>
    </section>
  );
}

/** The Resumen's block of a finished match: loads the summary for the signed-in view (a user's, or the Admin Console's preview). */
export function KnowledgeBlock({ ctx }: { ctx: MatchCtx }) {
  const shadow = usePreviewParam();
  const q = useQuery(live.matchKnowledge(ctx.fixtureId, shadow));
  const load: KnowledgeLoad = q.isPending
    ? { status: "pending" }
    : q.isError
      ? {
          status: "error",
          error: q.error,
          retry: () => {
            void q.refetch();
          },
        }
      : { status: "success", envelope: q.data };
  return (
    <KnowledgeView
      load={load}
      home={ctx.match.home.name}
      away={ctx.match.away.name}
      preview={shadow === "shadow"}
      admin={ctx.showAdmin}
    />
  );
}

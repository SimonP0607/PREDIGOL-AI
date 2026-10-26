/**
 * One news card (plan UX, A10; section 27) with its seven elements: the headline (kind and protagonist), the source and its
 * standing in words, the time in the reader's zone, PrediGol's own summary (never the article), the relevance for the match,
 * the status - in words, never only a colour, its explanation on a tap - and the link to the original in a new tab
 * (`rel="noopener noreferrer"`). A contradiction is one card with each claim and its own sources.
 */
import { useId } from "react";
import {
  ArrowLeftRight,
  BadgeCheck,
  CircleDot,
  CircleHelp,
  ExternalLink,
  History,
  SignalHigh,
  SignalLow,
  SignalMedium,
} from "lucide-react";
import { hintProps } from "@/components/system/tapHint";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import type { NewsClaim, NewsItem, NewsRelevance, NewsStatus } from "@/lib/api/v1/types_news";
import {
  headline,
  kindLabel,
  shownInSpanish,
  sourceLine,
  statusHelp,
  statusLabel,
  summary,
  whenText,
  whenTitle,
} from "./news";

const STATUS_TONE: Readonly<Record<NewsStatus, string>> = {
  CONFIRMED: "border-positive/40 bg-positive-soft text-positive",
  PROBABLE: "border-info/40 bg-info-soft text-info",
  CONTRADICTORY: "border-warning/40 bg-warning-soft text-warning",
  RUMOR: "border-border-strong bg-elevated text-muted-foreground",
  OUTDATED: "border-border bg-elevated/60 text-subtle-foreground",
};

const STATUS_ICON = {
  CONFIRMED: BadgeCheck,
  PROBABLE: CircleDot,
  CONTRADICTORY: ArrowLeftRight,
  RUMOR: CircleHelp,
  OUTDATED: History,
} as const;

const RELEVANCE_ICON = { high: SignalHigh, medium: SignalMedium, low: SignalLow } as const;

export function StatusChip({ status }: { status: NewsStatus }) {
  const Icon = STATUS_ICON[status];
  const help = statusHelp(status);
  return (
    <span
      {...hintProps(help)}
      data-testid="news-status"
      data-status={status}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold",
        STATUS_TONE[status],
      )}
    >
      <Icon aria-hidden className="h-3 w-3 shrink-0" />
      {statusLabel(status)}
      <span className="sr-only">: {help}</span>
    </span>
  );
}

export function RelevanceChip({ relevance }: { relevance: NewsRelevance }) {
  const Icon = RELEVANCE_ICON[relevance];
  const help = t("match.news.relevance.help");
  return (
    <span
      {...hintProps(help)}
      data-testid="news-relevance"
      data-relevance={relevance}
      className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[0.7rem] font-medium text-muted-foreground"
    >
      <Icon aria-hidden className="h-3 w-3 shrink-0" />
      {t(`match.news.relevance.${relevance}`)}
      <span className="sr-only">: {help}</span>
    </span>
  );
}

function SourceLink({ claim }: { claim: NewsClaim }) {
  const primary = claim.sources.find((s) => s.url);
  if (!primary?.url) {
    return (
      <span className="text-caption text-subtle-foreground" data-testid="news-no-link">
        {t("match.news.noLink")}
      </span>
    );
  }
  return (
    <a
      href={primary.url}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="news-link"
      aria-label={t("match.news.readNamed", { source: primary.name })}
      onClick={() => track("news_link_clicked")}
      className="tap-y inline-flex items-center gap-1 text-caption font-semibold text-primary underline-offset-2 hover:underline"
    >
      {t("match.news.read")}
      <ExternalLink aria-hidden className="h-3 w-3 shrink-0" />
    </a>
  );
}

function ClaimView({
  item,
  claim,
  labelled,
}: {
  item: NewsItem;
  claim: NewsClaim;
  labelled: boolean;
}) {
  const sources = claim.sources;
  return (
    <div className="space-y-1" data-testid="news-claim" data-assertion={claim.assertion}>
      {labelled ? (
        <p className="text-[0.7rem] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          {kindLabel(item.kind, claim.assertion)}
        </p>
      ) : null}
      <p
        className="text-sm leading-relaxed text-foreground/90"
        data-testid="news-summary"
        lang={claim.text ? "es" : undefined}
      >
        {summary(item, claim)}
        {shownInSpanish(claim) ? (
          <span className="ml-1 text-caption text-subtle-foreground" data-testid="news-in-spanish">
            {t("match.news.inSpanish")}
          </span>
        ) : null}
      </p>
      <p className="text-caption text-muted-foreground" data-testid="news-source">
        <span className="font-medium">
          {t(sources.length > 1 ? "match.news.sources" : "match.news.source")}
        </span>{" "}
        {sources.length
          ? sources.map((s, i) => (
              <span key={`${s.name}-${i}`} data-tier={s.tier}>
                {i > 0 ? "; " : null}
                <span className="break-words">{sourceLine(s)}</span>
              </span>
            ))
          : t("match.news.someSource")}
      </p>
      <SourceLink claim={claim} />
    </div>
  );
}

export function NewsCard({ item, now }: { item: NewsItem; now?: number | undefined }) {
  const id = useId();
  const contradiction = item.claims.length > 1;
  return (
    <article
      aria-labelledby={id}
      data-testid="news-card"
      data-status={item.status}
      data-kind={item.kind}
      className={cn(
        "min-w-0 rounded-xl border border-border bg-card p-3.5",
        item.status === "OUTDATED" && "bg-card/70",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusChip status={item.status} />
        <RelevanceChip relevance={item.relevance} />
        <time
          dateTime={item.published_at ?? item.seen_at}
          {...hintProps(whenTitle(item))}
          data-testid="news-time"
          className="ml-auto text-caption text-subtle-foreground"
        >
          {whenText(item, now)}
        </time>
      </div>
      <h3
        id={id}
        className="mt-2 break-words text-sm font-semibold leading-snug"
        data-testid="news-headline"
      >
        {headline(item)}
      </h3>
      <div
        className={cn(
          "mt-1.5",
          contradiction && "mt-2.5 space-y-3 border-l-2 border-warning/40 pl-3",
        )}
      >
        {item.claims.map((claim, i) => (
          <ClaimView key={i} item={item} claim={claim} labelled={contradiction} />
        ))}
      </div>
    </article>
  );
}

/**
 * Novedades (/updates; plan UX, B6 and section 40): what changed in PrediGol, newest first, in the reader's language -
 * the answer to what readers tell us. Opening it marks the newest entry as seen, and the dot on «Más» goes. An entry
 * born of the readers' comments says so; the others do not pretend. At the foot, the way to tell PrediGol what to
 * change next: a suggestion (A14), or the help when messages are off.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, Megaphone, MessageSquarePlus } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { buttonVariants } from "@/components/ui/button";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { PublicUpdate } from "@/lib/api/v1/types_announcements";
import { t, useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { formatDateYear } from "@/lib/time";
import { useReportProblem } from "@/product/support/report";
import {
  LATEST_UPDATE,
  UPDATES,
  UPDATE_FILTERS,
  countByFilter,
  matchesFilter,
  updateDay,
  type UpdateEntry,
  type UpdateFilter,
  type UpdateKind,
} from "./updates";

/** A link inside the app, its path and its anchor apart (the router wants them so). */
function AppLink({
  to,
  children,
  className,
}: {
  to: string;
  children: ReactNode;
  className?: string | undefined;
}) {
  const [path, hash] = to.split("#");
  return (
    <Link to={(path || "/") as never} {...(hash ? { hash } : {})} className={className}>
      {children}
    </Link>
  );
}

const KIND_TONE: Record<UpdateKind, string> = {
  new: "bg-primary-soft text-primary",
  improvement: "bg-info-soft text-info",
  fix: "bg-warning-soft text-warning",
  notice: "bg-gold-soft text-gold-strong",
};

/** What the entry is, in a word (decision 9): Nuevo, Mejora, Corrección or Aviso. */
function KindTag({ kind }: { kind: UpdateKind }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-full px-2.5 text-xs font-semibold",
        KIND_TONE[kind],
      )}
      data-testid="update-kind"
      data-kind={kind}
    >
      {t(`support.updates.kind.${kind}`)}
    </span>
  );
}

function Entry({ entry }: { entry: UpdateEntry }) {
  const titleId = `update-${entry.id}`;
  return (
    <article
      aria-labelledby={titleId}
      data-testid="update"
      data-update={entry.id}
      className="card-surface rounded-card p-4"
    >
      <p className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
        <KindTag kind={entry.kind} />
        <time dateTime={entry.id.slice(0, 10)}>{formatDateYear(updateDay(entry.id))}</time>
      </p>
      <h2 id={titleId} className="mt-2 text-title leading-snug">
        {t(`support.updates.items.${entry.key}.title`)}
      </h2>
      {entry.fromReaders ? (
        <p
          className="mt-1.5 inline-flex rounded-full border border-gold/40 bg-gold-soft px-2 py-0.5 text-caption font-semibold text-gold-strong"
          data-testid="update-from-readers"
        >
          {t("support.updates.fromReaders")}
        </p>
      ) : null}
      <p className="mt-1.5 text-sm leading-relaxed text-foreground/90">
        {t(`support.updates.items.${entry.key}.body`)}
      </p>
      {entry.to && entry.go ? (
        <AppLink
          to={entry.to}
          className="tap-y relative mt-2 inline-flex min-h-6 items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          {t(`support.updates.go.${entry.go}`)}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </AppLink>
      ) : null}
    </article>
  );
}

/** An entry the owner wrote in the console (closing plan 4.3): his words in the reader's language, dated by its start. */
function OwnerEntry({ entry }: { entry: PublicUpdate }) {
  const { locale } = useI18n();
  const titleId = `update-owner-${entry.id}`;
  return (
    <article
      aria-labelledby={titleId}
      data-testid="update"
      data-update={`owner-${entry.id}`}
      className="card-surface rounded-card p-4"
    >
      <p className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
        <KindTag kind="notice" />
        <time dateTime={entry.starts_at.slice(0, 10)}>{formatDateYear(entry.starts_at)}</time>
      </p>
      <h2 id={titleId} className="mt-2 text-title leading-snug">
        {locale === "en" ? entry.title_en : entry.title_es}
      </h2>
      <p className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-foreground/90">
        {locale === "en" ? entry.body_en : entry.body_es}
      </p>
    </article>
  );
}

/** The page from its entries (a test renders it without a session). ``onSuggest``: messages to PrediGol are on. */
export function UpdatesView({
  entries,
  owner = [],
  onSuggest,
}: {
  entries: readonly UpdateEntry[];
  /** What the owner published as updates, newest first: they lead the list. */
  owner?: readonly PublicUpdate[];
  onSuggest?: (() => void) | undefined;
}) {
  // the filters of decision 9: everything, or one kind. The owner's communiqués are notices: they show under «Todo».
  const [filter, setFilter] = useState<UpdateFilter>("all");
  const counts = countByFilter(entries);
  counts.all += owner.length;
  const shown = entries.filter((e) => matchesFilter(e.kind, filter));
  const shownOwner = filter === "all" ? owner : [];
  return (
    <div className="mx-auto max-w-2xl space-y-5" data-testid="updates">
      <PageHeader
        title={t("support.updates.title")}
        description={t("support.updates.intro")}
        actions={<Megaphone aria-hidden className="h-5 w-5 text-gold" />}
      />
      <div
        role="radiogroup"
        aria-label={t("support.updates.filterLabel")}
        className="scroll-strip -mx-1 flex gap-2 px-1 py-1"
        data-testid="updates-filters"
      >
        {UPDATE_FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            role="radio"
            aria-checked={filter === f}
            onClick={() => setFilter(f)}
            data-testid={`updates-filter-${f}`}
            className={cn(
              "tap-y relative inline-flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 text-[0.8125rem] font-semibold leading-none transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              filter === f
                ? "border-primary/40 bg-primary-soft text-primary"
                : "border-transparent bg-elevated text-foreground-soft hover:text-foreground",
            )}
          >
            {t(`support.updates.filter.${f}`)}
            <span className="numeric text-xs opacity-80">{counts[f]}</span>
          </button>
        ))}
      </div>
      {shown.length + shownOwner.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="updates-empty">
          {t("support.updates.emptyFilter")}
        </p>
      ) : (
        <ol className="space-y-3" data-testid="updates-list">
          {shownOwner.map((entry) => (
            <li key={`owner-${entry.id}`}>
              <OwnerEntry entry={entry} />
            </li>
          ))}
          {shown.map((entry) => (
            <li key={entry.id}>
              <Entry entry={entry} />
            </li>
          ))}
        </ol>
      )}
      <section
        aria-labelledby="updates-suggest-title"
        className="card-surface space-y-2 rounded-card p-4"
        data-testid="updates-suggest"
      >
        <h2
          id="updates-suggest-title"
          className="flex items-center gap-2 font-display text-base font-semibold"
        >
          <MessageSquarePlus aria-hidden className="h-4 w-4 text-primary" />
          {t("support.updates.suggest.title")}
        </h2>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {t("support.updates.suggest.body")}
        </p>
        {onSuggest ? (
          <button
            type="button"
            onClick={onSuggest}
            data-testid="updates-suggest-open"
            className={buttonVariants({ variant: "primary", size: "sm" })}
          >
            {t("support.updates.suggest.action")}
          </button>
        ) : (
          <AppLink
            to="/help"
            className="tap-y relative inline-flex min-h-11 items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            {t("support.updates.go.help")}
            <ChevronRight aria-hidden className="h-3.5 w-3.5" />
          </AppLink>
        )}
      </section>
    </div>
  );
}

export function UpdatesPage() {
  const auth = useAuth();
  const qc = useQueryClient();
  const report = useReportProblem();
  const signedIn = auth.status === "signed-in";
  const seen = useQuery({ ...live.updatesSeen, enabled: signedIn });
  const notices = useQuery(live.announcements);
  const last = seen.data?.last_seen;
  // the newest entry seen: the dot on «Más» goes (a failure keeps it, and the next visit tries again)
  useEffect(() => {
    if (!signedIn || !LATEST_UPDATE || !seen.isSuccess || last === LATEST_UPDATE) return;
    v1.markUpdatesSeen(LATEST_UPDATE)
      .then((saved) => qc.setQueryData(live.updatesSeen.queryKey, saved))
      .catch(() => undefined);
  }, [signedIn, seen.isSuccess, last, qc]);
  return (
    <UpdatesView
      entries={UPDATES}
      owner={notices.data?.updates ?? []}
      onSuggest={report.available ? () => report.open({ category: "suggestion" }) : undefined}
    />
  );
}

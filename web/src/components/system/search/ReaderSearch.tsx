/**
 * The readers' global search (plan maestro unificado, UX-153; maqueta 14): a layer over the page, opened from the top bar,
 * with «/» or Ctrl/⌘ K. It reads the same `GET /search` as the console's palette (one query, `useSearchHits`) and draws
 * the answer grouped - Equipos, Competiciones, Partidos - in the maqueta's order. Before typing: the recent searches of this
 * device (kept here, never sent) and the shortcuts. Arrows move, Intro opens, Esc closes (cmdk and the dialog).
 *
 * Loaded on first use only: no page pays for it until someone searches.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import {
  CalendarDays,
  Search,
  X,
  Coins,
  Newspaper,
  RotateCcw,
  Shield,
  Target,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { Command as CommandPrimitive } from "cmdk";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { t } from "@/lib/i18n";
import { formatKickoff } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { SearchHit } from "@/lib/api/v1/types";
import {
  cleanQuery,
  deviceStore,
  groupHits,
  hitKickoff,
  hitLink,
  MIN_QUERY,
  pushRecent,
  readRecent,
  writeRecent,
  type RecentHit,
  type SearchGroup,
} from "./model";
import { useSearchHits } from "./useSearchHits";

const GROUP_ICON: Record<SearchGroup, LucideIcon> = {
  team: Shield,
  competition: Trophy,
  fixture: CalendarDays,
};

const ITEM =
  "group flex min-h-12 cursor-pointer select-none items-center gap-3 rounded-control px-3 py-2 text-sm outline-none data-[selected=true]:bg-elevated data-[disabled=true]:pointer-events-none";
const HEADING =
  "[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:text-label [&_[cmdk-group-heading]]:text-subtle-foreground";

function subline(hit: Pick<SearchHit, "type" | "sublabel">): string {
  if (hit.type === "fixture") {
    const at = hitKickoff(hit.sublabel);
    return at ? formatKickoff(at) : "";
  }
  return hit.sublabel;
}

function HitRow({ hit, onPick }: { hit: RecentHit; onPick: (hit: RecentHit) => void }) {
  const Icon = GROUP_ICON[hit.type];
  const sub = subline(hit);
  return (
    <CommandPrimitive.Item
      value={`${hit.type}-${hit.id}`}
      onSelect={() => onPick(hit)}
      className={ITEM}
      data-testid="search-hit"
      data-type={hit.type}
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-elevated text-muted-foreground group-data-[selected=true]:bg-primary-soft group-data-[selected=true]:text-primary">
        <Icon aria-hidden className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-semibold">{hit.label}</span>
        {sub ? (
          <span className="block truncate text-caption text-muted-foreground">{sub}</span>
        ) : null}
      </span>
    </CommandPrimitive.Item>
  );
}

const SHORTCUTS: {
  to: "/matches" | "/picks" | "/odds" | "/news";
  label: string;
  icon: LucideIcon;
}[] = [
  { to: "/matches", label: "nav.search.go.matches", icon: CalendarDays },
  { to: "/picks", label: "nav.search.go.picks", icon: Target },
  { to: "/odds", label: "nav.search.go.odds", icon: Coins },
  { to: "/news", label: "nav.search.go.news", icon: Newspaper },
];

export default function ReaderSearch({
  open,
  onOpenChange,
  news = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Noticias is open to this reader: its shortcut is offered. */
  news?: boolean;
}) {
  const navigate = useNavigate();
  const [raw, setRaw] = useState("");
  const [recent, setRecent] = useState<RecentHit[]>(() => readRecent(deviceStore()));
  const term = cleanQuery(raw);
  const typing = term.length >= MIN_QUERY;
  const { hits, pending, error, refetch } = useSearchHits(term, open);
  const groups = useMemo(() => groupHits(hits ?? []), [hits]);

  function close() {
    onOpenChange(false);
    setRaw("");
  }

  function pick(hit: RecentHit) {
    const next = pushRecent(recent, hit);
    setRecent(next);
    writeRecent(deviceStore(), next);
    close();
    const link = hitLink(hit);
    if (link.to === "/matches/$fixtureId") void navigate({ to: link.to, params: link.params });
    else void navigate({ to: link.to, search: link.search });
  }

  function forget() {
    setRecent([]);
    writeRecent(deviceStore(), []);
  }

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/70 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          data-testid="reader-search"
          aria-describedby="reader-search-hint"
          // a phone: the whole width, from the top (the keyboard takes the bottom); a desk: a column under the bar
          className="fixed inset-x-0 top-[env(safe-area-inset-top)] z-50 mx-auto flex max-h-[calc(100dvh-env(safe-area-inset-top))] w-full flex-col overflow-hidden border-b border-foreground/[0.09] bg-card shadow-[0_30px_80px_-20px_rgb(0_0_0/0.95)] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 sm:top-[calc(env(safe-area-inset-top)+4.5rem)] sm:max-h-[min(36rem,calc(100dvh-6rem))] sm:w-[calc(100%-2rem)] sm:max-w-xl sm:rounded-feature sm:border"
        >
          <DialogPrimitive.Title className="sr-only">{t("nav.search.title")}</DialogPrimitive.Title>
          <CommandPrimitive
            shouldFilter={false}
            loop
            label={t("nav.search.title")}
            className="flex min-h-0 flex-1 flex-col"
          >
            <div className="flex items-center gap-2 border-b border-border px-4">
              <Search aria-hidden className="h-5 w-5 shrink-0 text-muted-foreground" />
              <CommandPrimitive.Input
                value={raw}
                onValueChange={setRaw}
                maxLength={80}
                placeholder={t("nav.search.placeholder")}
                data-testid="reader-search-input"
                className="h-14 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-subtle-foreground"
              />
              <DialogPrimitive.Close
                className="tap relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-elevated hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary"
                aria-label={t("common.close")}
              >
                <X aria-hidden className="h-5 w-5" />
              </DialogPrimitive.Close>
            </div>
            <CommandPrimitive.List
              className={cn("min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3", HEADING)}
            >
              {!typing ? (
                <>
                  {recent.length ? (
                    <CommandPrimitive.Group heading={t("nav.search.recent")}>
                      {recent.map((r) => (
                        <HitRow key={`${r.type}-${r.id}`} hit={r} onPick={pick} />
                      ))}
                      <CommandPrimitive.Item
                        value="forget-recent"
                        onSelect={forget}
                        className={cn(ITEM, "min-h-11 text-primary")}
                        data-testid="search-forget"
                      >
                        <RotateCcw aria-hidden className="h-4 w-4" />
                        {t("nav.search.forget")}
                      </CommandPrimitive.Item>
                    </CommandPrimitive.Group>
                  ) : null}
                  <CommandPrimitive.Group heading={t("nav.search.goTo")}>
                    {SHORTCUTS.filter((s) => news || s.to !== "/news").map((s) => (
                      <CommandPrimitive.Item
                        key={s.to}
                        value={`go-${s.to}`}
                        onSelect={() => {
                          close();
                          void navigate({ to: s.to });
                        }}
                        className={ITEM}
                      >
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-elevated text-muted-foreground">
                          <s.icon aria-hidden className="h-4 w-4" />
                        </span>
                        <span className="font-semibold">{t(s.label)}</span>
                      </CommandPrimitive.Item>
                    ))}
                  </CommandPrimitive.Group>
                </>
              ) : pending ? (
                <CommandPrimitive.Loading>
                  <div aria-hidden className="space-y-2 px-3 py-3" data-testid="search-loading">
                    {[0, 1, 2].map((i) => (
                      <div key={i} className="flex items-center gap-3">
                        <div className="h-8 w-8 animate-pulse rounded-full bg-elevated" />
                        <div className="h-4 flex-1 animate-pulse rounded bg-elevated" />
                      </div>
                    ))}
                  </div>
                  <span className="sr-only">{t("nav.search.loading")}</span>
                </CommandPrimitive.Loading>
              ) : error ? (
                <div className="px-4 py-6 text-center" role="alert" data-testid="search-error">
                  <p className="text-sm text-muted-foreground">{t("nav.search.error")}</p>
                  <button
                    type="button"
                    onClick={refetch}
                    className="tap-y relative mt-2 text-sm font-semibold text-primary hover:underline"
                  >
                    {t("common.retry")}
                  </button>
                </div>
              ) : groups.length === 0 ? (
                <div className="px-4 py-8 text-center" data-testid="search-empty">
                  <p className="font-semibold">{t("nav.search.none", { q: term })}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{t("nav.search.noneHint")}</p>
                </div>
              ) : (
                groups.map((g) => (
                  <CommandPrimitive.Group key={g.group} heading={t(`nav.search.groups.${g.group}`)}>
                    {g.hits.map((h) => (
                      <HitRow key={`${h.type}-${h.id}`} hit={h} onPick={pick} />
                    ))}
                  </CommandPrimitive.Group>
                ))
              )}
            </CommandPrimitive.List>
            <p
              id="reader-search-hint"
              className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-4 py-2.5 text-caption text-subtle-foreground"
            >
              <span>{t("nav.search.scope")}</span>
              <span className="hidden pointer-fine:inline">{t("nav.search.keys")}</span>
            </p>
          </CommandPrimitive>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

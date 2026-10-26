/**
 * The absences in the press, for Alineaciones (plan UX, A10; section 25: «A10 añade las bajas con su fuente»): what the
 * outlets say about who will not play or is in doubt - confirmed, probable or contradicted, never a rumour -, each line with
 * its status in words, its source and its standing, and the way to the whole card in Noticias. Nothing when there is none,
 * when the news cannot be read or when the owner turned them off: the line-ups stand on their own.
 */
import { Newspaper } from "lucide-react";
import { t } from "@/lib/i18n";
import type { NewsItem } from "@/lib/api/v1/types_news";
import { Block } from "@/product/match/ui";
import type { MatchCtx } from "@/product/match/context";
import { StatusChip } from "./NewsCard";
import { headline, pressAbsences, sourceLine } from "./news";
import { useNews } from "./useNews";

export function PressAbsencesView({ items, onMore }: { items: NewsItem[]; onMore: () => void }) {
  const said = pressAbsences(items);
  if (!said.length) return null;
  return (
    <Block title={t("match.news.press.title")} icon={<Newspaper />}>
      <div data-testid="press-absences" className="space-y-2">
        <p className="text-caption leading-snug text-subtle-foreground">
          {t("match.news.press.note")}
        </p>
        <ul className="divide-y divide-border/60">
          {said.map((item) => {
            const source = item.claims[0]?.sources[0];
            return (
              <li
                key={item.id}
                className="space-y-1 py-2"
                data-testid="press-absence"
                data-status={item.status}
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <StatusChip status={item.status} />
                  <span className="min-w-0 break-words text-sm font-medium">{headline(item)}</span>
                </div>
                {source ? (
                  <p className="text-caption text-muted-foreground">
                    {t("match.news.source")} {sourceLine(source)}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
        <button
          type="button"
          onClick={onMore}
          data-testid="press-absences-more"
          className="tap-y relative text-caption font-semibold text-primary underline-offset-2 hover:underline"
        >
          {t("match.news.press.more")}
        </button>
      </div>
    </Block>
  );
}

export function PressAbsences({ ctx }: { ctx: MatchCtx }) {
  const load = useNews(ctx.fixtureId);
  if (load.status !== "success" || load.envelope.status !== "ok" || !load.envelope.data)
    return null;
  return <PressAbsencesView items={load.envelope.data.items} onMore={() => ctx.goTo("news")} />;
}

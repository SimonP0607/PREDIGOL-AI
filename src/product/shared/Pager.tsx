/** Previous / next over pages of 15, with where the reader is (paging.ts). */
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import type { Paged } from "./paging";

export function Pager<T>({
  paged,
  className,
  onChange,
}: {
  paged: Paged<T>;
  className?: string | undefined;
  /** After a page change (e.g. scroll the list's top into view). */
  onChange?: (() => void) | undefined;
}) {
  if (paged.pages <= 1) return null;
  const go = (p: number) => {
    paged.setPage(p);
    onChange?.();
  };
  const button =
    "tap-y relative inline-flex min-h-9 items-center gap-1 rounded-lg border border-border-strong px-3 text-xs font-semibold transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40";
  return (
    <nav
      aria-label={t("common.pager.label")}
      className={cn("flex flex-wrap items-center justify-between gap-2", className)}
      data-testid="pager"
    >
      <span className="numeric text-caption text-muted-foreground" aria-live="polite">
        {t("common.pager.range", { from: paged.from, to: paged.to, total: paged.total })}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className={button}
          disabled={paged.page <= 1}
          onClick={() => go(paged.page - 1)}
          data-testid="pager-prev"
        >
          <ChevronLeft aria-hidden className="h-3.5 w-3.5" />
          {t("common.pager.prev")}
        </button>
        <span className="numeric text-caption text-subtle-foreground">
          {t("common.pager.page", { page: paged.page, pages: paged.pages })}
        </span>
        <button
          type="button"
          className={button}
          disabled={paged.page >= paged.pages}
          onClick={() => go(paged.page + 1)}
          data-testid="pager-next"
        >
          {t("common.pager.next")}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </button>
      </div>
    </nav>
  );
}

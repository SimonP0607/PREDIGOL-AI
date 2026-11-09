/** Loading, in the shape of what comes (plan Cuotas, section 5): tabs, chips and rows of a card - still with «reduce motion». */
import { t } from "@/lib/i18n";
import { Bone } from "./ui";

/** A row as it will be: time and competition, two teams, three prices with their lines, the actions. */
export function RowSkeleton() {
  return (
    <li aria-hidden className="px-3 py-3 sm:px-4" data-testid="explorer-row-skeleton">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:gap-5">
        <div className="space-y-2 lg:w-60 lg:shrink-0">
          <div className="flex items-center gap-2">
            <Bone className="h-4 w-10" />
            <Bone className="h-3 w-28" />
          </div>
          <Bone className="h-4 w-36" />
          <Bone className="h-4 w-32" />
        </div>
        <div className="grid flex-1 grid-cols-3 gap-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="space-y-1">
              <Bone className="h-3 w-8" />
              <Bone className="h-11 w-full" />
              <Bone className="h-3 w-16" />
            </div>
          ))}
        </div>
        <div className="flex gap-2 lg:w-40 lg:flex-col">
          <Bone className="h-9 w-28" />
          <Bone className="h-9 w-24" />
        </div>
      </div>
    </li>
  );
}

/** The whole explorer before the families arrive. */
export function ExplorerSkeleton() {
  return (
    <div
      className="space-y-3"
      aria-busy="true"
      aria-label={t("common.loading")}
      data-testid="explorer-skeleton"
    >
      <div className="flex gap-1 overflow-hidden rounded-xl border border-border bg-card p-1">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Bone key={i} className="h-9 w-24 shrink-0" />
        ))}
      </div>
      <div className="flex gap-1.5 overflow-hidden py-1">
        {[0, 1, 2, 3].map((i) => (
          <Bone key={i} className="h-9 w-28 shrink-0 rounded-full" />
        ))}
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="space-y-2.5 border-b border-border/70 px-3 py-3 sm:px-4">
          <Bone className="h-5 w-48" />
          <Bone className="h-9 w-64 rounded-full" />
        </div>
        <ul className="divide-y divide-border/70">
          {[0, 1, 2, 3].map((i) => (
            <RowSkeleton key={i} />
          ))}
        </ul>
      </div>
    </div>
  );
}

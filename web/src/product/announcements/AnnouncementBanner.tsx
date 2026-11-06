/**
 * The owner's banners at the top of the page (closing plan 4.3): maintenance, incident, update or a general notice, between
 * the dates he chose, in the reader's language. In the page's flow under the header (never over the tab bar), closable
 * per reader, and silent while there is nothing to say or the notice cannot be read.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info, Megaphone, TriangleAlert, Wrench, X } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import type { AnnouncementKind } from "@/lib/api/v1/types_announcements";
import { t, useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { readClosed, rememberClosed, visibleNotices } from "./banner";

const ICON = {
  incident: TriangleAlert,
  maintenance: Wrench,
  update: Megaphone,
  general: Info,
} as const;
const TONE: Readonly<Record<AnnouncementKind, string>> = {
  incident: "border-negative/40 bg-negative-soft",
  maintenance: "border-gold/45 bg-gold-soft",
  update: "border-border bg-elevated/40",
  general: "border-border bg-elevated/40",
};

export function AnnouncementBanner() {
  const { locale } = useI18n();
  const q = useQuery(live.announcements);
  const [closed, setClosed] = useState<number[]>(() => readClosed());
  const shown = visibleNotices(q.data?.banners ?? [], closed, locale);
  if (shown.length === 0) return null;
  return (
    <div
      className="px-safe mx-auto mt-3 flex w-full max-w-6xl flex-col gap-2"
      data-testid="announcements"
    >
      {shown.map((n) => {
        const Icon = ICON[n.kind];
        return (
          <div
            key={n.id}
            role={n.kind === "incident" ? "alert" : "status"}
            data-testid="announcement"
            data-kind={n.kind}
            className={cn(
              "flex items-start gap-3 rounded-md border px-3 py-2 text-xs",
              TONE[n.kind],
            )}
          >
            <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1 space-y-0.5">
              <p className="font-semibold">{n.title}</p>
              <p className="whitespace-pre-line text-foreground/90">{n.body}</p>
            </div>
            <button
              type="button"
              data-testid="announcement-close"
              aria-label={t("notices.banner.close")}
              onClick={() => setClosed(rememberClosed(n.id, closed))}
              className="tap-y relative -m-1 rounded-md p-1 text-muted-foreground hover:text-foreground"
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

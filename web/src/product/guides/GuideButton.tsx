/**
 * The «?» in a screen's header (plan UX-052): shows the guide of the screen again, whenever the reader wants. Nothing is drawn
 * outside the provider, for the owner's account, with the guides off (FBI_GUIDES=0) or on a screen whose guide is not built.
 */
import { CircleHelp } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { GuideKey } from "@/lib/api/v1/types_guides";
import { t } from "@/lib/i18n";
import { useGuides } from "./context";
import { GUIDES, launchable } from "./registry";

export function GuideButton({ guide }: { guide: GuideKey }) {
  const guides = useGuides();
  const user = useAuth().user;
  if (!guides.available || !user || user.role !== "USER" || user.guides_on === false) return null;
  if (!launchable(GUIDES[guide])) return null;
  return (
    <button
      type="button"
      onClick={() => guides.start(guide, "replay")}
      aria-label={t("guides.help.label")}
      title={t("guides.help.label")}
      aria-haspopup="dialog"
      data-testid="guide-help"
      className="tap relative inline-flex h-9 w-9 items-center justify-center rounded-full border border-border text-muted-foreground hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:h-11 pointer-coarse:w-11"
    >
      <CircleHelp aria-hidden className="h-4 w-4" />
    </button>
  );
}

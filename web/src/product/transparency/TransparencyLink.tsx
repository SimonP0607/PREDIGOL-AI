/**
 * The way to «Cómo le va a PrediGol» (plan UX, A12) from a day without picks: shown only when the page is open to readers
 * (FBI_TRANSPARENCY, the `transparency` flag of /auth/me) - or to the owner, who reviews it first. Never a link to a page
 * that would answer «not published».
 */
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";

function useTransparencyOpen(): boolean {
  const auth = useAuth();
  return Boolean(auth.user?.transparency) || auth.showAdmin;
}

export function TransparencyLink({ className }: { className?: string | undefined }) {
  const open = useTransparencyOpen();
  if (!open) return null;
  return (
    <Link
      to="/transparency"
      data-testid="transparency-link"
      title={t("transparency.page.linkHint")}
      className={
        className ??
        "tap-y relative inline-flex min-h-9 items-center gap-0.5 text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      }
    >
      {t("transparency.page.link")}
      <ChevronRight aria-hidden className="h-3.5 w-3.5" />
    </Link>
  );
}

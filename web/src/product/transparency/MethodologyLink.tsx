import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { t } from "@/lib/i18n";

/** The way to Metodología (decision 10): the same texts, on a page of their own. */
export function MethodologyLink() {
  return (
    <Link
      to="/transparency/methodology"
      data-testid="to-methodology"
      className="tap-y relative inline-flex items-center gap-1 text-sm font-semibold text-primary underline-offset-4 hover:underline"
    >
      {t("transparency.methodology.link")}
      <ChevronRight aria-hidden className="h-3.5 w-3.5" />
    </Link>
  );
}

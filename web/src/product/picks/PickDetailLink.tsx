import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import { ASK_BUTTON } from "@/product/shared/Bits";

/** The way from a pick's card to its page (decision 3): beside «¿Por qué?» and «Explícame», the same size. */
export function PickDetailLink({
  pickId,
  className,
}: {
  pickId: number;
  className?: string | undefined;
}) {
  return (
    <Link
      to="/picks/$pickId"
      params={{ pickId: String(pickId) }}
      data-testid="pick-detail-link"
      className={cn(buttonVariants({ variant: "text", size: "sm" }), ASK_BUTTON, className)}
    >
      {t("picks.detail.open")}
      <ChevronRight aria-hidden />
    </Link>
  );
}

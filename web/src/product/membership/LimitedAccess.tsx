/**
 * What a limited account sees instead of a page of the product (plan UX, A8): its membership ended - after the 3 days
 * of grace -, the owner suspended it, or it was just registered and has no period yet (no trial at the door). Its data stays: the profile, the saved picks to read, the help, the legal
 * texts and the copy of its data are one tap away, with how to renew. The server refuses the rest (403).
 */
import { Link } from "@tanstack/react-router";
import { Download, FileText, LifeBuoy, ListChecks, UserRound } from "lucide-react";
import type { MembershipSummary } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { Card } from "@/product/shared/States";
import { PaymentRequestPanel } from "./PaymentRequestPanel";

const item =
  "tap-y relative flex min-h-11 items-center gap-3 rounded-md border border-border px-3 text-sm font-medium hover:bg-elevated";

export function LimitedAccess({ membership }: { membership: MembershipSummary }) {
  const kind =
    ({ suspended: "suspended", none: "none" } as Record<string, string>)[membership.state] ??
    "expired";
  return (
    <div data-testid="limited-access" data-state={membership.state}>
      <Card className="mx-auto max-w-xl space-y-4 p-6">
        <h1 className="font-display text-xl font-semibold">
          {t(`profile.membership.limited.${kind}Title`)}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t(`profile.membership.limited.${kind}Body`)}
        </p>
        {kind === "suspended" ? null : <PaymentRequestPanel state={membership.state} />}
        <nav className="grid gap-2" aria-label={t("profile.membership.title")}>
          <Link to="/profile" hash="membership" className={item} data-testid="limited-profile">
            <UserRound aria-hidden className="h-4 w-4 text-primary" />
            {t("profile.membership.limited.profile")}
          </Link>
          <Link to="/my-picks" className={item} data-testid="limited-my-picks">
            <ListChecks aria-hidden className="h-4 w-4 text-primary" />
            {t("profile.membership.limited.myPicks")}
          </Link>
          <Link to="/profile" hash="privacy" className={item} data-testid="limited-export">
            <Download aria-hidden className="h-4 w-4 text-primary" />
            {t("profile.membership.limited.export")}
          </Link>
          <Link to="/help" className={item} data-testid="limited-help">
            <LifeBuoy aria-hidden className="h-4 w-4 text-primary" />
            {t("profile.membership.limited.help")}
          </Link>
          <Link to="/legal/$doc" params={{ doc: "terms" }} className={item}>
            <FileText aria-hidden className="h-4 w-4 text-primary" />
            {t("profile.membership.limited.legal")}
          </Link>
        </nav>
      </Card>
    </div>
  );
}

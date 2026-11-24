/**
 * What a reader who chose «solo fútbol» or a pause sees at an address that IS a price, a pick or a parlay (plan PM, PM-14-07): one
 * sentence, the way to football, and the way to their choice. The server refuses the calls behind it on its own; this is the page.
 */
import { Link } from "@tanstack/react-router";
import { CalendarDays, UserRound } from "lucide-react";
import { t } from "@/lib/i18n";
import { Card } from "@/product/shared/States";

const item =
  "tap-y relative flex min-h-11 items-center gap-3 rounded-md border border-border px-3 text-sm font-medium hover:bg-elevated";

export function WellbeingPage() {
  return (
    <div data-testid="wellbeing-page">
      <Card className="mx-auto max-w-xl space-y-4 p-6">
        <h1 className="font-display text-xl font-semibold">{t("profile.wellbeing.pageTitle")}</h1>
        <p className="text-sm text-muted-foreground">{t("profile.wellbeing.pageBody")}</p>
        <nav className="grid gap-2" aria-label={t("profile.wellbeing.pageTitle")}>
          <Link to="/matches" className={item} data-testid="wellbeing-matches">
            <CalendarDays aria-hidden className="h-4 w-4 text-primary" />
            {t("profile.wellbeing.toMatches")}
          </Link>
          <Link to="/profile" className={item} data-testid="wellbeing-profile">
            <UserRound aria-hidden className="h-4 w-4 text-primary" />
            {t("profile.wellbeing.toChoice")}
          </Link>
        </nav>
      </Card>
    </div>
  );
}

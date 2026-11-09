import { createFileRoute } from "@tanstack/react-router";
import { OddsScreen } from "@/product/odds/OddsScreen";
import { validateOddsSearch, type OddsSearch } from "@/product/odds/oddsSearch";
import { titled } from "@/lib/i18n/head";

/** The explorer's family, market, line, filters and order live in the URL (plan Cuotas, UX-069); the old page reads none. */
export const Route = createFileRoute("/odds")({
  validateSearch: (search: Record<string, unknown>): OddsSearch => validateOddsSearch(search),
  head: titled("nav.odds"),
  component: OddsScreen,
});

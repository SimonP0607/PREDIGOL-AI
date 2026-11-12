import { createFileRoute } from "@tanstack/react-router";
import { OddsStatusPage } from "@/product/odds/OddsStatusPage";
import { titled } from "@/lib/i18n/head";

/** «Estado de los precios» (plan maestro UX/UI 2026, decision 4; sheet C05): shown only while FBI_ODDS_STATUS is on. */
export const Route = createFileRoute("/odds/status")({
  head: titled("odds.status.title"),
  component: OddsStatusPage,
});

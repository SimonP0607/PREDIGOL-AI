import { createFileRoute } from "@tanstack/react-router";
import { OddsPage } from "@/product/odds/OddsPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/odds")({
  head: titled("nav.odds"),
  component: OddsPage,
});

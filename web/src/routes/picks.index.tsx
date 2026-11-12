import { createFileRoute } from "@tanstack/react-router";
import { PicksPage } from "@/product/picks/PicksPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/picks/")({
  head: titled("nav.picks"),
  component: PicksPage,
});

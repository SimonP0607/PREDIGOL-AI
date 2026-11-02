import { createFileRoute } from "@tanstack/react-router";
import { MyPicksPage } from "@/product/records/MyPicksPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/my-picks")({
  head: titled("nav.myPicks"),
  component: MyPicksPage,
});

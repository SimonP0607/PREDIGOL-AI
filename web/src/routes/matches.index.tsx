import { createFileRoute } from "@tanstack/react-router";
import { MatchesPage } from "@/product/matches/MatchesPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/matches/")({
  head: titled("nav.matches"),
  component: MatchesPage,
});

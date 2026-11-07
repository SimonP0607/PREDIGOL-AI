import { createFileRoute } from "@tanstack/react-router";
import { MatchesPage } from "@/product/matches/MatchesPage";
import { parseMatchesSearch, type MatchesSearch } from "@/product/matches/viewState";
import { titled } from "@/lib/i18n/head";

/** The list's day and filters live in its URL (plan Partidos, P4): validated here, what cannot be read is dropped. */
export const Route = createFileRoute("/matches/")({
  validateSearch: (search: Record<string, unknown>): MatchesSearch => parseMatchesSearch(search),
  head: titled("nav.matches"),
  component: MatchesPage,
});

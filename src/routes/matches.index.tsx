import { createFileRoute } from "@tanstack/react-router";
import { MatchesPage } from "@/product/matches/MatchesPage";

export const Route = createFileRoute("/matches/")({
  head: () => ({ meta: [{ title: "PrediGol" }] }),
  component: MatchesPage,
});

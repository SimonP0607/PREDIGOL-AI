import { createFileRoute } from "@tanstack/react-router";
import { TeamsPage } from "@/product/teams/TeamsPage";
import { titled } from "@/lib/i18n/head";

/** «Equipos» (plan maestro unificado, UX-157; decision D-03): shown only while FBI_PROFILES is on. */
export const Route = createFileRoute("/teams/")({
  head: titled("profiles.teams.title"),
  component: TeamsPage,
});

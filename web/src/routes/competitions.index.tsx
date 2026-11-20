import { createFileRoute } from "@tanstack/react-router";
import { DirectoryPage } from "@/product/competitions/DirectoryPage";
import { titled } from "@/lib/i18n/head";

/** The world directory of competitions (plan PM, PM-09-05; UX-179; lámina I08): shown only while FBI_COMPETITION_DIRECTORY is on. */
export const Route = createFileRoute("/competitions/")({
  head: titled("profiles.competitionsTitle"),
  component: DirectoryPage,
});

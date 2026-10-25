import { createFileRoute } from "@tanstack/react-router";
import { GlossaryPage } from "@/product/help/GlossaryPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/help/glossary")({
  head: titled("glossary.page.title"),
  component: GlossaryPage,
});

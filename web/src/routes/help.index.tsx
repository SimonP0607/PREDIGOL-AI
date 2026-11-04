import { createFileRoute } from "@tanstack/react-router";
import { HelpPage } from "@/product/help/HelpPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/help/")({
  head: titled("support.help.pageTitle"),
  component: HelpPage,
});

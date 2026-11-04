import { createFileRoute } from "@tanstack/react-router";
import { UpdatesPage } from "@/product/updates/UpdatesPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/updates")({
  head: titled("support.updates.title"),
  component: UpdatesPage,
});

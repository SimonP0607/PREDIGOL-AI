import { createFileRoute } from "@tanstack/react-router";
import { TransparencyPage } from "@/product/transparency/TransparencyPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/transparency")({
  head: titled("transparency.page.title"),
  component: TransparencyPage,
});

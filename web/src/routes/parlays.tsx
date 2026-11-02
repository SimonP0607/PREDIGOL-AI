import { createFileRoute } from "@tanstack/react-router";
import { ParlaysPage } from "@/product/parlays/ParlaysPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/parlays")({
  head: titled("nav.parlays"),
  component: ParlaysPage,
});

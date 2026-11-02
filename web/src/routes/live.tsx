import { createFileRoute } from "@tanstack/react-router";
import { LivePage } from "@/product/live/LivePage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/live")({
  head: titled("nav.live"),
  component: LivePage,
});

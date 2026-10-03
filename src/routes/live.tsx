import { createFileRoute } from "@tanstack/react-router";
import { LivePage } from "@/product/live/LivePage";

export const Route = createFileRoute("/live")({
  head: () => ({ meta: [{ title: "PrediGol" }] }),
  component: LivePage,
});

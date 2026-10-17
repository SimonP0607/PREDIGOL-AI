import { createFileRoute } from "@tanstack/react-router";
import { PicksPage } from "@/product/picks/PicksPage";

export const Route = createFileRoute("/picks")({
  head: () => ({ meta: [{ title: "PrediGol" }] }),
  component: PicksPage,
});

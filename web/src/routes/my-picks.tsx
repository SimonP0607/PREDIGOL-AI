import { createFileRoute } from "@tanstack/react-router";
import { MyPicksPage } from "@/product/records/MyPicksPage";

export const Route = createFileRoute("/my-picks")({
  head: () => ({ meta: [{ title: "PrediGol" }] }),
  component: MyPicksPage,
});

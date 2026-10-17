import { createFileRoute } from "@tanstack/react-router";
import { OddsPage } from "@/product/odds/OddsPage";

export const Route = createFileRoute("/odds")({
  head: () => ({ meta: [{ title: "PrediGol" }] }),
  component: OddsPage,
});

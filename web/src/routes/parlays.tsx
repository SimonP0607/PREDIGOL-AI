import { createFileRoute } from "@tanstack/react-router";
import { ParlaysPage } from "@/product/parlays/ParlaysPage";

export const Route = createFileRoute("/parlays")({
  head: () => ({ meta: [{ title: "PrediGol" }] }),
  component: ParlaysPage,
});

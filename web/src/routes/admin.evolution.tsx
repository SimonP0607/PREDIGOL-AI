import { createFileRoute } from "@tanstack/react-router";
import { EvolutionLive } from "@/live/EvolutionLive";

export const Route = createFileRoute("/admin/evolution")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: EvolutionLive,
});

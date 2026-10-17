import { createFileRoute } from "@tanstack/react-router";
import { AiLayerLive } from "@/live/AiLayerLive";

export const Route = createFileRoute("/admin/ai-layer")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: AiLayerLive,
});

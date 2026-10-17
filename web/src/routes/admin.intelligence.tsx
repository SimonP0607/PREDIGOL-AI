import { createFileRoute } from "@tanstack/react-router";
import { IntelligenceLive } from "@/live/IntelligenceLive";

export const Route = createFileRoute("/admin/intelligence")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: IntelligenceLive,
});

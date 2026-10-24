import { createFileRoute } from "@tanstack/react-router";
import { LegacyRedirect } from "@/live/AdminAiRedirect";

// Plan F13: the AI pages of the Admin Console are Operación and Aprendizaje now; the old address opens the tab that has what the page had.
export const Route = createFileRoute("/admin/ai-layer")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: Page,
});

function Page() {
  return <LegacyRedirect page="ai-layer" />;
}

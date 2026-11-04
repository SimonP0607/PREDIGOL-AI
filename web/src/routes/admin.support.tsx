import { createFileRoute } from "@tanstack/react-router";
import { SupportPage } from "@/admin/SupportPage";

export const Route = createFileRoute("/admin/support")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: SupportPage,
});

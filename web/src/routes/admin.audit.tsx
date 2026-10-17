import { createFileRoute } from "@tanstack/react-router";
import { AuditPage } from "@/admin/AuditPage";

export const Route = createFileRoute("/admin/audit")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: AuditPage,
});

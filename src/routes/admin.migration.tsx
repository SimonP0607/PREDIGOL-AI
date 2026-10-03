import { createFileRoute } from "@tanstack/react-router";
import { MigrationPage } from "@/admin/MigrationPage";

export const Route = createFileRoute("/admin/migration")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: MigrationPage,
});

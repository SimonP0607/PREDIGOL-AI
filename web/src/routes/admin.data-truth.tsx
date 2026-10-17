import { createFileRoute } from "@tanstack/react-router";
import { DataTruthPage } from "@/admin/DataTruthPage";

export const Route = createFileRoute("/admin/data-truth")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: DataTruthPage,
});

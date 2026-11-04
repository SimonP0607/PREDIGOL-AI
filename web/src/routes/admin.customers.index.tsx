import { createFileRoute } from "@tanstack/react-router";
import { CustomersPage } from "@/admin/CustomersPage";

export const Route = createFileRoute("/admin/customers/")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: CustomersPage,
});

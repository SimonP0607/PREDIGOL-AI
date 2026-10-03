import { createFileRoute } from "@tanstack/react-router";
import { UsersPage } from "@/admin/UsersPage";

export const Route = createFileRoute("/admin/users")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: UsersPage,
});

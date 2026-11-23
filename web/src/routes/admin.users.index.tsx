import { createFileRoute } from "@tanstack/react-router";
import { UsersPage } from "@/admin/UsersPage";

export const Route = createFileRoute("/admin/users/")({
  // `view` abre una de las vistas de clientes (AP-A03); `membership=due` es el aviso de la mañana del dueño.
  validateSearch: (raw: Record<string, unknown>): { view?: string; membership?: string } => ({
    ...(typeof raw["view"] === "string" ? { view: raw["view"] } : {}),
    ...(typeof raw["membership"] === "string" ? { membership: raw["membership"] } : {}),
  }),
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: UsersPage,
});

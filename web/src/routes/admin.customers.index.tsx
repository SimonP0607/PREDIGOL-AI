import { createFileRoute, redirect } from "@tanstack/react-router";

/** «Clientes» ya no es una pantalla aparte (AP-A03): sus vistas viven en «Usuarios». El enlace guardado sigue valiendo. */
export const Route = createFileRoute("/admin/customers/")({
  beforeLoad: () => {
    throw redirect({ to: "/admin/users", replace: true });
  },
});

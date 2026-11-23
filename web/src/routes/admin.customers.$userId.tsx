import { createFileRoute, redirect } from "@tanstack/react-router";

/** La ficha del cliente es la ficha del usuario (AP-A03): el enlace guardado sigue valiendo. */
export const Route = createFileRoute("/admin/customers/$userId")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/admin/users/$userId",
      params: { userId: params.userId },
      replace: true,
    });
  },
});

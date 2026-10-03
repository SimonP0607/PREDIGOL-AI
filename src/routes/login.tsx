import { createFileRoute } from "@tanstack/react-router";
import { LoginPage } from "@/product/auth/LoginPage";

export const Route = createFileRoute("/login")({
  validateSearch: (
    s: Record<string, unknown>,
  ): { next?: string | undefined; expired?: "1" | undefined } => ({
    next: typeof s["next"] === "string" ? s["next"] : undefined,
    expired: s["expired"] === "1" || s["expired"] === 1 ? "1" : undefined,
  }),
  head: () => ({ meta: [{ title: "PrediGol — Iniciar sesión" }] }),
  component: LoginRoute,
});

function LoginRoute() {
  const search = Route.useSearch();
  return <LoginPage expired={search.expired === "1"} />;
}

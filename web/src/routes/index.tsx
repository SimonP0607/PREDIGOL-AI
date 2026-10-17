import { createFileRoute, redirect } from "@tanstack/react-router";

/** The product starts at /home; signing in is decided client-side by the auth gate. */
export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/home" });
  },
});

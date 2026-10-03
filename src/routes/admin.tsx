import { Outlet, createFileRoute } from "@tanstack/react-router";

/** /admin/*: the Admin Console. The shell and the SUPER_ADMIN gate are applied in __root. */
export const Route = createFileRoute("/admin")({
  component: () => <Outlet />,
});

import { createFileRoute } from "@tanstack/react-router";
import { UserFile } from "@/admin/UserFile";

export const Route = createFileRoute("/admin/users/$userId")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: Page,
});

function Page() {
  const { userId } = Route.useParams();
  const id = Number(userId);
  return Number.isInteger(id) && id > 0 ? <UserFile userId={id} /> : null;
}

import { createFileRoute } from "@tanstack/react-router";
import { CustomerCard } from "@/admin/CustomerCard";

export const Route = createFileRoute("/admin/customers/$userId")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: Page,
});

function Page() {
  const { userId } = Route.useParams();
  const id = Number(userId);
  return Number.isInteger(id) && id > 0 ? <CustomerCard userId={id} /> : null;
}

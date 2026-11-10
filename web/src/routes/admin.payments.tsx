import { createFileRoute } from "@tanstack/react-router";
import { PaymentQueuePage } from "@/admin/PaymentQueuePage";

export const Route = createFileRoute("/admin/payments")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: PaymentQueuePage,
});

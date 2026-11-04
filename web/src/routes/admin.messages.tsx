import { createFileRoute } from "@tanstack/react-router";
import { MessagesPage } from "@/admin/MessagesPage";

export const Route = createFileRoute("/admin/messages")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: MessagesPage,
});

import { createFileRoute } from "@tanstack/react-router";
import { InboxPage } from "@/product/push/InboxPage";
import { titled } from "@/lib/i18n/head";

/** «Avisos», the reader's inbox (plan maestro UX/UI 2026, decision 1; sheet I05): shown only while FBI_INBOX is on. */
export const Route = createFileRoute("/inbox")({
  head: titled("push.inbox.title"),
  component: InboxPage,
});

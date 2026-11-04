import { createFileRoute } from "@tanstack/react-router";
import { UnsubscribePage } from "@/product/auth/UnsubscribePage";
import { titled } from "@/lib/i18n/head";

/** Plan UX, B8: public, for any visitor; the link's token travels in the fragment, never to the server. */
export const Route = createFileRoute("/unsubscribe")({
  head: titled("auth.account.unsubscribeTitle"),
  component: UnsubscribePage,
});

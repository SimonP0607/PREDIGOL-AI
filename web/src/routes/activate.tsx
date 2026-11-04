import { createFileRoute } from "@tanstack/react-router";
import { ActivatePage } from "@/product/auth/ActivatePage";
import { titled } from "@/lib/i18n/head";

/** Plan UX, A7: public, for any visitor; the link's token travels in the fragment, never to the server. */
export const Route = createFileRoute("/activate")({
  head: titled("auth.account.activateTitle"),
  component: ActivatePage,
});

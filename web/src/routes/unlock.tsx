import { createFileRoute } from "@tanstack/react-router";
import { UnlockPage } from "@/product/auth/UnlockPage";
import { titled } from "@/lib/i18n/head";

/** Plan UX, A7: public, for any visitor; the link's token travels in the fragment, never to the server. */
export const Route = createFileRoute("/unlock")({
  head: titled("auth.account.unlockTitle"),
  component: UnlockPage,
});

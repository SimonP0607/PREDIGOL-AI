import { createFileRoute } from "@tanstack/react-router";
import { ResetPasswordPage } from "@/product/auth/ResetPasswordPage";
import { titled } from "@/lib/i18n/head";

/** Plan UX, A7: public, for any visitor; the link's token travels in the fragment, never to the server. */
export const Route = createFileRoute("/reset-password")({
  head: titled("auth.account.resetTitle"),
  component: ResetPasswordPage,
});

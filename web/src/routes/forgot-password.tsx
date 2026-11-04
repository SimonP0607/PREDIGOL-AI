import { createFileRoute } from "@tanstack/react-router";
import { ForgotPasswordPage } from "@/product/auth/ForgotPasswordPage";
import { titled } from "@/lib/i18n/head";

/** Plan UX, A7: public, for any visitor; the link's token travels in the fragment, never to the server. */
export const Route = createFileRoute("/forgot-password")({
  head: titled("auth.account.forgotTitle"),
  component: ForgotPasswordPage,
});

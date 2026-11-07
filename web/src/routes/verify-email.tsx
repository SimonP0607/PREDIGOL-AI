import { createFileRoute } from "@tanstack/react-router";
import { VerifyEmailPage } from "@/product/auth/VerifyEmailPage";
import { titled } from "@/lib/i18n/head";

/** UX-038: public, for any visitor; the link's token travels in the fragment, never to the server. */
export const Route = createFileRoute("/verify-email")({
  head: titled("auth.verify.title"),
  component: VerifyEmailPage,
});

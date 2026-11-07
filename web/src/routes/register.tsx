import { createFileRoute } from "@tanstack/react-router";
import { RegisterPage } from "@/product/auth/RegisterPage";
import { titled } from "@/lib/i18n/head";

/** UX-038: public, for any visitor - and only while the API says the registration is open. */
export const Route = createFileRoute("/register")({
  head: titled("auth.signup.title"),
  component: RegisterPage,
});

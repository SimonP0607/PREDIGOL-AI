import { createFileRoute } from "@tanstack/react-router";
import { WelcomePage } from "@/product/welcome/WelcomePage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/welcome")({
  head: titled("onboarding.welcome.pageTitle"),
  component: WelcomePage,
});

import { createFileRoute } from "@tanstack/react-router";
import { HowItWorksPage } from "@/product/help/HowItWorksPage";
import { useTransparencyOpen } from "@/product/transparency/useTransparencyOpen";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/help/how-it-works")({
  head: titled("support.howItWorks.pageTitle"),
  component: HowItWorks,
});

function HowItWorks() {
  return <HowItWorksPage transparency={useTransparencyOpen()} />;
}

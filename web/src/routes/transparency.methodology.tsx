import { createFileRoute } from "@tanstack/react-router";
import { MethodologyPage } from "@/product/transparency/MethodologyPage";
import { titled } from "@/lib/i18n/head";

/** Metodología (plan maestro UX/UI 2026, decision 10; sheet T06): how a pick is decided, read and defined, on its own page. */
export const Route = createFileRoute("/transparency/methodology")({
  head: titled("transparency.methodology.title"),
  component: MethodologyPage,
});

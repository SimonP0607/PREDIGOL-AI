import { createFileRoute } from "@tanstack/react-router";
import { HomePage } from "@/product/home/HomePage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/home")({
  head: titled("nav.home"),
  component: HomePage,
});

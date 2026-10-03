import { createFileRoute } from "@tanstack/react-router";
import { HomePage } from "@/product/home/HomePage";

export const Route = createFileRoute("/home")({
  head: () => ({ meta: [{ title: "PrediGol" }] }),
  component: HomePage,
});

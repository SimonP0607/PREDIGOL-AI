import { createFileRoute } from "@tanstack/react-router";
import { ProductPage } from "@/admin/ProductPage";

export const Route = createFileRoute("/admin/product")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: ProductPage,
});

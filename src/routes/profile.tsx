import { createFileRoute } from "@tanstack/react-router";
import { ProfilePage } from "@/product/profile/ProfilePage";

export const Route = createFileRoute("/profile")({
  head: () => ({ meta: [{ title: "PrediGol" }] }),
  component: ProfilePage,
});

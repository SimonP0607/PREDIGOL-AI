import { createFileRoute } from "@tanstack/react-router";
import { ProfilePage } from "@/product/profile/ProfilePage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/profile")({
  head: titled("nav.profile"),
  component: ProfilePage,
});

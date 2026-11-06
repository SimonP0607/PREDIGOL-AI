import { createFileRoute } from "@tanstack/react-router";
import { AnnouncementsPage } from "@/admin/AnnouncementsPage";

export const Route = createFileRoute("/admin/announcements")({
  head: () => ({ meta: [{ title: "PrediGol · Admin" }] }),
  component: AnnouncementsPage,
});

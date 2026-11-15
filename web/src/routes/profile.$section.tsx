import { createFileRoute } from "@tanstack/react-router";
import { ProfileSectionPage } from "@/product/profile/ProfilePage";
import { titled } from "@/lib/i18n/head";

/** One section of the profile on its own screen (plan maestro UX/UI 2026, decision 7): /profile/privacy, /profile/security... */
export const Route = createFileRoute("/profile/$section")({
  head: titled("nav.profile"),
  component: Section,
});

function Section() {
  const { section } = Route.useParams();
  return <ProfileSectionPage section={section} />;
}

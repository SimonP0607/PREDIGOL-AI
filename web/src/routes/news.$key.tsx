import { createFileRoute } from "@tanstack/react-router";
import { StoryPage } from "@/product/news/StoryPage";
import { titled } from "@/lib/i18n/head";

/** One story (plan de correcciones UX, AP-N02; maqueta 09): shown only while FBI_NEWS_FEED and FBI_NEWS_V2 are on. */
export const Route = createFileRoute("/news/$key")({
  head: titled("nav.news"),
  component: Page,
});

function Page() {
  return <StoryPage storyKey={Route.useParams().key} />;
}

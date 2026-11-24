import { createFileRoute } from "@tanstack/react-router";
import { StoriesPage } from "@/product/news/StoriesPage";
import type { StoriesSearchParams } from "@/product/news/storiesSearch";
import { titled } from "@/lib/i18n/head";

/**
 * The Noticias section (plan maestro UX/UI 2026, decision 2; plan de correcciones UX, AP-N01 and AP-N03): shown only while
 * FBI_NEWS_FEED is on - as stories, with the search and its filters held in the address, while FBI_NEWS_V2 is on too. The
 * page checks the address (`parseStoriesSearch`), so the first visit's JS does not carry that code.
 */
export const Route = createFileRoute("/news/")({
  head: titled("nav.news"),
  component: Page,
});

function Page() {
  return <StoriesPage search={Route.useSearch() as StoriesSearchParams} />;
}

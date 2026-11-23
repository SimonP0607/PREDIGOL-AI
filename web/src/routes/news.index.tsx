import { createFileRoute } from "@tanstack/react-router";
import { NewsFeedPage } from "@/product/news/NewsFeedPage";
import { titled } from "@/lib/i18n/head";

/** The Noticias section (plan maestro UX/UI 2026, decision 2; sheets N01-N03): shown only while FBI_NEWS_FEED is on. */
export const Route = createFileRoute("/news/")({
  head: titled("nav.news"),
  component: NewsFeedPage,
});

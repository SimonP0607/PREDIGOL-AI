import { createFileRoute, notFound } from "@tanstack/react-router";
import { localeOfMatches, pageTitle } from "@/lib/i18n/head";
import { documentOfSlug } from "@/product/legal/links";
import { LegalPage } from "@/product/legal/LegalPage";

/** /legal/terms, /legal/privacy, /legal/responsible-gaming (plan UX, A4): public, before any account. */
export const Route = createFileRoute("/legal/$doc")({
  beforeLoad: ({ params }) => {
    if (!documentOfSlug(params.doc)) throw notFound();
  },
  head: ({ params, matches }) => {
    const document = documentOfSlug(params.doc);
    return {
      meta: [
        {
          title: document
            ? pageTitle(localeOfMatches(matches), `legal.doc.${document}`)
            : "PrediGol",
        },
      ],
    };
  },
  component: LegalRoute,
});

function LegalRoute() {
  const { doc } = Route.useParams();
  const document = documentOfSlug(doc);
  return document ? <LegalPage document={document} /> : null;
}

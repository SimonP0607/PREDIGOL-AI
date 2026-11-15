import { createFileRoute } from "@tanstack/react-router";
import { PickDetailPage } from "@/product/picks/PickDetailPage";
import { titled } from "@/lib/i18n/head";

/** The detail of a pick (plan maestro UX/UI 2026, decision 3; sheet K02): what «¿Por qué?» says, on a page of its own. */
export const Route = createFileRoute("/picks/$pickId")({
  head: titled("picks.detail.title"),
  component: PickDetail,
});

function PickDetail() {
  const { pickId } = Route.useParams();
  return <PickDetailPage pickId={pickId} />;
}

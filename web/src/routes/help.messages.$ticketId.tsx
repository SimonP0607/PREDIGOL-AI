import { createFileRoute } from "@tanstack/react-router";
import { TicketPage } from "@/product/help/TicketPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/help/messages/$ticketId")({
  head: titled("support.ticket.pageTitle"),
  component: TicketRoute,
});

function TicketRoute() {
  const { ticketId } = Route.useParams();
  return <TicketPage ticketId={Number(ticketId)} />;
}

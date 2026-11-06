import { useQuery } from "@tanstack/react-query";
import { MessageCircle } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { t } from "@/lib/i18n";
import { WhatsappLink } from "./WhatsappLink";

/**
 * «¿Sigue fallando? Escríbenos» under an error (closing plan 4.2): the WhatsApp chat with this error's reference in the
 * code. Only where the reader can already write to PrediGol (the same switch as «Reportar un problema»), and nothing
 * while the owner has not given the number.
 */
export function StillFailing({ requestId }: { requestId: string | null }) {
  const q = useQuery(live.supportContact);
  const digits = q.data?.whatsapp ?? null;
  if (!digits) return null;
  return (
    <WhatsappLink
      digits={digits}
      text={t("support.help.contact.stillFailingText")}
      requestId={requestId}
      testId="error-whatsapp"
      className="tap-y relative mt-0.5 inline-flex items-center gap-1.5 rounded-sm text-xs font-medium text-primary underline-offset-4 hover:underline"
    >
      <MessageCircle aria-hidden className="h-3.5 w-3.5" />
      {t("support.help.contact.stillFailing")}
    </WhatsappLink>
  );
}

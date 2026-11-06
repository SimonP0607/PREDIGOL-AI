/** How to renew (plan UX, A8): WhatsApp (P7 of the plan) and answering an e-mail, when the owner has given them. */
import { Mail, MessageCircle } from "lucide-react";
import type { RenewContact } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { WhatsappLink } from "@/product/support/WhatsappLink";

const link =
  "tap-y relative inline-flex min-h-9 items-center gap-2 rounded-md border border-border-strong px-3 text-sm font-medium hover:bg-elevated pointer-coarse:min-h-11";

export function RenewOptions({ contact }: { contact: RenewContact }) {
  if (!contact.whatsapp && !contact.email) {
    return (
      <p className="text-xs text-muted-foreground" data-testid="renew-none">
        {t("profile.membership.renewNone")}
      </p>
    );
  }
  return (
    <div className="flex flex-wrap gap-2" data-testid="renew-options">
      {contact.whatsapp ? (
        <WhatsappLink
          digits={contact.whatsapp}
          text={t("profile.membership.whatsappText")}
          className={link}
          testId="renew-whatsapp"
        >
          <MessageCircle aria-hidden className="h-4 w-4" />
          {t("profile.membership.renewWhatsapp")}
        </WhatsappLink>
      ) : null}
      {contact.email ? (
        <a href={`mailto:${contact.email}`} className={link} data-testid="renew-email">
          <Mail aria-hidden className="h-4 w-4" />
          {t("profile.membership.renewEmail")}
        </a>
      ) : null}
    </div>
  );
}

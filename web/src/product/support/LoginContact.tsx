/**
 * «¿No puedes entrar?» under the sign-in (plan UX, A14; section 32): the WhatsApp number and the reply address, read
 * from a public route, for whoever cannot sign in - the urgent «access» case. Nothing while the owner has given neither.
 */
import { useQuery } from "@tanstack/react-query";
import { Mail, MessageCircle } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { t } from "@/lib/i18n";
import { whatsappLink } from "@/product/membership/membership";

const link =
  "tap-y relative inline-flex min-h-9 items-center gap-1.5 text-xs font-medium text-primary underline-offset-2 hover:underline pointer-coarse:min-h-11";

export function LoginContact() {
  const q = useQuery(live.supportContact);
  const whatsapp = q.data?.whatsapp ?? null;
  const email = q.data?.email ?? null;
  if (!whatsapp && !email) return null;
  return (
    <div
      className="mt-3 flex flex-col items-center gap-0.5 text-center"
      data-testid="login-contact"
    >
      <p className="text-caption text-muted-foreground">{t("support.login.trouble")}</p>
      {whatsapp ? (
        <a
          href={whatsappLink(whatsapp, t("support.help.contact.whatsappText"))}
          target="_blank"
          rel="noopener noreferrer"
          className={link}
          data-testid="login-whatsapp"
        >
          <MessageCircle aria-hidden className="h-3.5 w-3.5" />
          {t("support.login.whatsapp")}
        </a>
      ) : null}
      {email ? (
        <a href={`mailto:${email}`} className={link} data-testid="login-email">
          <Mail aria-hidden className="h-3.5 w-3.5" />
          {t("support.login.email", { email })}
        </a>
      ) : null}
    </div>
  );
}

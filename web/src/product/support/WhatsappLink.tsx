/**
 * A link to the WhatsApp chat with the context code (closing plan 4.2): one component so that each place that offers
 * «Escríbenos» (Ayuda, Más, Perfil, renew, the sign-in, an error) writes the same message and never builds it by hand.
 */
import type { ReactNode } from "react";
import { useWhatsappHref } from "./whatsapp";

export function WhatsappLink({
  digits,
  text,
  requestId,
  className,
  testId,
  children,
}: {
  digits: string | null;
  /** The reader's first line; the code of where they were goes under it. */
  text: string;
  /** The reference of the error the reader is looking at, when there is one. */
  requestId?: string | null | undefined;
  className?: string | undefined;
  testId?: string | undefined;
  children: ReactNode;
}) {
  const href = useWhatsappHref(digits, text, requestId);
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
      data-testid={testId}
    >
      {children}
    </a>
  );
}

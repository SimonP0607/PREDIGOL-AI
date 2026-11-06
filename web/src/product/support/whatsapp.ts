/**
 * The WhatsApp chat of every «Escríbenos» (closing plan 4.2): the business number with a first line already written and,
 * under it, a short code of where the reader was - the web's version, the screen's path and, in an error, its reference.
 * The code says nothing about the person: no name, no address, no query string, no account, no pick (the same pieces a
 * ticket carries, built by the same function). The number comes from the server; nothing of it is in this code.
 */
import { useEffect, useState } from "react";
import { t } from "@/lib/i18n";
import { whatsappLink } from "@/product/membership/membership";
import { buildContext, type ContextOptions } from "./context";

/** «v1.4.2 · /matches/812 · ref a1b2c3»: only the pieces that exist. */
export function contextCode(options: ContextOptions = {}, context = buildContext(options)): string {
  return [
    context.web_version ? `v${context.web_version}` : null,
    context.route ?? null,
    context.request_id ? `ref ${context.request_id}` : null,
  ]
    .filter((part): part is string => part !== null)
    .join(" · ");
}

/** The first line the reader sends, then (on its own lines) the code, so that whoever answers knows where to look. */
export function messageWithCode(text: string, code: string): string {
  return code ? `${text}\n\n${t("support.whatsapp.code", { code })}` : text;
}

/** The chat's address on the client, with the code of this moment; the server's render has the line alone. */
export function useWhatsappHref(
  digits: string | null,
  text: string,
  requestId?: string | null,
): string | null {
  const [code, setCode] = useState("");
  // the screen the reader is on now (a page change re-renders what holds the link); the server's render has none
  const path = typeof window === "undefined" ? "" : window.location.pathname;
  useEffect(() => {
    setCode(contextCode({ requestId }));
  }, [path, requestId]);
  return digits ? whatsappLink(digits, messageWithCode(text, code)) : null;
}

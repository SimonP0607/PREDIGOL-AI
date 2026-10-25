/**
 * The language a page is served in (plan UX, A1, defect F08). On the server: the request's Accept-Language, so
 * <html lang>, the title and the description come in the reader's language instead of a fixed Spanish lang with an
 * English title. In the browser: the language the reader chose or the account's (remembered), else the browser's.
 */
import { createIsomorphicFn } from "@tanstack/react-start";
import { getRequestHeader } from "@tanstack/react-start/server";
import { browserLocale } from "./index";
import { localeFromAcceptLanguage } from "./negotiate";
import type { Locale } from "./catalogs";

export const requestLocale = createIsomorphicFn()
  .server((): Locale => localeFromAcceptLanguage(getRequestHeader("accept-language")))
  .client((): Locale => browserLocale());

/**
 * Plan F13: the five AI pages of the Admin Console are two (see adminAi.ts). An old address still works: its page sends the reader, as soon as it
 * opens, to the tab of Operación or Aprendizaje that has what the page had. It reads the hash from the window, where the browser keeps it: a
 * fragment never reaches the server. (A link that names a tab of the other of the two pages is moved by useStrayRedirect.)
 */
import { useEffect } from "react";
import { useNavigate } from "@tanstack/react-router";
import { legacyAddress, type LegacyPage } from "./adminAi";

/** The body of an old page of the Admin Console that talked about the AI: it shows nothing and goes to the place that has what the page had. */
export function LegacyRedirect({ page }: { page: LegacyPage }) {
  const navigate = useNavigate();
  useEffect(() => {
    const { to, hash } = legacyAddress(page, window.location.hash);
    void navigate({ to, hash, replace: true });
  }, [navigate, page]);
  return null;
}

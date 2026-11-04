/** Where the reader goes after the welcome (plan UX, A13): the page they asked for (a link they opened), else Inicio. */
export function afterWelcome(searchStr: string | undefined): string {
  const next = new URLSearchParams(searchStr ?? "").get("next");
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/welcome")
    ? next
    : "/home";
}

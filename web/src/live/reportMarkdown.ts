/**
 * A small Markdown reader for the reports the API writes (headings, lists, tables, bold,
 * italics, code and links) - into a tree React renders, never into HTML. A link is kept only
 * for http(s) addresses; anything else stays text.
 */

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "italic"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

export type Block =
  | { kind: "heading"; level: 1 | 2 | 3; inline: Inline[] }
  | { kind: "list"; items: Array<{ depth: number; inline: Inline[] }> }
  | { kind: "table"; header: Inline[][]; rows: Inline[][][] }
  | { kind: "para"; inline: Inline[] };

const TOKEN = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\)|`[^`]+`|\*[^*\s][^*]*\*)/g;

export function safeHref(href: string): string | null {
  return /^https?:\/\/[^\s"'<>]+$/i.test(href) ? href : null;
}

export function inline(text: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: "text", text: text.slice(last, at) });
    const tok = m[0];
    if (tok.startsWith("**")) out.push({ kind: "bold", text: tok.slice(2, -2) });
    else if (tok.startsWith("`")) out.push({ kind: "code", text: tok.slice(1, -1) });
    else if (tok.startsWith("[")) {
      const close = tok.indexOf("](");
      const label = tok.slice(1, close);
      const href = safeHref(tok.slice(close + 2, -1));
      out.push(href ? { kind: "link", text: label, href } : { kind: "text", text: label });
    } else out.push({ kind: "italic", text: tok.slice(1, -1) });
    last = at + tok.length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

function cells(row: string): string[] {
  return row
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

export function parse(md: string): Block[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push({ kind: "heading", level: h[1]!.length as 1 | 2 | 3, inline: inline(h[2]!) });
      i += 1;
      continue;
    }
    if (/^\s*\|/.test(line)) {
      const rows: string[] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i] ?? "")) {
        rows.push(lines[i]!);
        i += 1;
      }
      const body = rows.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r.replace(/\|/g, "|")));
      const [head, ...rest] = body;
      blocks.push({
        kind: "table",
        header: head ? cells(head).map(inline) : [],
        rows: rest.map((r) => cells(r).map(inline)),
      });
      continue;
    }
    if (/^\s*[*-]\s+/.test(line)) {
      const items: Array<{ depth: number; inline: Inline[] }> = [];
      while (i < lines.length && /^\s*[*-]\s+/.test(lines[i] ?? "")) {
        const l = lines[i]!;
        const depth = Math.min(3, Math.floor((l.length - l.trimStart().length) / 2));
        items.push({ depth, inline: inline(l.trimStart().replace(/^[*-]\s+/, "")) });
        i += 1;
      }
      blocks.push({ kind: "list", items });
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      (lines[i] ?? "").trim() &&
      !/^(#{1,3})\s/.test(lines[i]!) &&
      !/^\s*[|*-]/.test(lines[i]!)
    ) {
      para.push(lines[i]!.trim());
      i += 1;
    }
    if (para.length) blocks.push({ kind: "para", inline: inline(para.join(" ")) });
    else i += 1;
  }
  return blocks;
}

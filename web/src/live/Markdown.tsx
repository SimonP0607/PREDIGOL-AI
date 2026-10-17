/** Renders the API's report Markdown as React elements (``./reportMarkdown``) - never as HTML. */
import { Fragment } from "react";
import { cn } from "@/lib/utils";
import { parse, type Inline } from "./reportMarkdown";

function Inlines({ items }: { items: Inline[] }) {
  return (
    <>
      {items.map((x, i) => {
        switch (x.kind) {
          case "bold":
            return <strong key={i}>{x.text}</strong>;
          case "italic":
            return <em key={i}>{x.text}</em>;
          case "code":
            return (
              <code key={i} className="rounded bg-muted px-1 text-caption">
                {x.text}
              </code>
            );
          case "link":
            return (
              <a
                key={i}
                href={x.href}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="text-primary underline-offset-2 hover:underline"
              >
                {x.text}
              </a>
            );
          default:
            return <Fragment key={i}>{x.text}</Fragment>;
        }
      })}
    </>
  );
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const blocks = parse(text);
  return (
    <div className={cn("space-y-3 text-sm leading-relaxed", className)}>
      {blocks.map((b, i) => {
        if (b.kind === "heading") {
          const size = b.level === 1 ? "text-base" : b.level === 2 ? "text-sm" : "text-xs";
          return (
            <p
              key={i}
              role="heading"
              aria-level={b.level + 1}
              className={cn("font-semibold text-foreground", size, b.level < 3 && "pt-1")}
            >
              <Inlines items={b.inline} />
            </p>
          );
        }
        if (b.kind === "list") {
          return (
            <ul key={i} className="space-y-1">
              {b.items.map((it, j) => (
                <li
                  key={j}
                  className="flex gap-2 text-muted-foreground"
                  style={{ paddingLeft: `${it.depth * 1}rem` }}
                >
                  <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary/70" />
                  <span>
                    <Inlines items={it.inline} />
                  </span>
                </li>
              ))}
            </ul>
          );
        }
        if (b.kind === "table") {
          return (
            <div key={i} className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-caption">
                <thead className="bg-muted/50 text-left text-subtle-foreground">
                  <tr>
                    {b.header.map((h, j) => (
                      <th key={j} className="px-2 py-1.5 font-medium">
                        <Inlines items={h} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((r, j) => (
                    <tr key={j} className="border-t border-border align-top">
                      {r.map((c, k) => (
                        <td key={k} className="px-2 py-1.5 text-muted-foreground">
                          <Inlines items={c} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        return (
          <p key={i} className="text-muted-foreground">
            <Inlines items={b.inline} />
          </p>
        );
      })}
    </div>
  );
}

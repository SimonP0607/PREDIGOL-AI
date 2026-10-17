import { describe, expect, test } from "bun:test";
import { inline, parse, safeHref } from "./reportMarkdown";

describe("report markdown", () => {
  test("headings, lists, tables and paragraphs", () => {
    const blocks = parse(
      "# Title\n\nSome **bold** text\nand more.\n\n* one\n  * nested\n- two\n\n| A | B |\n|---|---:|\n| 1 | [x](https://a.b/c) |\n",
    );
    expect(blocks.map((b) => b.kind)).toEqual(["heading", "para", "list", "table"]);
    const list = blocks[2];
    expect(list?.kind === "list" && list.items.map((i) => i.depth)).toEqual([0, 1, 0]);
    const table = blocks[3];
    expect(table?.kind === "table" && table.rows.length).toBe(1);
    expect(table?.kind === "table" && table.rows[0]![1]![0]).toEqual({
      kind: "link",
      text: "x",
      href: "https://a.b/c",
    });
  });

  test("only http(s) links survive; everything else is text", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    const evil = inline("[click](javascript:alert(1))");
    expect(evil.some((x) => x.kind === "link")).toBe(false);
    expect(evil[0]).toEqual({ kind: "text", text: "click" });
    expect(inline("[x](https://ok.example/p)")).toEqual([
      { kind: "link", text: "x", href: "https://ok.example/p" },
    ]);
    expect(inline("a `code` and *it*")).toEqual([
      { kind: "text", text: "a " },
      { kind: "code", text: "code" },
      { kind: "text", text: " and " },
      { kind: "italic", text: "it" },
    ]);
  });
});

import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { ImageSlot } from "@/components/system/ImageSlot";
import { BallIcon, CardIcon, PenaltyIcon, SubstitutionIcon } from "./football";

describe("football's own icons", () => {
  test("on Lucide's grid: 24 px box, 2 px stroke, round ends, the current colour, hidden from a screen reader", () => {
    for (const Icon of [BallIcon, SubstitutionIcon, PenaltyIcon]) {
      const html = renderToStaticMarkup(<Icon className="h-6 w-6 text-primary" />);
      expect(html).toContain('viewBox="0 0 24 24"');
      expect(html).toContain('stroke="currentColor"');
      expect(html).toContain('stroke-width="2"');
      expect(html).toContain('stroke-linecap="round"');
      expect(html).toContain('aria-hidden="true"');
      // the size the page asks for wins over the 16 px it has when none is given
      expect(html).toContain("h-6 w-6");
      expect(html).not.toContain("h-4");
    }
    expect(
      new Set([BallIcon, SubstitutionIcon, PenaltyIcon].map((I) => renderToStaticMarkup(<I />)))
        .size,
    ).toBe(3);
  });

  test("the cards: a card's own yellow, red, and the second yellow that becomes red", () => {
    const yellow = renderToStaticMarkup(<CardIcon tone="yellow" />);
    const red = renderToStaticMarkup(<CardIcon tone="red" />);
    const second = renderToStaticMarkup(<CardIcon tone="second" />);
    expect(yellow).toContain("bg-card-yellow");
    expect(yellow).not.toContain("bg-negative");
    expect(red).toContain("bg-negative");
    expect(second).toContain("bg-card-yellow");
    expect(second).toContain("bg-negative");
    for (const html of [yellow, red, second]) expect(html).toContain('aria-hidden="true"');
  });
});

describe("the place of a picture", () => {
  test("without a picture it is the scene, with the picture's proportions already kept", () => {
    const html = renderToStaticMarkup(<ImageSlot ratio="empty" testId="slot" />);
    expect(html).toContain('data-image="scene"');
    expect(html).toContain("aspect-ratio:3 / 2");
    expect(html).not.toContain("<img");
  });

  test("with one: lighter formats first, lazy, decoded off the main path, and silent to a screen reader", () => {
    const html = renderToStaticMarkup(
      <ImageSlot
        ratio="scene"
        src="/img/a-01.jpg"
        sources={[
          { srcSet: "/img/a-01.avif", type: "image/avif" },
          { srcSet: "/img/a-01.webp", type: "image/webp" },
        ]}
        width={1600}
        height={1000}
      />,
    );
    expect(html).toContain('data-image="picture"');
    expect(html).toContain("aspect-ratio:16 / 10");
    expect(html.indexOf("image/avif")).toBeLessThan(html.indexOf("image/webp"));
    expect(html).toMatch(/<img[^>]*alt=""/);
    expect(html).toMatch(/<img[^>]*loading="lazy"/);
    expect(html).toMatch(/<img[^>]*decoding="async"/);
    expect(html).toMatch(/<img[^>]*width="1600"[^>]*height="1000"/);
  });

  test("only the picture that is a page's largest content loads at once", () => {
    expect(renderToStaticMarkup(<ImageSlot ratio="scene" src="/img/a-01.jpg" priority />)).toMatch(
      /<img[^>]*loading="eager"/,
    );
  });
});

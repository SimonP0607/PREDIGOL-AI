/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { waitText } from "./format";

describe("waitText", () => {
  test("a wait as a person reads it", () => {
    expect(waitText(null)).toBe("—");
    expect(waitText(0)).toBe("0 s");
    expect(waitText(42.4)).toBe("42 s");
    expect(waitText(60)).toBe("1 min");
    expect(waitText(75)).toBe("1 min 15 s");
    expect(waitText(3_600)).toBe("1 h");
    expect(waitText(7_260)).toBe("2 h 1 min");
    expect(waitText(-5)).toBe("0 s");
  });
});

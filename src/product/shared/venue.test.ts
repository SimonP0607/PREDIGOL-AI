import { describe, expect, it } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { venueFacts, venuePlace, venueSurface } from "./venue";

describe("venue", () => {
  it("reads the name and city as sent, and only the details the provider gave", () => {
    setLocale("es");
    expect(venuePlace({ id: null, name: "Estadio X", city: null })).toBe("Estadio X");
    expect(venuePlace({ id: 1, name: "Old Trafford", city: "Manchester" })).toBe(
      "Old Trafford, Manchester",
    );
    expect(venueFacts({ id: 1, name: "A", city: null })).toEqual([]);
    expect(venueFacts({ id: 1, name: "A", city: null, capacity: 40943, surface: "grass" })).toEqual(
      ["40.943 espectadores", "césped"],
    );
  });

  it("translates the provider's surface and keeps an unknown one as sent", () => {
    setLocale("en");
    expect(venueSurface("artificial turf")).toBe("artificial turf");
    expect(venueSurface("Artificial Turf")).toBe("artificial turf");
    setLocale("es");
    expect(venueSurface("Artificial turf")).toBe("césped artificial");
    expect(venueSurface("hybrid grass")).toBe("hybrid grass");
    expect(venueSurface(null)).toBeNull();
  });
});

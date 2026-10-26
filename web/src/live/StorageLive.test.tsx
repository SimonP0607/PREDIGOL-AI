/// <reference types="bun" />
/**
 * Almacenamiento (Admin Console): the host's storage report shown as it was measured - the disk and its level, what fills it largest first,
 * the projection, the copies (honest when nothing leaves the server), the last cleanup and the retention policy - in both languages, with no
 * control that deletes anything.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { StorageOverview, StorageReport } from "@/lib/api/v1/types_storage";
import { StorageView } from "./StorageLive";
import { bytes, daysText, levelTone, offsiteState, parts, retentionByTier } from "./storageModel";

afterEach(() => setLocale("es"));

const GIB = 1024 ** 3;
const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/\s+/g, " ");

const RETENTION: StorageOverview["retention"] = [
  { tier: "permanent", what: "picks_parlays_settlements", where: "postgres", keep: "forever" },
  { tier: "medium", what: "daily_dumps", where: "vps+r2", keep: "14_days_r2_locked" },
  { tier: "none", what: "orphan_volumes_test_restores", where: "vps", keep: "delete_after_review" },
];

function report(over: Partial<StorageReport> = {}): StorageReport {
  return {
    version: "storage-report-v1",
    measured_at: new Date(Date.now() - 3_600_000).toISOString(),
    host: "vmi",
    disk: {
      size_bytes: 200 * GIB,
      used_bytes: 124 * GIB,
      avail_bytes: 76 * GIB,
      pct: 62,
      level: "ok",
    },
    parts: {
      pgdata_bytes: 21 * GIB,
      raw_bytes: 2.5 * GIB,
      raw_files: 300_000,
      backups_bytes: 5 * GIB,
      backups_count: 4,
    },
    docker: {
      images_bytes: 16 * GIB,
      images_reclaimable_bytes: 3.5 * GIB,
      volumes_bytes: 59 * GIB,
      volumes_orphan_bytes: 54 * GIB,
      volumes_orphan_count: 5,
      build_cache_bytes: 17 * GIB,
      build_cache_reclaimable_bytes: 12 * GIB,
    },
    database: { bytes: 22 * GIB, top_tables: [{ name: "raw.odds_snapshots", bytes: 9 * GIB }] },
    backups: {
      latest: {
        name: "predigol-20261026T030000Z",
        at: new Date().toISOString(),
        bytes: 1.4 * GIB,
        sha256: "ab".repeat(32),
        offsite: null,
      },
      offsite_configured: false,
      restore_test: {
        dump: "predigol-20261026T030000Z",
        at: new Date().toISOString(),
        passed: true,
        seconds: 812,
      },
      keep_daily: 3,
      keep_weekly: 2,
    },
    cleanup: null,
    growth: {
      last_day: "2026-10-25",
      last_delta_bytes: 6 * GIB,
      median_delta_bytes: 300 * 1024 ** 2,
      anomaly: true,
      days: 15,
    },
    ...over,
  };
}

function overview(over: Partial<StorageOverview> = {}): StorageOverview {
  return {
    report: report(),
    level: "ok",
    stale: false,
    projection: {
      per_day_bytes: GIB,
      at: [
        { days: 30, used_bytes: 154 * GIB, pct: 77 },
        { days: 90, used_bytes: 214 * GIB, pct: 107 },
        { days: 365, used_bytes: 489 * GIB, pct: 244.5 },
      ],
      days_to: { "80": 36, "90": 56 },
    },
    retention: RETENTION.map((r) => ({ ...r })),
    ...over,
  };
}

describe("the arithmetic", () => {
  test("sizes are 1024-based and a missing size is a dash, not zero", () => {
    expect(bytes(1536)).toContain("1,5");
    expect(bytes(54 * GIB)).toContain("GB");
    expect(bytes(null)).toBe("—");
    expect(bytes(-2 * GIB).startsWith("−")).toBe(true);
  });

  test("what fills the disk comes largest first, and an unmeasured part is left out", () => {
    const rows = parts(report({ parts: { pgdata_bytes: 21 * GIB } }));
    expect(rows[0]!.key).toBe("dockerVolumes");
    expect(rows.map((r) => r.key)).not.toContain("raw");
    expect(rows.find((r) => r.key === "buildCache")!.reclaimable).toBe(12 * GIB);
  });

  test("levels, days and the off-site state", () => {
    expect(levelTone("critical")).toBe("negative");
    expect(levelTone("warning")).toBe("warning");
    expect(levelTone("ok")).toBe("positive");
    expect(daysText(0)).toBe("ya alcanzado");
    expect(daysText(null)).toBe("no se alcanza a este ritmo");
    expect(daysText(40)).toBe("40");
    expect(offsiteState(overview())).toBe("notConfigured");
    const sent = overview();
    sent.report!.backups.offsite_configured = true;
    expect(offsiteState(sent)).toBe("missing");
    sent.report!.backups.latest!.offsite = { verified_at: new Date().toISOString() };
    expect(offsiteState(sent)).toBe("ok");
    expect(offsiteState(overview({ report: report({ backups: {} }) }))).toBe("none");
  });

  test("the policy is grouped by tier in the backend's order", () => {
    expect(retentionByTier(overview()).map((g) => g.tier)).toEqual(["permanent", "medium", "none"]);
  });
});

describe("the page", () => {
  test("shows the disk, the parts, the anomaly, the projection, the copies and the policy", () => {
    const html = text(renderToStaticMarkup(<StorageView data={overview()} stale={false} />));
    expect(html).toContain("62 % · Bien");
    expect(html).toContain("Volúmenes huérfanos (5)");
    expect(html).toContain("Crecimiento anómalo");
    expect(html).toContain("En 30 días");
    expect(html).toContain("Días hasta el 90 %");
    expect(html).toContain("No configurada: todas las copias están en el mismo disco");
    expect(html).toContain("superada");
    expect(html).toContain("3 diarias y 2 semanales");
    expect(html).toContain("raw.odds_snapshots");
    expect(html).toContain("Aún no hay limpieza registrada.");
    expect(html).toContain("Picks, combinadas y liquidaciones");
    expect(html).toContain("Se borra tras revisarlo, con la palabra del dueño");
    expect(html).toContain("Esta página no borra nada");
    expect(html).toContain("489,0 GB (245 %)");
  });

  test("no report yet: says when it comes and still shows the policy", () => {
    const html = text(
      renderToStaticMarkup(
        <StorageView data={{ report: null, retention: RETENTION }} stale={false} />,
      ),
    );
    expect(html).toContain("Todavía no hay informe de almacenamiento");
    expect(html).toContain("Política de retención");
  });

  test("a stale report and a missing projection say so", () => {
    const html = text(
      renderToStaticMarkup(
        <StorageView
          data={overview({
            stale: true,
            projection: { per_day_bytes: null, at: [], days_to: { "80": null, "90": null } },
          })}
          stale
        />,
      ),
    );
    expect(html).toContain("más de 8 horas");
    expect(html).toContain("Hacen falta al menos 7 días");
  });

  test("nothing on the page deletes anything", () => {
    const html = renderToStaticMarkup(<StorageView data={overview()} stale={false} />);
    expect(html).not.toContain("<button");
    expect(html).not.toContain("<form");
  });

  test("English", () => {
    setLocale("en");
    const html = text(renderToStaticMarkup(<StorageView data={overview()} stale={false} />));
    expect(html).toContain("Orphan volumes (5)");
    expect(html).toContain("Not configured: every copy is on the same disk");
    expect(html).toContain("Retention policy");
  });
});

/** The «Almacenamiento» page's arithmetic and wording, kept apart from the page so that it can be tested on its own. */
import { t } from "@/lib/i18n";
import { localFixed } from "@/lib/i18n/format";
import type { StorageLevel, StorageOverview, StorageReport } from "@/lib/api/v1/types_storage";

/** 1024-based sizes, the way `df -h` and Docker's own tools are read on the server. */
export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  const sign = n < 0 ? "−" : "";
  let v = Math.abs(n);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${sign}${localFixed(v, i === 0 ? 0 : 1)} ${units[i]}`;
}

export type Tone = "default" | "positive" | "warning" | "negative";

export function levelTone(level: StorageLevel | undefined): Tone {
  if (level === "critical") return "negative";
  if (level === "high" || level === "warning") return "warning";
  return level === "ok" ? "positive" : "default";
}

export interface PartRow {
  key: string;
  label: string;
  bytes: number;
  reclaimable: number | null;
}

/** What fills the disk, largest first; a part the report did not measure is left out (never shown as zero). */
export function parts(r: StorageReport): PartRow[] {
  const p = r.parts;
  const d = r.docker;
  const rows: Array<PartRow | null> = [
    row("pgdata", t("storage.parts.pgdata"), p.pgdata_bytes),
    row("raw", t("storage.parts.raw"), p.raw_bytes),
    row("backups", t("storage.parts.backups"), p.backups_bytes),
    row("releases", t("storage.parts.releases"), p.releases_bytes),
    row("logs", t("storage.parts.logs"), p.logs_bytes),
    row(
      "dockerImages",
      t("storage.parts.dockerImages"),
      d.images_bytes,
      d.images_reclaimable_bytes,
    ),
    row("dockerVolumes", t("storage.parts.dockerVolumes"), d.volumes_bytes, d.volumes_orphan_bytes),
    row(
      "buildCache",
      t("storage.parts.buildCache"),
      d.build_cache_bytes,
      d.build_cache_reclaimable_bytes,
    ),
  ];
  return rows.filter((x): x is PartRow => x !== null).sort((a, b) => b.bytes - a.bytes);
}

function row(
  key: string,
  label: string,
  value: number | undefined,
  reclaimable?: number,
): PartRow | null {
  if (value === undefined || value === null) return null;
  return { key, label, bytes: value, reclaimable: reclaimable ?? null };
}

/** "45 days", "already reached" or "not reached at this pace". */
export function daysText(n: number | null | undefined): string {
  if (n === null || n === undefined) return t("storage.growth.never");
  if (n <= 0) return t("storage.growth.now");
  return String(n);
}

export type BackupState = "none" | "notConfigured" | "missing" | "ok";

/** Did the newest copy leave the server? Honest about a server that has no off-site copy at all. */
export function offsiteState(o: StorageOverview): BackupState {
  const b = o.report?.backups;
  if (!b?.latest) return "none";
  if (!b.offsite_configured) return "notConfigured";
  return b.latest.offsite?.verified_at ? "ok" : "missing";
}

/** The policy grouped by tier, in the order of the table the backend holds. */
export function retentionByTier(
  o: StorageOverview,
): Array<{ tier: string; rows: StorageOverview["retention"] }> {
  const out: Array<{ tier: string; rows: StorageOverview["retention"] }> = [];
  for (const r of o.retention) {
    const g = out.find((x) => x.tier === r.tier);
    if (g) g.rows.push(r);
    else out.push({ tier: r.tier, rows: [r] });
  }
  return out;
}

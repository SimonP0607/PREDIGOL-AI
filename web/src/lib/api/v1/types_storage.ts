/** GET /admin/storage: the host's storage report (bin/storage-report.sh), its projection and the retention policy. Reading only. */

export type StorageLevel = "ok" | "warning" | "high" | "critical";

export interface StorageTable {
  name: string;
  bytes: number;
}

export interface StorageBackup {
  name: string;
  at: string;
  bytes: number | null;
  sha256: string | null;
  offsite: { remote?: string; bytes?: number; verified_at?: string } | null;
}

export interface StorageReport {
  version: "storage-report-v1";
  measured_at: string;
  host: string;
  disk: {
    size_bytes: number;
    used_bytes: number;
    avail_bytes: number;
    pct: number;
    level: StorageLevel;
  };
  parts: {
    pgdata_bytes?: number;
    raw_bytes?: number;
    raw_files?: number;
    backups_bytes?: number;
    backups_count?: number;
    releases_bytes?: number;
    logs_bytes?: number;
  };
  docker: {
    images_bytes?: number;
    images_reclaimable_bytes?: number;
    images_count?: number;
    volumes_bytes?: number;
    volumes_orphan_bytes?: number;
    volumes_orphan_count?: number;
    build_cache_bytes?: number;
    build_cache_reclaimable_bytes?: number;
  };
  database: { bytes: number; top_tables: StorageTable[] };
  backups: {
    latest?: StorageBackup | null;
    last_offsite_at?: string | null;
    offsite_configured?: boolean;
    restore_test?: {
      dump: string | null;
      at: string | null;
      passed: boolean | null;
      seconds: number | null;
    } | null;
    keep_daily?: number;
    keep_weekly?: number;
  };
  cleanup: { at: string | null; freed_bytes: number | null; items: string[] } | null;
  growth: {
    last_day?: string;
    last_delta_bytes?: number | null;
    median_delta_bytes?: number | null;
    anomaly?: boolean;
    days?: number;
  };
}

export interface StorageProjection {
  per_day_bytes: number | null;
  at: Array<{ days: number; used_bytes: number; pct: number }>;
  days_to: { "80": number | null; "90": number | null };
}

export interface StorageRetentionRow {
  tier: string;
  what: string;
  where: string;
  keep: string;
}

export interface StorageHistoryRow {
  date: string;
  used_bytes: number;
  db_bytes?: number;
  raw_bytes?: number;
  docker_bytes?: number;
  backups_bytes?: number;
}

export interface StorageOverview {
  report: StorageReport | null;
  level?: StorageLevel;
  stale?: boolean;
  projection?: StorageProjection;
  parts_pace?: Record<string, number | null>;
  history?: StorageHistoryRow[];
  retention: StorageRetentionRow[];
}

# Legacy knowledge inputs

Three small Parquet files, byte-identical copies of the audited backups:

| File | Origin | Rows | Checksum in |
|---|---|---:|---|
| `competition_context.parquet` | `football-bot/archive/legacy-duckdb/2026-09-01/parquet/` | 81 | that folder's `MANIFEST.md` |
| `tracked_competitions.parquet` | `football-bot/archive/legacy-supabase/2026-09-02/tables/` | 77 | `checksums.sha256` |
| `ref_bookmakers.parquet` | `football-bot/archive/legacy-supabase/2026-09-02/tables/` | 32 | `checksums.sha256` |

They are the ONLY legacy data the platform reads, and they are read by exactly
one thing: `python -m scripts.manage_competitions import-legacy`, which writes
`migration_report.json` next to them.

Not here, by decision of the audit: calibration_registry, backtest_runs,
training_samples, the MatchContextScorer heuristics, OddsPredictor. None of
those is knowledge.

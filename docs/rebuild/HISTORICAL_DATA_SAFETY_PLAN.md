# Historical data safety plan — and the DATASET_V2 rebuild

*Data truth audit V2, 4 October 2026. The rule: the history we hold is evidence. It is never deleted,
never overwritten in place, never "fixed" by hand. A correction is a new fact with its provenance; a
rebuild is a new dataset version next to the old one.*

## 1. The rules this audit followed

| Rule | How |
|---|---|
| Backup before any change | Verified dump (1,033 TOC entries, sha256) + RAW tar + tags + count snapshot, and a **restore test** that restored all 91 tables in 91 s (`DATA_TRUTH_BASELINE_2026.md` §1) |
| RAW is evidence | The RAW store is content-addressed (file name = hash) and `raw.ingestion_payloads` is keyed by hash: an existing payload cannot be rewritten. Every audit request was stored as a **new** payload under its own ingestion run (`truth_v2_<kind>`); identical answers dedupe to the existing file |
| No silent UPDATE | The audit commands write only `audit.truth_v2_runs` and `audit.evidence_ledger` (and RAW). Corrections to stored data go through `audit.data_repairs` (rule, entity, before, after, reason, evidence) |
| Keep the old next to the new | Standings are snapshots (`snapshot_at`): a refresh adds a snapshot, never edits one. The only rows added to an *existing* snapshot were the rows the pre-0048 writer had dropped, taken from **the same provider payload** that snapshot was written from — each such season is a row in `audit.data_repairs` (`standings_dropped_tables`, before/after row counts) |
| No training while the data is in question | `data/research.frozen` — the weekly research run skips and `research_v2 --apply` refuses |

What the audit changed in stored data, all additive:

1. New snapshots of league tables (cups now refreshed; every current season re-read on 4 Oct).
2. Rows added to legacy snapshots from their own payloads (`audit.data_repairs`, rule
   `standings_dropped_tables`).
3. Match detail (events, line-ups, team and player rows) for current-season fixtures that never had
   any (queued by `seed_current_details`, fetched by the backfill) — rows that did not exist.
4. New RAW payloads (audit requests, one Football-Data CSV per golden season not stored before).

Nothing in `core.fixtures`, `core.fixture_results`, `market.*` or `features.*` was updated or deleted.

## 2. Labels for results computed before the audit

The research runs of 4 Oct (`RESEARCH_V2`, 2022–2024 seasons of the five big leagues) read results
and closing prices of exactly the seasons the golden validation checked (`DATA_TRUTH_AUDIT_V2.md`
§golden). The audit found **no error in those results**; the product-side bugs it fixed (player
"apps", team record scope, stale cup tables) were never model inputs. The earlier runs therefore keep
their labels (`LEGACY_RESEARCH_RUN`, `RESEARCH_V2`) and gain no new one; any run trained after the
audit closes on DATASET_V2 will carry `dataset_version` and supersede them — old runs are never
deleted or overwritten.

## 3. DATASET_V2 — the rebuild, step by step (not started: it needs the owner's go)

1. **Version table** — `analytics.dataset_versions` (version, built_at, code_version, rules,
   RAW inputs as payload hashes / run ids, row counts, content hash, status
   BUILDING / READY / SUPERSEDED / LEGACY). `DATASET_V1` = what exists today, frozen by the
   pre-audit backup and its hashes.
2. **Normalizers first, with tests** — store what the audit found dropped and useful
   (`DATA_TRUTH_AUDIT_V2.md` §fields): fixture referee, `teams.*.winner`, the fixture's
   `league.standings` flag, a player's match position, offsides, dribbled past, penalties won /
   conceded / saved. New columns only; their values come from RAW (no request).
3. **Replay from RAW into a scratch schema** — `dataset_v2.*` built by the replay that the dry-run
   already uses (`fbi.migration.dryrun._replay`), from the payloads indexed in `raw.ingestion_payloads`
   (every fixture's provenance is indexed: 225,753 of 225,753). Compare with `core` table by table:
   equal rows confirm; different rows become either explained provider corrections (newer payload)
   or `audit.data_repairs` candidates — reviewed, never bulk-applied.
4. **Golden dataset as the acceptance test** — the 21 golden competition-seasons must stay
   GOLDEN_VALIDATED on DATASET_V2 (provider list, final table, Football-Data results).
5. **Then, and only then** — features (`fv2.2` from DATASET_V2 only, `MODEL_READY` seasons), Elo,
   model datasets, predictions and backtests, each stamped with `dataset_version`; research unfrozen
   by the owner.

## 4. Current-season cadences (after the fixes)

| Dataset | Provider updates | PrediGol reads |
|---|---|---|
| Fixtures and results | every 15 s | daily season sync, results sweep every few hours, live follower every minute while tracked matches are played, stale-result repair by id |
| Match detail | every minute (live) | live follower in play; **current-season gaps seeded before every backfill tick** (new) |
| League tables | hourly | hourly after each finished match until the table changes (24 h max) + every 12 h for every current season **with a table — cups included** (new) |
| Injuries | every 4 h | every 4 h for seasons with a match in the next 48 h + every 12 h |
| Squads | several times a week | weekly round (current squads only) |
| Player profiles | several times a week | monthly sweep |
| Team statistics | twice a day | not ingested: computed from fixtures, per competition and season (audited against `/teams/statistics`) |
| Player season statistics | several times a week | computed from match rows (audited against `/players`) |
| Leagues / seasons | several times a day | daily catalogue refresh |

## 5. Re-running the audit

```
python -m scripts.audit_data_truth baseline
python -m scripts.audit_standings --external data/truth/external/external_standings_20261004.json
python -m scripts.audit_team_stats --history 80
python -m scripts.audit_player_stats --external data/truth/external/external_players_20261004.json
python -m scripts.audit_data_truth leagues | fixtures | identity | fields | golden | ledger
```

An entry the next run no longer reproduces is marked CLEARED (kept); one marked FIXED that comes back
is re-opened; ACCEPTED (an owner's decision) stays.

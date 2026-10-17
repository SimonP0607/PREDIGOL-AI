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
| Keep the old next to the new | Standings are snapshots (`snapshot_at`): a refresh adds a snapshot, never edits one. The only rows added to an *existing* snapshot were the rows the pre-0048 writer had dropped, taken from **the same provider payload** that snapshot was written from — **156 seasons**, each a row in `audit.data_repairs` (`standings_dropped_tables`, before/after row counts). Snapshots whose tables had **merged** under a repeated label were not edited: **16 seasons** got a NEW snapshot rebuilt from the same payload with the fixed parser, the damaged one kept (`standings_group_label_collision`, 616 → 669 rows) |
| No training while the data is in question | `data/research.frozen` — the weekly research run skips and `research_v2 --apply` refuses |
| A finished match's detail is never replaced silently (4 Oct 2026, migration 0061) | The detail tables (events, line-ups and their players, team and player statistics) hold the newest payload's view of a match. The restore test of `post-api-contract-v3` found `core.fixture_events` 11 rows shorter than its dump four minutes earlier: nine in-play lists replaced by the provider's newer list (RAW keeps every payload). The event and line-up lists are now written change-only, and for a FINISHED match the trigger `audit.keep_settled_detail` keeps every row a newer payload changes or removes, as it was and with its payload, in `audit.settled_detail_changes` (provenance-only updates and internal links are not changes). In-play replacements stay in RAW only. Test: `tests/integration/test_settled_details.py` |

What the audit changed in stored data, all additive:

1. New snapshots of league tables (cups now refreshed; every current season re-read on 4 Oct; 16 past seasons
   rebuilt beside their merged snapshots, rule `standings_group_label_collision`).
2. Rows added to legacy snapshots from their own payloads (`audit.data_repairs`, rule
   `standings_dropped_tables`, 156 seasons).
3. Match detail (events, line-ups, team and player rows) for current-season fixtures that never had
   any (queued by `seed_current_details`, fetched by the backfill) — rows that did not exist.
4. New RAW payloads (audit requests — 3,365 in 48 runs, 594 distinct payloads; the five 2025/26 Football-Data CSVs, read from a
   copy fetched where the network allowed it and stored with their origin).
5. The evidence ledger itself (`audit.truth_v2_runs`, `audit.evidence_ledger`, 417 entries).

`audit.data_repairs` at the close: `status_spelling` 79, `fixture_sides` 3, `standings_dropped_tables` 156,
`standings_group_label_collision` 16 — every one with before, after, reason and evidence.

Nothing in `core.fixtures`, `core.fixture_results`, `market.*` or `features.*` was updated or deleted.

## 2. Labels for results computed before the audit

The research runs of 4 Oct (`RESEARCH_V2`, 2022–2024 seasons of the five big leagues) read results and
closing prices that the golden validation re-checked for 2023 and 2024 (2022 was not re-checked): every result
equal to the provider's and to Football-Data's, the one difference being Union Berlin v Bochum (1-1 played, 0-2
awarded), where the models' 1-1 is the score bookmakers settled on. The product-side bugs the audit fixed (player
"apps", team record scope, stale cup tables, merged play-off tables) were never model inputs. The earlier runs
therefore keep their labels (`LEGACY_RESEARCH_RUN`, `RESEARCH_V2`) and gain no new one; any run trained after the
audit closes on DATASET_V2 will carry `dataset_version` and supersede them — old runs are never deleted or
overwritten.

## 3. DATASET_V2 — the rebuild, step by step (not started: it needs the owner's go)

1. **Version table** — `analytics.dataset_versions` (version, built_at, code_version, rules,
   RAW inputs as payload hashes / run ids, row counts, content hash, status
   BUILDING / READY / SUPERSEDED / LEGACY). `DATASET_V1` = what exists today, frozen by the
   pre-audit backup and its hashes.
2. **Normalizers first, with tests** — store what the audit found dropped and useful
   (`DATA_TRUTH_AUDIT_V2.md` §10): fixture referee, `teams.*.winner`, the fixture's
   `league.standings` flag, a player's match position, offsides, dribbled past, penalties won /
   conceded / saved, **the official score of an AWD/WO match**. New columns only; their values come from
   RAW (no request).
2b. **Result basis on every fixture** — `played` (the match ran its course), `stopped` (abandoned; the score is
   the one at the stop, which the provider may report as FT: four Colombian matches, Nantes v Toulouse) or
   `awarded` (the official result differs: AWD/WO, or an official decision in
   `config/truth/official_decisions.json` with its sources). Models train on `played` only; tables and history
   use the official result; bookmaker settlement keeps the provider's score.
2c. **Identity** — an alias table `(provider, provider_id) -> canonical id` for the 155 people and 2 team pairs the
   provider duplicates, each entry with its evidence; applied in reads. A fixture the provider moved to another
   competition (Kirin Cup) is re-homed through `audit.data_repairs`, never silently.
3. **Replay from RAW into a scratch schema** — `dataset_v2.*` built by the replay that the dry-run
   already uses (`fbi.migration.dryrun._replay`), from the payloads indexed in `raw.ingestion_payloads`
   (every fixture's provenance is indexed: 225,753 of 225,753). Compare with `core` table by table:
   equal rows confirm; different rows become either explained provider corrections (newer payload)
   or `audit.data_repairs` candidates — reviewed, never bulk-applied.
4. **Golden dataset as the acceptance test** — the 21 golden competition-seasons must stay at their
   audit verdicts on DATASET_V2 (20 GOLDEN_VALIDATED; Ligue 1 2025/26 NEEDS_REVIEW because of the provider's
   table, to be built from fixtures + the LFP decision): provider list, final table, Football-Data results,
   `python -m scripts.audit_data_truth golden --decisions config/truth/official_decisions.json`.
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
python -m scripts.audit_standings --external config/truth/external_standings_20261004.json \
                                  --decisions config/truth/official_decisions.json
python -m scripts.audit_standings --league 239 --season 2024 --decisions config/truth/official_decisions.json
python -m scripts.audit_team_stats --history 80
python -m scripts.audit_player_stats --external config/truth/external_players_20261004.json
python -m scripts.audit_data_truth golden --decisions config/truth/official_decisions.json
python -m scripts.audit_data_truth leagues | fixtures | identity | fields | ledger
python -m scripts.refresh_tables --relabel --dry-run      # snapshots merged by a repeated label (0 left)
```

An entry the next run no longer reproduces is marked CLEARED (kept); one marked FIXED that comes back
is re-opened; ACCEPTED (an owner's decision) stays.

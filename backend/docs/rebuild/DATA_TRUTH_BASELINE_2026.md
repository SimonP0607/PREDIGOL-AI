# Data truth baseline — 4 October 2026, before the audit touched anything

*Block A of the data truth audit V2 (`docs/rebuild/DATA_TRUTH_AUDIT_V2.md`). Taken read-only with
`python -m scripts.audit_data_truth baseline` at 14:02 UTC; report folder
`data/truth/20261004T140239Z-baseline/` on the machine. Nothing below was changed to produce it.*

## 1. Backup, before anything else

| Item | Value |
|---|---|
| Database dump | `~/backups/fbi-20261004T134632Z-pre-data-truth-audit-v2.dump` — 500,225,494 bytes, custom format, **1,033 TOC entries**, sha256 `45bdf2c974781e6dfbbff2a4bb22ab3be56d8fb251e32ecb4a8dbaa4dfd0357c` |
| RAW payload store | `~/backups/raw-20261004T134632Z-pre-data-truth-audit-v2.tar` — 683,192,320 bytes, 25,355 entries, sha256 `3df36180fc726b8267d428f3eccd38a838ff5c3dab0db28a1ba5145d91df7325` |
| Checksums file | `~/backups/SHA256SUMS-pre-data-truth-audit-v2` (re-verified `OK` before the restore test) |
| Git tags | `pre-data-truth-audit-v2` on backend `8c4a3d4` and frontend `5208c33`, pushed to the local bare repositories (never to GitHub) |
| Count snapshot | `data/baselines/20261004T134949Z-pre-data-truth-audit-v2` (`scripts.baseline_snapshot`) |
| **Restore test** | `pg_restore -j 2` of the dump into a scratch database `fbi_restore_v2audit` on the same server: **rc 0 in 91 s**; 91 tables compared with the live database: **65 equal, 26 grew since the dump (live capture kept writing), 0 fewer**; 38,344,550 rows restored; scratch database dropped, copy removed (`fbi_scratch/predigol/truth_restore.sh`, output `~/.fbi/truth_restore.out`) |
| Database size | 7,036 MB; disk free 946 GB (WSL), 421 GB (C:) |

## 2. Research frozen for the audit

`data/research.frozen` exists on the machine (text: *data truth audit V2 in progress …*). While it does,
`research_v2_weekly` skips and `scripts.research_v2 --apply` refuses (exit 3) — **no new model is
trained, stored or promoted** until the audit closes (`fbi.research.loop.frozen`, tests in
`tests/unit/test_research_freeze.py`). The daily shadow forecasts keep running with the existing
models; picks stay owner-only (0 qualified).

## 3. Every table, before the audit

| Table | Rows | From | To | Latest provider stamp | Latest PrediGol write |
|---|---:|---|---|---|---|
| `core.competitions` | 154 | - | - | - | 2026-10-03 18:39 |
| `core.competition_seasons` | 1,784 | 2008-06-07 | 2027-02-02 | 2026-10-04 07:23 (listed) | - |
| `core.fixtures` | 225,753 | 2015-03-12 | 2027-06-06 | 2026-10-04 14:01 | 2026-10-04 14:01 |
| `core.fixture_results` | 209,920 | 2015-03-12 | 2026-10-04 | 2026-10-04 13:56 | 2026-10-04 13:56 |
| `core.teams` | 8,165 | - | - | 2026-10-01 02:58 | 2026-10-04 14:01 |
| `core.venues` | 7,063 | - | - | 2026-10-01 02:58 | - |
| `core.players` | 179,298 | - | - | 2026-10-04 09:32 (profiles) | 2026-10-04 14:01 |
| `core.squad_members` | 62,476 | 2026-10-04 06:49 | 2026-10-04 10:27 | 2026-10-04 10:27 | 2026-10-04 10:27 |
| `core.coaches` | 11,515 | - | - | 2026-10-04 14:01 | 2026-10-04 14:01 |
| `core.standings` | 15,545 | 2026-09-29 04:39 | 2026-10-04 13:51 | 2026-10-04 00:00 | 2026-10-04 13:51 |
| `core.team_season_stats` (legacy) | **0** | - | - | - | - |
| `core.fixture_team_stats` | 346,478 | 2015-10-08 | 2026-10-04 | 2026-10-04 14:01 | 2026-10-04 14:01 |
| `core.fixture_player_stats` | 5,208,331 | 2016-11-13 | 2026-10-04 | 2026-10-04 14:01 | 2026-10-04 14:01 |
| `core.fixture_events` | 2,905,225 | 2015-03-12 | 2026-10-04 | 2026-10-04 14:01 | 2026-10-04 14:01 |
| `core.fixture_lineups` | 387,141 | 2015-03-12 | 2026-10-04 | 2026-10-04 14:01 | 2026-10-04 14:01 |
| `core.fixture_lineup_players` | 7,660,451 | 2015-03-12 | 2026-10-04 | - | - |
| `core.player_absences` | 183,440 | 2021-04-06 | 2026-10-21 | 2026-10-04 05:32 | 2026-10-04 05:32 |
| `market.odds_snapshots` | 120,799 | 2026-09-25 | 2026-10-04 | 2026-10-04 13:30 | 2026-10-04 13:30 |
| `market.final_prematch_odds` | 90,565 | 2026-09-28 | 2026-10-04 | 2026-10-04 09:05 | 2026-10-04 13:22 |
| `market.live_odds_snapshots` | 953,512 | 2026-10-01 | 2026-10-04 | 2026-10-04 14:02 | 2026-10-04 14:02 |
| `market.market_consensus` | 98,001 | 2026-09-25 | 2026-10-04 | - | 2026-10-04 13:30 |
| `market.historical_odds` (Football-Data) | 345,964 | 2022-08-05 | 2025-05-25 | - | - |
| `raw.ingestion_payloads` | 24,993 | - | - | 2026-10-04 14:02 | 2026-10-04 14:02 |

Other facts: fixtures by status — finished 209,925, scheduled 12,888, cancelled 2,520, postponed 404,
live 16; 124 tracked competitions of 154 (72 leagues), 154 current seasons; 453 national teams of
8,165; repairs before the audit: `status_spelling` 79, `fixture_sides` 3; historical validation:
209,219 HISTORICAL_APPROVED, 672 VALIDATED, 19 QUARANTINED, 5 INGESTED.

**Provenance**: every one of the 225,753 fixtures points at a payload indexed in
`raw.ingestion_payloads` (`source_payload_hash`, 0 without, 0 not indexed — query `q/prov.sql`), so
every fixture can be rebuilt from RAW.

## 4. Requests by endpoint (RAW index)

| Endpoint | Payloads | First | Last | Last 24 h |
|---|---:|---|---|---:|
| `/fixtures` | 13,504 | 2026-09-12 | 2026-10-04 | 1,181 |
| `/odds` | 1,125 | 2026-09-25 | 2026-10-04 | 807 |
| `/odds/live` | 2,730 | 2026-09-29 | 2026-10-04 | 1,847 |
| `/standings` | 788 | 2026-09-29 | 2026-10-04 | 34 |
| `/teams` | 1,095 | 2026-09-29 | 2026-10-04 | 95 |
| `/players/profiles` | 2,741 | 2026-10-04 | 2026-10-04 | 2,741 |
| `/players/squads` | 2,590 | 2026-10-04 | 2026-10-04 | 2,590 |
| `/injuries` | 261 | 2026-09-29 | 2026-10-04 | 6 |
| `/players` | 96 | 2026-10-04 | 2026-10-04 | 96 |
| `/coachs` | 39 | 2026-10-04 | 2026-10-04 | 39 |
| `/leagues` | 8 | 2026-09-12 | 2026-10-04 | 2 |
| `/odds/bookmakers` | 1 | 2026-10-04 | 2026-10-04 | 1 |
| Football-Data CSVs | 15 | 2026-09-24 | 2026-09-24 | 0 |

## 5. What the baseline already said

* The oldest standings snapshot is from **29 Sep 2026**: no table of a past season was kept from the
  provider before then — past seasons' tables were re-read during the audit (`--legacy`, below).
* `core.team_season_stats` is **empty**: `/teams/statistics` was never ingested; every team figure in
  the product is computed from fixtures (see `TEAM_DATA_VALIDATION.md`).
* Squads exist only from **4 Oct 2026 06:49** (the first weekly round): `captured_at` is the only
  time a squad has (the provider serves the *current* squad only).

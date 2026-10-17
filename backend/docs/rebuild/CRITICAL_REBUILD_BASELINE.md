# Critical rebuild — baseline (frozen before any change)

Taken 4 Oct 2026, 06:07–06:13 UTC, on the machine (`mila`). Everything below was read from
the live database, the files written, or the API as it served the pages at that moment.
Nothing in this document was changed by the rebuild; later documents compare against it.

## What was preserved

| Artefact | Where | Check |
|---|---|---|
| PostgreSQL dump (custom format) | `~/backups/fbi-20261004T060811Z-pre-critical-rebuild.dump` — 346,400,443 bytes, 848 TOC entries | sha256 `accd65bb…5f0d97` |
| RAW store archive | `~/backups/raw-20261004T060729Z-pre-critical-rebuild.tar` — 618,536,960 bytes, 18,065 entries (`data/raw`, 615 MB, 18,045 files) | sha256 `b375645e…ce58b79` |
| Checksums | `~/backups/SHA256SUMS-pre-critical-rebuild` | — |
| Git tag `pre-critical-rebuild` | backend `0ad5c59`, frontend `a8dad5a`; pushed to both local bare repositories | — |
| Every admin page and product endpoint as served (40 JSON files) + exact row counts of 67 tables | `data/baselines/20261004T061222Z-pre-critical-rebuild/` (`python -m scripts.baseline_snapshot`) | `manifest.json` |

A first `pg_dump` attempt (06:07) exited non-zero after writing 24 MB without printing an error.
It was **not** kept as a backup: it is renamed `…060729Z-pre-critical-rebuild.dump.INCOMPLETE-pg_dump-failed`
and the retry (06:08, exit 0, 31 s) is the baseline. The backup code checks the exit status for
exactly this reason.

## Counts (exact `count(*)`)

| Table | Rows | | Table | Rows |
|---|---:|---|---|---:|
| core.fixtures | 216,580 | | core.fixture_results | 201,776 |
| core.fixture_events | 2,902,223 | | core.fixture_lineups | 386,464 |
| core.fixture_lineup_players | 7,653,449 | | core.fixture_team_stats | 345,706 |
| core.fixture_player_stats | 5,204,720 | | core.fixture_detail_coverage | 805,752 |
| core.standings | 15,385 | | core.player_absences | 183,484 |
| core.players | 178,888 | | core.coaches | 11,403 |
| core.teams | 8,165 | | core.venues | 7,063 |
| core.competitions | 154 (124 tracked) | | core.competition_seasons | 1,454 |
| market.odds_snapshots (pre-match) | 92,509 | | market.live_odds_snapshots | 764,486 |
| market.historical_odds (football-data) | 345,964 | | market.market_consensus | 76,347 |
| features.fixture_features | 5,034,376 | | features.feature_sets | 118,910 |
| features.elo_ratings | 27,028 | | models.predictions | 257,097 |
| models.model_versions | 65 | | analytics.backtest_samples | 50,382 |
| picks.pick_candidates | 8,040 | | picks.picks | 1,512 |
| audit.data_quality_issues | 89,468 | | raw.ingestion_payloads | 17,782 |

Fixtures by status group: finished 201,781 · scheduled 12,706 · cancelled 1,691 · postponed 402.

## What the research pipeline says today

**Picks (shadow, never published):** 8,040 candidates · 6,528 rejected · 587 shadow pending ·
925 settled · **0 qualified** · 0 published.

**Shadow performance (settled at the captured price):** 923 settled picks, 920 units staked,
**−204.45 units, ROI −22.22 %, hit rate 30.44 %**.

**Models in the shadow pipeline (created 4 Oct 03:09):** Poisson (Maher) and Dixon-Coles trained on
**762** fixtures; Elo V2 + ordered logit on **6,764**. Neither has a stored walk-forward backtest, so
neither can qualify.

**Walk-forward backtest (session 1, 25 Sep, 5 leagues, test season 2024/25, 2,224 fixtures):**

| Model | Log loss | Brier | ECE | vs Pinnacle closing (Shin), Δ log loss [95 %] | Verdict |
|---|---:|---:|---:|---|---|
| League base rates | 1.0765 | 0.6518 | 0.0088 | +0.1192 [+0.1017, +0.1375], n = 1,751 | worse |
| Multinomial logit (features v2) | 0.9948 | 0.5937 | 0.0137 | +0.0245 [+0.0152, +0.0333], n = 1,684 | worse |

Hypothetical flat staking at the historical closing price: base rates −11.07 %, logit −5.34 %
(CI [−13.99 %, +3.50 %]). **No model beats the de-vigged market.**

**Elo:** 27,028 rating rows — about 13,500 rated matches out of 201,776 finished fixtures. The
Rankings page shows PSG, Barcelona and Inter last rated on 31 May 2025 / 25 May 2025 and Arsenal on
12 Sep 2026: the ratings were computed on 24 Sep from what existed then and never extended.

## Data quality (as the pages showed it)

| Signal | Value |
|---|---|
| Fixtures past kick-off without a result (high) | 85 |
| Upcoming fixtures with stale odds (high) | 71 |
| Open registry issues | 6 error · 16,430 warning · 68,408 info |
| Pre-match price rows, last 24 h | 34,999 |
| In-play price changes, last 24 h | 522,736 |
| Fixtures in the next 7 days | 552 |
| Provider requests today | 1,258 of a 60,000 guard (plan 75,000) |

## Tests at the baseline (last full run, backend `0ad5c59` / frontend `a8dad5a`)

ruff ✓ · mypy ✓ (387 files) · pytest **1,205 passed** · bun lint 0 errors · typecheck ✓ ·
81 unit tests ✓ · build ✓ · Playwright **41/41**.

## First signals checked while freezing (details in DATA_TRUTH_AUDIT.md)

* **78 cancelled fixtures and 1 abandoned one are classified as `scheduled`.** The provider sends the
  short status as `"Canc"`/`"Abd"` for some fixtures and `"CANC"`/`"ABD"` for others; our status-group
  map was case-sensitive, so `Canc` fell through to the default `scheduled`. Those 79 rows are most of the
  "85 fixtures past kick-off without a result".
* Player profiles are mostly empty (nationality and birth date unknown on the Players page): `/players`
  season profiles were never fetched by design (`API_DATA_PIPELINE_STATUS.md`).

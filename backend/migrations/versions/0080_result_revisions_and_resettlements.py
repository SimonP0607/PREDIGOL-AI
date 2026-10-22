"""A corrected result is a recorded revision, and what was settled on the old result is re-settled with a trail (plan F0, defect 5)

WHY THIS EXISTS
---------------
The result of a match reaches ``core.fixture_results`` from several writers (the date sweep, the live follow, the stale
results repair, the post-match detail reads at kick-off + 150 minutes and + 26 hours, a reprocess of the raw payloads) and
each one overwrites the row in place when its payload is newer (``ON CONFLICT DO UPDATE ... WHERE monotonic``). That is
right for the table - it holds the latest word of the provider - but it left two holes:

* a correction left no trace: the previous score was gone the moment the new one was written (the plan's section 4 lists
  "historial de correcciones de resultado" among what does not exist), and
* nothing looked at what had already been settled: the fast settlement runs on the FIRST read that says FT, before the
  re-reads that exist to catch corrections, and a settled pick, pick of the day, parlay or user pick is never revisited.

A score the provider fixes an hour after the final whistle (a goal given, a goal taken away) therefore left every record
settled on the wrong result, for ever, with nothing in the database saying so.

WHAT IS ADDED
-------------
``core.fixture_result_revisions``  the history of corrections. A trigger on ``core.fixture_results`` writes a row when a
    stored score changes (the score columns and the regulation score they derive; not the lineage columns), and a trigger
    on ``core.fixtures`` writes one when a match that had finished (FT, AET, PEN) changes status. It is the database that
    records them, so no writer can skip it. The functions are SECURITY DEFINER: a result write must never fail because
    the role that writes it cannot write the history. Rows are never edited; they go only with their fixture.
``picks.resettlements``  the trail of re-settlements: one row per record whose result changed, with the result and profit
    it had, the ones it has, the settlement version, the reason (the correction, or the audit) and the revision it
    answers. Nothing about the previous result is lost: the record shows the current result, this table the history. A
    parlay un-settled because the leg that lost it was corrected is a row too.
``picks.pick_events.event_kind``  ('status' as always, or 'resettlement'): the pick's own timeline shows the correction.
``picks.v_pick_record``  is replaced: ``status_before_settlement`` reads only status events (a re-settlement is a pick
    that stays settled, not a change of status) and a last column, ``resettlements``, counts the pick's corrections.

``fbi.picks.resettlement`` (settle-v4) reads these and re-settles; it never runs inside a migration and changes no row
here. The routine is idempotent, re-settles only what a score decided and the current score decides differently, and
reports (instead of guessing) any record the current state no longer settles.

Additive. The downgrade drops the history, the trail, the triggers and the column: export the two tables first if the
revision is being undone on a database that has had corrections.

Revision ID: 0080
Revises: 0079
"""

from __future__ import annotations

from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None

SCORE_COLUMNS = (
    "goals_home", "goals_away", "ht_goals_home", "ht_goals_away", "ft_goals_home", "ft_goals_away",
    "et_goals_home", "et_goals_away", "pen_home", "pen_away", "reg_goals_home", "reg_goals_away",
)
"""What a result is, for the history: the score at every stage the provider gives and the regulation score derived from
them (what 1X2, Over/Under, BTTS and handicaps settle on). The lineage columns and ``settled_at`` are not a result."""
FINISHED = "'FT', 'AET', 'PEN'"


def _state(alias: str) -> str:
    return "jsonb_build_object(" + ", ".join(f"'{c}', {alias}.{c}" for c in SCORE_COLUMNS) + ")"


def _pick_record_view(*, resettlements: bool) -> str:
    """``picks.v_pick_record`` as revision 0074 created it, or - with ``resettlements`` - as this revision replaces it."""
    status_only = " AND e.event_kind = 'status'" if resettlements else ""
    extra = (",\n               (SELECT count(*) FROM picks.resettlements x WHERE x.record_kind = 'pick' "
             "AND x.record_key = p.id::text) AS resettlements") if resettlements else ""
    return f"""
        CREATE VIEW picks.v_pick_record AS
        SELECT p.id AS pick_id, p.fixture_id, f.kickoff_at, p.market_key, p.selection, p.line,
               p.created_at, p.odds_captured_at AS price_taken_at, p.market_odds AS odds_taken, p.bookmaker_id,
               b.name AS bookmaker, p.p_calibrated AS p_model, p.p_market_fair AS p_market, p.fair_odds, p.edge,
               p.ev, p.model_version_id, m.name AS model, v.version AS model_version, p.calibrator_id,
               p.decision_rule_version, p.code_version, p.data_cutoff_ts, p.status,
               (SELECT e.from_status FROM picks.pick_events e
                 WHERE e.pick_id = p.id AND e.to_status = 'settled'{status_only} ORDER BY e.at LIMIT 1)
                   AS status_before_settlement,
               rv.decision AS ai_decision, rv.reviewed_at AS ai_reviewed_at, rv.engine_version AS ai_engine,
               rv.evidence_ids AS ai_evidence_ids,
               pr.result_status, pr.profit_units, pr.settled_at, pr.rule_version AS settlement_rule,
               pr.review_reason,
               lv.near_close_odds, lv.near_close_captured_at, lv.lv_raw AS line_value,
               lv.lv_devigged AS line_value_devigged, lv.is_validated_close{extra}
          FROM picks.picks p
          JOIN core.fixtures f ON f.id = p.fixture_id
          JOIN models.model_versions v ON v.id = p.model_version_id
          JOIN models.model_registry m ON m.id = v.model_id
          LEFT JOIN market.bookmakers b ON b.id = p.bookmaker_id
          LEFT JOIN picks.pick_results pr ON pr.pick_id = p.id
          LEFT JOIN picks.pick_line_value lv ON lv.pick_id = p.id
          LEFT JOIN LATERAL (
              SELECT r.decision, r.reviewed_at, r.engine_version, r.evidence_ids FROM ai.pick_reviews r
               WHERE r.fixture_id = p.fixture_id AND r.market_key = p.market_key AND r.selection = p.selection
                 AND r.line = p.line AND r.engine = 'combined' AND r.reviewed_at < f.kickoff_at
               ORDER BY r.reviewed_at DESC, r.id DESC LIMIT 1) rv ON true"""


VIEW_COMMENT = """COMMENT ON VIEW picks.v_pick_record IS
          'One pick''s whole record: what was decided before kick-off (frozen), the AI''s last pre-match review of the
           selection, the result and the line value against the last pre-match price.'"""


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The worker is stopped during the
    # migration; CREATE TRIGGER still takes a short lock on core.fixtures and core.fixture_results.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE FUNCTION core.refuse_history_update() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.history_maintenance', true), '') = 'on' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION '%.%: a history is never edited (UPDATE refused)', TG_TABLE_SCHEMA, TG_TABLE_NAME
                USING ERRCODE = 'check_violation';
        END
        $fn$""")
    op.execute("""
        CREATE TABLE core.fixture_result_revisions (
            id                  BIGSERIAL   PRIMARY KEY,
            fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            kind                TEXT        NOT NULL CHECK (kind IN ('score', 'status')),
            observed_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            old_state           JSONB       NOT NULL,
            new_state           JSONB       NOT NULL,
            changed             TEXT[]      NOT NULL CHECK (cardinality(changed) > 0),
            before_payload_hash TEXT,
            after_payload_hash  TEXT,
            after_fetched_at    TIMESTAMPTZ,
            CHECK (old_state <> new_state)
        )""")
    op.execute("CREATE INDEX fixture_result_revisions_fixture ON core.fixture_result_revisions (fixture_id, observed_at)")
    op.execute("CREATE INDEX fixture_result_revisions_observed ON core.fixture_result_revisions (observed_at DESC)")
    op.execute("""
        COMMENT ON TABLE core.fixture_result_revisions IS
        'Every correction of a result after it was first stored: the score columns before and after (kind score), or the
         status of a match that had finished (kind status), written by a trigger so that no writer can skip it. The first
         read of a result is not a revision. Nothing is edited; rows go only with their fixture. History before revision
         0080 was not recorded (a correction overwrote the previous score). fbi.picks.resettlement reads this table to
         know which matches to re-check (plan F0, defect 5).'""")
    op.execute(f"""
        CREATE FUNCTION core.log_result_revision() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $fn$
        DECLARE
            o jsonb := {_state("OLD")};
            n jsonb := {_state("NEW")};
            diff text[];
        BEGIN
            IF o = n THEN
                RETURN NULL;
            END IF;
            SELECT array_agg(k ORDER BY k) INTO diff FROM jsonb_object_keys(n) AS k WHERE n -> k IS DISTINCT FROM o -> k;
            INSERT INTO core.fixture_result_revisions
                   (fixture_id, kind, old_state, new_state, changed, before_payload_hash, after_payload_hash, after_fetched_at)
            VALUES (NEW.fixture_id, 'score', o, n, diff, OLD.source_payload_hash, NEW.source_payload_hash,
                    NEW.source_fetched_at);
            RETURN NULL;
        END
        $fn$""")
    op.execute("CREATE TRIGGER fixture_results_revision AFTER UPDATE ON core.fixture_results "
               "FOR EACH ROW EXECUTE FUNCTION core.log_result_revision()")
    op.execute("""
        CREATE FUNCTION core.log_status_revision() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $fn$
        BEGIN
            INSERT INTO core.fixture_result_revisions
                   (fixture_id, kind, old_state, new_state, changed, before_payload_hash, after_payload_hash, after_fetched_at)
            VALUES (NEW.id, 'status',
                    jsonb_build_object('status_short', OLD.status_short, 'status_group', OLD.status_group),
                    jsonb_build_object('status_short', NEW.status_short, 'status_group', NEW.status_group),
                    ARRAY['status_short'], OLD.source_payload_hash, NEW.source_payload_hash, NEW.source_fetched_at);
            RETURN NULL;
        END
        $fn$""")
    op.execute(f"""
        CREATE TRIGGER fixtures_status_revision AFTER UPDATE OF status_short ON core.fixtures
        FOR EACH ROW WHEN (OLD.status_short IN ({FINISHED}) AND NEW.status_short IS DISTINCT FROM OLD.status_short)
        EXECUTE FUNCTION core.log_status_revision()""")
    op.execute("CREATE TRIGGER fixture_result_revisions_no_update BEFORE UPDATE ON core.fixture_result_revisions "
               "FOR EACH ROW EXECUTE FUNCTION core.refuse_history_update()")

    op.execute("""
        CREATE TABLE picks.resettlements (
            id              BIGSERIAL     PRIMARY KEY,
            at              TIMESTAMPTZ   NOT NULL,
            record_kind     TEXT          NOT NULL CHECK (record_kind IN ('pick', 'daily_item', 'parlay_leg', 'parlay',
                                          'user_pick', 'user_parlay_leg', 'user_parlay')),
            record_key      TEXT          NOT NULL,
            fixture_id      BIGINT        REFERENCES core.fixtures(id) ON DELETE CASCADE,
            revision_id     BIGINT        REFERENCES core.fixture_result_revisions(id),
            from_status     TEXT          NOT NULL,
            from_profit     NUMERIC(12,4),
            from_settled_at TIMESTAMPTZ,
            to_status       TEXT          NOT NULL,
            to_profit       NUMERIC(12,4),
            rule_version    TEXT          NOT NULL,
            reason          TEXT          NOT NULL CHECK (length(btrim(reason)) > 0),
            run_id          BIGINT        REFERENCES raw.ingestion_runs(id) ON DELETE SET NULL,
            CHECK (from_status <> to_status OR from_profit IS DISTINCT FROM to_profit)
        )""")
    op.execute("CREATE INDEX resettlements_record ON picks.resettlements (record_kind, record_key, at)")
    op.execute("CREATE INDEX resettlements_fixture ON picks.resettlements (fixture_id, at)")
    op.execute("CREATE INDEX resettlements_at ON picks.resettlements (at DESC)")
    op.execute("""
        COMMENT ON TABLE picks.resettlements IS
        'The trail of re-settlements (plan F0, defect 5): one row each time a settled record - a pick, a pick of the day, a
         parlay and its legs, a user''s pick, parlay or leg - changed result because the provider corrected the match, or
         because the audit found it settled under an earlier rule. The record shows the current result; this table keeps
         the one it had (from_*), the one it has (to_*), the settlement version, the reason and the revision it answers.
         record_key: the id, or set_id/rank (daily_item) or parlay_id/leg_no (legs). Rows are never edited, and the
         revision a row answers cannot be deleted from under it (both go with their match).'""")
    op.execute("CREATE TRIGGER resettlements_no_update BEFORE UPDATE ON picks.resettlements "
               "FOR EACH ROW EXECUTE FUNCTION core.refuse_history_update()")
    op.execute("ALTER TABLE picks.pick_events ADD COLUMN event_kind TEXT NOT NULL DEFAULT 'status' "
               "CHECK (event_kind IN ('status', 'resettlement'))")
    op.execute("""
        COMMENT ON COLUMN picks.pick_events.event_kind IS
        'status: a change of the pick''s status, as always. resettlement: the pick stayed settled but its result changed
         because the provider corrected the match (the reason says from what to what; picks.resettlements has the rest).'""")
    op.execute("DROP VIEW IF EXISTS picks.v_pick_record")
    op.execute(_pick_record_view(resettlements=True))
    op.execute(VIEW_COMMENT)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP VIEW IF EXISTS picks.v_pick_record")  # it reads the column and the table dropped below
    op.execute(_pick_record_view(resettlements=False))
    op.execute(VIEW_COMMENT)
    op.execute("ALTER TABLE picks.pick_events DROP COLUMN IF EXISTS event_kind")
    op.execute("DROP TABLE IF EXISTS picks.resettlements")
    op.execute("DROP TRIGGER IF EXISTS fixtures_status_revision ON core.fixtures")
    op.execute("DROP TRIGGER IF EXISTS fixture_results_revision ON core.fixture_results")
    op.execute("DROP TABLE IF EXISTS core.fixture_result_revisions")
    op.execute("DROP FUNCTION IF EXISTS core.log_status_revision()")
    op.execute("DROP FUNCTION IF EXISTS core.log_result_revision()")
    op.execute("DROP FUNCTION IF EXISTS core.refuse_history_update()")

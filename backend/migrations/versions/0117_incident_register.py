"""The incident register: every opening, update and closing of an alert, and the owner's notes, in a table that can only grow (security plan S3, section 21)

WHY THIS EXISTS
---------------
Until S3 PrediGol keeps no record of incidents: ``health.json`` holds only the last verdict. From S3 on, ``healthcheck.sh`` and
``security-alerts.sh`` write one line per event (open, update, close) to ``state/incidents.jsonl`` on the host, with an id
``INC-<year>-<nnn>``; that file is the truth because it works with the database down. A timer (``bin/incident-dump.sh``) mirrors it
into this table whenever the database answers, so that the register is inside the dumps and the point-in-time copies like everything
else, and ``bin/incident.sh`` lets the owner add what only a person knows (cause, impact, users affected, personal data, repair,
prevention) as notes. The register is the evidence for the post-incident review and for the legal clock when personal data is involved.

WHAT IS ADDED
-------------
``audit.incident_events``  one row per event, never edited or deleted (a trigger refuses UPDATE, DELETE and TRUNCATE, for everybody).
    ``line_sha256`` is the sha256 of the exact line of the file, unique: mirroring the same file twice adds nothing. A note names its field
    (cause, evidence, impact, affected_users, personal_data, detection, repair, prevention) and is the owner's; the numbers of users are
    digits only (never a list of people), and ``personal_data`` starts with ``si`` or ``no``. The text of an event holds service names,
    counts and ids: no e-mail address and no secret (the scripts that write it refuse both).
``audit.incidents``  the current state of each incident: opened, closed, duration, service, alert, severity now, symptom, the newest note
    of each field and the earlier incidents of the same alert (recurrence). Computed; nothing is stored.

Nobody but the owner role touches either: the grants of the application roles are revoked here and again by ``db/grants.sql`` after
every migration (its loop would hand them back). Additive: no existing table, view or function is changed. The downgrade drops the view,
the table and the function (a record of incidents: export it first if the revision is being undone on a database that has had one).

Revision ID: 0117
Revises: 0116
"""

from __future__ import annotations

from alembic import op

revision = "0117"
down_revision = "0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). Everything here is new and refers to nothing that exists.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(r"""
        CREATE FUNCTION audit.refuse_incident_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit.%: append-only (% refused)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'check_violation';
        END
        $$""")

    op.execute(r"""
        CREATE TABLE audit.incident_events (
            id           BIGSERIAL   PRIMARY KEY,
            line_sha256  TEXT        NOT NULL UNIQUE CHECK (line_sha256 ~ '^[0-9a-f]{64}$'),
            incident_id  TEXT        NOT NULL CHECK (incident_id ~ '^INC-[0-9]{4}-[0-9]{3,}$'),
            event        TEXT        NOT NULL CHECK (event IN ('open', 'update', 'close', 'note')),
            at           TIMESTAMPTZ NOT NULL,
            alert_key    TEXT        CHECK (alert_key IS NULL OR alert_key ~ '^[a-z0-9_]+(\.[a-z0-9_-]+)+$'),
            service      TEXT        CHECK (service IS NULL OR service ~ '^[a-z0-9_]+$'),
            severity     TEXT        CHECK (severity IS NULL OR severity IN ('SEV1', 'SEV2', 'SEV3')),
            body         TEXT        NOT NULL CHECK (length(body) <= 2000),
            field        TEXT        CHECK (field IS NULL OR field IN ('cause', 'evidence', 'impact', 'affected_users', 'personal_data',
                                                                       'detection', 'repair', 'prevention')),
            minutes      INTEGER     CHECK (minutes IS NULL OR minutes >= 0),
            actor        TEXT        NOT NULL DEFAULT 'system' CHECK (actor IN ('system', 'owner')),
            raw          JSONB       NOT NULL CHECK (jsonb_typeof(raw) = 'object'),
            recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT incident_events_an_opening_says_what CHECK (
                event <> 'open' OR (alert_key IS NOT NULL AND service IS NOT NULL AND severity IS NOT NULL)),
            CONSTRAINT incident_events_a_note_names_its_field CHECK ((event = 'note') = (field IS NOT NULL)),
            CONSTRAINT incident_events_a_note_is_the_owners CHECK (event <> 'note' OR actor = 'owner'),
            CONSTRAINT incident_events_users_are_a_number CHECK (field IS DISTINCT FROM 'affected_users' OR body ~ '^[0-9]{1,9}$'),
            CONSTRAINT incident_events_personal_data_is_yes_or_no CHECK (field IS DISTINCT FROM 'personal_data' OR body ~ '^(si|no)([[:space:]:].*)?$')
        )""")
    op.execute("CREATE INDEX incident_events_incident ON audit.incident_events (incident_id, at, id)")
    op.execute("CREATE INDEX incident_events_openings ON audit.incident_events (alert_key, at) WHERE event = 'open'")
    op.execute("CREATE INDEX incident_events_at ON audit.incident_events (at)")
    op.execute("CREATE TRIGGER incident_events_append_only BEFORE UPDATE OR DELETE ON audit.incident_events "
               "FOR EACH ROW EXECUTE FUNCTION audit.refuse_incident_change()")
    op.execute("CREATE TRIGGER incident_events_no_truncate BEFORE TRUNCATE ON audit.incident_events "
               "FOR EACH STATEMENT EXECUTE FUNCTION audit.refuse_incident_change()")
    op.execute(r"""
        COMMENT ON TABLE audit.incident_events IS
        'The incident register: one row per event (open, update, close, note) of the incidents that healthcheck.sh and security-alerts.sh open
         and close on the host, and of the notes the owner adds. Mirrored from state/incidents.jsonl by bin/incident-dump.sh, idempotently by
         line_sha256. Append-only (trigger); only the owner role reads or writes it. Text: service names, counts and ids - never an address
         or a secret. python/bash: bin/incident.sh list, show.'""")
    op.execute("COMMENT ON COLUMN audit.incident_events.line_sha256 IS 'sha256 of the exact line of state/incidents.jsonl: the same line is never stored twice'")
    op.execute("COMMENT ON COLUMN audit.incident_events.body IS 'open/update/close: the text of the alert (a close says recuperado). note: the value the owner wrote'")
    op.execute("COMMENT ON COLUMN audit.incident_events.field IS 'note only: which part of the incident the note fills in'")

    op.execute(r"""
        CREATE VIEW audit.incidents AS
        WITH opened AS (
            SELECT DISTINCT ON (incident_id) incident_id, at AS opened_at, alert_key, service, body AS symptom, severity AS first_severity, actor AS opened_by
              FROM audit.incident_events WHERE event = 'open' ORDER BY incident_id, at, id
        ), closed AS (
            SELECT DISTINCT ON (incident_id) incident_id, at AS closed_at, actor AS closed_by
              FROM audit.incident_events WHERE event = 'close' ORDER BY incident_id, at DESC, id DESC
        ), sev AS (
            SELECT DISTINCT ON (incident_id) incident_id, severity
              FROM audit.incident_events WHERE event IN ('open', 'update') AND severity IS NOT NULL ORDER BY incident_id, at DESC, id DESC
        ), notes AS (
            SELECT incident_id,
                   max(body) FILTER (WHERE field = 'cause')          AS cause,
                   max(body) FILTER (WHERE field = 'evidence')       AS evidence,
                   max(body) FILTER (WHERE field = 'impact')         AS impact,
                   max(body) FILTER (WHERE field = 'affected_users') AS affected_users,
                   max(body) FILTER (WHERE field = 'personal_data')  AS personal_data,
                   max(body) FILTER (WHERE field = 'detection')      AS detection,
                   max(body) FILTER (WHERE field = 'repair')         AS repair,
                   max(body) FILTER (WHERE field = 'prevention')     AS prevention
              FROM (SELECT DISTINCT ON (incident_id, field) incident_id, field, body
                      FROM audit.incident_events WHERE event = 'note' ORDER BY incident_id, field, at DESC, id DESC) newest
             GROUP BY incident_id
        )
        SELECT o.incident_id, o.opened_at, c.closed_at,
               CASE WHEN c.closed_at IS NULL THEN 'open' ELSE 'closed' END AS state,
               c.closed_at - o.opened_at AS duration,
               o.service, o.alert_key, s.severity, o.first_severity, o.symptom,
               n.cause, n.evidence, n.impact, n.affected_users, n.personal_data,
               coalesce(n.detection, CASE o.opened_by WHEN 'owner' THEN 'owner' ELSE 'server check' END) AS detection,
               n.repair, n.prevention,
               (SELECT array_agg(p.incident_id ORDER BY p.opened_at DESC)
                  FROM (SELECT o2.incident_id, o2.opened_at FROM opened o2
                         WHERE o2.alert_key = o.alert_key AND o2.opened_at < o.opened_at ORDER BY o2.opened_at DESC LIMIT 5) p) AS earlier_same_alert
          FROM opened o
          LEFT JOIN closed c USING (incident_id)
          LEFT JOIN sev s USING (incident_id)
          LEFT JOIN notes n USING (incident_id)""")
    op.execute("COMMENT ON VIEW audit.incidents IS "
               "'The current state of each incident of audit.incident_events: when it opened and closed, how long, the severity now, the symptom, the newest note of each field "
               "and the earlier incidents of the same alert (recurrence). Computed; nothing stored.'")

    # The application roles never see it: the owner role (fbi) writes and reads it. db/grants.sql hands every table of every schema to them after each
    # migration, so the same revoke lives there too. The roles do not exist on a scratch database of the tests.
    op.execute(r"""
        DO $revoke$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'predigol_api') THEN
                REVOKE ALL ON audit.incident_events, audit.incidents FROM predigol_api;
                REVOKE ALL ON SEQUENCE audit.incident_events_id_seq FROM predigol_api;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'predigol_worker') THEN
                REVOKE ALL ON audit.incident_events, audit.incidents FROM predigol_worker;
                REVOKE ALL ON SEQUENCE audit.incident_events_id_seq FROM predigol_worker;
            END IF;
        END
        $revoke$""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP VIEW IF EXISTS audit.incidents")
    op.execute("DROP TABLE IF EXISTS audit.incident_events")
    op.execute("DROP FUNCTION IF EXISTS audit.refuse_incident_change()")

"""The registry of sources v2 and its access policy (IA-062 and IA-063, plan pieces AD-C01 and AD-C02): five tables, and nothing else

WHY THIS EXISTS
---------------
The research reads what Exa returns, and today any result reaches the extractor: betting and tips sites (18,5 % of the results of 60
days, with 11 useful items), the search engine's own pages (``exa.ai``, 277 results) and media whose robots or terms reserve their text
from AI (71 sources of the directory v2). The directory v2 (2.001 sources, 16-nov-2026) says, per source, its state, its family, the four
permissions (automated access, extraction by AI, storage, publication) and its authority per type of claim; the exclusion list classifies
the 559 domains Exa brought. This migration gives both a place in the database, versioned, so the policy reads them (``fbi.ai.
source_policy``) and every block is recorded.

WHAT CHANGES
------------
- ``ai.source_registry_versions``: one row per file loaded (``directory`` or ``exclusion``) - its name, sha256, rows and counts. The
  version is named after the content: loading the same file twice writes nothing. The newest of each kind is in force.
- ``ai.source_registry``: one row per source and version - state, family, type, the four permissions, the authority per type of claim
  (``authority``), the date of the last review, the whole record of the directory (``record``) and its hash.
- ``ai.domain_rules``: one row per domain and version of the exclusion list - its class and what the policy does (``block`` the four
  safe classes, ``review`` the doubtful, ``none`` the rest).
- ``ai.source_signoffs``: the owner's signatures - a source moves to authorised only with one (``decided_by = 'owner'``), and so does
  the exclusion list as a whole.
- ``ai.source_policy_log``: every page the policy kept away from a model, or would have in shadow - when, which path, which page, which
  source and state, why, and whether it was applied.

All five are append-only (``ai.refuse_change()``); the data itself is NOT here: ``scripts/ia_sources_load.py`` loads the pinned files of
``config/sources`` after the deploy (idempotent). ``ai.sources`` (402 domains, the tiers of the evidence) is not touched, and no
foreign key points at a table that exists: the only ones are between these new tables.

Downgrade: drops the five tables. The directory is in the repository; what the log recorded is lost with it (it is a record of what the
policy did, nothing reads it to decide).

Revision ID: 0139
Revises: 0137 (provisional: it goes on top of 0138_capability_registry when that one is merged)
"""

from alembic import op

revision = "0139"
down_revision = "0138"
branch_labels = None
depends_on = None

STATES = ("'verificada_autorizada', 'verificada_pendiente_derechos', 'solo_referencia', 'no_comprobada', 'bloqueada'")
CLASSES = ("'apuestas_o_pronosticos', 'resultados_sin_redaccion', 'contenido_generado_o_baja_calidad', 'no_futbol_u_otro', "
           "'agregador_o_refrito', 'dudoso', 'medio_real', 'oficial', 'datos_reconocidos'")
SHA256 = "^[0-9a-f]{64}$"
DOMAIN = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
VERSION = "^[a-z0-9][a-z0-9.:+-]{2,79}$"
TABLES = ("source_policy_log", "source_signoffs", "domain_rules", "source_registry", "source_registry_versions")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE ai.source_registry_versions (
            version        TEXT         PRIMARY KEY CHECK (version ~ '{VERSION}'),
            seq            BIGSERIAL    NOT NULL UNIQUE,
            kind           TEXT         NOT NULL CHECK (kind IN ('directory', 'exclusion')),
            file_name      TEXT         NOT NULL CHECK (length(file_name) BETWEEN 1 AND 200),
            file_sha256    TEXT         NOT NULL CHECK (file_sha256 ~ '{SHA256}'),
            origin_sha256  TEXT         CHECK (origin_sha256 IS NULL OR origin_sha256 ~ '{SHA256}'),
            rows           INTEGER      NOT NULL CHECK (rows >= 0),
            counts         JSONB        NOT NULL DEFAULT '{{}}'::jsonb,
            previous       TEXT         REFERENCES ai.source_registry_versions(version),
            loaded_at      TIMESTAMPTZ  NOT NULL,
            loaded_by      TEXT         NOT NULL CHECK (loaded_by IN ('loader', 'owner')),
            code_version   TEXT
        );
        COMMENT ON TABLE ai.source_registry_versions IS
          'IA-062: each file of config/sources loaded (the directory of sources, the exclusion list), named after its content. The newest '
          'of each kind is in force; an older one is kept, never rewritten.';

        CREATE TABLE ai.source_registry (
            id               BIGSERIAL    PRIMARY KEY,
            version          TEXT         NOT NULL REFERENCES ai.source_registry_versions(version),
            source_id        TEXT         NOT NULL CHECK (length(source_id) BETWEEN 1 AND 120),
            domain           TEXT         NOT NULL CHECK (domain ~ '{DOMAIN}'),
            name             TEXT         NOT NULL,
            family           TEXT         NOT NULL CHECK (family IN ('A', 'B', 'C', 'D', 'E')),
            source_type      TEXT         NOT NULL,
            country          TEXT,
            official_of      TEXT,
            state            TEXT         NOT NULL CHECK (state IN ({STATES})),
            automated_access TEXT         NOT NULL,
            ai_extraction    TEXT         NOT NULL,
            storage          TEXT         NOT NULL,
            publication      TEXT         NOT NULL,
            authority        JSONB        NOT NULL DEFAULT '{{}}'::jsonb,
            last_reviewed    DATE,
            record           JSONB        NOT NULL,
            record_sha256    TEXT         NOT NULL CHECK (record_sha256 ~ '{SHA256}'),
            UNIQUE (version, source_id)
        );
        CREATE INDEX ai_source_registry_domain ON ai.source_registry (version, domain);
        COMMENT ON TABLE ai.source_registry IS
          'IA-062: one row per source of the directory and version: state, family, the four permissions, the authority per type of claim '
          '(authority: {{claim type: {{level, note}}}}), the last review and the whole record. «Identified» is not «authorised»: a source '
          'passes strictly only when the directory says verificada_autorizada AND the owner signed it (ai.source_signoffs).';

        CREATE TABLE ai.domain_rules (
            id            BIGSERIAL    PRIMARY KEY,
            version       TEXT         NOT NULL REFERENCES ai.source_registry_versions(version),
            domain        TEXT         NOT NULL CHECK (domain ~ '{DOMAIN}'),
            domain_class  TEXT         NOT NULL CHECK (domain_class IN ({CLASSES})),
            action        TEXT         NOT NULL CHECK (action IN ('block', 'review', 'none')),
            results       INTEGER      NOT NULL DEFAULT 0 CHECK (results >= 0),
            evidences     INTEGER      NOT NULL DEFAULT 0 CHECK (evidences >= 0),
            useful        INTEGER      NOT NULL DEFAULT 0 CHECK (useful >= 0),
            reason        TEXT,
            country       TEXT,
            UNIQUE (version, domain),
            CHECK ((action = 'block') = (domain_class IN ('apuestas_o_pronosticos', 'resultados_sin_redaccion',
                                                           'contenido_generado_o_baja_calidad', 'no_futbol_u_otro')))
        );
        COMMENT ON TABLE ai.domain_rules IS
          'IA-062: the exclusion list, one row per domain and version. block = the four safe classes (taken out of the results before a '
          'model reads them, FBI_SOURCE_EXCLUSION); review = doubtful, in the owner''s queue; none = only classified. results, evidences '
          'and useful are the 60 days of production it was measured on.';

        CREATE TABLE ai.source_signoffs (
            id                BIGSERIAL    PRIMARY KEY,
            source_id         TEXT         CHECK (source_id IS NULL OR length(source_id) BETWEEN 1 AND 120),
            decision          TEXT         NOT NULL CHECK (decision IN ('authorize', 'revoke', 'exclusion_list')),
            registry_version  TEXT         NOT NULL REFERENCES ai.source_registry_versions(version),
            decided_by        TEXT         NOT NULL CHECK (decided_by = 'owner'),
            at                TIMESTAMPTZ  NOT NULL,
            reason            TEXT         NOT NULL CHECK (length(btrim(reason)) BETWEEN 3 AND 500),
            CHECK ((decision = 'exclusion_list') = (source_id IS NULL))
        );
        CREATE INDEX ai_source_signoffs_source ON ai.source_signoffs (source_id, at DESC, id DESC);
        COMMENT ON TABLE ai.source_signoffs IS
          'IA-062: the owner''s signatures. The newest row of a source decides (a revoke takes an authorisation back); exclusion_list signs '
          'a version of the exclusion list as a whole.';

        CREATE TABLE ai.source_policy_log (
            id               BIGSERIAL    PRIMARY KEY,
            at               TIMESTAMPTZ  NOT NULL,
            policy_version   TEXT         NOT NULL,
            mode             TEXT         NOT NULL CHECK (mode IN ('shadow', 'enforce')),
            exclusion_mode   TEXT         NOT NULL CHECK (exclusion_mode IN ('off', 'shadow', 'enforce')),
            path             TEXT         NOT NULL CHECK (path IN ('v1', 'v2', 'analyst', 'ingest', 'publish', 'other')),
            action           TEXT         NOT NULL CHECK (action IN ('fetch', 'extract', 'store', 'publish')),
            outcome          TEXT         NOT NULL CHECK (outcome IN ('blocked', 'would_block')),
            reason           TEXT         NOT NULL CHECK (length(reason) BETWEEN 1 AND 120),
            hard             BOOLEAN      NOT NULL,
            url              TEXT         NOT NULL CHECK (length(url) BETWEEN 1 AND 2000),
            host             TEXT,
            domain           TEXT,
            source_id        TEXT,
            state            TEXT         NOT NULL,
            rule_class       TEXT,
            registry_version TEXT         NOT NULL,
            fixture_id       BIGINT       CHECK (fixture_id IS NULL OR fixture_id >= 1)
        );
        CREATE INDEX ai_source_policy_log_at ON ai.source_policy_log (at);
        COMMENT ON TABLE ai.source_policy_log IS
          'IA-063: every page kept away from a model (blocked) or that the strict policy would keep away (would_block, shadow). hard = the '
          'AI reservation, applied whatever the switches say. No foreign key: fixture_id is the research''s own.';
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON ai.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS ai.{table}")

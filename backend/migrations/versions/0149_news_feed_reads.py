"""The reading state of each feed (IA-085, plan piece AD-C03): ``news.feed_reads``, one append-only row per pass over a feed

WHY THIS EXISTS
---------------
The ingestion of signals reads the RSS feeds and sitemaps of the directory incrementally: it asks with the ``ETag`` and the
``Last-Modified`` the server gave last time, does not parse again a body whose sha256 it has already read, reads a feed that fails less
often, and plans the next read by the proximity of the matches of its source. That state does not fit in ``news.feeds`` without rewriting
it (IA-080 said so: «AD-C03 necesitará guardar el estado de lectura de cada feed ... irá en un registro propio de solo añadido»).

WHAT CHANGES
------------
``news.feed_reads``: one row per feed and pass that did something - a read (``read``, ``not_modified``, ``unchanged``), a failure
(``failed``, ``robots``: robots.txt forbids the address, never read by another route) or, for a source the policy does not let be read
yet, what the reader WOULD have read (``would_read``: no request is made; the shadow's «habría leído»). The newest row of a feed is its
state: the conditional headers, the consecutive failures and when it is due again. Append-only (``ai.refuse_change()``, as every table of
the plan: the static test of IA-059). Nothing reads it but the ingestion itself and the owner's script.

Downgrade: drops the table (the reading state is rebuilt by the next full read: the feeds and the items stay in ``news.feeds`` and
``news.items``).

Revision ID: 0149
Revises: 0147 (provisional: the head of this branch; the merge re-chains it after 0148)
"""

from __future__ import annotations

from alembic import op

revision = "0149"
down_revision = "0147"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
WRITER = "^[a-z0-9][a-z0-9._:+-]{1,79}$"
OUTCOMES = ("read", "not_modified", "unchanged", "failed", "robots", "would_read")
BANDS = ("le6h", "6_36h", "36h_7d", "none")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE news.feed_reads (
            id                   BIGSERIAL    PRIMARY KEY,
            feed_id              BIGINT       NOT NULL REFERENCES news.feeds(id),
            url_sha256           TEXT         NOT NULL CHECK (url_sha256 ~ '{SHA256}'),
            source_id            TEXT         NOT NULL CHECK (length(source_id) BETWEEN 1 AND 120),
            at                   TIMESTAMPTZ  NOT NULL,
            mode                 TEXT         NOT NULL CHECK (mode IN ('shadow')),
            outcome              TEXT         NOT NULL CHECK (outcome IN ({_in(OUTCOMES)})),
            reason               TEXT         CHECK (length(reason) BETWEEN 1 AND 120),
            http_status          INTEGER      CHECK (http_status BETWEEN 100 AND 599),
            etag                 TEXT         CHECK (length(etag) BETWEEN 1 AND 500),
            last_modified        TEXT         CHECK (length(last_modified) BETWEEN 1 AND 100),
            body_sha256          TEXT         CHECK (body_sha256 ~ '{SHA256}'),
            bytes                INTEGER      CHECK (bytes >= 0),
            elapsed_ms           INTEGER      CHECK (elapsed_ms >= 0),
            entries              INTEGER      NOT NULL DEFAULT 0 CHECK (entries >= 0),
            created              INTEGER      NOT NULL DEFAULT 0 CHECK (created >= 0),
            new_versions         INTEGER      NOT NULL DEFAULT 0 CHECK (new_versions >= 0),
            unchanged            INTEGER      NOT NULL DEFAULT 0 CHECK (unchanged >= 0),
            refused              INTEGER      NOT NULL DEFAULT 0 CHECK (refused >= 0),
            newest_published_at  TIMESTAMPTZ,
            failures             INTEGER      NOT NULL DEFAULT 0 CHECK (failures >= 0),
            band                 TEXT         NOT NULL CHECK (band IN ({_in(BANDS)})),
            next_due_at          TIMESTAMPTZ  NOT NULL,
            reader_version       TEXT         NOT NULL CHECK (reader_version ~ '{WRITER}'),
            registry_version     TEXT         NOT NULL CHECK (length(registry_version) BETWEEN 1 AND 200),
            CHECK (next_due_at > at),
            CHECK (outcome <> 'would_read' OR (http_status IS NULL AND etag IS NULL AND body_sha256 IS NULL AND entries = 0)),
            CHECK (outcome NOT IN ('failed', 'robots') OR failures >= 1),
            CHECK (outcome IN ('failed', 'robots', 'would_read') OR http_status IS NOT NULL)
        );
        CREATE INDEX news_feed_reads_feed ON news.feed_reads (url_sha256, at DESC, id DESC);
        CREATE INDEX news_feed_reads_at ON news.feed_reads (at);
        COMMENT ON TABLE news.feed_reads IS
          'IA-085 (AD-C03): what each pass of the ingestion of signals did with a feed of news.feeds - read it (read, not_modified, '
          'unchanged body), failed (failed; robots: robots.txt forbids it, never read by another route), or, for a source the policy does '
          'not let be read yet, what it would have read (would_read: no request made). The newest row of a feed is its state: ETag, '
          'Last-Modified, consecutive failures, next due. Append-only.';
    """)
    op.execute("CREATE TRIGGER feed_reads_append_only BEFORE UPDATE OR DELETE ON news.feed_reads "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS news.feed_reads")

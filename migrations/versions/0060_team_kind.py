"""team kind: PrediGol's own national / club classification of a side, from the competitions it plays

The teams audit (4 Oct 2026) found the provider's ``team.national`` flag wrong both ways: youth national
sides (Bolivia U20, Denmark U17, ...) and Guadeloupe flagged as clubs, two amateur clubs (Alo Egypt, France
Aizenay) flagged as national. The product resolved a player's club with that flag, so a national youth side
could be shown as a player's club.

``core.team_kind`` holds PrediGol's classification, recomputed from the stored fixtures by
``fbi.catalog.team_kind.refresh_team_kind`` (rule version in each row):

* a side that plays any competitive club competition (club scope, not a friendly) is a club;
* otherwise one that plays national-team competitions and no club friendly is a national side;
* otherwise the provider's flag (which may be NULL: unknown).

The provider's flag stays as it was in ``core.teams.is_national`` (never overwritten); a difference between
the two is an evidence entry of the teams audit. It is a derived table: a refresh rewrites a row only when
the classification or its counts change.

Revision ID: 0060
Revises: 0059
"""

from __future__ import annotations

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS core.team_kind (
            team_id                   BIGINT      PRIMARY KEY REFERENCES core.teams(id) ON DELETE CASCADE,
            is_national               BOOLEAN,
            basis                     TEXT        NOT NULL,
            provider_national         BOOLEAN,
            competitive_club_matches  INTEGER     NOT NULL CHECK (competitive_club_matches >= 0),
            national_matches          INTEGER     NOT NULL CHECK (national_matches >= 0),
            club_friendly_matches     INTEGER     NOT NULL CHECK (club_friendly_matches >= 0),
            rule_version              TEXT        NOT NULL,
            refreshed_at              TIMESTAMPTZ NOT NULL
        )""")
    op.execute("""COMMENT ON TABLE core.team_kind IS
        'PrediGol''s classification of a side as national or club, from the competitions it plays (the provider''s
         team.national is wrong both ways for some sides). Derived and recomputed (fbi.catalog.team_kind); the
         provider''s flag stays in core.teams.is_national.'""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core.team_kind")

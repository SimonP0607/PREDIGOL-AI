"""schemas and extensions

Source of truth: docs/rebuild/schema_v2/001_schemas_and_extensions.sql
The DDL is the specification. It is embedded verbatim; semantics are not
altered here.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = (
    "raw",
    "core",
    "market",
    "features",
    "models",
    "picks",
    "analytics",
    "audit",
)

UPGRADE = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS features;
CREATE SCHEMA IF NOT EXISTS models;
CREATE SCHEMA IF NOT EXISTS picks;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS audit;

COMMENT ON SCHEMA raw       IS 'Payloads originales del proveedor. Inmutable.';
COMMENT ON SCHEMA core      IS 'Modelo deportivo normalizado, independiente del proveedor.';
COMMENT ON SCHEMA market    IS 'Precios: serie temporal de cuotas y snapshots proximos al cierre.';
COMMENT ON SCHEMA features  IS 'Feature store con correccion point-in-time.';
COMMENT ON SCHEMA models    IS 'Registro de modelos, versiones, calibradores y predicciones.';
COMMENT ON SCHEMA picks     IS 'Decisiones, publicacion, liquidacion y valor de linea.';
COMMENT ON SCHEMA analytics IS 'Backtests y metricas agregadas. Reconstruible.';
COMMENT ON SCHEMA audit     IS 'Auditoria de decisiones y calidad de datos.';
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    # Extensions are intentionally NOT dropped: they may be shared with other
    # databases/roles and dropping them is not the inverse of CREATE IF NOT EXISTS.

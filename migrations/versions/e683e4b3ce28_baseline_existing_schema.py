"""Baseline — represents the existing schema as of Alembic adoption.

Prod databases (Postgres on Railway and local SQLite) already have every table
created by database._init_schema(). This migration is a no-op used only as the
anchor so future schema changes can be versioned incrementally.

To adopt on an existing environment:
    alembic stamp head

For a fresh environment:
    python -c "import database; database._init_schema()"
    alembic stamp head
"""
from typing import Sequence, Union


revision: str = "e683e4b3ce28"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: baseline captures state after _init_schema() has already run."""
    pass


def downgrade() -> None:
    raise RuntimeError("Cannot downgrade past the baseline migration.")

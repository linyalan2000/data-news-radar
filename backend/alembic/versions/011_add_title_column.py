"""Add title column to posts table.

Display code (MCP tools) uses content[:80] as a pseudo-title, which
breaks when the content starts with long body text.  A proper title
column lets us show clean titles everywhere.

Revision ID: 011
Revises: 010
Create Date: 2026-05-13
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
    )
    # Backfill: use first 100 chars of content as fallback title
    # (same heuristic as the pre-title-column workaround documented in CLAUDE.md)
    op.execute("UPDATE posts SET title = substr(content, 1, 100) WHERE title = ''")


def downgrade() -> None:
    op.drop_column("posts", "title")

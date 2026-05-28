"""Add relevance_note column for LLM-based relevance judgment.

Before summarising, the pipeline now runs a lightweight MiniMax
"judge" call.  If the judge considers a post irrelevant, it stores
the reason in relevance_note so the post is skipped by future
summary passes.  NULL = not yet judged, populated = irrelevant + why.

Revision ID: 010
Revises: 009
Create Date: 2026-05-12
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("relevance_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("posts", "relevance_note")

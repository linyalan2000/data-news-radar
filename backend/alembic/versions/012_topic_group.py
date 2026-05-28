"""Add topic_group column for grouping duplicate/similar news.

When multiple sources report the same story, they share a topic_group
hash so the frontend can fold them together (e.g. "关联 X 信源").

Revision ID: 012
Revises: 011
Create Date: 2026-05-15
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("topic_group", sa.String(32), nullable=True),
    )
    op.create_index("ix_posts_topic_group", "posts", ["topic_group"])


def downgrade() -> None:
    op.drop_index("ix_posts_topic_group")
    op.drop_column("posts", "topic_group")

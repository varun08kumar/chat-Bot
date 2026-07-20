"""add is_admin flag to users

Revision ID: 0003_add_user_is_admin
Revises: 0002_add_users
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_add_user_is_admin"
down_revision = "0002_add_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")

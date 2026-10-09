"""Store the destination account for transfer idempotency.

Revision ID: b72d9f03a615
Revises: a91f2e7b6c04
"""

from alembic import op
import sqlalchemy as sa

revision = "b72d9f03a615"
down_revision = "a91f2e7b6c04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("to_account_id", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            "fk_transactions_to_account_id_accounts", "accounts", ["to_account_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint("fk_transactions_to_account_id_accounts", type_="foreignkey")
        batch_op.drop_column("to_account_id")
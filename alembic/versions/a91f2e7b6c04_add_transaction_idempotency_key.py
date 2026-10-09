"""Enforce unique transaction idempotency keys.

Revision ID: a91f2e7b6c04
Revises: d2c1c3e6710a
"""

from alembic import op
import sqlalchemy as sa

revision = "a91f2e7b6c04"
down_revision = "d2c1c3e6710a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    transactions = sa.table("transactions", sa.column("idempotency_key", sa.String()))
    duplicate = op.get_bind().execute(
        sa.select(transactions.c.idempotency_key)
        .group_by(transactions.c.idempotency_key)
        .having(sa.func.count() > 1)
        .limit(1)
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Duplicate transaction idempotency keys exist. Reconcile these records "
            "before applying the unique constraint; no records were deleted."
        )
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_transactions_idempotency_key", ["idempotency_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint("uq_transactions_idempotency_key", type_="unique")
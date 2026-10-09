from app.db import Base
from sqlalchemy import BigInteger, DateTime, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_transactions_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"))
    to_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", name="fk_transactions_to_account_id_accounts"), nullable=True
    )
    type: Mapped[str] = mapped_column(default="")
    amount: Mapped[int] = mapped_column(BigInteger, default=0)
    description: Mapped[str] = mapped_column(default="")
    idempotency_key: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
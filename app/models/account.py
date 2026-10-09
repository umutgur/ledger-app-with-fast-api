
from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from datetime import datetime

class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("customers.id", name="fk_accounts_customer_id_customers"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(default="")
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

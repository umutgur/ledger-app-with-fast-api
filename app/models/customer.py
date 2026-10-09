from app.db import Base
from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(default="")
    email: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
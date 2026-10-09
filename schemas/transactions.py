from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

class Transaction(BaseModel):
    id: int
    account_id: int
    type: str
    amount: int
    description: str
    idempotency_key: str
    created_at: datetime

class TopUpCredit(BaseModel):
    account_id: int
    amount: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1)

class WithdrawCredit(BaseModel):
    account_id: int
    amount: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1)

class TransferCredit(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1)

class TransactionCreate(BaseModel):
    account_id: int
    type: str
    amount: int
    description: str
    idempotency_key: str
    created_at: datetime

class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    to_account_id: int | None = None
    type: str
    amount: int
    description: str
    idempotency_key: str
    created_at: datetime
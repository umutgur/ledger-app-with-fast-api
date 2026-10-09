from pydantic import BaseModel, ConfigDict

class Account(BaseModel):
    id: int
    customer_id: int
    currency: str
    balance: int

class AccountCreate(BaseModel):
    customer_id: int
    currency: str

class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    currency: str
    balance: int
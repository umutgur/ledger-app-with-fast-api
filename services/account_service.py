from sqlalchemy.orm import Session

from schemas.accounts import AccountCreate

from app.models.account import Account

class AccountService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, account_create: AccountCreate) -> Account:
        account = Account(
            customer_id=account_create.customer_id,
            currency=account_create.currency
        )
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account

    def get(self, account_id: int) -> Account:
        return self.db.query(Account).filter(Account.id == account_id).first()

    def list(self, limit: int = 50, offset: int = 0) -> list[Account]:
        return self.db.query(Account).limit(limit).offset(offset).all()

    
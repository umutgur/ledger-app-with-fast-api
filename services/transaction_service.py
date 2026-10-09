from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from schemas.transactions import TopUpCredit, WithdrawCredit, TransferCredit

from app.models.account import Account
from app.models.transaction import Transaction

class TransactionService:
    def __init__(self, db: Session):
        self.db = db

    #Bakiye yükle
    def top_up(self, tu_req: TopUpCredit) -> Transaction:
        self._validate_request(tu_req.amount, tu_req.idempotency_key)
        transaction = Transaction(
            account_id=tu_req.account_id,
            type="top_up",
            amount=tu_req.amount,
            description="Top up credit",
            idempotency_key=tu_req.idempotency_key,
        )
        return self._execute_transaction(transaction)

    #Para çek
    def withdraw(self, wd_req: WithdrawCredit) -> Transaction:
        self._validate_request(wd_req.amount, wd_req.idempotency_key)
        transaction = Transaction(
            account_id=wd_req.account_id,
            type="withdraw",
            amount=wd_req.amount,
            description="Withdraw credit",
            idempotency_key=wd_req.idempotency_key,
        )
        return self._execute_transaction(transaction)

    #Transfer yap
    def transfer(self, tr_req: TransferCredit) -> Transaction:
        self._validate_request(tr_req.amount, tr_req.idempotency_key)
        if tr_req.from_account_id == tr_req.to_account_id:
            raise HTTPException(status_code=422, detail="Source and destination accounts must differ")
        transaction = Transaction(
            account_id=tr_req.from_account_id,
            to_account_id=tr_req.to_account_id,
            type="transfer",
            amount=tr_req.amount,
            description=f"Transfer to account {tr_req.to_account_id}",
            idempotency_key=tr_req.idempotency_key,
        )
        return self._execute_transaction(transaction)

    @staticmethod
    def _validate_request(amount: int, idempotency_key: str) -> None:
        if amount <= 0 or not idempotency_key.strip():
            raise HTTPException(status_code=422, detail="A positive amount and non-empty idempotency key are required")

    def _execute_transaction(self, transaction: Transaction) -> Transaction:
        try:
            self.db.add(transaction)
            # Reserve the key before changing the balance; concurrent retries
            # are serialized by the database unique constraint.
            self.db.flush()
            if transaction.type == "top_up":
                self._credit_account(transaction.account_id, transaction.amount)
            elif transaction.type == "withdraw":
                self._debit_account(transaction.account_id, transaction.amount)
            elif transaction.type == "transfer":
                destination_id = transaction.to_account_id
                if destination_id is None:
                    raise ValueError("A transfer requires a destination account")
                # Lock both accounts in a consistent order on databases with
                # row locks. SQLite serializes writers at the earlier flush.
                accounts = self.db.execute(
                    select(Account.id, Account.currency)
                    .where(Account.id.in_([transaction.account_id, destination_id]))
                    .order_by(Account.id)
                    .with_for_update(key_share=True)
                ).all()
                if len(accounts) != 2:
                    raise HTTPException(status_code=404, detail="Account not found")
                if accounts[0].currency != accounts[1].currency:
                    raise HTTPException(status_code=422, detail="Accounts must use the same currency")
                self._debit_account(transaction.account_id, transaction.amount)
                self._credit_account(destination_id, transaction.amount)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(
                select(Transaction).where(
                    Transaction.idempotency_key == transaction.idempotency_key
                )
            )
            if existing is not None:
                if (
                    existing.account_id != transaction.account_id
                    or existing.to_account_id != transaction.to_account_id
                    or existing.amount != transaction.amount
                    or existing.type != transaction.type
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key was already used for a different request",
                    )
                return existing
            if self.db.get(Account, transaction.account_id) is None:
                raise HTTPException(status_code=404, detail="Account not found")
            if transaction.to_account_id is not None and self.db.get(Account, transaction.to_account_id) is None:
                raise HTTPException(status_code=404, detail="Account not found")
            raise
        except Exception:
            self.db.rollback()
            raise

        self.db.refresh(transaction)
        return transaction

    def _credit_account(self, account_id: int, amount: int) -> None:
        updated_id = self.db.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(balance=Account.balance + amount)
            .returning(Account.id)
        ).scalar_one_or_none()
        if updated_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

    def _debit_account(self, account_id: int, amount: int) -> None:
        updated_id = self.db.execute(
            update(Account)
            .where(Account.id == account_id, Account.balance >= amount)
            .values(balance=Account.balance - amount)
            .returning(Account.id)
        ).scalar_one_or_none()
        if updated_id is None:
            if self.db.get(Account, account_id) is None:
                raise HTTPException(status_code=404, detail="Account not found")
            raise HTTPException(status_code=400, detail="Insufficient balance")
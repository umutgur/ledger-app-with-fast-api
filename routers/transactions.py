from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.transaction import Transaction
from schemas.transactions import TopUpCredit, TransactionRead, TransferCredit, WithdrawCredit
from services.transaction_service import TransactionService

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post("/top-up", response_model=TransactionRead)
def top_up(request: TopUpCredit, db: Session = Depends(get_db)) -> Transaction:
    return TransactionService(db).top_up(request)


@router.post("/withdraw", response_model=TransactionRead)
def withdraw(request: WithdrawCredit, db: Session = Depends(get_db)) -> Transaction:
    return TransactionService(db).withdraw(request)


@router.post("/transfer", response_model=TransactionRead)
def transfer(request: TransferCredit, db: Session = Depends(get_db)) -> Transaction:
    return TransactionService(db).transfer(request)
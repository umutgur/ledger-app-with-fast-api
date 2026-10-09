from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.account import Account
from schemas.accounts import AccountCreate, AccountRead
from services.account_service import AccountService
from services.customer_service import CustomerService

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(request: AccountCreate, db: Session = Depends(get_db)) -> Account:
    if CustomerService(db).get(request.customer_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return AccountService(db).create(request)


@router.get("", response_model=list[AccountRead])
def list_accounts(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Account]:
    return AccountService(db).list(limit=limit, offset=offset)


@router.get("/{account_id}", response_model=AccountRead)
def get_account(account_id: int, db: Session = Depends(get_db)) -> Account:
    account = AccountService(db).get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account
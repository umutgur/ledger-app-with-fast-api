from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.customer import Customer
from schemas.customers import CustomerCreate, CustomerRead
from services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(request: CustomerCreate, db: Session = Depends(get_db)) -> Customer:
    return CustomerService(db).create(request)


@router.get("", response_model=list[CustomerRead])
def list_customers(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Customer]:
    return CustomerService(db).list(limit=limit, offset=offset)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(customer_id: int, db: Session = Depends(get_db)) -> Customer:
    customer = CustomerService(db).get(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
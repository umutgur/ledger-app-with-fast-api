from sqlalchemy.orm import Session

from app.models.customer import Customer

from schemas.customers import CustomerCreate
class CustomerService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, customer_create: CustomerCreate) -> Customer:
        customer = Customer(
            name=customer_create.name,
            email=customer_create.email
        )
        self.db.add(customer)
        self.db.commit()
        self.db.refresh(customer)
        return customer

    def get(self, customer_id: int) -> Customer:
        return self.db.query(Customer).filter(Customer.id == customer_id).first()

    def list(self, limit: int = 50, offset: int = 0) -> list[Customer]:
        return self.db.query(Customer).limit(limit).offset(offset).all()

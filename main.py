from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db import get_db
from routers.accounts import router as accounts_router
from routers.customers import router as customers_router
from routers.transactions import router as transactions_router

app = FastAPI()
app.include_router(customers_router)
app.include_router(accounts_router)
app.include_router(transactions_router)

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/health/db")
def health_check_db(db: Session = Depends(get_db)):
    return {"db": db.execute(text("SELECT 1")).scalar()}
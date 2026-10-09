import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, get_db
from app.models.account import Account
from app.models.customer import Customer
from app.models.transaction import Transaction
from schemas.transactions import TopUpCredit, TransferCredit, WithdrawCredit
from services.transaction_service import TransactionService
from main import app


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        database = Path(self.directory.name) / "ledger.db"
        self.engine = create_engine(
            f"sqlite:///{database.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 15},
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            customer = Customer(name="Test", email="test@example.com")
            db.add(customer)
            db.flush()
            db.add_all([
                Account(id=1, customer_id=customer.id, balance=100, currency="TRY"),
                Account(id=2, customer_id=customer.id, balance=200, currency="TRY"),
            ])
            db.commit()

    def tearDown(self):
        self.engine.dispose()
        self.directory.cleanup()

    def top_up(self, key="request-1", amount=25, account_id=1):
        with Session(self.engine) as db:
            transaction = TransactionService(db).top_up(
                TopUpCredit(account_id=account_id, amount=amount, idempotency_key=key)
            )
            return transaction.id

    def assert_state(self, balance, count):
        with Session(self.engine) as db:
            self.assertEqual(db.get(Account, 1).balance, balance)
            self.assertEqual(db.scalar(select(func.count()).select_from(Transaction)), count)


class TopUpTests(LedgerTestCase):
    def test_top_up_increases_balance_and_records_transaction(self):
        transaction_id = self.top_up()
        self.assert_state(125, 1)
        with Session(self.engine) as db:
            transaction = db.get(Transaction, transaction_id)
            self.assertEqual((transaction.account_id, transaction.amount, transaction.type), (1, 25, "top_up"))

    def test_retry_returns_original_transaction_without_crediting_again(self):
        self.assertEqual(self.top_up(), self.top_up())
        self.assert_state(125, 1)

    def test_same_session_can_retry_after_unique_violation(self):
        with Session(self.engine) as db:
            service = TransactionService(db)
            request = TopUpCredit(account_id=1, amount=25, idempotency_key="same-session")
            first_id = service.top_up(request).id
            self.assertEqual(service.top_up(request).id, first_id)
            self.assertEqual(service.top_up(request).id, first_id)
        self.assert_state(125, 1)

    def test_key_cannot_be_reused_with_different_payload(self):
        self.top_up()
        for payload in ({"amount": 50}, {"account_id": 2}):
            with self.subTest(payload=payload), self.assertRaises(HTTPException) as error:
                self.top_up(**payload)
            self.assertEqual(error.exception.status_code, 409)
        self.assert_state(125, 1)

    def test_key_cannot_be_reused_for_a_different_operation(self):
        with Session(self.engine) as db:
            db.add(Transaction(account_id=1, amount=25, type="withdraw", idempotency_key="request-1"))
            db.commit()
        with self.assertRaises(HTTPException) as error:
            self.top_up()
        self.assertEqual(error.exception.status_code, 409)
        self.assert_state(100, 1)

    def test_missing_account_does_not_leave_transaction(self):
        with self.assertRaises(HTTPException) as error:
            self.top_up(account_id=999)
        self.assertEqual(error.exception.status_code, 404)
        self.assert_state(100, 0)
        self.top_up()
        self.assert_state(125, 1)

    def test_invalid_amount_or_key_does_not_change_balance(self):
        for amount in (0, -25):
            with self.assertRaises(ValidationError):
                self.top_up(amount=amount)
        with self.assertRaises(ValidationError):
            self.top_up(key="")
        with self.assertRaises(HTTPException) as error:
            self.top_up(key="   ")
        self.assertEqual(error.exception.status_code, 422)
        self.assert_state(100, 0)

    def test_commit_failure_rolls_back_balance_and_transaction(self):
        with Session(self.engine) as db:
            with patch.object(db, "commit", side_effect=RuntimeError("Commit failed")):
                with self.assertRaises(RuntimeError):
                    TransactionService(db).top_up(
                        TopUpCredit(account_id=1, amount=25, idempotency_key="request-1")
                    )
        self.assert_state(100, 0)

    def test_concurrent_retries_credit_once(self):
        barrier = Barrier(4)

        def request(_):
            barrier.wait(timeout=10)
            return self.top_up()

        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(request, range(4)))
        self.assertEqual(len(set(ids)), 1)
        self.assert_state(125, 1)

    def test_concurrent_distinct_requests_do_not_lose_balance_updates(self):
        barrier = Barrier(4)

        def request(index):
            barrier.wait(timeout=10)
            return self.top_up(key=f"request-{index}")

        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(request, range(4)))
        self.assertEqual(len(set(ids)), 4)
        self.assert_state(200, 4)


class WithdrawTransferTests(LedgerTestCase):
    def withdraw(self, key="withdraw-1", amount=25, account_id=1):
        with Session(self.engine) as db:
            return TransactionService(db).withdraw(
                WithdrawCredit(account_id=account_id, amount=amount, idempotency_key=key)
            ).id

    def transfer(self, key="transfer-1", amount=25, source=1, destination=2):
        with Session(self.engine) as db:
            return TransactionService(db).transfer(
                TransferCredit(
                    from_account_id=source, to_account_id=destination,
                    amount=amount, idempotency_key=key,
                )
            ).id

    def assert_balances(self, source, destination, count):
        self.assert_state(source, count)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Account, 2).balance, destination)

    def test_withdraw_retry_debits_once_even_if_balance_is_now_insufficient(self):
        self.assertEqual(self.withdraw(amount=100), self.withdraw(amount=100))
        self.assert_balances(0, 200, 1)

    def test_transfer_retry_moves_money_once_even_if_balance_is_now_insufficient(self):
        first_id = self.transfer(amount=100)
        self.assertEqual(first_id, self.transfer(amount=100))
        self.assert_balances(0, 300, 1)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Transaction, first_id).to_account_id, 2)

    def test_insufficient_balance_rolls_back_and_allows_retry_after_funding(self):
        for operation in (self.withdraw, self.transfer):
            with self.subTest(operation=operation.__name__), self.assertRaises(HTTPException) as error:
                operation(amount=150)
            self.assertEqual(error.exception.status_code, 400)
        self.assert_balances(100, 200, 0)
        self.top_up(amount=200)
        self.withdraw(amount=150)
        self.transfer(amount=150)
        self.assert_balances(0, 350, 3)

    def test_missing_accounts_roll_back_without_debiting(self):
        for operation, payload in (
            (self.withdraw, {"account_id": 999}),
            (self.transfer, {"source": 999}),
            (self.transfer, {"destination": 999}),
        ):
            with self.subTest(payload=payload), self.assertRaises(HTTPException) as error:
                operation(**payload)
            self.assertEqual(error.exception.status_code, 404)
        self.assert_balances(100, 200, 0)

    def test_transfer_to_same_account_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            self.transfer(destination=1)
        self.assertEqual(error.exception.status_code, 422)
        self.assert_balances(100, 200, 0)

    def test_transfer_with_different_currencies_is_rejected(self):
        with Session(self.engine) as db:
            db.get(Account, 2).currency = "USD"
            db.commit()
        with self.assertRaises(HTTPException) as error:
            self.transfer()
        self.assertEqual(error.exception.status_code, 422)
        self.assert_balances(100, 200, 0)

    def test_withdraw_key_cannot_be_reused_with_different_payload(self):
        self.withdraw()
        for payload in ({"amount": 50}, {"account_id": 2}):
            with self.subTest(payload=payload), self.assertRaises(HTTPException) as error:
                self.withdraw(**payload)
            self.assertEqual(error.exception.status_code, 409)
        self.assert_balances(75, 200, 1)

    def test_transfer_key_cannot_be_reused_with_different_payload(self):
        self.transfer()
        for payload in ({"amount": 50}, {"source": 2, "destination": 1}, {"destination": 999}):
            with self.subTest(payload=payload), self.assertRaises(HTTPException) as error:
                self.transfer(**payload)
            self.assertEqual(error.exception.status_code, 409)
        self.assert_balances(75, 225, 1)

    def test_key_cannot_be_reused_between_operations(self):
        self.withdraw(key="shared")
        for operation in (self.top_up, self.transfer):
            with self.subTest(operation=operation.__name__), self.assertRaises(HTTPException) as error:
                operation(key="shared")
            self.assertEqual(error.exception.status_code, 409)
        self.assert_balances(75, 200, 1)

    def test_invalid_requests_do_not_change_balances(self):
        for operation in (self.withdraw, self.transfer):
            for amount in (0, -25):
                with self.subTest(operation=operation.__name__, amount=amount), self.assertRaises(ValidationError):
                    operation(amount=amount)
            with self.assertRaises(ValidationError):
                operation(key="")
            with self.assertRaises(HTTPException) as error:
                operation(key="   ")
            self.assertEqual(error.exception.status_code, 422)
        self.assert_balances(100, 200, 0)

    def test_commit_failure_rolls_back_withdraw_and_transfer(self):
        for method, request in (
            ("withdraw", WithdrawCredit(account_id=1, amount=25, idempotency_key="withdraw-1")),
            ("transfer", TransferCredit(from_account_id=1, to_account_id=2, amount=25, idempotency_key="transfer-1")),
        ):
            with self.subTest(method=method), Session(self.engine) as db:
                with patch.object(db, "commit", side_effect=RuntimeError("Commit failed")):
                    with self.assertRaises(RuntimeError):
                        getattr(TransactionService(db), method)(request)
            self.assert_balances(100, 200, 0)

    def test_destination_update_failure_rolls_back_source_debit(self):
        with Session(self.engine) as db:
            service = TransactionService(db)
            with patch.object(service, "_credit_account", side_effect=RuntimeError("Credit failed")):
                with self.assertRaises(RuntimeError):
                    service.transfer(TransferCredit(
                        from_account_id=1, to_account_id=2, amount=25, idempotency_key="transfer-1"
                    ))
        self.assert_balances(100, 200, 0)

    def test_concurrent_retries_debit_and_transfer_once(self):
        for operation in (self.withdraw, self.transfer):
            barrier = Barrier(4)

            def request(_):
                barrier.wait(timeout=10)
                return operation()

            with self.subTest(operation=operation.__name__), ThreadPoolExecutor(max_workers=4) as pool:
                ids = list(pool.map(request, range(4)))
            self.assertEqual(len(set(ids)), 1)
        self.assert_balances(50, 225, 2)

    def test_concurrent_distinct_debits_cannot_overdraw_account(self):
        barrier = Barrier(4)

        def request(index):
            barrier.wait(timeout=10)
            try:
                if index % 2:
                    return self.transfer(key=f"concurrent-{index}", amount=40)
                return self.withdraw(key=f"concurrent-{index}", amount=40)
            except HTTPException as error:
                self.assertEqual(error.status_code, 400)
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(request, range(4)))
        self.assertEqual(sum(item is not None for item in ids), 2)
        self.assert_state(20, 2)
        with Session(self.engine) as db:
            transfer_count = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.type == "transfer"))
            self.assertEqual(db.get(Account, 2).balance, 200 + 40 * transfer_count)

    def test_concurrent_opposite_transfers_preserve_balances(self):
        barrier = Barrier(2)

        def request(source):
            barrier.wait(timeout=10)
            return self.transfer(key=f"opposite-{source}", source=source, destination=3 - source)

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(request, (1, 2)))
        self.assertEqual(len(set(ids)), 2)
        self.assert_balances(100, 200, 2)


class TransactionRouteTests(LedgerTestCase):
    def setUp(self):
        super().setUp()

        def override_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        super().tearDown()

    def test_transaction_routes_return_serialized_results_and_support_retries(self):
        for path, payload, expected_balance in (
            ("/transactions/top-up", {"account_id": 1}, 125),
            ("/transactions/withdraw", {"account_id": 1}, 100),
            ("/transactions/transfer", {"from_account_id": 1, "to_account_id": 2}, 75),
        ):
            request = {**payload, "amount": 25, "idempotency_key": path}
            with self.subTest(path=path):
                response = self.client.post(path, json=request)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["amount"], 25)
                retry = self.client.post(path, json=request)
                self.assertEqual(retry.status_code, 200, retry.text)
                self.assertEqual(retry.json(), response.json())
                account = self.client.get("/accounts/1")
                self.assertEqual(account.json()["balance"], expected_balance)
        self.assertEqual(response.json()["to_account_id"], 2)
        self.assert_state(75, 3)

    def test_route_errors_and_validation(self):
        response = self.client.post("/transactions/withdraw", json={
            "account_id": 1, "amount": 150, "idempotency_key": "insufficient",
        })
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/transactions/top-up", json={
            "account_id": 999, "amount": 25, "idempotency_key": "missing",
        })
        self.assertEqual(response.status_code, 404)
        response = self.client.post("/transactions/top-up", json={
            "account_id": 1, "amount": 0, "idempotency_key": "invalid",
        })
        self.assertEqual(response.status_code, 422)
        self.assert_state(100, 0)

    def test_route_rejects_key_reuse_with_different_payload(self):
        request = {"account_id": 1, "amount": 25, "idempotency_key": "shared"}
        self.assertEqual(self.client.post("/transactions/top-up", json=request).status_code, 200)
        response = self.client.post("/transactions/top-up", json={**request, "amount": 50})
        self.assertEqual(response.status_code, 409)
        self.assert_state(125, 1)

    def test_create_and_read_customer_and_account(self):
        customer = self.client.post("/customers", json={"name": "API Test", "email": "api@example.com"})
        self.assertEqual(customer.status_code, 201, customer.text)
        customer_id = customer.json()["id"]
        self.assertEqual(self.client.get(f"/customers/{customer_id}").json(), customer.json())
        account = self.client.post("/accounts", json={"customer_id": customer_id, "currency": "TRY"})
        self.assertEqual(account.status_code, 201, account.text)
        self.assertEqual(account.json()["balance"], 0)
        self.assertEqual(self.client.get(f"/accounts/{account.json()['id']}").json(), account.json())
        self.assertEqual(len(self.client.get("/customers").json()), 2)
        self.assertEqual(len(self.client.get("/accounts").json()), 3)

    def test_customer_account_not_found_and_pagination_validation(self):
        for path in ("/customers/999", "/accounts/999"):
            self.assertEqual(self.client.get(path).status_code, 404)
        response = self.client.post("/accounts", json={"customer_id": 999, "currency": "TRY"})
        self.assertEqual(response.status_code, 404)
        for path in ("/customers", "/accounts"):
            self.assertEqual(self.client.get(path, params={"limit": 0}).status_code, 422)
            self.assertEqual(self.client.get(path, params={"offset": -1}).status_code, 422)


class IdempotencyMigrationTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "alembic/versions/a91f2e7b6c04_add_transaction_idempotency_key.py"
        spec = importlib.util.spec_from_file_location("idempotency_migration", path)
        self.migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.migration)
        self.engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        self.transactions = Table(
            "transactions", metadata,
            Column("id", Integer, primary_key=True),
            Column("idempotency_key", String, nullable=False),
        )
        metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_upgrade_enforces_unique_key_and_downgrade_removes_constraint(self):
        with self.engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            with patch.object(self.migration, "op", operations):
                self.migration.upgrade()
                constraints = inspect(connection).get_unique_constraints("transactions")
                self.assertEqual(constraints[0]["name"], "uq_transactions_idempotency_key")
                connection.execute(self.transactions.insert().values(idempotency_key="key"))
                with self.assertRaises(IntegrityError):
                    connection.execute(self.transactions.insert().values(idempotency_key="key"))
                self.migration.downgrade()
                self.assertEqual(inspect(connection).get_unique_constraints("transactions"), [])

    def test_duplicate_existing_keys_abort_migration_without_deleting_records(self):
        with self.engine.begin() as connection:
            connection.execute(self.transactions.insert(), [
                {"idempotency_key": "duplicate"}, {"idempotency_key": "duplicate"},
            ])
            operations = Operations(MigrationContext.configure(connection))
            with patch.object(self.migration, "op", operations):
                with self.assertRaisesRegex(RuntimeError, "Duplicate transaction"):
                    self.migration.upgrade()
            self.assertEqual(connection.scalar(select(func.count()).select_from(self.transactions)), 2)


if __name__ == "__main__":
    unittest.main()
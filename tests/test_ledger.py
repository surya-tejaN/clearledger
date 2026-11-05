from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi.testclient import TestClient

from app.auth import issue_token
from app.ledger import Ledger, TransferError
from app.main import app


def client() -> TestClient:
    return TestClient(app)


def auth() -> dict:
    return {"Authorization": f"Bearer {issue_token('surya')}"}


def test_transfer_requires_jwt_and_idempotency_key():
    assert client().post(
        "/transfers", json={"from_account": "a", "to_account": "b", "cents": 1}
    ).status_code == 401
    assert client().post(
        "/transfers",
        json={"from_account": "a", "to_account": "b", "cents": 1},
        headers=auth(),
    ).status_code == 400


def test_retry_does_not_debit_twice():
    ledger = Ledger()
    src = ledger.create_account("src", 5000)
    dst = ledger.create_account("dst", 0)
    first = ledger.transfer(src.id, dst.id, 2000, "pay-1")
    second = ledger.transfer(src.id, dst.id, 2000, "pay-1")
    assert first.id == second.id
    assert ledger.get_account(src.id).cents == 3000
    assert ledger.get_account(dst.id).cents == 2000


def test_insufficient_funds_is_rejected():
    ledger = Ledger()
    src = ledger.create_account("src", 100)
    dst = ledger.create_account("dst", 0)
    try:
        ledger.transfer(src.id, dst.id, 200, "too-much")
        assert False, "should have failed"
    except TransferError as exc:
        assert exc.status_code == 409
    assert ledger.get_account(src.id).cents == 100


def test_twenty_concurrent_transfers_never_overdraw():
    ledger = Ledger()
    src = ledger.create_account("src", 5000)
    dst = ledger.create_account("dst", 0)

    def once(i: int):
        try:
            return ledger.transfer(src.id, dst.id, 1000, f"race-{i}")
        except TransferError:
            return None

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = [future.result() for future in as_completed(pool.submit(once, i) for i in range(20))]

    succeeded = [item for item in results if item is not None]
    assert len(succeeded) == 5
    assert ledger.get_account(src.id).cents == 0
    assert ledger.get_account(dst.id).cents == 5000

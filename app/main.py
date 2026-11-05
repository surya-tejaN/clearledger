from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_user
from app.ledger import Ledger, TransferError

app = FastAPI(title="ClearLedger")
ledger = Ledger()


class CreateAccount(BaseModel):
    name: str
    cents: int = Field(ge=0)


class CreateTransfer(BaseModel):
    from_account: str
    to_account: str
    cents: int = Field(gt=0)


@app.exception_handler(TransferError)
def transfer_error(_, exc: TransferError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.post("/accounts")
def create_account(body: CreateAccount, user: str = Depends(require_user)) -> dict:
    _ = user
    account = ledger.create_account(body.name, body.cents)
    return account.__dict__


@app.get("/accounts/{account_id}")
def get_account(account_id: str, user: str = Depends(require_user)) -> dict:
    _ = user
    account = ledger.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    return account.__dict__


@app.post("/transfers")
def create_transfer(
    body: CreateTransfer,
    user: str = Depends(require_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    _ = user
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    transfer = ledger.transfer(body.from_account, body.to_account, body.cents, idempotency_key)
    return transfer.__dict__

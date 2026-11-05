# ClearLedger

Transfer API that moves integer balances between accounts. Amounts are cents. Every `POST /transfers` needs a JWT and an `Idempotency-Key`. A retry with the same key returns the first transfer and does not debit again.

Accounts are locked in id order. Updates use a version column so a stale write does not commit.

## API

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/accounts` | JWT. Body: `{"name": "checking", "cents": 10000}` |
| GET | `/accounts/{id}` | JWT |
| POST | `/transfers` | JWT + `Idempotency-Key`. Body: `{"from_account": "...", "to_account": "...", "cents": 2500}` |

## Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export CLEARLEDGER_JWT_SECRET=dev-secret
uvicorn app.main:app --reload
pytest
```

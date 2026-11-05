from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from typing import Optional


class TransferError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass
class Account:
    id: str
    name: str
    cents: int
    version: int


@dataclass
class Transfer:
    id: str
    from_account: str
    to_account: str
    cents: int


class Ledger:
    """In-process ledger with exclusive transfer lock and CAS versions.

    Production equivalent: BEGIN; SELECT ... FOR UPDATE on both accounts
    ordered by id; UPDATE ... WHERE version = expected.
    """

    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cents INTEGER NOT NULL,
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transfers (
                id TEXT PRIMARY KEY,
                from_account TEXT NOT NULL,
                to_account TEXT NOT NULL,
                cents INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key TEXT PRIMARY KEY,
                transfer_id TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def create_account(self, name: str, cents: int) -> Account:
        if cents < 0:
            raise TransferError(400, "opening balance cannot be negative")
        account = Account(str(uuid.uuid4()), name, cents, 0)
        with self._lock:
            self._conn.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?)",
                (account.id, account.name, account.cents, account.version),
            )
            self._conn.commit()
        return account

    def get_account(self, account_id: str) -> Optional[Account]:
        row = self._conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return self._account(row) if row else None

    def transfer(
        self,
        from_account: str,
        to_account: str,
        cents: int,
        idempotency_key: str,
    ) -> Transfer:
        if cents <= 0:
            raise TransferError(400, "transfer must be a positive amount")
        if from_account == to_account:
            raise TransferError(400, "cannot transfer to the same account")

        with self._lock:
            existing = self._conn.execute(
                "SELECT transfer_id FROM idempotency_keys WHERE key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                row = self._conn.execute(
                    "SELECT * FROM transfers WHERE id = ?",
                    (existing["transfer_id"],),
                ).fetchone()
                return Transfer(row["id"], row["from_account"], row["to_account"], row["cents"])

            first_id, second_id = sorted([from_account, to_account])
            first = self._locked_account(first_id)
            second = self._locked_account(second_id)
            accounts = {first.id: first, second.id: second}
            source = accounts[from_account]
            dest = accounts[to_account]
            if source.cents < cents:
                raise TransferError(409, "insufficient funds")

            source_next = source.cents - cents
            dest_next = dest.cents + cents
            self._cas_update(source.id, source.version, source_next)
            self._cas_update(dest.id, dest.version, dest_next)

            transfer = Transfer(str(uuid.uuid4()), from_account, to_account, cents)
            self._conn.execute(
                "INSERT INTO transfers VALUES (?, ?, ?, ?)",
                (transfer.id, transfer.from_account, transfer.to_account, transfer.cents),
            )
            self._conn.execute(
                "INSERT INTO idempotency_keys VALUES (?, ?)",
                (idempotency_key, transfer.id),
            )
            self._conn.commit()
            return transfer

    def _locked_account(self, account_id: str) -> Account:
        row = self._conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if row is None:
            raise TransferError(404, f"account {account_id} not found")
        return self._account(row)

    def _cas_update(self, account_id: str, version: int, cents: int) -> None:
        cur = self._conn.execute(
            "UPDATE accounts SET cents = ?, version = version + 1 WHERE id = ? AND version = ?",
            (cents, account_id, version),
        )
        if cur.rowcount != 1:
            raise TransferError(409, "stale account version")

    def _account(self, row: sqlite3.Row) -> Account:
        return Account(row["id"], row["name"], row["cents"], row["version"])

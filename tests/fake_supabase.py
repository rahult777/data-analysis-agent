"""An in-memory stand-in for the Supabase table API, with fault injection (Build L.2).

Supports the chains the backend uses: table().select(cols).eq()/.is_().execute(),
table().insert(row).execute(), table().update(payload).eq()/.is_().execute().
Rows are plain dicts keyed by table. A fault makes the next matching execute
fail with a transient error, in one of three ways:

  "before" — raise without applying (the request never landed);
  "after"  — apply, then raise (a lost success);
  "late"   — raise without applying, then apply right after the next select on
             that table (a commit that lands after the caller's re-read).

`after_raise` runs a callable on the fake just after the fault raises, and
`on_next_select` just after the next select on that table returns — to move the
row on at exactly those points.
"""

import copy
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx
from postgrest.exceptions import APIError


@dataclass
class Fault:
    op: str
    table: str
    mode: str = "before"
    error: Callable[[], Exception] = lambda: httpx.RemoteProtocolError("Server disconnected")
    when: Callable[[dict], bool] = lambda payload: True
    after_raise: Optional[Callable[["FakeSupabase"], None]] = None
    on_next_select: Optional[Callable[["FakeSupabase"], None]] = None


@dataclass
class Call:
    op: str
    table: str
    payload: Optional[dict]
    filters: list
    columns: Optional[str] = None


@dataclass
class _Result:
    data: list
    count: Optional[int] = None


class _Query:
    def __init__(self, fake: "FakeSupabase", table: str, op: str, payload: Optional[dict] = None, columns: Optional[str] = None) -> None:
        self.fake, self.table, self.op, self.payload, self.columns = fake, table, op, payload, columns
        self.filters: list = []

    def eq(self, column: str, value: object) -> "_Query":
        self.filters.append(("eq", column, value))
        return self

    def is_(self, column: str, value: str) -> "_Query":
        self.filters.append(("is", column, value))
        return self

    def execute(self) -> _Result:
        return self.fake._execute(self)


class _Table:
    def __init__(self, fake: "FakeSupabase", name: str) -> None:
        self.fake, self.name = fake, name

    def select(self, columns: str = "*", count: Optional[str] = None) -> _Query:
        return _Query(self.fake, self.name, "select", columns=columns)

    def insert(self, row: dict) -> _Query:
        return _Query(self.fake, self.name, "insert", payload=copy.deepcopy(row))

    def update(self, payload: dict) -> _Query:
        return _Query(self.fake, self.name, "update", payload=copy.deepcopy(payload))


@dataclass
class FakeSupabase:
    rows: dict = field(default_factory=dict)
    faults: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    _pending_after_select: dict = field(default_factory=dict)

    def table(self, name: str) -> _Table:
        return _Table(self, name)

    def row(self, table: str, row_id: str) -> Optional[dict]:
        return next((r for r in self.rows.get(table, []) if r.get("id") == row_id), None)

    def executes(self, op: str, table: str) -> list[Call]:
        return [c for c in self.calls if c.op == op and c.table == table]

    @staticmethod
    def _matches(row: dict, filters: list) -> bool:
        for kind, column, value in filters:
            if kind == "eq" and row.get(column) != value:
                return False
            if kind == "is" and not (value == "null" and row.get(column) is None):
                return False
        return True

    def _apply(self, query: _Query) -> _Result:
        rows = self.rows.setdefault(query.table, [])
        if query.op == "insert":
            if any(r.get("id") == query.payload.get("id") for r in rows):
                raise APIError({"code": "23505", "message": "duplicate key value violates unique constraint"})
            rows.append(copy.deepcopy(query.payload))
            return _Result([copy.deepcopy(query.payload)])
        matched = [r for r in rows if self._matches(r, query.filters)]
        if query.op == "update":
            for r in matched:
                r.update(copy.deepcopy(query.payload))
            return _Result(copy.deepcopy(matched))
        columns = [c.strip() for c in (query.columns or "*").split(",")]
        if columns == ["*"]:
            return _Result(copy.deepcopy(matched))
        return _Result([{c: copy.deepcopy(r.get(c)) for c in columns} for r in matched])

    def _execute(self, query: _Query) -> _Result:
        self.calls.append(Call(query.op, query.table, copy.deepcopy(query.payload), list(query.filters), query.columns))
        fault = next(
            (f for f in self.faults if f.op == query.op and f.table == query.table and f.when(query.payload or {"columns": query.columns})),
            None,
        )
        if fault is not None:
            self.faults.remove(fault)
            if fault.mode == "after":
                self._apply(query)
            if fault.mode == "late":
                self._pending_after_select.setdefault(query.table, []).append(lambda fake, q=query: fake._apply(q))
            if fault.on_next_select is not None:
                self._pending_after_select.setdefault(query.table, []).append(fault.on_next_select)
            if fault.after_raise is not None:
                fault.after_raise(self)
            raise fault.error()
        result = self._apply(query)
        if query.op == "select":
            for pending in self._pending_after_select.pop(query.table, []):
                pending(self)
        return result


def recording_client(fail_updates: frozenset = frozenset()) -> tuple:
    """A MagicMock client recording every update as (table, payload), in order.

    The updates at the given 0-based indices fail once with a transient error;
    supabase_call re-sends them, so each shows up twice in the record.
    """
    from unittest.mock import MagicMock

    updates: list = []
    client = MagicMock()

    def table(name: str) -> MagicMock:
        builder = MagicMock()

        def update(payload: dict) -> MagicMock:
            index = len(updates)
            updates.append((name, copy.deepcopy(payload)))
            query = MagicMock()
            if index in fail_updates:
                query.eq.return_value.execute.side_effect = httpx.RemoteProtocolError("Server disconnected")
            return query

        builder.update.side_effect = update
        return builder

    client.table.side_effect = table
    return client, updates

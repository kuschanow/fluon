from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any, TypeGuard

from fluon._core.backend import ChangeSet
from fluon._core.errors import DuplicateIdError, TransactionClosedError, TransactionConflictError, UnknownEntityError

# Reference backend on plain dicts: the simplest thing that satisfies the Backend contract.
# A transaction works on its own copy of the state and hands it back on commit.

_Data = dict[str, dict[int, dict[str, Any]]]  # type key -> id -> field values


def _copy(data: _Data) -> _Data:
    # Two levels are enough: a row is never changed after it is created.
    return {type_key: dict(rows) for type_key, rows in data.items()}


def _is_tuple(value: object) -> TypeGuard[tuple[Any, ...]]:
    # A plain isinstance check narrows to a tuple of unknown items, which strict pyright rejects.
    return isinstance(value, tuple)


class _DictTransaction:
    def __init__(self, data: _Data, next_id: dict[str, int], commit: Callable[[_Data, dict[str, int], int], None], version: int) -> None:
        self._data = data
        self._next_id = next_id
        self._commit = commit
        self._version = version

        self._readonly = True  # a transaction that wrote nothing neither conflicts nor moves the version
        self._closed = False

    def _create(self, changes: ChangeSet, data: _Data, next_id: dict[str, int]) -> None:
        for batch in changes.created:
            type_data = data.setdefault(batch.type_key, {})
            for name, column in batch.columns.items():
                if len(column) != len(batch.ids):
                    raise ValueError(f"column {name!r} has {len(column)} values for {len(batch.ids)} ids")
            for i, id_ in enumerate(batch.ids):
                if id_ in type_data:
                    raise DuplicateIdError(batch.type_key, id_)
                # Ids need not arrive in order: operations commit in any order.
                next_id[batch.type_key] = max(next_id.get(batch.type_key, 0), id_ + 1)
                type_data[id_] = {name: column[i] for name, column in batch.columns.items()}

    def _delete(self, changes: ChangeSet, data: _Data) -> None:
        for batch in changes.deleted:
            if not batch.ids:
                continue
            type_data = data.get(batch.type_key)
            if type_data is None:
                raise UnknownEntityError(batch.type_key, batch.ids[0])
            for id_ in batch.ids:
                if id_ not in type_data:
                    raise UnknownEntityError(batch.type_key, id_)
                del type_data[id_]

    async def apply(self, changes: ChangeSet) -> None:
        if self._closed:
            raise TransactionClosedError()
        # Work on a copy and install it only at the end: a rejected change set leaves no trace.
        data = _copy(self._data)
        next_id = self._next_id.copy()

        self._create(changes, data, next_id)
        self._delete(changes, data)

        self._data = data
        self._next_id = next_id
        self._readonly = False

    async def fields(self, type_key: str, ids: Sequence[int]) -> dict[str, list[Any]]:
        if self._closed:
            raise TransactionClosedError()
        type_data = self._data.get(type_key, {})
        columns: dict[str, list[Any]] = {}
        for id_ in ids:
            entity_data = type_data.get(id_)
            if entity_data is None:
                raise UnknownEntityError(type_key, id_)
            for column_name, value in entity_data.items():
                columns.setdefault(column_name, []).append(value)
        return columns

    async def all(self, type_key: str) -> list[int]:
        if self._closed:
            raise TransactionClosedError()
        return list(self._data.get(type_key, {}).keys())

    async def referencing(self, type_key: str, field: str, targets: Sequence[int]) -> list[int]:
        if self._closed:
            raise TransactionClosedError()
        # A full scan; a real backend would keep an index. A column holds one id or a tuple of ids.
        wanted = set(targets)
        result: list[int] = []
        for id_, entity_data in self._data.get(type_key, {}).items():
            value = entity_data.get(field)
            held = value if _is_tuple(value) else (value,)
            if any(item is not None and item in wanted for item in held):
                result.append(id_)
        return sorted(result)

    async def next_id(self, type_key: str) -> int:
        if self._closed:
            raise TransactionClosedError()
        return self._next_id.get(type_key, 0)

    async def commit(self) -> None:
        if self._closed:
            raise TransactionClosedError()
        try:
            if not self._readonly:
                self._commit(self._data, self._next_id, self._version)
        finally:
            await self.close()  # closed even if the commit was rejected

    async def rollback(self) -> None:
        if self._closed:
            raise TransactionClosedError()
        self._closed = True

    async def close(self) -> None:
        self._closed = True


class DictBackend:
    def __init__(self) -> None:
        self._data: _Data = {}
        self._next_id: dict[str, int] = {}
        self._version: int = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[_DictTransaction, None]:
        tx = _DictTransaction(_copy(self._data), self._next_id.copy(), self._install, self._version)
        try:
            yield tx
        finally:
            await tx.close()

    def _install(self, data: _Data, next_id: dict[str, int], based_on: int) -> None:
        # The one place where the state changes. A transaction that started before another one
        # committed would overwrite that commit, so it is rejected instead.
        if based_on != self._version:
            raise TransactionConflictError()
        self._data = data
        self._next_id = next_id
        self._version += 1

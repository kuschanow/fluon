from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fluon._core.backend import ChangeSet
from fluon._core.errors import DuplicateIdError, TransactionClosedError, TransactionConflictError, UnknownEntityError

_Data = dict[str, dict[int, dict[str, Any]]]


def _copy(data: _Data) -> _Data:
    return {type_key: dict(rows) for type_key, rows in data.items()}


class _DictTransaction:
    def __init__(self, data: _Data, commit: Callable[[_Data, int], None], version: int) -> None:
        self._data = data
        self._commit = commit
        self._version = version

        self._readonly = True
        self._closed = False

    async def apply(self, changes: ChangeSet) -> None:
        if self._closed:
            raise TransactionClosedError()
        data = _copy(self._data)
        for batch in changes.created:
            type_data = data.setdefault(batch.type_key, {})
            for name, column in batch.columns.items():
                if len(column) != len(batch.ids):
                    raise ValueError(f"column {name!r} has {len(column)} values for {len(batch.ids)} ids")
            for i, id_ in enumerate(batch.ids):
                if id_ in type_data:
                    raise DuplicateIdError(batch.type_key, id_)
                type_data[id_] = {name: column[i] for name, column in batch.columns.items()}
        self._data = data
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

    async def commit(self) -> None:
        if self._closed:
            raise TransactionClosedError()
        try:
            if not self._readonly:
                self._commit(self._data, self._version)
        finally:
            await self.close()

    async def rollback(self) -> None:
        if self._closed:
            raise TransactionClosedError()
        self._closed = True

    async def close(self) -> None:
        self._closed = True


class DictBackend:
    def __init__(self) -> None:
        self._data: _Data = {}
        self._version: int = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[_DictTransaction, None]:
        tx = _DictTransaction(_copy(self._data), self._install, self._version)
        try:
            yield tx
        finally:
            await tx.close()

    def _install(self, data: _Data, based_on: int) -> None:
        if based_on != self._version:
            raise TransactionConflictError()
        self._data = data
        self._version += 1

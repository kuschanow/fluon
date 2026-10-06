import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from fluon._core.backend import ChangeSet, Transaction
from fluon._core.dict_backend import DictBackend
from fluon._core.entity import make_handle

T = TypeVar("T")


class FakeSource:
    """Minimal stand-in for a store: keeps field values by entity id and builds handles on request.

    The source contract used by fields:
      handle(cls, id) -> handle of a live entity
      is_alive(cls, id) -> whether the entity still exists
    """

    def __init__(self) -> None:
        self.rows: dict[int, tuple[type, dict[str, Any]]] = {}
        self.dead: set[int] = set()
        self.handle_calls = 0
        self.alive_calls = 0

    def add(self, cls: type[T], id_: int, **values: Any) -> T:
        self.rows[id_] = (cls, values)
        return make_handle(cls, self, id_, values)  # type: ignore[arg-type]

    def remove(self, id_: int) -> None:
        self.dead.add(id_)

    def handle(self, cls: type[T], id_: int) -> T:
        self.handle_calls += 1
        assert id_ not in self.dead, f"handle() called for dead entity {id_}; check is_alive() first"
        stored_cls, values = self.rows[id_]
        assert stored_cls is cls, f"entity {id_} is {stored_cls.__name__}, not {cls.__name__}"
        return make_handle(cls, self, id_, values)  # type: ignore[arg-type]

    def is_alive(self, cls: type, id_: int) -> bool:
        self.alive_calls += 1
        stored_cls, _ = self.rows[id_]
        assert stored_cls is cls, f"entity {id_} is {stored_cls.__name__}, not {cls.__name__}"
        return id_ not in self.dead


class _SlowTransaction:
    """Delegates to a real transaction but gives other tasks a chance to run inside every call."""

    def __init__(self, inner: Transaction, backend: "SlowBackend") -> None:
        self._inner = inner
        self._backend = backend

    async def apply(self, changes: ChangeSet) -> None:
        await asyncio.sleep(0)
        await self._inner.apply(changes)

    async def fields(self, type_key: str, ids: Sequence[int]) -> dict[str, list[Any]]:
        await asyncio.sleep(0)
        self._backend.field_reads.append((type_key, list(ids)))
        return await self._inner.fields(type_key, ids)

    async def all(self, type_key: str) -> list[int]:
        await asyncio.sleep(0)
        return await self._inner.all(type_key)

    async def existing(self, type_key: str, ids: Sequence[int]) -> list[int]:
        await asyncio.sleep(0)
        self._backend.existence_checks.append((type_key, list(ids)))
        return await self._inner.existing(type_key, ids)

    async def referencing(self, type_key: str, field: str, targets: Sequence[int]) -> list[int]:
        await asyncio.sleep(0)
        return await self._inner.referencing(type_key, field, targets)

    async def next_id(self, type_key: str) -> int:
        await asyncio.sleep(0)
        if self._backend.fail_marks:
            raise RuntimeError("backend is down")
        return await self._inner.next_id(type_key)

    async def commit(self) -> None:
        await asyncio.sleep(0)
        await self._inner.commit()

    async def rollback(self) -> None:
        await asyncio.sleep(0)
        await self._inner.rollback()


class SlowBackend:
    """A DictBackend whose every call suspends, like a backend doing real I/O; records what it was asked."""

    def __init__(self) -> None:
        self.inner = DictBackend()
        self.transactions = 0
        self.field_reads: list[tuple[str, list[int]]] = []  # every `fields` call: (type key, ids)
        self.existence_checks: list[tuple[str, list[int]]] = []  # every `existing` call
        self.fail_marks = False

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[_SlowTransaction, None]:
        self.transactions += 1
        async with self.inner.transaction() as tx:
            yield _SlowTransaction(tx, self)

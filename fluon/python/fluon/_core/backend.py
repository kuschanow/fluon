from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class CreatedBatch:
    type_key: str
    ids: Sequence[int]
    columns: Mapping[str, Sequence[Any]] = field(default_factory=dict[str, Sequence[Any]])


@dataclass(frozen=True)
class ChangeSet:
    created: Sequence[CreatedBatch] = ()


class Transaction(Protocol):
    async def apply(self, changes: ChangeSet) -> None: ...

    async def fields(self, type_key: str, ids: Sequence[int]) -> dict[str, list[Any]]: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class Backend(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[Transaction]: ...

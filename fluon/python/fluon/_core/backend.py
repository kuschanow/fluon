from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol

# The contract between the store and whatever keeps its state.
#
# A backend knows nothing about entity semantics: no classes, no references, no cascades. It is told
# which rows to write and asked for columns of rows by id. Data travels as columns, one batch per type,
# so that a columnar backend can serve it without converting.
#
# Ids are integers issued by the store; every type has its own id space, so a row is addressed by
# (type key, id). `fluon.testing.BackendContract` is the executable form of this contract.


@dataclass(frozen=True)
class CreatedBatch:
    """New entities of one type: columns[name][i] is the value of field `name` for ids[i]."""

    type_key: str
    ids: Sequence[int]
    columns: Mapping[str, Sequence[Any]] = field(default_factory=dict[str, Sequence[Any]])


@dataclass(frozen=True)
class DeletedBatch:
    """Entities of one type to remove."""

    type_key: str
    ids: Sequence[int]


@dataclass(frozen=True)
class ChangeSet:
    """Everything a transaction is asked to write at once. Creations are applied before deletions."""

    created: Sequence[CreatedBatch] = ()
    deleted: Sequence[DeletedBatch] = ()


class Transaction(Protocol):
    """A consistent view of the backend plus the changes made through it.

    Reads see the state as of the start and the transaction's own writes. Nothing is stored
    without `commit`; a finished transaction rejects every call.
    """

    async def apply(self, changes: ChangeSet) -> None:
        """Write a change set as a whole: if any part is rejected, none of it is written."""
        ...

    async def fields(self, type_key: str, ids: Sequence[int]) -> dict[str, list[Any]]:
        """Columns of the given entities, each in the order of `ids`."""
        ...

    async def all(self, type_key: str) -> list[int]:
        """Ids of every entity of a type, ascending."""
        ...

    async def referencing(self, type_key: str, field: str, targets: Sequence[int]) -> list[int]:
        """Ids of the entities holding one of `targets` in column `field`, ascending.

        The backend does not know which columns are references: the store names the column.
        """
        ...

    async def next_id(self, type_key: str) -> int:
        """One past the highest id ever written for a type; the store continues numbering from it."""
        ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class Backend(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[Transaction]: ...

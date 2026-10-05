"""Static check that the bundled backend satisfies the Backend contract.

This file is never executed; it is checked by mypy and pyright (see `make typecheck`).
"""

from typing import Any

from fluon import Backend, ChangeSet, CreatedBatch, Transaction
from fluon._core.dict_backend import DictBackend

backend: Backend = DictBackend()


async def usage(tx: Transaction) -> None:
    await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", (1, 2), {"label": ("a", "b")})]))
    columns: dict[str, list[Any]] = await tx.fields("graph.Node", (1, 2))
    mark: int = await tx.next_id("graph.Node")
    ids: list[int] = await tx.all("graph.Node")
    carriers: list[int] = await tx.referencing("graph.Edge", "u", (1, 2))
    await tx.commit()
    del columns, mark, ids, carriers

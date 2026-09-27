from typing import Any, TypeVar

from fluon._core.entity import make_handle

T = TypeVar("T")


class FakeSource:
    """Minimal stand-in for a store: keeps field values by entity id and builds handles on request.

    The source contract used by fields:
      handle(cls, id) -> handle of a live entity
      alive(cls, id)  -> whether the entity still exists
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
        assert id_ not in self.dead, f"handle() called for dead entity {id_}; check alive() first"
        stored_cls, values = self.rows[id_]
        assert stored_cls is cls, f"entity {id_} is {stored_cls.__name__}, not {cls.__name__}"
        return make_handle(cls, self, id_, values)  # type: ignore[arg-type]

    def alive(self, cls: type, id_: int) -> bool:
        self.alive_calls += 1
        stored_cls, _ = self.rows[id_]
        assert stored_cls is cls, f"entity {id_} is {stored_cls.__name__}, not {cls.__name__}"
        return id_ not in self.dead

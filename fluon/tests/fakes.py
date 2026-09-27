from typing import Any, TypeVar

from fluon._core.entity import make_handle

T = TypeVar("T")


class FakeSource:
    """Minimal stand-in for a store: keeps field values by entity id and builds handles on request."""

    def __init__(self) -> None:
        self.rows: dict[int, tuple[type, dict[str, Any]]] = {}
        self.handle_calls = 0

    def add(self, cls: type[T], id_: int, **values: Any) -> T:
        self.rows[id_] = (cls, values)
        return make_handle(cls, self, id_, values)  # type: ignore[arg-type]

    def handle(self, cls: type[T], id_: int) -> T:
        self.handle_calls += 1
        stored_cls, values = self.rows[id_]
        assert stored_cls is cls, f"entity {id_} is {stored_cls.__name__}, not {cls.__name__}"
        return make_handle(cls, self, id_, values)  # type: ignore[arg-type]

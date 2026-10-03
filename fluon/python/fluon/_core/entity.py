from collections.abc import Callable
from typing import Any, TypeVar, dataclass_transform

from fluon._core.errors import FrozenEntityError, NoActiveOperationError
from fluon._core.registry import Registry
from fluon._core.registry import registry as default_registry
from fluon._core.types.field import Field

T = TypeVar("T")


def _entity_init(self: object, **kwargs: Any) -> None:
    raise NoActiveOperationError("Entity instances cannot be initialized directly. Use the appropriate factory method.")


def _frozen_setattr(obj: object, name: str, value: Any) -> None:
    raise FrozenEntityError(name)


class _HandleMethods:
    """Methods copied onto every entity class. Never instantiated."""

    _src: Any
    _id: int

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return self._id == other._id and self._src is other._src

    def __hash__(self) -> int:
        return hash((id(self._src), self._id))

    def __repr__(self) -> str:
        return f"<{type(self).__name__} #{self._id}>"


def make_handle(cls: type[T], src: str, id: int, values: dict[str, Any]) -> T:
    obj = object.__new__(cls)
    object.__setattr__(obj, "_src", src)
    object.__setattr__(obj, "_id", id)
    object.__setattr__(obj, "_values", values)
    return obj


@dataclass_transform(frozen_default=True, kw_only_default=True)
def entity(type_key: str, *, version: int, registry: Registry | None = None) -> Callable[[type[T]], type[T]]:
    def wrap(cls: type[T]) -> type[T]:
        target = registry or default_registry
        target.register(type_key, version, cls)
        for name in cls.__annotations__:
            setattr(cls, name, Field(name))
        setattr(cls, "__fluon_registry__", target)
        setattr(cls, "__init__", _entity_init)
        setattr(cls, "__setattr__", _frozen_setattr)
        setattr(cls, "__repr__", _HandleMethods.__repr__)
        setattr(cls, "__eq__", _HandleMethods.__eq__)
        setattr(cls, "__hash__", _HandleMethods.__hash__)
        return cls

    return wrap

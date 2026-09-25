from collections.abc import Callable
from typing import Any, TypeVar

from fluon._core.errors import FrozenEntityError, NoActiveOperationError, TypeKeyCollisionError
from fluon._core.types.field import Field

T = TypeVar("T")

_registry: dict[str, type] = {}  # TODO: replace with actual registry implementation


def _entity_init(self: object, **kwargs: Any) -> None:
    raise NoActiveOperationError("Entity instances cannot be initialized directly. Use the appropriate factory method.")


def _frozen_setattr(obj: object, name: str, value: Any) -> None:
    raise FrozenEntityError(name)


def make_handle(cls: type[T], src: str, id: int, values: dict[str, Any]) -> T:
    obj = object.__new__(cls)
    object.__setattr__(obj, "_src", src)
    object.__setattr__(obj, "_id", id)
    object.__setattr__(obj, "_values", values)
    return obj


def entity(type_key: str, *, version: int) -> Callable[[type[T]], type[T]]:
    def wrap(cls: type[T]) -> type[T]:
        if type_key in _registry:
            raise TypeKeyCollisionError(type_key)
        _registry[type_key] = cls
        for name in cls.__annotations__:
            setattr(cls, name, Field(name))
        setattr(cls, "__init__", _entity_init)
        setattr(cls, "__setattr__", _frozen_setattr)
        return cls

    return wrap

from collections.abc import Callable
from typing import Any, ClassVar, TypeVar, dataclass_transform, get_origin

from fluon._core.errors import FrozenEntityError, InvalidFieldNameError, NoActiveOperationError
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


def _is_class_var(annotation: object) -> bool:
    if isinstance(annotation, str):
        # "ClassVar[int]" -> "ClassVar", " typing.ClassVar[int] " -> "typing.ClassVar"
        head = annotation.split("[", 1)[0].strip()
        return head in ("ClassVar", "typing.ClassVar")
    return annotation is ClassVar or get_origin(annotation) is ClassVar


@dataclass_transform(frozen_default=True, kw_only_default=True)
def entity(type_key: str, *, version: int, registry: Registry | None = None) -> Callable[[type[T]], type[T]]:
    def wrap(cls: type[T]) -> type[T]:
        names = [name for name, annotation in cls.__annotations__.items() if not _is_class_var(annotation)]
        for name in names:
            if name.startswith("_"):
                raise InvalidFieldNameError(cls, name)
        target = registry if registry is not None else default_registry
        target.register(type_key, version, cls)
        for name in names:
            has_default = name in cls.__dict__
            if has_default:
                default_value = cls.__dict__[name]
            else:
                default_value = None
            setattr(cls, name, Field(name, has_default=has_default, default=default_value))
        setattr(cls, "__fluon_registry__", target)
        setattr(cls, "__init__", _entity_init)
        setattr(cls, "__setattr__", _frozen_setattr)
        setattr(cls, "__repr__", _HandleMethods.__repr__)
        setattr(cls, "__eq__", _HandleMethods.__eq__)
        setattr(cls, "__hash__", _HandleMethods.__hash__)
        return cls

    return wrap

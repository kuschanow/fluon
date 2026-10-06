from collections.abc import Callable
from typing import Any, ClassVar, TypeVar, dataclass_transform, get_origin

from fluon._core.errors import FrozenEntityError, InvalidFieldNameError
from fluon._core.registry import Registry
from fluon._core.registry import registry as default_registry
from fluon._core.types.field import Field, resolve

T = TypeVar("T")


def _entity_init(self: object, **kwargs: Any) -> None:
    # Installed as __init__ of every entity class. Calling the class only describes a new entity:
    # the object has no id and no store until it is passed to `op.add`. Handles of existing entities
    # are built by make_handle, which skips __init__.
    cls = type(self)
    resolve(cls)
    fields = {name: attr for name, attr in vars(cls).items() if isinstance(attr, Field)}
    if extra := set(kwargs) - set(fields):
        raise TypeError(f"{cls.__name__} got unexpected keyword arguments: {', '.join(repr(name) for name in sorted(extra))}")
    values: dict[str, Any] = {}
    for name, field in fields.items():
        if name in kwargs:
            given = kwargs[name]
        elif field.has_default:
            given = field.default
        else:
            raise TypeError(f"{cls.__name__} is missing required field {name!r}")
        assert field.field_type is not None
        try:
            values[name] = field.field_type.accept(given)
        except TypeError as e:
            raise TypeError(f"{cls.__name__}.{name}: {e}") from None
    fill_draft(self, values)


def _frozen_setattr(obj: object, name: str, value: Any) -> None:
    # Installed as __setattr__ of every entity class: the structure of an entity never changes.
    # The core itself writes handle attributes through object.__setattr__.
    raise FrozenEntityError(name)


class _HandleMethods:
    """Methods copied onto every entity class. Never instantiated."""

    _src: Any
    _id: int | None

    # A handle is identified by (source, type, id), never by the Python object or by field values.
    # An entity that is not added yet has no id: it is equal only to itself.

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        if self._id is None:
            return self is other
        return self._id == other._id and self._src is other._src

    def __hash__(self) -> int:
        # A hash must never change, and the identity of a new entity appears only when it is added.
        if self._id is None:
            raise TypeError(f"unhashable: {self!r} is not added to a store yet")
        # id() of the source, to match the `is` in __eq__ and to work with unhashable sources.
        return hash((id(self._src), self._id))

    def __repr__(self) -> str:
        # Identity only: repr must stay cheap and work for unloaded and dead entities alike.
        if self._id is None:
            return f"<{type(self).__name__} (not added)>"
        return f"<{type(self).__name__} #{self._id}>"


def fill_handle(obj: object, src: Any, id_: int, values: dict[str, Any] | None) -> None:
    """Attach identity and field values to an entity object, bypassing the frozen __setattr__.

    `values` is None for a handle that is not loaded. Calling this again on the same object replaces
    its values and keeps everything else it has accumulated.
    """
    object.__setattr__(obj, "_src", src)
    object.__setattr__(obj, "_id", id_)
    object.__setattr__(obj, "_values", values)
    object.__setattr__(obj, "_draft", None)
    if not hasattr(obj, "_refs"):
        object.__setattr__(obj, "_refs", {})  # resolved references: field name -> handle(s)
        object.__setattr__(obj, "_op", None)  # the operation creating this entity, until it is written
        object.__setattr__(obj, "_dead", False)  # True if the entity is known to be deleted in its source


def fill_draft(obj: object, values: dict[str, Any]) -> None:
    """Make an entity object a new, not yet added entity: no source, no id, field values as accepted."""
    object.__setattr__(obj, "_src", None)
    object.__setattr__(obj, "_id", None)  # None is what marks the entity as not added
    object.__setattr__(obj, "_values", None)
    object.__setattr__(obj, "_draft", values)  # what `op.add` turns into stored values
    object.__setattr__(obj, "_refs", {})
    object.__setattr__(obj, "_op", None)
    object.__setattr__(obj, "_dead", False)


def make_handle(cls: type[T], src: Any, id_: int, values: dict[str, Any] | None) -> T:
    """Create a handle of an existing entity without calling __init__."""
    obj = object.__new__(cls)
    fill_handle(obj, src, id_, values)
    return obj


def set_operation(obj: object, operation: object | None) -> None:
    """Record which operation is creating the entity; None once the entity is written to the backend."""
    object.__setattr__(obj, "_op", operation)


def unload(obj: object) -> None:
    """Forget the field values of a handle: the backend no longer confirms them."""
    object.__setattr__(obj, "_values", None)


def mark_dead(obj: object) -> None:
    """Mark a handle as dead: the backend no longer confirms its existence."""
    unload(obj)
    object.__setattr__(obj, "_dead", True)


def _is_class_var(annotation: object) -> bool:
    # Annotations are not evaluated at decoration time, so with `from __future__ import annotations`
    # a ClassVar arrives here as text.
    if isinstance(annotation, str):
        # "ClassVar[int]" -> "ClassVar", " typing.ClassVar[int] " -> "typing.ClassVar"
        head = annotation.split("[", 1)[0].strip()
        return head in ("ClassVar", "typing.ClassVar")
    return annotation is ClassVar or get_origin(annotation) is ClassVar


@dataclass_transform(frozen_default=True, kw_only_default=True)
def entity(type_key: str, *, version: int, registry: Registry | None = None) -> Callable[[type[T]], type[T]]:
    """Register a class as an entity type.

    `dataclass_transform` is a promise to type checkers: __init__ takes the fields by keyword and
    instances are frozen. It does nothing at run time; this decorator keeps the promise itself.
    """

    def wrap(cls: type[T]) -> type[T]:
        # Everything that can fail comes before the class is touched: a rejected class stays as it was.
        names = [name for name, annotation in cls.__annotations__.items() if not _is_class_var(annotation)]
        for name in names:
            if name.startswith("_"):
                raise InvalidFieldNameError(cls, name)
        target = registry if registry is not None else default_registry
        target.register(type_key, version, cls)
        # Annotations are only remembered here; their types are resolved on first use (see `resolve`),
        # when every class they mention exists.
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

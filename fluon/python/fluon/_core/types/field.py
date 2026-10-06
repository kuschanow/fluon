from typing import Any, get_type_hints

from fluon._core.context import current_operation
from fluon._core.errors import CrossRegistryReferenceError, EntityNotAliveError, NotAddedError, NotLoadedError, UnresolvedAnnotationError
from fluon._core.types.field_type import FieldType, Reference, parse
from fluon._core.utils import registry_of


def resolve(cls: type) -> None:
    """Parse the annotations of an entity class and give every field its type.

    Done on first use rather than in the decorator: by then every class an annotation mentions
    exists, including the class itself and classes declared later.
    """
    if not any(isinstance(attr, Field) for attr in vars(cls).values()):
        return
    try:
        # localns lets a class declared inside a function refer to itself.
        hints = get_type_hints(cls, localns={cls.__name__: cls})
    except NameError as e:
        raise UnresolvedAnnotationError(cls.__name__, str(e.name)) from e
    # The decorator decided what is a field by installing a Field; ClassVars have none.
    for name, attr in vars(cls).items():
        if not isinstance(attr, Field):
            continue
        field_type = parse(hints[name])
        if isinstance(field_type, Reference) and registry_of(field_type.target) is not registry_of(cls):
            raise CrossRegistryReferenceError(cls, name, field_type.target)
        attr.field_type = field_type


def _removed_now(obj: Any) -> bool:
    operation = current_operation.get()
    return operation is not None and operation.store is obj._src and (type(obj), obj._id) in operation.removed


class Field:
    """The descriptor installed on an entity class for each of its fields.

    Reads the value from the handle; a reference is turned into the handle (or Link) of its target.
    """

    def __init__(self, name: str, field_type: FieldType | None = None, has_default: bool = False, default: Any = None) -> None:
        self.name = name
        self.field_type = field_type
        self.has_default = has_default
        self._default = default

    @property
    def default(self) -> Any:
        if not self.has_default:
            raise AttributeError(f"Field '{self.name}' has no default value")
        return self._default

    def __get__(self, obj: Any, owner: type) -> Any:
        if obj is None:
            return self
        if obj._id is None:
            raise NotAddedError(obj)
        if obj._dead or _removed_now(obj):
            raise EntityNotAliveError(obj)
        # None in place of the whole dict means "not loaded"; None inside it is an ordinary value.
        if obj._values is None:
            raise NotLoadedError(obj)
        raw = obj._values[self.name]
        if self.field_type is None:
            resolve(owner)
            assert self.field_type is not None
        if not isinstance(self.field_type, Reference):
            return self.field_type.load(obj._src, raw)
        # Only references are cached: the handle keeps the handles it refers to. The store holds
        # handles only weakly, so without this `edge.u` would be a new, unloaded object on every read
        # and a load would not stick.
        if self.name not in obj._refs:
            obj._refs[self.name] = self.field_type.load(obj._src, raw)
        return obj._refs[self.name]

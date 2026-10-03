from typing import Any, get_type_hints

from fluon._core.errors import CrossRegistryReferenceError, UnresolvedAnnotationError
from fluon._core.types.field_type import FieldType, Reference, parse
from fluon._core.utils import registry_of


def resolve(cls: type) -> None:
    """Resolve forward references in the annotations of a class."""
    try:
        hints = get_type_hints(cls, localns={cls.__name__: cls})
    except NameError as e:
        raise UnresolvedAnnotationError(cls.__name__, str(e.name)) from e
    for name, attr in vars(cls).items():
        if not isinstance(attr, Field):
            continue
        field_type = parse(hints[name])
        if isinstance(field_type, Reference) and registry_of(field_type.target) is not registry_of(cls):
            raise CrossRegistryReferenceError(cls, name, field_type.target)
        attr.field_type = field_type


class Field:
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
        raw = obj._values[self.name]
        if self.field_type is None:
            resolve(owner)
            assert self.field_type is not None
        return self.field_type.load(obj._src, raw)

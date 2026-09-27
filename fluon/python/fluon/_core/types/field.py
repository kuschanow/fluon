from typing import Any, get_type_hints

from fluon._core.errors import UnresolvedAnnotationError
from fluon._core.types.field_type import FieldType, Reference, parse


def resolve(cls: type) -> None:
    """Resolve forward references in the annotations of a class."""
    try:
        hints = get_type_hints(cls, localns={cls.__name__: cls})
    except NameError as e:
        raise UnresolvedAnnotationError(cls.__name__, str(e.name)) from e
    for name, hint in hints.items():
        cls.__dict__[name].field_type = parse(hint)


class Field:
    def __init__(self, name: str, field_type: FieldType | None = None) -> None:
        self.name = name
        self.field_type = field_type

    def __get__(self, obj: Any, owner: type) -> Any:
        if obj is None:
            return self
        raw = obj._values[self.name]
        if self.field_type is None:
            resolve(owner)
        if isinstance(self.field_type, Reference):
            return obj._src.handle(self.field_type.target, raw)
        return raw

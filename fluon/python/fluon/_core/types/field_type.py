from dataclasses import dataclass
from enum import Enum
from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin

from fluon._core.errors import FieldTypeError
from fluon._core.types.descriptors import Link, OptionalRef, OptionalRefs, Ref, Refs


class FieldType:
    def load(self, src: Any, raw: Any) -> Any:
        """Turn a stored value into what the user sees. Plain values are returned as stored."""
        return raw


@dataclass(frozen=True)
class Scalar(FieldType):
    """A scalar type, such as int, str, or float."""

    typ: type


@dataclass(frozen=True)
class Reference(FieldType):
    """A reference to another entity type: Ref, OptionalRef, Refs or OptionalRefs."""

    target: type
    optional: bool = False
    many: bool = False

    def load(self, src: Any, raw: Any) -> Any:
        """Turn a stored value into what the user sees. References are loaded from the source."""
        if self.many:
            if self.optional:
                return tuple(Link[Any](r, src, self.target) for r in raw)
            return tuple(src.handle(self.target, r) for r in raw)
        if self.optional:
            return Link[Any](raw, src, self.target)
        return src.handle(self.target, raw)


@dataclass(frozen=True)
class Nullable(FieldType):
    """A nullable type, such as int | None."""

    typ: "FieldType"


@dataclass(frozen=True)
class FixedTuple(FieldType):
    """A fixed-length tuple type, such as tuple[int, str]."""

    types: tuple["FieldType", ...]


@dataclass(frozen=True)
class VarTuple(FieldType):
    """A variable-length tuple type, such as tuple[int, ...]."""

    typ: "FieldType"


@dataclass(frozen=True)
class FrozenSetOf(FieldType):
    """A frozen set type, such as frozenset[int]."""

    typ: "FieldType"


_SCALARS: tuple[type, ...] = (bool, int, float, str, bytes, NoneType, Enum)
_MUTABLE_CONTAINERS: tuple[object, ...] = (list, dict, set)
# reference marker -> (optional, many)
_REFERENCES: dict[object, tuple[bool, bool]] = {
    Ref: (False, False),
    OptionalRef: (True, False),
    Refs: (False, True),
    OptionalRefs: (True, True),
}


def parse(hint: object) -> FieldType:
    """Parse a resolved field annotation into a FieldType, or raise FieldTypeError."""
    return _parse(hint, in_container=False)


def _parse(hint: object, *, in_container: bool) -> FieldType:
    origin, args = get_origin(hint), get_args(hint)

    if origin in _REFERENCES:
        return _parse_reference(hint, origin, args, in_container=in_container)
    if origin is Union or origin is UnionType:
        return _parse_nullable(hint, args, in_container=in_container)
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return VarTuple(_parse(args[0], in_container=True))
        return FixedTuple(tuple(_parse(arg, in_container=True) for arg in args))
    if origin is frozenset:
        return FrozenSetOf(_parse(args[0], in_container=True))
    if hint in _MUTABLE_CONTAINERS or origin in _MUTABLE_CONTAINERS:
        raise FieldTypeError(hint, "mutable containers are not allowed; use tuple[...] or frozenset[...]")
    if isinstance(hint, type) and issubclass(hint, _SCALARS):
        return Scalar(hint)
    raise FieldTypeError(
        hint,
        "supported field types are bool, int, float, str, bytes, None, Enum, "
        "tuple[...], frozenset[...], X | None and Ref/OptionalRef/Refs/OptionalRefs",
    )


def _parse_reference(hint: object, origin: object, args: tuple[object, ...], *, in_container: bool) -> Reference:
    if in_container:
        raise FieldTypeError(hint, "references are not allowed inside tuple[...] or frozenset[...]; use Refs[...] or OptionalRefs[...]")
    target = args[0]
    if not isinstance(target, type):
        raise FieldTypeError(hint, f"reference target must be a class, got {target!r}")
    optional, many = _REFERENCES[origin]
    return Reference(target, optional=optional, many=many)


def _parse_nullable(hint: object, args: tuple[object, ...], *, in_container: bool) -> Nullable:
    others = [arg for arg in args if arg is not NoneType]
    if len(others) != 1:
        raise FieldTypeError(hint, "the only supported union is X | None")
    inner = _parse(others[0], in_container=in_container)
    if isinstance(inner, Reference):
        raise FieldTypeError(hint, "references cannot be nullable; OptionalRef[...] already allows an empty link")
    return Nullable(inner)

import enum
from typing import Optional, Union

import pytest

from fluon._core.errors import FieldTypeError
from fluon._core.types.descriptors import OptionalRef, OptionalRefs, Ref, Refs
from fluon._core.types.field_type import (
    FixedTuple,
    FrozenSetOf,
    Nullable,
    Reference,
    Scalar,
    VarTuple,
    parse,
)


class Node:
    pass


class Color(enum.Enum):
    RED = 1
    GREEN = 2


# --- Scalars ---


@pytest.mark.parametrize("hint", [bool, int, float, str, bytes])
def test_builtin_scalar(hint: type) -> None:
    assert parse(hint) == Scalar(hint)


def test_none_is_scalar() -> None:
    # get_type_hints turns a `None` annotation into NoneType.
    assert parse(type(None)) == Scalar(type(None))


def test_enum_is_scalar() -> None:
    assert parse(Color) == Scalar(Color)


def test_scalars_of_different_types_differ() -> None:
    assert parse(int) != parse(bool)


# --- References ---


def test_ref() -> None:
    assert parse(Ref[Node]) == Reference(Node, optional=False, many=False)


def test_optional_ref() -> None:
    assert parse(OptionalRef[Node]) == Reference(Node, optional=True, many=False)


def test_refs() -> None:
    assert parse(Refs[Node]) == Reference(Node, optional=False, many=True)


def test_optional_refs() -> None:
    assert parse(OptionalRefs[Node]) == Reference(Node, optional=True, many=True)


def test_reference_remembers_target() -> None:
    class Other:
        pass

    assert parse(Ref[Node]) != parse(Ref[Other])


# --- Nullable ---


def test_pipe_none_is_nullable() -> None:
    assert parse(int | None) == Nullable(Scalar(int))


def test_none_first_is_nullable() -> None:
    assert parse(None | int) == Nullable(Scalar(int))


def test_typing_optional_is_nullable() -> None:
    assert parse(Optional[int]) == Nullable(Scalar(int))  # noqa: UP045


def test_typing_union_with_none_is_nullable() -> None:
    assert parse(Union[str, None]) == Nullable(Scalar(str))  # noqa: UP007


# --- Tuples and frozensets ---


def test_fixed_tuple() -> None:
    assert parse(tuple[int, str]) == FixedTuple((Scalar(int), Scalar(str)))


def test_variadic_tuple() -> None:
    assert parse(tuple[int, ...]) == VarTuple(Scalar(int))


def test_frozenset() -> None:
    assert parse(frozenset[str]) == FrozenSetOf(Scalar(str))


def test_nested_containers() -> None:
    assert parse(tuple[tuple[int, ...], frozenset[str] | None]) == FixedTuple((VarTuple(Scalar(int)), Nullable(FrozenSetOf(Scalar(str)))))


def test_nullable_inside_tuple() -> None:
    assert parse(tuple[int | None, ...]) == VarTuple(Nullable(Scalar(int)))


# --- Rejected: mutable containers ---


@pytest.mark.parametrize("hint", [list, list[int], dict, dict[str, int], set, set[int]])
def test_mutable_container_is_rejected(hint: object) -> None:
    with pytest.raises(FieldTypeError, match=r"tuple\[\.\.\.\]|frozenset\[\.\.\.\]"):
        parse(hint)


def test_mutable_container_nested_in_tuple_is_rejected() -> None:
    with pytest.raises(FieldTypeError):
        parse(tuple[list[int], ...])


# --- Rejected: references inside containers ---


@pytest.mark.parametrize(
    "hint",
    [
        tuple[Ref[Node] | None, ...],
        tuple[Ref[Node], ...],
        tuple[OptionalRef[Node], int],
        frozenset[Ref[Node]],
        tuple[Refs[Node], ...],
    ],
)
def test_reference_inside_container_is_rejected(hint: object) -> None:
    with pytest.raises(FieldTypeError, match="Refs"):
        parse(hint)


# --- Rejected: everything else ---


@pytest.mark.parametrize("hint", [int | str, int | str | None, Union[int, str]])  # noqa: UP007
def test_union_of_two_types_is_rejected(hint: object) -> None:
    with pytest.raises(FieldTypeError, match="None"):
        parse(hint)


def test_bare_tuple_is_rejected() -> None:
    with pytest.raises(FieldTypeError):
        parse(tuple)


def test_bare_frozenset_is_rejected() -> None:
    with pytest.raises(FieldTypeError):
        parse(frozenset)


@pytest.mark.parametrize("hint", [object, Node, complex])
def test_unsupported_type_is_rejected(hint: object) -> None:
    with pytest.raises(FieldTypeError):
        parse(hint)


def test_error_names_the_offending_type() -> None:
    with pytest.raises(FieldTypeError, match="complex"):
        parse(complex)


def test_unsupported_type_error_does_not_blame_mutable_containers() -> None:
    with pytest.raises(FieldTypeError) as exc_info:
        parse(complex)
    assert "mutable" not in str(exc_info.value)


# --- Rejected: nullable references ---


@pytest.mark.parametrize("hint", [Ref[Node] | None, Optional[Refs[Node]], OptionalRef[Node] | None])  # noqa: UP045
def test_nullable_reference_is_rejected(hint: object) -> None:
    # A descriptor inside a union breaks typing; an empty link is already OptionalRef.
    with pytest.raises(FieldTypeError, match="OptionalRef"):
        parse(hint)


def test_unresolved_reference_target_is_rejected() -> None:
    with pytest.raises(FieldTypeError, match="class"):
        parse(Ref["Node"])

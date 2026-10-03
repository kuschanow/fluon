from typing import ClassVar

import pytest
from fakes import FakeSource

from fluon._core.entity import entity
from fluon._core.errors import InvalidFieldNameError
from fluon._core.registry import registry
from fluon._core.types.field import Field, resolve

# --- An entity may have no fields at all ---


def test_entity_without_fields(src: FakeSource) -> None:
    @entity("decl.Marker", version=1)
    class Marker:
        pass

    resolve(Marker)
    marker = src.add(Marker, 1)

    assert repr(marker) == "<Marker #1>"


# --- Field names starting with an underscore are reserved for the handle internals ---


@pytest.mark.parametrize("name", ["_hidden", "__private", "_id", "_src", "_values"])
def test_underscore_field_name_is_rejected(name: str) -> None:
    with pytest.raises(InvalidFieldNameError, match=name):
        entity("decl.Bad", version=1)(type("Bad", (), {"__annotations__": {name: int}}))


def test_invalid_field_name_error_names_the_class() -> None:
    with pytest.raises(InvalidFieldNameError, match="Bad") as exc_info:

        @entity("decl.Bad", version=1)
        class Bad:
            _hidden: int

    assert exc_info.value.field == "_hidden"


def test_class_with_an_invalid_field_name_is_not_registered() -> None:
    class Bad:
        ok: int
        _hidden: int

    with pytest.raises(InvalidFieldNameError):
        entity("decl.Bad", version=1)(Bad)

    assert not registry.is_registered(Bad)
    assert "ok" not in Bad.__dict__


# --- ClassVar annotations are class attributes, not fields ---


def test_class_var_is_not_a_field(src: FakeSource) -> None:
    @entity("decl.Counter", version=1)
    class Counter:
        limit: ClassVar[int] = 10
        count: int

    counter = src.add(Counter, 1, count=3)

    assert Counter.limit == 10
    assert counter.limit == 10
    assert counter.count == 3
    assert not isinstance(Counter.__dict__["limit"], Field)


def test_class_var_does_not_break_resolution() -> None:
    @entity("decl.Counter", version=1)
    class Counter:
        registry_hint: ClassVar[list[int]] = []  # a mutable ClassVar is fine: it is not stored
        count: int

    resolve(Counter)

    assert Counter.__dict__["count"].field_type is not None


def test_bare_class_var_is_not_a_field() -> None:
    @entity("decl.Counter", version=1)
    class Counter:
        limit: ClassVar = 10
        count: int

    resolve(Counter)

    assert Counter.limit == 10


@pytest.mark.parametrize("annotation", ["ClassVar[int]", "typing.ClassVar[int]", "ClassVar", " ClassVar[int] "])
def test_class_var_written_as_a_string_is_not_a_field(annotation: str) -> None:
    # With `from __future__ import annotations` every annotation reaches the decorator as a string.
    cls = type("Counter", (), {"__annotations__": {"limit": annotation, "count": "int"}, "limit": 10})

    entity("decl.Counter", version=1)(cls)

    assert cls.__dict__["limit"] == 10
    assert isinstance(cls.__dict__["count"], Field)


def test_field_whose_name_merely_contains_class_var_is_a_field() -> None:
    cls = type("Odd", (), {"__annotations__": {"value": "MyClassVarLike"}})

    entity("decl.Odd", version=1)(cls)

    assert isinstance(cls.__dict__["value"], Field)


# --- Defaults survive the decorator ---


def test_field_default_is_kept() -> None:
    @entity("decl.Edge", version=1)
    class Edge:
        weight: float = 1.0
        label: str = ""

    assert Edge.__dict__["weight"].has_default
    assert Edge.__dict__["weight"].default == 1.0
    assert Edge.__dict__["label"].default == ""


def test_field_without_a_default() -> None:
    @entity("decl.Edge", version=1)
    class Edge:
        weight: float

    assert not Edge.__dict__["weight"].has_default


def test_none_is_a_real_default() -> None:
    @entity("decl.Note", version=1)
    class Note:
        text: str | None = None
        other: str | None

    assert Note.__dict__["text"].has_default
    assert Note.__dict__["text"].default is None
    assert not Note.__dict__["other"].has_default


def test_reading_the_default_of_a_field_without_one_is_an_error() -> None:
    @entity("decl.Edge", version=1)
    class Edge:
        weight: float

    with pytest.raises(AttributeError, match="weight"):
        _ = Edge.__dict__["weight"].default


def test_stored_value_wins_over_the_default(src: FakeSource) -> None:
    @entity("decl.Edge", version=1)
    class Edge:
        weight: float = 1.0

    edge = src.add(Edge, 1, weight=2.5)

    assert edge.weight == 2.5

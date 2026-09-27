import pytest
from fakes import FakeSource

from fluon._core.entity import entity
from fluon._core.errors import FieldTypeError, UnresolvedAnnotationError
from fluon._core.types.descriptors import Ref
from fluon._core.types.field import resolve

# Module-level types: forward references are resolved against module globals, like in real user code.
# They are registered once at import; the autouse fixture in conftest.py gives every test its own empty registry.


@entity("lazy.Folder", version=1)
class Folder:
    name: str
    parent: Ref["Folder"]


@entity("lazy.Wire", version=1)
class Wire:
    plug: Ref["Plug"]  # Plug is declared below


@entity("lazy.Plug", version=1)
class Plug:
    label: str


@entity("lazy.Left", version=1)
class Left:
    right: Ref["Right"]


@entity("lazy.Right", version=1)
class Right:
    left: Ref[Left]


# --- Forward references ---


def test_self_reference(src: FakeSource) -> None:
    src.add(Folder, 1, name="root", parent=1)
    docs = src.add(Folder, 2, name="docs", parent=1)

    assert docs.parent.name == "root"
    assert docs.parent.parent.name == "root"


def test_reference_to_a_class_declared_later(src: FakeSource) -> None:
    src.add(Plug, 1, label="out")
    wire = src.add(Wire, 2, plug=1)

    assert wire.plug.label == "out"


def test_mutual_references(src: FakeSource) -> None:
    src.add(Left, 1, right=2)
    right = src.add(Right, 2, left=1)

    assert isinstance(right.left, Left)
    assert isinstance(right.left.right, Right)


def test_self_reference_in_a_local_class(src: FakeSource) -> None:
    # A class can always refer to itself by name, even when declared inside a function.
    @entity("lazy.LocalNode", version=1)
    class LocalNode:
        next: Ref["LocalNode"]

    node = src.add(LocalNode, 1, next=1)

    assert isinstance(node.next, LocalNode)


# --- Resolution is lazy ---


def test_decoration_does_not_resolve_annotations() -> None:
    @entity("lazy.Broken", version=1)
    class Broken:
        target: Ref["Missing"]  # type: ignore[name-defined]  # noqa: F821

    assert Broken.__dict__["target"].field_type is None


def test_field_type_is_filled_on_first_read(src: FakeSource) -> None:
    @entity("lazy.Item", version=1)
    class Item:
        count: int

    item = src.add(Item, 1, count=3)
    assert Item.__dict__["count"].field_type is None

    _ = item.count

    assert Item.__dict__["count"].field_type is not None


def test_first_read_resolves_all_fields_of_the_class(src: FakeSource) -> None:
    @entity("lazy.Item", version=1)
    class Item:
        count: int
        name: str

    item = src.add(Item, 1, count=3, name="a")
    _ = item.count

    assert Item.__dict__["name"].field_type is not None


# --- Errors surface on first use, not at import ---


def test_unresolvable_name_fails_on_first_read(src: FakeSource) -> None:
    @entity("lazy.Broken", version=1)
    class Broken:
        target: Ref["Missing"]  # type: ignore[name-defined]  # noqa: F821

    broken = src.add(Broken, 1, target=1)

    with pytest.raises(UnresolvedAnnotationError, match="Missing"):
        _ = broken.target


def test_unresolvable_name_error_names_the_class(src: FakeSource) -> None:
    @entity("lazy.Broken", version=1)
    class Broken:
        target: Ref["Missing"]  # type: ignore[name-defined]  # noqa: F821

    broken = src.add(Broken, 1, target=1)

    with pytest.raises(UnresolvedAnnotationError, match="Broken"):
        _ = broken.target


def test_unresolvable_name_breaks_every_field_of_the_class(src: FakeSource) -> None:
    @entity("lazy.Broken", version=1)
    class Broken:
        count: int
        target: Ref["Missing"]  # type: ignore[name-defined]  # noqa: F821

    broken = src.add(Broken, 1, count=3, target=1)

    with pytest.raises(UnresolvedAnnotationError):
        _ = broken.count


def test_invalid_field_type_fails_on_first_read_not_at_decoration(src: FakeSource) -> None:
    @entity("lazy.Bad", version=1)
    class Bad:
        items: list[int]

    bad = src.add(Bad, 1, items=[1])

    with pytest.raises(FieldTypeError):
        _ = bad.items


# --- Explicit resolution ---


def test_resolve_fills_all_field_types() -> None:
    @entity("lazy.Item", version=1)
    class Item:
        count: int
        name: str

    resolve(Item)

    assert Item.__dict__["count"].field_type is not None
    assert Item.__dict__["name"].field_type is not None


def test_resolve_raises_on_unresolvable_name() -> None:
    @entity("lazy.Broken", version=1)
    class Broken:
        target: Ref["Missing"]  # type: ignore[name-defined]  # noqa: F821

    with pytest.raises(UnresolvedAnnotationError, match="Missing"):
        resolve(Broken)


def test_resolve_raises_on_invalid_field_type() -> None:
    @entity("lazy.Bad", version=1)
    class Bad:
        items: list[int]

    with pytest.raises(FieldTypeError):
        resolve(Bad)


def test_resolve_is_idempotent(src: FakeSource) -> None:
    resolve(Wire)
    resolve(Wire)

    src.add(Plug, 1, label="out")
    wire = src.add(Wire, 2, plug=1)

    assert wire.plug.label == "out"

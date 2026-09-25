import pytest

import fluon._core.entity as entity_module
from fluon._core.entity import entity, make_handle
from fluon._core.errors import FrozenEntityError, NoActiveOperationError, TypeKeyCollisionError
from fluon._core.types.field import Field


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    # The registry is global: each test gets an empty one so type keys never collide between tests.
    monkeypatch.setattr(entity_module, "_registry", {})


# --- Registration ---


def test_decorator_returns_same_class() -> None:
    class Node:
        label: str

    assert entity("graph.Node", version=1)(Node) is Node


def test_registered_class_is_found_by_key() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    assert entity_module._registry["graph.Node"] is Node


def test_duplicate_key_is_rejected() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    with pytest.raises(TypeKeyCollisionError, match="graph.Node"):

        @entity("graph.Node", version=1)
        class Other:
            label: str


def test_rejected_duplicate_keeps_first_class() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    with pytest.raises(TypeKeyCollisionError):

        @entity("graph.Node", version=1)
        class Other:
            label: str

    assert entity_module._registry["graph.Node"] is Node


def test_version_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        entity("graph.Node", 1)  # type: ignore[misc]


# --- Handles and reading plain fields ---


def test_field_is_read_from_handle_values() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str
        weight: float

    n = make_handle(Node, "store", 1, {"label": "a", "weight": 2.5})

    assert n.label == "a"
    assert n.weight == 2.5


def test_handle_is_instance_of_entity_class() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    assert isinstance(make_handle(Node, "store", 1, {"label": "a"}), Node)


def test_handle_keeps_source_and_id() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    n = make_handle(Node, "store", 7, {"label": "a"})

    assert n._src == "store"  # type: ignore[attr-defined]
    assert n._id == 7  # type: ignore[attr-defined]


def test_class_access_returns_field_descriptor() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    assert isinstance(Node.__dict__["label"], Field)
    assert isinstance(Node.label, Field)


def test_handles_do_not_share_values() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    a = make_handle(Node, "store", 1, {"label": "a"})
    b = make_handle(Node, "store", 2, {"label": "b"})

    assert (a.label, b.label) == ("a", "b")


def test_direct_construction_needs_operation() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    with pytest.raises(NoActiveOperationError):
        Node(label="a")  # type: ignore[call-arg]


# --- Immutability ---


def test_field_cannot_be_assigned() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    n = make_handle(Node, "store", 1, {"label": "a"})

    with pytest.raises(FrozenEntityError, match="label"):
        n.label = "b"
    assert n.label == "a"


def test_new_attribute_cannot_be_assigned() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    n = make_handle(Node, "store", 1, {"label": "a"})

    with pytest.raises(FrozenEntityError, match="other"):
        n.other = 1  # type: ignore[attr-defined]


def test_internal_attributes_cannot_be_assigned() -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    n = make_handle(Node, "store", 1, {"label": "a"})

    with pytest.raises(FrozenEntityError):
        n._id = 2  # type: ignore[attr-defined]
    assert n._id == 1  # type: ignore[attr-defined]

import pytest
from fakes import FakeSource

from fluon import alive, id_of
from fluon._core.entity import entity
from fluon._core.types.descriptors import OptionalRef


@entity("introspection.Node", version=1)
class Node:
    label: str


@entity("introspection.Product", version=1)
class Product:
    # Field names that would clash with handle methods if the handle had any.
    id: str
    alive: bool


@entity("introspection.Note", version=1)
class Note:
    target: OptionalRef[Node]


# --- id_of ---


def test_id_of_returns_the_entity_id(src: FakeSource) -> None:
    node = src.add(Node, 7, label="a")

    assert id_of(node) == 7


def test_id_of_is_independent_of_a_user_field_named_id(src: FakeSource) -> None:
    product = src.add(Product, 7, id="SKU-1", alive=False)

    assert product.id == "SKU-1"
    assert id_of(product) == 7


def test_id_of_does_not_touch_the_source(src: FakeSource) -> None:
    node = src.add(Node, 7, label="a")

    id_of(node)

    assert (src.handle_calls, src.alive_calls) == (0, 0)


def test_id_of_works_for_a_removed_entity(src: FakeSource) -> None:
    node = src.add(Node, 7, label="a")
    src.remove(7)

    assert id_of(node) == 7


# --- alive ---


def test_alive_is_true_for_an_existing_entity(src: FakeSource) -> None:
    node = src.add(Node, 7, label="a")

    assert alive(node) is True


def test_alive_is_false_after_removal(src: FakeSource) -> None:
    node = src.add(Node, 7, label="a")
    src.remove(7)

    assert alive(node) is False


def test_alive_is_not_cached(src: FakeSource) -> None:
    node = src.add(Node, 7, label="a")
    assert alive(node) is True

    src.remove(7)

    assert alive(node) is False


def test_alive_is_independent_of_a_user_field_named_alive(src: FakeSource) -> None:
    product = src.add(Product, 7, id="SKU-1", alive=False)

    assert product.alive is False
    assert alive(product) is True


# --- Only entity handles are accepted ---


@pytest.mark.parametrize("value", [42, "node", None, object()])
def test_id_of_rejects_non_entities(value: object) -> None:
    with pytest.raises(TypeError, match="entity"):
        id_of(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [42, "node", None, object()])
def test_alive_rejects_non_entities(value: object) -> None:
    with pytest.raises(TypeError, match="entity"):
        alive(value)  # type: ignore[arg-type]


def test_entity_class_itself_is_rejected() -> None:
    with pytest.raises(TypeError, match="entity"):
        id_of(Node)  # type: ignore[arg-type]


def test_link_is_rejected(src: FakeSource) -> None:
    # A Link has its own .id and .alive; passing it here is almost certainly a mistake.
    src.add(Node, 1, label="a")
    note = src.add(Note, 2, target=1)

    with pytest.raises(TypeError, match="entity"):
        id_of(note.target)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="entity"):
        alive(note.target)  # type: ignore[arg-type]


def test_object_that_merely_looks_like_a_handle_is_rejected(src: FakeSource) -> None:
    # Having `_id` and `_src` is not enough: only instances of registered entity types count.
    class Impostor:
        def __init__(self, src: FakeSource) -> None:
            self._id = 1
            self._src = src

    with pytest.raises(TypeError, match="entity"):
        id_of(Impostor(src))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="entity"):
        alive(Impostor(src))  # type: ignore[arg-type]

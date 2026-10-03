from fakes import FakeSource

from fluon._core.entity import entity
from fluon._core.types.descriptors import Ref


@entity("identity.Node", version=1)
class Node:
    label: str


@entity("identity.Edge", version=1)
class Edge:
    u: Ref[Node]
    v: Ref[Node]


# --- Equality: a handle is identified by (source, id), not by the Python object ---


def test_two_handles_of_the_same_entity_are_equal(src: FakeSource) -> None:
    src.add(Node, 1, label="a")

    first = src.handle(Node, 1)
    second = src.handle(Node, 1)

    assert first is not second
    assert first == second


def test_handles_of_different_entities_are_not_equal(src: FakeSource) -> None:
    a = src.add(Node, 1, label="a")
    b = src.add(Node, 2, label="a")

    assert a != b


def test_handles_from_different_sources_are_not_equal() -> None:
    live, snapshot = FakeSource(), FakeSource()
    a = live.add(Node, 1, label="a")
    b = snapshot.add(Node, 1, label="a")

    assert a != b


def test_handle_is_not_equal_to_other_objects(src: FakeSource) -> None:
    a = src.add(Node, 1, label="a")

    assert a != 1
    assert a != "a"
    assert a != None  # noqa: E711


def test_equality_ignores_field_values(src: FakeSource) -> None:
    # Fields are immutable and loaded with the handle, so identity alone decides equality.
    a = src.add(Node, 1, label="a")
    same_entity = src.handle(Node, 1)

    assert a == same_entity


def test_handle_read_through_a_reference_equals_a_direct_handle(src: FakeSource) -> None:
    node = src.add(Node, 1, label="a")
    edge = src.add(Edge, 2, u=1, v=1)

    assert edge.u == node
    assert edge.u == edge.v


# --- Hashing ---


def test_equal_handles_have_equal_hashes(src: FakeSource) -> None:
    src.add(Node, 1, label="a")

    assert hash(src.handle(Node, 1)) == hash(src.handle(Node, 1))


def test_handles_work_as_set_members(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    src.add(Node, 2, label="b")

    nodes = {src.handle(Node, 1), src.handle(Node, 1), src.handle(Node, 2)}

    assert len(nodes) == 2


def test_handles_work_as_dict_keys(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    visited = {src.handle(Node, 1): "seen"}

    assert visited[src.handle(Node, 1)] == "seen"


# --- Representation ---


def test_repr_names_the_type_and_the_id(src: FakeSource) -> None:
    node = src.add(Node, 7, label="a")

    assert repr(node) == "<Node #7>"


def test_repr_does_not_read_fields(src: FakeSource) -> None:
    # repr must stay cheap and safe: no source calls, usable even for a dead entity.
    src.add(Node, 1, label="a")
    edge = src.add(Edge, 2, u=1, v=1)

    repr(edge)

    assert (src.handle_calls, src.alive_calls) == (0, 0)


def test_handles_are_hashable_even_if_the_source_is_not() -> None:
    class UnhashableSource(FakeSource):
        __hash__ = None  # type: ignore[assignment]

    src = UnhashableSource()
    src.add(Node, 1, label="a")

    assert hash(src.handle(Node, 1)) == hash(src.handle(Node, 1))
    assert len({src.handle(Node, 1), src.handle(Node, 1)}) == 1

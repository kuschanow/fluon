from fakes import FakeSource

from fluon._core.entity import entity
from fluon._core.types.descriptors import Ref

# --- Scalars are returned as stored ---


def test_scalar_fields_are_returned_as_stored(src: FakeSource) -> None:
    @entity("test.Item", version=1)
    class Item:
        count: int
        name: str
        tags: tuple[str, ...]
        note: str | None

    item = src.add(Item, 1, count=3, name="a", tags=("x", "y"), note=None)

    assert (item.count, item.name, item.tags, item.note) == (3, "a", ("x", "y"), None)


def test_reading_a_scalar_does_not_touch_the_source(src: FakeSource) -> None:
    @entity("test.Item", version=1)
    class Item:
        count: int

    item = src.add(Item, 1, count=3)
    _ = item.count

    assert src.handle_calls == 0


# --- Ref fields return the target's handle ---


def test_ref_field_returns_a_handle_of_the_target(src: FakeSource) -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    @entity("graph.Edge", version=1)
    class Edge:
        u: Ref[Node]

    src.add(Node, 7, label="a")
    edge = src.add(Edge, 1, u=7)

    assert isinstance(edge.u, Node)
    assert edge.u._id == 7  # type: ignore[attr-defined]


def test_target_handle_reads_its_own_fields(src: FakeSource) -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    @entity("graph.Edge", version=1)
    class Edge:
        u: Ref[Node]

    src.add(Node, 7, label="a")
    edge = src.add(Edge, 1, u=7)

    assert edge.u.label == "a"


def test_target_handle_comes_from_the_same_source(src: FakeSource) -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    @entity("graph.Edge", version=1)
    class Edge:
        u: Ref[Node]

    src.add(Node, 7, label="a")
    edge = src.add(Edge, 1, u=7)

    assert edge.u._src is src  # type: ignore[attr-defined]


def test_each_ref_field_points_to_its_own_target(src: FakeSource) -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    @entity("graph.Edge", version=1)
    class Edge:
        u: Ref[Node]
        v: Ref[Node]
        weight: float

    src.add(Node, 7, label="a")
    src.add(Node, 9, label="b")
    edge = src.add(Edge, 1, u=7, v=9, weight=1.5)

    assert (edge.u.label, edge.v.label, edge.weight) == ("a", "b", 1.5)


def test_refs_to_different_entity_types(src: FakeSource) -> None:
    @entity("graph.Node", version=1)
    class Node:
        label: str

    @entity("sockets.Socket", version=1)
    class Socket:
        node: Ref[Node]
        name: str

    @entity("sockets.Wire", version=1)
    class Wire:
        src_socket: Ref[Socket]
        dst_node: Ref[Node]

    src.add(Node, 1, label="n")
    src.add(Socket, 2, node=1, name="out")
    wire = src.add(Wire, 3, src_socket=2, dst_node=1)

    assert isinstance(wire.src_socket, Socket)
    assert isinstance(wire.dst_node, Node)
    assert wire.src_socket.node.label == "n"

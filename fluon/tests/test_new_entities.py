import pytest

from fluon import OptionalRef, OptionalRefs, Ref, Refs, Store, alive, entity, id_of
from fluon._core.dict_backend import DictBackend
from fluon._core.errors import FrozenEntityError, NotAddedError

# Calling an entity class only describes a new entity. Until it is passed to `op.add` it has no id
# and no store: it can be handed to `op.add` or used as a reference of another new entity, nothing else.


@entity("new_entities.Node", version=1)
class Node:
    label: str = ""


@entity("new_entities.Edge", version=1)
class Edge:
    u: Ref[Node]
    v: Ref[Node]
    weight: float = 1.0


@entity("new_entities.Note", version=1)
class Note:
    target: OptionalRef[Node]


@entity("new_entities.Team", version=1)
class Team:
    owners: Refs[Node]
    members: OptionalRefs[Node]


@pytest.fixture
def store() -> Store:
    return Store(DictBackend())


# --- Building needs no operation and no store ---


def test_entity_is_built_without_an_operation() -> None:
    node = Node(label="a")

    assert isinstance(node, Node)


def test_entities_are_built_from_other_new_entities() -> None:
    a, b = Node(), Node()

    Edge(u=a, v=b)
    Note(target=a)
    Note(target=None)
    Team(owners=[a, b], members=(b, None))


def test_repr_says_the_entity_is_not_added() -> None:
    assert repr(Node(label="a")) == "<Node (not added)>"


def test_new_entity_is_frozen() -> None:
    node = Node(label="a")

    with pytest.raises(FrozenEntityError):
        node.label = "b"  # type: ignore[misc]


# --- A new entity has no identity yet ---


def test_new_entity_has_no_id() -> None:
    with pytest.raises(NotAddedError, match="op.add"):
        id_of(Node())


def test_new_entity_cannot_be_asked_whether_it_is_alive() -> None:
    with pytest.raises(NotAddedError):
        alive(Node())


def test_fields_of_a_new_entity_cannot_be_read() -> None:
    node = Node(label="a")

    with pytest.raises(NotAddedError, match="Node"):
        _ = node.label


def test_new_entity_is_equal_only_to_itself() -> None:
    a, same_fields = Node(label="a"), Node(label="a")

    assert a == a
    assert a != same_fields
    assert a != "a"


def test_new_entity_is_not_hashable() -> None:
    with pytest.raises(TypeError, match="not added"):
        hash(Node())


async def test_new_entity_cannot_be_loaded(store: Store) -> None:
    with pytest.raises(NotAddedError):
        await store.load(Node())
    with pytest.raises(NotAddedError):
        await store.reload(Node())


# --- Adding gives it one ---


async def test_added_entity_gets_its_identity(store: Store) -> None:
    node, other = Node(label="a"), Node(label="a")

    async with store.op() as op:
        op.add(node)
        op.add(other)

    assert id_of(node) == 0
    assert repr(node) == "<Node #0>"
    assert node.label == "a"
    assert node == node and node != other
    assert len({node, other}) == 2


# --- Arguments are checked when the entity is built ---


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(TypeError, match="colour"):
        Node(colour="red")  # type: ignore[call-arg]


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(TypeError, match="'v'"):
        Edge(u=Node())  # type: ignore[call-arg]


def test_positional_arguments_are_rejected() -> None:
    with pytest.raises(TypeError):
        Node("a")  # type: ignore[misc]


def test_ref_must_be_an_entity() -> None:
    with pytest.raises(TypeError, match=r"Edge\.u"):
        Edge(u=0, v=Node())  # type: ignore[arg-type]


def test_ref_must_be_an_entity_of_the_declared_type() -> None:
    a = Node()
    edge = Edge(u=a, v=a)

    with pytest.raises(TypeError, match="expected Node"):
        Edge(u=edge, v=a)  # type: ignore[arg-type]


def test_ref_cannot_be_none() -> None:
    with pytest.raises(TypeError, match=r"Edge\.v"):
        Edge(u=Node(), v=None)  # type: ignore[arg-type]


def test_element_of_a_reference_collection_must_be_an_entity() -> None:
    with pytest.raises(TypeError, match=r"Team\.owners"):
        Team(owners=[Node(), "b"], members=[])  # type: ignore[list-item]


async def test_reference_collection_is_read_once_when_the_entity_is_built(store: Store) -> None:
    a, b = Node(label="a"), Node(label="b")
    owners = [a, b]
    team = Team(owners=(n for n in owners), members=owners)
    owners.clear()

    async with store.op() as op:
        op.add(a)
        op.add(b)
        op.add(team)

    assert team.owners == (a, b)
    assert [m.id for m in team.members] == [0, 1]

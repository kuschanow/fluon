import pytest
from fakes import SlowBackend

from fluon import Backend, Ref, Refs, Store, entity, id_of
from fluon._core.backend import ChangeSet, DeletedBatch
from fluon._core.dict_backend import DictBackend
from fluon._core.errors import NotLoadedError, UnknownEntityError


@entity("store_read.Node", version=1)
class Node:
    label: str = ""


@entity("store_read.Edge", version=1)
class Edge:
    u: Ref[Node]
    v: Ref[Node]
    weight: float = 1.0


@entity("store_read.Team", version=1)
class Team:
    owners: Refs[Node]


@entity("store_read.Marker", version=1)
class Marker:
    pass


NODE = "store_read.Node"


@pytest.fixture
def backend() -> Backend:
    return DictBackend()


@pytest.fixture
async def store(backend: Backend) -> Store:
    """A store that did not create the data it reads: nodes a(0), b(1), c(2); edges 0: a->b, 1: b->c; team {a, c}."""
    writer = Store(backend)
    async with writer.op() as op:
        a, b, c = op.add(Node(label="a")), op.add(Node(label="b")), op.add(Node(label="c"))
        op.add(Edge(u=a, v=b, weight=0.5))
        op.add(Edge(u=b, v=c))
        op.add(Team(owners=[a, c]))
        op.add(Marker())
    return Store(backend)


async def delete_in_backend(backend: Backend, type_key: str, *ids: int) -> None:
    async with backend.transaction() as tx:
        await tx.apply(ChangeSet(deleted=[DeletedBatch(type_key, ids)]))
        await tx.commit()


# --- Fetching one entity ---


async def test_fetch_returns_a_loaded_handle(store: Store) -> None:
    node = await store.fetch(Node, 1)

    assert isinstance(node, Node)
    assert id_of(node) == 1
    assert node.label == "b"


async def test_fetch_reads_every_field(store: Store) -> None:
    edge = await store.fetch(Edge, 0)

    assert edge.weight == 0.5
    assert id_of(edge.u) == 0
    assert id_of(edge.v) == 1


async def test_fetch_of_an_entity_without_fields(store: Store) -> None:
    marker = await store.fetch(Marker, 0)

    assert repr(marker) == "<Marker #0>"


async def test_fetch_needs_no_operation(store: Store) -> None:
    assert (await store.fetch(Node, 0)).label == "a"


async def test_fetching_twice_gives_equal_handles(store: Store) -> None:
    assert await store.fetch(Node, 2) == await store.fetch(Node, 2)


async def test_fetch_of_an_unknown_id_is_rejected(store: Store) -> None:
    with pytest.raises(UnknownEntityError, match="99"):
        await store.fetch(Node, 99)


async def test_fetch_uses_the_id_space_of_the_requested_type(store: Store) -> None:
    # Node 0 and Edge 0 are different entities.
    assert isinstance(await store.fetch(Node, 0), Node)
    assert isinstance(await store.fetch(Edge, 0), Edge)
    with pytest.raises(UnknownEntityError):
        await store.fetch(Edge, 2)


async def test_fetched_handle_equals_the_one_from_creation(backend: Backend) -> None:
    store = Store(backend)
    async with store.op() as op:
        created = op.add(Node(label="a"))

    assert await store.fetch(Node, 0) == created


# --- Fetching all entities of a type ---


async def test_all_returns_loaded_handles_sorted_by_id(store: Store) -> None:
    nodes = await store.all(Node)

    assert [id_of(n) for n in nodes] == [0, 1, 2]
    assert [n.label for n in nodes] == ["a", "b", "c"]


async def test_all_returns_only_the_requested_type(store: Store) -> None:
    assert [id_of(e) for e in await store.all(Edge)] == [0, 1]
    assert all(isinstance(e, Edge) for e in await store.all(Edge))


async def test_all_of_a_type_without_entities_is_empty(backend: Backend) -> None:
    assert await Store(backend).all(Node) == []


async def test_all_skips_deleted_entities(store: Store, backend: Backend) -> None:
    await delete_in_backend(backend, "store_read.Edge", 0)

    assert [id_of(e) for e in await store.all(Edge)] == [1]


# --- A reference gives a handle that may not be loaded yet ---


async def test_reference_gives_a_handle_with_identity(store: Store) -> None:
    edge = await store.fetch(Edge, 1)

    assert isinstance(edge.u, Node)
    assert id_of(edge.u) == 1
    assert repr(edge.u) == "<Node #1>"


async def test_fields_of_an_unloaded_handle_cannot_be_read(store: Store) -> None:
    edge = await store.fetch(Edge, 1)

    with pytest.raises(NotLoadedError, match="load"):
        _ = edge.u.label


async def test_not_loaded_error_names_the_entity(store: Store) -> None:
    edge = await store.fetch(Edge, 1)

    with pytest.raises(NotLoadedError, match="Node #1"):
        _ = edge.u.label


async def test_unloaded_handle_equals_the_loaded_one(store: Store) -> None:
    edge = await store.fetch(Edge, 0)

    assert edge.v == await store.fetch(Node, 1)
    assert hash(edge.v) == hash(await store.fetch(Node, 1))


async def test_same_target_read_twice_is_the_same_entity(store: Store) -> None:
    first, second = await store.fetch(Edge, 0), await store.fetch(Edge, 1)

    assert first.v == second.u
    assert len({first.u, first.v, second.u, second.v}) == 3


async def test_reference_collection_gives_handles(store: Store) -> None:
    team = await store.fetch(Team, 0)

    assert [id_of(n) for n in team.owners] == [0, 2]
    assert all(isinstance(n, Node) for n in team.owners)


# --- Loading on request ---


async def test_load_makes_fields_readable(store: Store) -> None:
    edge = await store.fetch(Edge, 1)

    await store.load(edge.u)

    assert edge.u.label == "b"


async def test_load_takes_several_handles_of_several_types(store: Store) -> None:
    edge = await store.fetch(Edge, 1)
    team = await store.fetch(Team, 0)

    await store.load(edge.u, edge.v, *team.owners)

    assert (edge.u.label, edge.v.label) == ("b", "c")
    assert [n.label for n in team.owners] == ["a", "c"]


async def test_load_accepts_loaded_handles_and_repeats(store: Store) -> None:
    node = await store.fetch(Node, 0)
    edge = await store.fetch(Edge, 0)

    await store.load(node, edge.u, edge.u, edge.v)

    assert (edge.u.label, edge.v.label) == ("a", "b")


async def test_load_of_nothing_is_fine(store: Store) -> None:
    await store.load()


async def test_handle_stays_loaded(store: Store) -> None:
    edge = await store.fetch(Edge, 1)
    await store.load(edge.u)

    again = await store.fetch(Edge, 1)

    assert again.u.label == "b"


async def test_fetch_loads_handles_obtained_earlier_through_a_reference(store: Store) -> None:
    # One entity has one state per store: loading it anywhere makes it loaded everywhere.
    edge = await store.fetch(Edge, 1)
    target = edge.u

    await store.fetch(Node, 1)

    assert target.label == "b"


async def test_all_loads_handles_obtained_earlier_through_a_reference(store: Store) -> None:
    edge = await store.fetch(Edge, 1)
    target = edge.v

    await store.all(Node)

    assert target.label == "c"


async def test_loading_a_deleted_entity_is_rejected(store: Store, backend: Backend) -> None:
    edge = await store.fetch(Edge, 1)
    await delete_in_backend(backend, NODE, 1)

    with pytest.raises(UnknownEntityError, match="1"):
        await store.load(edge.u)


# --- An unloaded handle is good enough to refer to ---


async def test_unloaded_handle_can_be_used_as_a_reference(store: Store, backend: Backend) -> None:
    edge = await store.fetch(Edge, 0)

    async with store.op() as op:
        shortcut = op.add(Edge(u=edge.v, v=edge.u))

    async with backend.transaction() as tx:
        assert await tx.fields("store_read.Edge", [id_of(shortcut)]) == {"u": [1], "v": [0], "weight": [1.0]}


# --- Reads inside an operation see the operation's own creations ---


async def test_fetch_inside_an_operation_sees_its_own_creation(store: Store) -> None:
    async with store.op() as op:
        created = op.add(Node(label="new"))

        assert await store.fetch(Node, id_of(created)) == created
        assert (await store.fetch(Node, id_of(created))).label == "new"


async def test_all_inside_an_operation_includes_its_own_creations(store: Store) -> None:
    async with store.op() as op:
        op.add(Node(label="new"))

        assert [n.label for n in await store.all(Node)] == ["a", "b", "c", "new"]


async def test_creations_of_an_operation_are_invisible_to_another_store(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        op.add(Node(label="new"))

        assert [n.label for n in await Store(backend).all(Node)] == ["a", "b", "c"]


async def test_entity_of_a_discarded_operation_cannot_be_fetched(store: Store) -> None:
    # The handle is still around, but the entity never reached the backend.
    with pytest.raises(RuntimeError):
        async with store.op() as op:
            lost = op.add(Node(label="lost"))
            raise RuntimeError

    with pytest.raises(UnknownEntityError):
        await store.fetch(Node, id_of(lost))
    assert [n.label for n in await store.all(Node)] == ["a", "b", "c"]


# --- A handle keeps the handles it refers to ---


async def test_reading_a_reference_twice_gives_the_same_object(store: Store) -> None:
    # Otherwise loading `edge.u` would be lost by the time `edge.u.label` is read.
    edge = await store.fetch(Edge, 1)

    assert edge.u is edge.u
    assert edge.u is not edge.v


async def test_reading_a_reference_collection_twice_gives_the_same_objects(store: Store) -> None:
    team = await store.fetch(Team, 0)

    assert all(first is second for first, second in zip(team.owners, team.owners, strict=True))


async def test_entity_is_one_object_while_it_is_referenced(store: Store) -> None:
    node = await store.fetch(Node, 1)
    edge = await store.fetch(Edge, 1)

    assert edge.u is node
    assert await store.fetch(Node, 1) is node


# --- The store does not ask the backend for what it already holds ---
#
# The store is the only writer to its backend, so a loaded entity it has seen written stays valid.


@pytest.fixture
async def recording() -> tuple[Store, SlowBackend]:
    """Same data as `store`, on a backend that records every read."""
    backend = SlowBackend()
    writer = Store(backend)
    async with writer.op() as op:
        a, b, c = op.add(Node(label="a")), op.add(Node(label="b")), op.add(Node(label="c"))
        op.add(Edge(u=a, v=b, weight=0.5))
        op.add(Edge(u=b, v=c))
    del a, b, c
    backend.field_reads.clear()
    backend.transactions = 0
    return Store(backend), backend


async def test_fetch_of_an_entity_not_seen_before_reads_it_once(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording

    await store.fetch(Node, 1)

    assert backend.field_reads == [(NODE, [1])]


async def test_fetch_of_a_loaded_entity_does_not_touch_the_backend(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording
    node = await store.fetch(Node, 1)
    backend.transactions = 0

    again = await store.fetch(Node, 1)

    assert again is node
    assert backend.transactions == 0


async def test_fetch_of_an_entity_created_here_does_not_touch_the_backend() -> None:
    backend = SlowBackend()
    store = Store(backend)
    async with store.op() as op:
        created = op.add(Node(label="a"))
    backend.transactions = 0

    assert await store.fetch(Node, 0) is created
    assert backend.transactions == 0


async def test_fetch_of_an_unloaded_handle_reads_it(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording
    edge = await store.fetch(Edge, 0)
    target = edge.u
    backend.field_reads.clear()

    await store.fetch(Node, 0)

    assert backend.field_reads == [(NODE, [0])]
    assert target.label == "a"


async def test_entity_of_a_discarded_operation_is_looked_up_in_the_backend() -> None:
    backend = SlowBackend()
    store = Store(backend)
    with pytest.raises(RuntimeError):
        async with store.op() as op:
            lost = op.add(Node(label="lost"))
            raise RuntimeError
    backend.field_reads.clear()

    with pytest.raises(UnknownEntityError):
        await store.fetch(Node, id_of(lost))

    assert backend.field_reads == [(NODE, [0])]


async def test_all_reads_every_entity_when_none_is_loaded(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording

    await store.all(Node)

    assert backend.field_reads == [(NODE, [0, 1, 2])]


async def test_all_reads_only_the_entities_not_loaded_yet(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording
    held = await store.fetch(Node, 1)
    backend.field_reads.clear()

    nodes = await store.all(Node)

    assert backend.field_reads == [(NODE, [0, 2])]
    assert [n.label for n in nodes] == ["a", "b", "c"]
    assert nodes[1] is held


async def test_all_reads_no_fields_when_everything_is_loaded(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording
    first = await store.all(Node)
    backend.field_reads.clear()

    second = await store.all(Node)

    assert backend.field_reads == []
    assert all(a is b for a, b in zip(first, second, strict=True))


async def test_all_still_asks_which_entities_exist(recording: tuple[Store, SlowBackend]) -> None:
    # The list of ids is the one thing the store cannot know by itself.
    store, backend = recording
    held = await store.all(Node)
    backend.transactions = 0

    await store.all(Node)

    assert backend.transactions == 1
    assert len(held) == 3


async def test_load_reads_only_the_handles_not_loaded_yet(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording
    edge = await store.fetch(Edge, 1)
    loaded = await store.fetch(Node, 1)
    backend.field_reads.clear()

    await store.load(loaded, edge.u, edge.v)

    assert backend.field_reads == [(NODE, [2])]


async def test_load_of_loaded_handles_does_not_touch_the_backend(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording
    nodes = await store.all(Node)
    backend.transactions = 0

    await store.load(*nodes)

    assert backend.transactions == 0


# --- Forced reload ---


async def test_reload_reads_loaded_entities_again(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording
    node = await store.fetch(Node, 1)
    backend.field_reads.clear()

    await store.reload(node)

    assert backend.field_reads == [(NODE, [1])]
    assert node.label == "b"


async def test_reload_loads_an_unloaded_handle(store: Store) -> None:
    edge = await store.fetch(Edge, 1)

    await store.reload(edge.u)

    assert edge.u.label == "b"


async def test_reload_takes_several_handles_of_several_types(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording
    edge = await store.fetch(Edge, 0)
    nodes = await store.all(Node)
    backend.field_reads.clear()

    await store.reload(edge, nodes[2], nodes[0], nodes[2])

    assert sorted(backend.field_reads) == [("store_read.Edge", [0]), (NODE, [2, 0])]


async def test_reload_of_nothing_is_fine(store: Store) -> None:
    await store.reload()


async def test_reload_keeps_the_object_and_what_it_refers_to(store: Store) -> None:
    edge = await store.fetch(Edge, 1)
    target = edge.u
    await store.load(target)

    await store.reload(edge)

    assert edge.u is target
    assert edge.u.label == "b"


async def test_reload_of_a_deleted_entity_is_rejected(store: Store, backend: Backend) -> None:
    # The way to find out that something outside this store changed the backend.
    node = await store.fetch(Node, 2)
    await delete_in_backend(backend, "store_read.Edge", 1)
    await delete_in_backend(backend, NODE, 2)

    with pytest.raises(UnknownEntityError, match="2"):
        await store.reload(node)


async def test_fetch_after_a_rejected_reload_asks_the_backend_again(store: Store, backend: Backend) -> None:
    node = await store.fetch(Node, 2)
    await delete_in_backend(backend, "store_read.Edge", 1)
    await delete_in_backend(backend, NODE, 2)
    with pytest.raises(UnknownEntityError):
        await store.reload(node)

    with pytest.raises(UnknownEntityError):
        await store.fetch(Node, 2)


# --- Entities being created have nothing to load ---


async def test_load_and_reload_skip_entities_of_the_current_operation(recording: tuple[Store, SlowBackend]) -> None:
    store, backend = recording

    async with store.op() as op:
        created = op.add(Node(label="new"))
        backend.transactions = 0

        await store.load(created)
        await store.reload(created)

        assert backend.transactions == 0
        assert created.label == "new"

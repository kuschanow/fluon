import asyncio

import pytest
from fakes import SlowBackend

from fluon import Backend, OptionalRef, OptionalRefs, Ref, Refs, Registry, Store, entity, id_of
from fluon._core.backend import ChangeSet, CreatedBatch
from fluon._core.context import current_operation
from fluon._core.dict_backend import DictBackend
from fluon._core.errors import (
    AlreadyAddedError,
    ForeignEntityError,
    NoActiveOperationError,
    NotAddedError,
    NotRegisteredError,
    UnknownEntityError,
)


@entity("store_create.Node", version=1)
class Node:
    label: str = ""


@entity("store_create.Edge", version=1)
class Edge:
    u: Ref[Node]
    v: Ref[Node]
    weight: float = 1.0


@entity("store_create.Note", version=1)
class Note:
    target: OptionalRef[Node]


@entity("store_create.Team", version=1)
class Team:
    owners: Refs[Node]
    members: OptionalRefs[Node]


NODE, EDGE, NOTE, TEAM = "store_create.Node", "store_create.Edge", "store_create.Note", "store_create.Team"


@pytest.fixture
def backend() -> Backend:
    return DictBackend()


@pytest.fixture
def store(backend: Backend) -> Store:
    return Store(backend)


async def stored(backend: Backend, type_key: str, *ids: int) -> dict[str, list[object]]:
    """What the backend holds for these entities."""
    async with backend.transaction() as tx:
        return await tx.fields(type_key, ids)


async def stored_ids(backend: Backend, type_key: str) -> list[int]:
    async with backend.transaction() as tx:
        return await tx.all(type_key)


# --- Adding an entity to an operation creates it ---


async def test_creation_returns_a_handle_of_the_class(store: Store) -> None:
    async with store.op() as op:
        node = op.add(Node(label="a"))

    assert isinstance(node, Node)


async def test_fields_are_readable_right_away(store: Store) -> None:
    async with store.op() as op:
        node = op.add(Node(label="a"))

        assert node.label == "a"


async def test_fields_stay_readable_after_the_operation(store: Store) -> None:
    async with store.op() as op:
        node = op.add(Node(label="a"))

    assert node.label == "a"


async def test_omitted_fields_take_their_defaults(store: Store) -> None:
    async with store.op() as op:
        a, b = op.add(Node()), op.add(Node())
        edge = op.add(Edge(u=a, v=b))

    assert a.label == ""
    assert edge.weight == 1.0


async def test_explicit_value_overrides_the_default(store: Store) -> None:
    async with store.op() as op:
        a = op.add(Node())
        edge = op.add(Edge(u=a, v=a, weight=2.5))

    assert edge.weight == 2.5


# --- Ids are issued at once, per type ---


async def test_id_is_available_before_the_operation_ends(store: Store) -> None:
    async with store.op() as op:
        node = op.add(Node())

        assert id_of(node) == 0


async def test_ids_of_a_type_count_up_from_zero(store: Store) -> None:
    async with store.op() as op:
        nodes = [op.add(Node()), op.add(Node()), op.add(Node())]

    assert [id_of(n) for n in nodes] == [0, 1, 2]


async def test_each_type_has_its_own_counter(store: Store) -> None:
    async with store.op() as op:
        a, b = op.add(Node()), op.add(Node())
        edge = op.add(Edge(u=a, v=b))
        note = op.add(Note(target=None))

    assert (id_of(a), id_of(b), id_of(edge), id_of(note)) == (0, 1, 0, 0)


async def test_counting_continues_across_operations(store: Store) -> None:
    async with store.op() as op:
        first = op.add(Node())
    async with store.op() as op:
        second = op.add(Node())

    assert (id_of(first), id_of(second)) == (0, 1)


async def test_counting_continues_from_what_the_backend_already_holds(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.apply(ChangeSet(created=[CreatedBatch(NODE, [0, 1, 2], {"label": ["a", "b", "c"]})]))
        await tx.commit()

    store = Store(backend)
    async with store.op() as op:
        node = op.add(Node())

    assert id_of(node) == 3


async def test_two_handles_of_distinct_entities_differ(store: Store) -> None:
    async with store.op() as op:
        a, b = op.add(Node(label="same")), op.add(Node(label="same"))

    assert a != b


# --- The operation writes to the backend when it ends ---


async def test_entities_reach_the_backend_when_the_operation_ends(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        op.add(Node(label="a"))
        op.add(Node(label="b"))

    assert await stored(backend, NODE, 0, 1) == {"label": ["a", "b"]}


async def test_nothing_reaches_the_backend_before_the_operation_ends(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        op.add(Node(label="a"))

        assert await stored_ids(backend, NODE) == []


async def test_defaults_are_stored(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        a = op.add(Node())
        op.add(Edge(u=a, v=a))

    assert await stored(backend, NODE, 0) == {"label": [""]}
    assert await stored(backend, EDGE, 0) == {"u": [0], "v": [0], "weight": [1.0]}


async def test_entities_of_several_types_are_stored_together(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        a, b = op.add(Node(label="a")), op.add(Node(label="b"))
        op.add(Edge(u=a, v=b, weight=0.5))
        op.add(Edge(u=b, v=a))

    assert await stored(backend, NODE, 0, 1) == {"label": ["a", "b"]}
    assert await stored(backend, EDGE, 0, 1) == {"u": [0, 1], "v": [1, 0], "weight": [0.5, 1.0]}


async def test_empty_operation_is_fine(store: Store, backend: Backend) -> None:
    async with store.op():
        pass

    assert await stored_ids(backend, NODE) == []


# --- References are stored as ids and read back as handles ---


async def test_ref_is_stored_as_the_target_id(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        op.add(Node()), op.add(Node())
        b = op.add(Node())
        op.add(Edge(u=b, v=b))

    assert await stored(backend, EDGE, 0) == {"u": [2], "v": [2], "weight": [1.0]}


async def test_ref_reads_back_as_the_target(store: Store) -> None:
    async with store.op() as op:
        a, b = op.add(Node(label="a")), op.add(Node(label="b"))
        edge = op.add(Edge(u=a, v=b))

        assert edge.u == a
        assert edge.v == b
        assert edge.v.label == "b"


async def test_ref_to_an_entity_of_an_earlier_operation(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        a = op.add(Node(label="a"))
    async with store.op() as op:
        edge = op.add(Edge(u=a, v=a))

    assert edge.u == a
    assert await stored(backend, EDGE, 0) == {"u": [0], "v": [0], "weight": [1.0]}


async def test_optional_ref_is_stored_as_the_target_id_or_none(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        a = op.add(Node())
        linked = op.add(Note(target=a))
        empty = op.add(Note(target=None))

    assert await stored(backend, NOTE, 0, 1) == {"target": [0, None]}
    assert linked.target.id == 0
    assert empty.target.id is None


async def test_reference_collections_are_stored_as_tuples_of_ids(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        a, b, c = op.add(Node()), op.add(Node()), op.add(Node())
        op.add(Team(owners=[a, b], members=(c, None, a)))
        op.add(Team(owners=(n for n in (c,)), members=[]))

    assert await stored(backend, TEAM, 0, 1) == {"owners": [(0, 1), (2,)], "members": [(2, None, 0), ()]}


async def test_reference_collections_read_back_in_order(store: Store) -> None:
    async with store.op() as op:
        a, b = op.add(Node(label="a")), op.add(Node(label="b"))
        team = op.add(Team(owners=[b, a], members=[a, None]))

        assert team.owners == (b, a)
        assert [m.id for m in team.members] == [0, None]


# --- A failed operation writes nothing ---


async def test_exception_in_the_block_discards_the_operation(store: Store, backend: Backend) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with store.op() as op:
            op.add(Node(label="a"))
            raise RuntimeError("boom")

    assert await stored_ids(backend, NODE) == []


async def test_ids_of_a_discarded_operation_are_not_issued_again(store: Store, backend: Backend) -> None:
    # Handles of the discarded entities may still be around; their ids must not start meaning something else.
    with pytest.raises(RuntimeError):
        async with store.op() as op:
            lost = op.add(Node())
            raise RuntimeError

    async with store.op() as op:
        kept = op.add(Node(label="kept"))

    assert (id_of(lost), id_of(kept)) == (0, 1)
    assert await stored_ids(backend, NODE) == [1]


async def test_store_keeps_working_after_a_discarded_operation(store: Store, backend: Backend) -> None:
    with pytest.raises(RuntimeError):
        async with store.op() as op:
            op.add(Node())
            raise RuntimeError

    async with store.op() as op:
        op.add(Node(label="a"))
        op.add(Node(label="b"))

    assert await stored(backend, NODE, 1, 2) == {"label": ["a", "b"]}


# --- op.add takes a new entity, once, while the operation runs ---


async def test_add_returns_the_entity_it_was_given(store: Store) -> None:
    node = Node(label="a")

    async with store.op() as op:
        assert op.add(node) is node


async def test_entity_may_be_built_before_the_operation(store: Store, backend: Backend) -> None:
    node = Node(label="a")

    async with store.op() as op:
        op.add(node)

    assert id_of(node) == 0
    assert await stored(backend, NODE, 0) == {"label": ["a"]}


async def test_entity_that_was_never_added_is_not_stored(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        op.add(Node(label="a"))
        Node(label="forgotten")

    assert await stored(backend, NODE, *await stored_ids(backend, NODE)) == {"label": ["a"]}


async def test_adding_twice_is_rejected(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        node = op.add(Node())
        with pytest.raises(AlreadyAddedError, match="Node #0"):
            op.add(node)

    assert await stored_ids(backend, NODE) == [0]


async def test_adding_an_entity_of_an_earlier_operation_is_rejected(store: Store) -> None:
    async with store.op() as op:
        node = op.add(Node())

    async with store.op() as op:
        with pytest.raises(AlreadyAddedError):
            op.add(node)


async def test_adding_an_entity_read_from_a_store_is_rejected(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        op.add(Node())
    other = Store(backend)
    fetched = await other.fetch(Node, 0)

    async with other.op() as op:
        with pytest.raises(AlreadyAddedError):
            op.add(fetched)


async def test_adding_something_that_is_not_an_entity_is_rejected(store: Store) -> None:
    async with store.op() as op:
        with pytest.raises(TypeError, match="entity"):
            op.add(42)
        with pytest.raises(TypeError, match="entity"):
            op.add(Node)


async def test_adding_an_entity_of_another_registry_is_rejected(store: Store) -> None:
    @entity("store_create.Alien", version=1, registry=Registry())
    class Alien:
        pass

    async with store.op() as op:
        with pytest.raises(NotRegisteredError, match="Alien"):
            op.add(Alien())


async def test_adding_through_a_finished_operation_is_rejected(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        pass
    node = Node()

    with pytest.raises(NoActiveOperationError):
        op.add(node)
    with pytest.raises(NotAddedError):
        id_of(node)
    assert await stored_ids(backend, NODE) == []


async def test_adding_through_a_failed_operation_is_rejected(store: Store) -> None:
    with pytest.raises(RuntimeError):
        async with store.op() as op:
            raise RuntimeError

    with pytest.raises(NoActiveOperationError):
        op.add(Node())


# --- What an added entity refers to must be added first, to the same store ---


async def test_entities_may_be_built_in_any_order_and_added_targets_first(store: Store, backend: Backend) -> None:
    a, b = Node(label="a"), Node(label="b")
    edge = Edge(u=a, v=b)

    async with store.op() as op:
        op.add(b)
        op.add(a)
        op.add(edge)

    assert await stored(backend, EDGE, 0) == {"u": [1], "v": [0], "weight": [1.0]}
    assert edge.u == a


async def test_ref_to_an_entity_that_is_not_added_is_rejected(store: Store) -> None:
    async with store.op() as op:
        a = op.add(Node())
        with pytest.raises(NotAddedError, match=r"Edge\.v"):
            op.add(Edge(u=a, v=Node()))


async def test_optional_ref_to_an_entity_that_is_not_added_is_rejected(store: Store) -> None:
    async with store.op() as op:
        with pytest.raises(NotAddedError, match=r"Note\.target"):
            op.add(Note(target=Node()))


async def test_collection_element_that_is_not_added_is_rejected(store: Store) -> None:
    async with store.op() as op:
        a = op.add(Node())
        with pytest.raises(NotAddedError, match=r"Team\.owners"):
            op.add(Team(owners=[a, Node()], members=[]))
        with pytest.raises(NotAddedError, match=r"Team\.members"):
            op.add(Team(owners=[a], members=[None, Node()]))


async def test_ref_to_an_entity_of_another_store_is_rejected(store: Store) -> None:
    other = Store(DictBackend())
    async with other.op() as op:
        foreign = op.add(Node())

    async with store.op() as op:
        a = op.add(Node())
        with pytest.raises(ForeignEntityError, match=r"Edge\.v: <Node #0>"):
            op.add(Edge(u=a, v=foreign))


async def test_rejected_add_leaves_no_trace(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        a, b = op.add(Node()), Node()
        edge = Edge(u=a, v=b)
        with pytest.raises(NotAddedError):
            op.add(edge)
        with pytest.raises(NotAddedError):
            id_of(edge)

        # Once the target is added, the same entity goes in, and no id was spent on the failed attempt.
        op.add(b)
        op.add(edge)

    assert id_of(edge) == 0
    assert await stored(backend, EDGE, 0) == {"u": [0], "v": [1], "weight": [1.0]}


# --- Operations of one store may overlap; operations of two stores do not mix ---


async def test_overlapping_operations_commit_in_any_order(store: Store, backend: Backend) -> None:
    # The first operation takes the lower id but finishes last.
    first_created, second_done = asyncio.Event(), asyncio.Event()

    async def first() -> None:
        async with store.op() as op:
            op.add(Node(label="first"))
            first_created.set()
            await second_done.wait()

    async def second() -> None:
        await first_created.wait()
        async with store.op() as op:
            op.add(Node(label="second"))
        second_done.set()

    await asyncio.gather(first(), second())

    assert await stored(backend, NODE, 0, 1) == {"label": ["first", "second"]}


async def test_each_task_has_its_own_current_operation(store: Store, backend: Backend) -> None:
    # A failure in one task must not discard what another task is creating.
    started, failed = asyncio.Event(), asyncio.Event()

    async def failing() -> None:
        with pytest.raises(RuntimeError):
            async with store.op() as op:
                op.add(Node(label="lost"))
                started.set()
                raise RuntimeError
        failed.set()

    async def succeeding() -> None:
        async with store.op() as op:
            await started.wait()
            await failed.wait()
            op.add(Node(label="kept"))

    await asyncio.gather(failing(), succeeding())

    assert await stored_ids(backend, NODE) == [1]
    assert await stored(backend, NODE, 1) == {"label": ["kept"]}


async def test_entity_belongs_to_the_store_of_its_operation() -> None:
    first_backend, second_backend = DictBackend(), DictBackend()
    first, second = Store(first_backend), Store(second_backend)

    async with first.op() as op:
        op.add(Node(label="in first"))
    async with second.op() as op:
        op.add(Node(label="in second"))
        op.add(Node(label="in second too"))

    assert await stored(first_backend, NODE, 0) == {"label": ["in first"]}
    assert await stored(second_backend, NODE, 0, 1) == {"label": ["in second", "in second too"]}
    with pytest.raises(UnknownEntityError):
        await stored(first_backend, NODE, 1)


async def test_handles_of_two_stores_are_never_equal() -> None:
    first, second = Store(DictBackend()), Store(DictBackend())

    async with first.op() as op:
        a = op.add(Node())
    async with second.op() as op:
        b = op.add(Node())

    assert id_of(a) == id_of(b) == 0
    assert a != b


# --- The store and a backend that really is asynchronous ---


async def test_operations_ending_at_the_same_time_are_applied_one_by_one() -> None:
    # Applying an operation takes several awaits on a real backend; two operations must not interleave there.
    backend = SlowBackend()
    store = Store(backend)

    async def create(label: str) -> None:
        async with store.op() as op:
            op.add(Node(label=label))

    await asyncio.gather(create("a"), create("b"), create("c"))

    assert await stored_ids(backend.inner, NODE) == [0, 1, 2]


async def test_empty_operation_does_not_touch_the_backend() -> None:
    backend = SlowBackend()
    store = Store(backend)
    async with store.op() as op:
        op.add(Node())
    before = backend.transactions

    async with store.op():
        pass

    assert backend.transactions == before


async def test_marks_are_read_once_per_type() -> None:
    backend = SlowBackend()
    store = Store(backend)
    async with store.op() as op:
        op.add(Node())
    before = backend.transactions

    async with store.op() as op:
        op.add(Node())

    assert backend.transactions == before + 1  # the write itself, no extra read


async def test_failure_to_read_marks_leaves_no_current_operation() -> None:
    backend = SlowBackend()
    backend.fail_marks = True
    store = Store(backend)

    with pytest.raises(RuntimeError, match="backend is down"):
        async with store.op():
            pytest.fail("the block must not run")  # pragma: no cover

    assert current_operation.get() is None

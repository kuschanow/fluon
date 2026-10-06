import asyncio

import pytest
from fakes import SlowBackend

from fluon import Backend, OptionalRef, OptionalRefs, Store, alive, entity, id_of
from fluon._core.dict_backend import DictBackend
from fluon._core.errors import (
    AwaitRequiredError,
    EntityNotAliveError,
    ForeignEntityError,
    NoActiveOperationError,
    NotAddedError,
    UnknownEntityError,
)

# Only weak references here: what removing an entity does to the entities that *must* have it
# (Ref, Refs) is the cascade, covered separately.


@entity("store_remove.Node", version=1)
class Node:
    label: str = ""


@entity("store_remove.Note", version=1)
class Note:
    target: OptionalRef[Node]


@entity("store_remove.Team", version=1)
class Team:
    members: OptionalRefs[Node]


NODE, NOTE = "store_remove.Node", "store_remove.Note"


@pytest.fixture
def backend() -> Backend:
    return DictBackend()


@pytest.fixture
def store(backend: Backend) -> Store:
    return Store(backend)


async def stored_ids(backend: Backend, type_key: str) -> list[int]:
    async with backend.transaction() as tx:
        return await tx.all(type_key)


async def three_nodes(store: Store) -> tuple[Node, Node, Node]:
    async with store.op() as op:
        nodes = op.add(Node(label="a")), op.add(Node(label="b")), op.add(Node(label="c"))
    return nodes


# --- Removing ---


async def test_removed_entity_leaves_the_backend_when_the_operation_ends(store: Store, backend: Backend) -> None:
    a, b, c = await three_nodes(store)

    async with store.op() as op:
        op.remove(b)

        assert await stored_ids(backend, NODE) == [0, 1, 2]

    assert await stored_ids(backend, NODE) == [0, 2]


async def test_several_entities_of_several_types_are_removed_together(store: Store, backend: Backend) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        note = op.add(Note(target=None))

    async with store.op() as op:
        op.remove(c)
        op.remove(note)
        op.remove(a)

    assert await stored_ids(backend, NODE) == [1]
    assert await stored_ids(backend, NOTE) == []


async def test_remove_returns_nothing(store: Store) -> None:
    (a, _, _) = await three_nodes(store)

    async with store.op() as op:
        assert op.remove(a) is None  # type: ignore[func-returns-value]


async def test_failed_operation_removes_nothing(store: Store, backend: Backend) -> None:
    a, b, c = await three_nodes(store)

    with pytest.raises(RuntimeError):
        async with store.op() as op:
            op.remove(b)
            raise RuntimeError

    assert await stored_ids(backend, NODE) == [0, 1, 2]
    assert await store.alive(b) is True
    assert b.label == "b"


async def test_id_of_a_removed_entity_is_not_issued_again(store: Store) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        op.remove(c)

    async with store.op() as op:
        new = op.add(Node())

    assert id_of(new) == 3


# --- A removed entity is not alive ---


async def test_store_tells_whether_an_entity_is_alive(store: Store) -> None:
    a, b, c = await three_nodes(store)

    async with store.op() as op:
        op.remove(b)

    assert [await store.alive(n) for n in (a, b, c)] == [True, False, True]


async def test_fields_of_a_removed_entity_cannot_be_read(store: Store) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        op.remove(b)

    with pytest.raises(EntityNotAliveError, match="Node #1"):
        _ = b.label
    assert a.label == "a"


async def test_handle_of_a_removed_entity_keeps_its_identity(store: Store) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        op.remove(b)

    assert id_of(b) == 1
    assert repr(b) == "<Node #1>"
    assert b == b and b != a
    assert len({a, b, c}) == 3


async def test_removed_entity_cannot_be_fetched(store: Store) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        op.remove(b)

    with pytest.raises(UnknownEntityError, match="1"):
        await store.fetch(Node, 1)
    assert [id_of(n) for n in await store.all(Node)] == [0, 2]


async def test_removed_entity_cannot_be_loaded_or_reloaded(store: Store) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        op.remove(b)

    with pytest.raises(UnknownEntityError):
        await store.load(b)
    with pytest.raises(UnknownEntityError):
        await store.reload(b)


async def test_another_store_sees_the_removal(store: Store, backend: Backend) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        op.remove(b)

    other = Store(backend)

    assert [n.label for n in await other.all(Node)] == ["a", "c"]


# --- Inside the operation the removal is already visible, and only there ---


async def test_removed_entity_is_not_alive_inside_the_operation(store: Store) -> None:
    a, b, c = await three_nodes(store)

    async with store.op() as op:
        op.remove(b)

        assert await store.alive(b) is False
        assert await store.alive(a) is True
        with pytest.raises(EntityNotAliveError):
            _ = b.label


async def test_reads_inside_the_operation_skip_what_it_removed(store: Store) -> None:
    a, b, c = await three_nodes(store)

    async with store.op() as op:
        op.remove(b)

        assert [id_of(n) for n in await store.all(Node)] == [0, 2]
        with pytest.raises(UnknownEntityError):
            await store.fetch(Node, 1)


async def test_removal_is_invisible_to_other_tasks_until_the_operation_ends(store: Store) -> None:
    a, b, c = await three_nodes(store)
    removed, checked = asyncio.Event(), asyncio.Event()
    seen: list[object] = []

    async def remover() -> None:
        async with store.op() as op:
            op.remove(b)
            removed.set()
            await checked.wait()

    async def observer() -> None:
        await removed.wait()
        seen.append(await store.alive(b))
        seen.append(b.label)
        seen.append([id_of(n) for n in await store.all(Node)])
        checked.set()

    await asyncio.gather(remover(), observer())

    assert seen == [True, "b", [0, 1, 2]]
    assert await store.alive(b) is False


# --- Removing what is already gone, or was never written ---


async def test_removing_twice_in_one_operation_is_fine(store: Store, backend: Backend) -> None:
    a, b, c = await three_nodes(store)

    async with store.op() as op:
        op.remove(b)
        op.remove(b)

    assert await stored_ids(backend, NODE) == [0, 2]


async def test_removing_an_already_removed_entity_is_a_no_op(store: Store, backend: Backend) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        op.remove(b)

    async with store.op() as op:
        op.remove(b)

    assert await stored_ids(backend, NODE) == [0, 2]


async def test_no_op_removal_does_not_touch_the_backend() -> None:
    backend = SlowBackend()
    store = Store(backend)
    async with store.op() as op:
        node = op.add(Node())
    async with store.op() as op:
        op.remove(node)
    backend.transactions = 0

    async with store.op() as op:
        op.remove(node)

    assert backend.transactions == 0


async def test_entity_created_and_removed_in_one_operation_never_stays(store: Store, backend: Backend) -> None:
    async with store.op() as op:
        kept = op.add(Node(label="kept"))
        gone = op.add(Node(label="gone"))
        op.remove(gone)

        assert await store.alive(gone) is False
        assert await store.alive(kept) is True

    assert await stored_ids(backend, NODE) == [0]
    assert await store.alive(gone) is False
    with pytest.raises(EntityNotAliveError):
        _ = gone.label


async def test_id_of_an_entity_created_and_removed_at_once_is_spent(store: Store) -> None:
    async with store.op() as op:
        op.remove(op.add(Node()))

    async with store.op() as op:
        new = op.add(Node())

    assert id_of(new) == 1


# --- Removing what the store has not loaded: the backend is asked what is there ---


async def test_unloaded_entity_is_removed(store: Store, backend: Backend) -> None:
    await three_nodes(store)
    reader = Store(backend)
    unloaded = reader.handle(Node, 1)  # what a reference gives: an id and nothing else

    async with reader.op() as op:
        op.remove(unloaded)

    assert await stored_ids(backend, NODE) == [0, 2]
    assert await reader.alive(unloaded) is False


async def test_removing_an_unloaded_entity_that_does_not_exist_is_a_no_op(store: Store, backend: Backend) -> None:
    await three_nodes(store)
    reader = Store(backend)

    async with reader.op() as op:
        op.remove(reader.handle(Node, 7))
        op.remove(reader.handle(Node, 2))

    assert await stored_ids(backend, NODE) == [0, 1]


async def test_removing_an_entity_of_a_discarded_operation_is_a_no_op(store: Store, backend: Backend) -> None:
    await three_nodes(store)
    with pytest.raises(RuntimeError):
        async with store.op() as op:
            lost = op.add(Node())
            raise RuntimeError

    async with store.op() as op:
        op.remove(lost)

    assert await stored_ids(backend, NODE) == [0, 1, 2]


# --- Weak references outlive their target ---


async def test_holder_of_an_optional_ref_survives(store: Store, backend: Backend) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        note = op.add(Note(target=b))

    async with store.op() as op:
        op.remove(b)

    assert await stored_ids(backend, NOTE) == [0]
    assert await store.alive(note) is True


async def test_link_to_a_removed_target_is_dead_but_keeps_the_id(store: Store) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        to_b, to_a, empty = op.add(Note(target=b)), op.add(Note(target=a)), op.add(Note(target=None))

    async with store.op() as op:
        op.remove(b)

    assert [await store.alive(n.target) for n in (to_b, to_a, empty)] == [False, True, False]
    assert to_b.target.id == 1


async def test_links_of_a_collection_are_checked_one_by_one(store: Store) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        team = op.add(Team(members=[a, b, None, c]))

    async with store.op() as op:
        op.remove(b)

    assert [await store.alive(m) for m in team.members] == [True, False, False, True]


# --- store.alive ---


async def test_alive_knows_entities_being_created(store: Store) -> None:
    async with store.op() as op:
        node = op.add(Node())

        assert await store.alive(node) is True


async def test_entity_of_a_discarded_operation_is_not_alive(store: Store) -> None:
    with pytest.raises(RuntimeError):
        async with store.op() as op:
            lost = op.add(Node())
            raise RuntimeError

    assert await store.alive(lost) is False


async def test_alive_asks_the_backend_only_about_what_the_store_does_not_know() -> None:
    backend = SlowBackend()
    writer = Store(backend)
    async with writer.op() as op:
        a, b = op.add(Node()), op.add(Node())
        note = op.add(Note(target=b))
    async with writer.op() as op:
        op.remove(a)
    backend.existence_checks.clear()

    assert await writer.alive(b) is True  # written by this store
    assert await writer.alive(a) is False  # removed by this store
    assert backend.existence_checks == []

    reader = Store(backend)
    fetched = await reader.fetch(Note, id_of(note))
    assert await reader.alive(fetched) is True  # loaded by this store
    assert backend.existence_checks == []
    assert await reader.alive(fetched.target) is True  # only an id: has to ask
    assert backend.existence_checks == [(NODE, [1])]


async def test_alive_rejects_what_is_not_an_entity_or_a_link(store: Store) -> None:
    with pytest.raises(TypeError, match="entity"):
        await store.alive(42)  # type: ignore[arg-type]


# --- On a live store the synchronous questions cannot be answered ---


async def test_sync_alive_points_to_the_store(store: Store) -> None:
    a, b, c = await three_nodes(store)

    with pytest.raises(AwaitRequiredError, match="store.alive"):
        alive(a)


async def test_link_alive_and_get_point_to_the_store(store: Store) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        note = op.add(Note(target=a))

    with pytest.raises(AwaitRequiredError, match="store.alive"):
        _ = note.target.alive
    with pytest.raises(AwaitRequiredError):
        note.target.get()


async def test_empty_link_needs_no_store(store: Store) -> None:
    async with store.op() as op:
        note = op.add(Note(target=None))

    assert note.target.alive is False


# --- Rejected removals ---


async def test_removing_something_that_is_not_an_entity_is_rejected(store: Store) -> None:
    async with store.op() as op:
        with pytest.raises(TypeError, match="entity"):
            op.remove(42)  # type: ignore[arg-type]


async def test_removing_a_link_is_rejected(store: Store) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        note = op.add(Note(target=a))

    async with store.op() as op:
        with pytest.raises(TypeError, match="entity"):
            op.remove(note.target)  # type: ignore[arg-type]


async def test_removing_an_entity_that_is_not_added_is_rejected(store: Store) -> None:
    async with store.op() as op:
        with pytest.raises(NotAddedError):
            op.remove(Node())


async def test_alive_rejects_an_entity_that_is_not_added(store: Store) -> None:
    with pytest.raises(NotAddedError):
        await store.alive(Node())


async def test_removing_an_entity_of_another_store_is_rejected(store: Store) -> None:
    other = Store(DictBackend())
    async with other.op() as op:
        foreign = op.add(Node())

    async with store.op() as op:
        with pytest.raises(ForeignEntityError, match="Node #0"):
            op.remove(foreign)


async def test_removing_through_a_finished_operation_is_rejected(store: Store, backend: Backend) -> None:
    a, b, c = await three_nodes(store)
    async with store.op() as op:
        pass

    with pytest.raises(NoActiveOperationError):
        op.remove(a)
    assert await stored_ids(backend, NODE) == [0, 1, 2]

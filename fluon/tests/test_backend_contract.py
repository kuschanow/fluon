"""Contract of a storage backend.

A backend stores state and knows nothing about entity semantics: it is told which rows to write
and asked for columns of rows by id. Every backend implementation must pass these tests.
"""

import pytest

from fluon._core.backend import Backend, ChangeSet, CreatedBatch
from fluon._core.dict_backend import DictBackend
from fluon._core.errors import DuplicateIdError, TransactionClosedError, TransactionConflictError, UnknownEntityError


@pytest.fixture
def backend() -> Backend:
    return DictBackend()


async def create(backend: Backend, type_key: str, ids: list[int], **columns: list[object]) -> None:
    """Write one batch of new entities and commit."""
    async with backend.transaction() as tx:
        await tx.apply(ChangeSet(created=[CreatedBatch(type_key, ids, columns)]))
        await tx.commit()


# --- Writing and reading back ---


async def test_committed_entity_is_readable_in_a_later_transaction(backend: Backend) -> None:
    await create(backend, "graph.Node", [1], label=["a"])

    async with backend.transaction() as tx:
        assert await tx.fields("graph.Node", [1]) == {"label": ["a"]}


async def test_fields_are_returned_as_columns(backend: Backend) -> None:
    await create(backend, "graph.Edge", [10, 11, 12], u=[1, 2, 3], v=[2, 3, 1], weight=[0.5, 1.5, 2.5])

    async with backend.transaction() as tx:
        columns = await tx.fields("graph.Edge", [10, 11, 12])

    assert columns == {"u": [1, 2, 3], "v": [2, 3, 1], "weight": [0.5, 1.5, 2.5]}


async def test_columns_follow_the_order_of_the_requested_ids(backend: Backend) -> None:
    await create(backend, "graph.Node", [1, 2, 3], label=["a", "b", "c"])

    async with backend.transaction() as tx:
        assert await tx.fields("graph.Node", [3, 1]) == {"label": ["c", "a"]}


async def test_an_id_may_be_requested_more_than_once(backend: Backend) -> None:
    await create(backend, "graph.Node", [1, 2], label=["a", "b"])

    async with backend.transaction() as tx:
        assert await tx.fields("graph.Node", [2, 1, 2]) == {"label": ["b", "a", "b"]}


async def test_requesting_no_ids_returns_empty_columns(backend: Backend) -> None:
    await create(backend, "graph.Node", [1], label=["a"])

    async with backend.transaction() as tx:
        columns = await tx.fields("graph.Node", [])

    assert all(len(column) == 0 for column in columns.values())


async def test_entity_without_fields(backend: Backend) -> None:
    await create(backend, "graph.Marker", [1, 2])

    async with backend.transaction() as tx:
        assert await tx.fields("graph.Marker", [1, 2]) == {}


@pytest.mark.parametrize(
    "value",
    [None, True, 0, -7, 2.5, "", "text", b"\x00\xff", (), (1, "a", None), ((1, 2), (3,)), frozenset({1, 2})],
)
async def test_values_are_stored_unchanged(backend: Backend, value: object) -> None:
    await create(backend, "test.Box", [1], value=[value])

    async with backend.transaction() as tx:
        columns = await tx.fields("test.Box", [1])

    assert columns == {"value": [value]}
    assert type(columns["value"][0]) is type(value)


# --- Several batches, several types ---


async def test_types_are_stored_independently(backend: Backend) -> None:
    await create(backend, "graph.Node", [1], label=["node"])
    await create(backend, "shop.Product", [2], label=["product"], price=[9.5])

    async with backend.transaction() as tx:
        assert await tx.fields("graph.Node", [1]) == {"label": ["node"]}
        assert await tx.fields("shop.Product", [2]) == {"label": ["product"], "price": [9.5]}


async def test_one_change_set_may_carry_several_batches(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.apply(
            ChangeSet(
                created=[
                    CreatedBatch("graph.Node", [1, 2], {"label": ["a", "b"]}),
                    CreatedBatch("graph.Edge", [3], {"u": [1], "v": [2]}),
                    CreatedBatch("graph.Node", [4], {"label": ["c"]}),
                ]
            )
        )
        await tx.commit()

    async with backend.transaction() as tx:
        assert await tx.fields("graph.Node", [1, 2, 4]) == {"label": ["a", "b", "c"]}
        assert await tx.fields("graph.Edge", [3]) == {"u": [1], "v": [2]}


async def test_apply_may_be_called_several_times_in_one_transaction(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1], {"label": ["a"]})]))
        await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [2], {"label": ["b"]})]))
        await tx.commit()

    async with backend.transaction() as tx:
        assert await tx.fields("graph.Node", [1, 2]) == {"label": ["a", "b"]}


async def test_empty_change_set_is_a_no_op(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.apply(ChangeSet())
        await tx.commit()


# --- Rejected writes ---


async def test_column_shorter_than_ids_is_rejected(backend: Backend) -> None:
    async with backend.transaction() as tx:
        with pytest.raises(ValueError, match="label"):
            await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1, 2], {"label": ["a"]})]))


async def test_column_longer_than_ids_is_rejected(backend: Backend) -> None:
    async with backend.transaction() as tx:
        with pytest.raises(ValueError, match="label"):
            await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1], {"label": ["a", "b"]})]))


async def test_creating_an_existing_id_is_rejected(backend: Backend) -> None:
    await create(backend, "graph.Node", [1], label=["a"])

    async with backend.transaction() as tx:
        with pytest.raises(DuplicateIdError, match="1"):
            await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1], {"label": ["again"]})]))


async def test_each_type_has_its_own_id_space(backend: Backend) -> None:
    # An entity is identified by (type, id): the same id under another type is a different entity.
    await create(backend, "graph.Node", [1], label=["a"])
    await create(backend, "graph.Edge", [1], u=[1], v=[1])

    async with backend.transaction() as tx:
        assert await tx.fields("graph.Node", [1]) == {"label": ["a"]}
        assert await tx.fields("graph.Edge", [1]) == {"u": [1], "v": [1]}


async def test_duplicate_id_error_names_the_type(backend: Backend) -> None:
    await create(backend, "graph.Node", [1], label=["a"])

    async with backend.transaction() as tx:
        with pytest.raises(DuplicateIdError, match="graph.Node"):
            await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1], {"label": ["again"]})]))


async def test_duplicate_id_within_one_batch_is_rejected(backend: Backend) -> None:
    async with backend.transaction() as tx:
        with pytest.raises(DuplicateIdError):
            await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1, 1], {"label": ["a", "b"]})]))


async def test_rejected_change_set_writes_nothing(backend: Backend) -> None:
    # A change set is applied as a whole: a failure in a later batch must not leave earlier batches behind.
    async with backend.transaction() as tx:
        with pytest.raises(DuplicateIdError):
            await tx.apply(
                ChangeSet(
                    created=[
                        CreatedBatch("graph.Node", [1], {"label": ["a"]}),
                        CreatedBatch("graph.Node", [2, 2], {"label": ["b", "c"]}),
                    ]
                )
            )
        with pytest.raises(UnknownEntityError):
            await tx.fields("graph.Node", [1])


async def test_failed_apply_keeps_earlier_applies_of_the_same_transaction(backend: Backend) -> None:
    # Only the failed change set is discarded; what the transaction applied before it stays.
    async with backend.transaction() as tx:
        await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1], {"label": ["a"]})]))
        with pytest.raises(DuplicateIdError):
            await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [2, 1], {"label": ["b", "again"]})]))
        assert await tx.fields("graph.Node", [1]) == {"label": ["a"]}
        await tx.commit()

    async with backend.transaction() as tx:
        assert await tx.fields("graph.Node", [1]) == {"label": ["a"]}
        with pytest.raises(UnknownEntityError):
            await tx.fields("graph.Node", [2])


# --- Rejected reads ---


async def test_reading_an_unknown_id_is_rejected(backend: Backend) -> None:
    await create(backend, "graph.Node", [1], label=["a"])

    async with backend.transaction() as tx:
        with pytest.raises(UnknownEntityError, match="99"):
            await tx.fields("graph.Node", [1, 99])


async def test_an_id_taken_under_one_type_is_unknown_under_another(backend: Backend) -> None:
    await create(backend, "graph.Node", [1], label=["a"])

    async with backend.transaction() as tx:
        with pytest.raises(UnknownEntityError, match="graph.Edge"):
            await tx.fields("graph.Edge", [1])


# --- Nothing is stored without a commit ---


def node(id_: int, label: str = "a") -> ChangeSet:
    return ChangeSet(created=[CreatedBatch("graph.Node", [id_], {"label": [label]})])


async def exists(backend: Backend, type_key: str, id_: int) -> bool:
    async with backend.transaction() as tx:
        try:
            await tx.fields(type_key, [id_])
        except UnknownEntityError:
            return False
        return True


async def test_leaving_the_block_without_commit_discards_changes(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.apply(node(1))

    assert not await exists(backend, "graph.Node", 1)


async def test_exception_inside_the_block_discards_changes(backend: Backend) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with backend.transaction() as tx:
            await tx.apply(node(1))
            raise RuntimeError("boom")

    assert not await exists(backend, "graph.Node", 1)


async def test_rollback_discards_changes(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.apply(node(1))
        await tx.rollback()

    assert not await exists(backend, "graph.Node", 1)


async def test_rollback_keeps_what_was_committed_before(backend: Backend) -> None:
    await create(backend, "graph.Node", [1], label=["a"])

    async with backend.transaction() as tx:
        await tx.apply(node(2))
        await tx.rollback()

    assert await exists(backend, "graph.Node", 1)
    assert not await exists(backend, "graph.Node", 2)


# --- Isolation ---


async def test_transaction_sees_its_own_uncommitted_changes(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.apply(node(1, "mine"))

        assert await tx.fields("graph.Node", [1]) == {"label": ["mine"]}


async def test_uncommitted_changes_are_invisible_to_other_transactions(backend: Backend) -> None:
    async with backend.transaction() as writer:
        await writer.apply(node(1))

        async with backend.transaction() as reader:
            with pytest.raises(UnknownEntityError):
                await reader.fields("graph.Node", [1])


async def test_reader_keeps_working_while_another_transaction_commits(backend: Backend) -> None:
    await create(backend, "graph.Node", [1], label=["a"])

    async with backend.transaction() as reader:
        await create(backend, "graph.Node", [2], label=["b"])

        assert await reader.fields("graph.Node", [1]) == {"label": ["a"]}


# --- Overlapping writers: a committed write is never lost silently ---


async def test_second_of_two_overlapping_writers_gets_a_conflict(backend: Backend) -> None:
    async with backend.transaction() as first, backend.transaction() as second:
        await first.apply(node(1))
        await second.apply(node(2))
        await first.commit()

        with pytest.raises(TransactionConflictError):
            await second.commit()

    assert await exists(backend, "graph.Node", 1)
    assert not await exists(backend, "graph.Node", 2)


async def test_conflict_is_detected_even_when_the_writers_touch_different_types(backend: Backend) -> None:
    async with backend.transaction() as first, backend.transaction() as second:
        await first.apply(node(1))
        await second.apply(ChangeSet(created=[CreatedBatch("shop.Product", [1], {"name": ["x"]})]))
        await first.commit()

        with pytest.raises(TransactionConflictError):
            await second.commit()


async def test_work_can_be_retried_after_a_conflict(backend: Backend) -> None:
    async with backend.transaction() as first, backend.transaction() as second:
        await first.apply(node(1))
        await second.apply(node(2))
        await first.commit()
        with pytest.raises(TransactionConflictError):
            await second.commit()

    async with backend.transaction() as retry:
        await retry.apply(node(2))
        await retry.commit()

    assert await exists(backend, "graph.Node", 1)
    assert await exists(backend, "graph.Node", 2)


async def test_read_only_transaction_never_conflicts(backend: Backend) -> None:
    async with backend.transaction() as reader:
        await create(backend, "graph.Node", [1], label=["a"])

        await reader.commit()

    assert await exists(backend, "graph.Node", 1)


async def test_read_only_commit_does_not_disturb_a_running_writer(backend: Backend) -> None:
    async with backend.transaction() as writer:
        await writer.apply(node(1))

        async with backend.transaction() as reader:
            await reader.commit()

        await writer.commit()

    assert await exists(backend, "graph.Node", 1)


async def test_rolled_back_writer_does_not_disturb_another_writer(backend: Backend) -> None:
    async with backend.transaction() as first, backend.transaction() as second:
        await first.apply(node(1))
        await second.apply(node(2))
        await first.rollback()

        await second.commit()

    assert not await exists(backend, "graph.Node", 1)
    assert await exists(backend, "graph.Node", 2)


# --- A finished transaction cannot be used ---


async def test_transaction_is_closed_after_commit(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.apply(node(1))
        await tx.commit()

        with pytest.raises(TransactionClosedError):
            await tx.apply(node(2))
        with pytest.raises(TransactionClosedError):
            await tx.fields("graph.Node", [1])
        with pytest.raises(TransactionClosedError):
            await tx.commit()
        with pytest.raises(TransactionClosedError):
            await tx.rollback()


async def test_transaction_is_closed_after_rollback(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.rollback()

        with pytest.raises(TransactionClosedError):
            await tx.apply(node(1))
        with pytest.raises(TransactionClosedError):
            await tx.commit()


async def test_transaction_is_closed_after_a_conflict(backend: Backend) -> None:
    async with backend.transaction() as first, backend.transaction() as second:
        await first.apply(node(1))
        await second.apply(node(2))
        await first.commit()
        with pytest.raises(TransactionConflictError):
            await second.commit()

        with pytest.raises(TransactionClosedError):
            await second.commit()


async def test_transaction_is_closed_after_leaving_the_block(backend: Backend) -> None:
    async with backend.transaction() as tx:
        await tx.apply(node(1))

    with pytest.raises(TransactionClosedError):
        await tx.commit()
    with pytest.raises(TransactionClosedError):
        await tx.fields("graph.Node", [1])

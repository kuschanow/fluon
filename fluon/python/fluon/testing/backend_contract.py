"""Contract tests for storage backends.

A backend stores state and knows nothing about entity semantics: it is told which rows to write
and asked for columns of rows by id. Every backend implementation must pass these tests.

Usage, in the test suite of a backend:

    import pytest
    from fluon.testing import BackendContract

    class TestMyBackend(BackendContract):
        @pytest.fixture
        def backend(self) -> Backend:
            return MyBackend()

Requires pytest and pytest-asyncio (``pip install fluon[testing]``).
"""

import pytest

from fluon._core.backend import Backend, ChangeSet, CreatedBatch, DeletedBatch
from fluon._core.errors import DuplicateIdError, TransactionClosedError, TransactionConflictError, UnknownEntityError

__all__ = ["BackendContract"]


async def _create(backend: Backend, type_key: str, ids: list[int], **columns: list[object]) -> None:
    """Write one batch of new entities and commit."""
    async with backend.transaction() as tx:
        await tx.apply(ChangeSet(created=[CreatedBatch(type_key, ids, columns)]))
        await tx.commit()


def _node(id_: int, label: str = "a") -> ChangeSet:
    return ChangeSet(created=[CreatedBatch("graph.Node", [id_], {"label": [label]})])


async def _exists(backend: Backend, type_key: str, id_: int) -> bool:
    async with backend.transaction() as tx:
        try:
            await tx.fields(type_key, [id_])
        except UnknownEntityError:
            return False
        return True


def _delete(type_key: str, *ids: int) -> ChangeSet:
    return ChangeSet(deleted=[DeletedBatch(type_key, ids)])


async def _commit(backend: Backend, *changes: ChangeSet) -> None:
    async with backend.transaction() as tx:
        for change_set in changes:
            await tx.apply(change_set)
        await tx.commit()


async def _next_id(backend: Backend, type_key: str) -> int:
    async with backend.transaction() as tx:
        return await tx.next_id(type_key)


async def _all_ids(backend: Backend, type_key: str) -> list[int]:
    async with backend.transaction() as tx:
        return await tx.all(type_key)


async def _referencing(backend: Backend, type_key: str, field: str, *targets: int) -> list[int]:
    async with backend.transaction() as tx:
        return await tx.referencing(type_key, field, targets)


async def _edges(backend: Backend) -> None:
    """Edges 0..3 over nodes 0..2: 0: 0->1, 1: 1->2, 2: 0->2, 3: 2->2."""
    await _create(backend, "graph.Node", [0, 1, 2], label=["a", "b", "c"])
    await _create(backend, "graph.Edge", [0, 1, 2, 3], u=[0, 1, 0, 2], v=[1, 2, 2, 2])


class BackendContract:
    """Inherit in a ``Test...`` class and override the ``backend`` fixture."""

    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def backend(self) -> Backend:
        raise NotImplementedError("override the `backend` fixture to return the backend under test")

    # --- Writing and reading back ---

    async def test_committed_entity_is_readable_in_a_later_transaction(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [1]) == {"label": ["a"]}

    async def test_fields_are_returned_as_columns(self, backend: Backend) -> None:
        await _create(backend, "graph.Edge", [10, 11, 12], u=[1, 2, 3], v=[2, 3, 1], weight=[0.5, 1.5, 2.5])

        async with backend.transaction() as tx:
            columns = await tx.fields("graph.Edge", [10, 11, 12])

        assert columns == {"u": [1, 2, 3], "v": [2, 3, 1], "weight": [0.5, 1.5, 2.5]}

    async def test_columns_follow_the_order_of_the_requested_ids(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1, 2, 3], label=["a", "b", "c"])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [3, 1]) == {"label": ["c", "a"]}

    async def test_an_id_may_be_requested_more_than_once(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1, 2], label=["a", "b"])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [2, 1, 2]) == {"label": ["b", "a", "b"]}

    async def test_requesting_no_ids_returns_empty_columns(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            columns = await tx.fields("graph.Node", [])

        assert all(len(column) == 0 for column in columns.values())

    async def test_entity_without_fields(self, backend: Backend) -> None:
        await _create(backend, "graph.Marker", [1, 2])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Marker", [1, 2]) == {}

    @pytest.mark.parametrize(
        "value",
        [None, True, 0, -7, 2.5, "", "text", b"\x00\xff", (), (1, "a", None), ((1, 2), (3,)), frozenset({1, 2})],
    )
    async def test_values_are_stored_unchanged(self, backend: Backend, value: object) -> None:
        await _create(backend, "test.Box", [1], value=[value])

        async with backend.transaction() as tx:
            columns = await tx.fields("test.Box", [1])

        assert columns == {"value": [value]}
        assert type(columns["value"][0]) is type(value)

    # --- Several batches, several types ---

    async def test_types_are_stored_independently(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["node"])
        await _create(backend, "shop.Product", [2], label=["product"], price=[9.5])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [1]) == {"label": ["node"]}
            assert await tx.fields("shop.Product", [2]) == {"label": ["product"], "price": [9.5]}

    async def test_one_change_set_may_carry_several_batches(self, backend: Backend) -> None:
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

    async def test_apply_may_be_called_several_times_in_one_transaction(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1], {"label": ["a"]})]))
            await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [2], {"label": ["b"]})]))
            await tx.commit()

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [1, 2]) == {"label": ["a", "b"]}

    async def test_empty_change_set_is_a_no_op(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.apply(ChangeSet())
            await tx.commit()

    # --- Rejected writes ---

    async def test_column_shorter_than_ids_is_rejected(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            with pytest.raises(ValueError, match="label"):
                await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1, 2], {"label": ["a"]})]))

    async def test_column_longer_than_ids_is_rejected(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            with pytest.raises(ValueError, match="label"):
                await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1], {"label": ["a", "b"]})]))

    async def test_creating_an_existing_id_is_rejected(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            with pytest.raises(DuplicateIdError, match="1"):
                await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1], {"label": ["again"]})]))

    async def test_each_type_has_its_own_id_space(self, backend: Backend) -> None:
        # An entity is identified by (type, id): the same id under another type is a different entity.
        await _create(backend, "graph.Node", [1], label=["a"])
        await _create(backend, "graph.Edge", [1], u=[1], v=[1])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [1]) == {"label": ["a"]}
            assert await tx.fields("graph.Edge", [1]) == {"u": [1], "v": [1]}

    async def test_duplicate_id_error_names_the_type(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            with pytest.raises(DuplicateIdError, match="graph.Node"):
                await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1], {"label": ["again"]})]))

    async def test_duplicate_id_within_one_batch_is_rejected(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            with pytest.raises(DuplicateIdError):
                await tx.apply(ChangeSet(created=[CreatedBatch("graph.Node", [1, 1], {"label": ["a", "b"]})]))

    async def test_rejected_change_set_writes_nothing(self, backend: Backend) -> None:
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

    async def test_failed_apply_keeps_earlier_applies_of_the_same_transaction(self, backend: Backend) -> None:
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

    async def test_reading_an_unknown_id_is_rejected(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            with pytest.raises(UnknownEntityError, match="99"):
                await tx.fields("graph.Node", [1, 99])

    async def test_an_id_taken_under_one_type_is_unknown_under_another(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            with pytest.raises(UnknownEntityError, match="graph.Edge"):
                await tx.fields("graph.Edge", [1])

    # --- Nothing is stored without a commit ---

    async def test_leaving_the_block_without_commit_discards_changes(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.apply(_node(1))

        assert not await _exists(backend, "graph.Node", 1)

    async def test_exception_inside_the_block_discards_changes(self, backend: Backend) -> None:
        with pytest.raises(RuntimeError, match="boom"):
            async with backend.transaction() as tx:
                await tx.apply(_node(1))
                raise RuntimeError("boom")

        assert not await _exists(backend, "graph.Node", 1)

    async def test_rollback_discards_changes(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.apply(_node(1))
            await tx.rollback()

        assert not await _exists(backend, "graph.Node", 1)

    async def test_rollback_keeps_what_was_committed_before(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            await tx.apply(_node(2))
            await tx.rollback()

        assert await _exists(backend, "graph.Node", 1)
        assert not await _exists(backend, "graph.Node", 2)

    # --- Isolation ---

    async def test_transaction_sees_its_own_uncommitted_changes(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.apply(_node(1, "mine"))

            assert await tx.fields("graph.Node", [1]) == {"label": ["mine"]}

    async def test_uncommitted_changes_are_invisible_to_other_transactions(self, backend: Backend) -> None:
        async with backend.transaction() as writer:
            await writer.apply(_node(1))

            async with backend.transaction() as reader:
                with pytest.raises(UnknownEntityError):
                    await reader.fields("graph.Node", [1])

    async def test_reader_keeps_working_while_another_transaction_commits(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as reader:
            await _create(backend, "graph.Node", [2], label=["b"])

            assert await reader.fields("graph.Node", [1]) == {"label": ["a"]}

    # --- Overlapping writers: a committed write is never lost silently ---

    async def test_second_of_two_overlapping_writers_gets_a_conflict(self, backend: Backend) -> None:
        async with backend.transaction() as first, backend.transaction() as second:
            await first.apply(_node(1))
            await second.apply(_node(2))
            await first.commit()

            with pytest.raises(TransactionConflictError):
                await second.commit()

        assert await _exists(backend, "graph.Node", 1)
        assert not await _exists(backend, "graph.Node", 2)

    async def test_conflict_is_detected_even_when_the_writers_touch_different_types(self, backend: Backend) -> None:
        async with backend.transaction() as first, backend.transaction() as second:
            await first.apply(_node(1))
            await second.apply(ChangeSet(created=[CreatedBatch("shop.Product", [1], {"name": ["x"]})]))
            await first.commit()

            with pytest.raises(TransactionConflictError):
                await second.commit()

    async def test_work_can_be_retried_after_a_conflict(self, backend: Backend) -> None:
        async with backend.transaction() as first, backend.transaction() as second:
            await first.apply(_node(1))
            await second.apply(_node(2))
            await first.commit()
            with pytest.raises(TransactionConflictError):
                await second.commit()

        async with backend.transaction() as retry:
            await retry.apply(_node(2))
            await retry.commit()

        assert await _exists(backend, "graph.Node", 1)
        assert await _exists(backend, "graph.Node", 2)

    async def test_read_only_transaction_never_conflicts(self, backend: Backend) -> None:
        async with backend.transaction() as reader:
            await _create(backend, "graph.Node", [1], label=["a"])

            await reader.commit()

        assert await _exists(backend, "graph.Node", 1)

    async def test_read_only_commit_does_not_disturb_a_running_writer(self, backend: Backend) -> None:
        async with backend.transaction() as writer:
            await writer.apply(_node(1))

            async with backend.transaction() as reader:
                await reader.commit()

            await writer.commit()

        assert await _exists(backend, "graph.Node", 1)

    async def test_rolled_back_writer_does_not_disturb_another_writer(self, backend: Backend) -> None:
        async with backend.transaction() as first, backend.transaction() as second:
            await first.apply(_node(1))
            await second.apply(_node(2))
            await first.rollback()

            await second.commit()

        assert not await _exists(backend, "graph.Node", 1)
        assert await _exists(backend, "graph.Node", 2)

    # --- A finished transaction cannot be used ---

    async def test_transaction_is_closed_after_commit(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.apply(_node(1))
            await tx.commit()

            with pytest.raises(TransactionClosedError):
                await tx.apply(_node(2))
            with pytest.raises(TransactionClosedError):
                await tx.fields("graph.Node", [1])
            with pytest.raises(TransactionClosedError):
                await tx.commit()
            with pytest.raises(TransactionClosedError):
                await tx.rollback()

    async def test_transaction_is_closed_after_rollback(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.rollback()

            with pytest.raises(TransactionClosedError):
                await tx.apply(_node(1))
            with pytest.raises(TransactionClosedError):
                await tx.commit()

    async def test_transaction_is_closed_after_a_conflict(self, backend: Backend) -> None:
        async with backend.transaction() as first, backend.transaction() as second:
            await first.apply(_node(1))
            await second.apply(_node(2))
            await first.commit()
            with pytest.raises(TransactionConflictError):
                await second.commit()

            with pytest.raises(TransactionClosedError):
                await second.commit()

    async def test_transaction_is_closed_after_leaving_the_block(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.apply(_node(1))

        with pytest.raises(TransactionClosedError):
            await tx.commit()
        with pytest.raises(TransactionClosedError):
            await tx.fields("graph.Node", [1])

    # --- Deleting ---

    async def test_deleted_entity_is_gone(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1, 2, 3], label=["a", "b", "c"])

        await _commit(backend, _delete("graph.Node", 2))

        assert not await _exists(backend, "graph.Node", 2)
        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [1, 3]) == {"label": ["a", "c"]}

    async def test_several_entities_are_deleted_in_one_batch(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1, 2, 3], label=["a", "b", "c"])

        await _commit(backend, _delete("graph.Node", 3, 1))

        assert [await _exists(backend, "graph.Node", i) for i in (1, 2, 3)] == [False, True, False]

    async def test_deletion_is_visible_inside_the_transaction(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            await tx.apply(_delete("graph.Node", 1))

            with pytest.raises(UnknownEntityError):
                await tx.fields("graph.Node", [1])

    async def test_deleting_under_one_type_leaves_other_types_alone(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])
        await _create(backend, "graph.Edge", [1], u=[1], v=[1])

        await _commit(backend, _delete("graph.Node", 1))

        assert not await _exists(backend, "graph.Node", 1)
        assert await _exists(backend, "graph.Edge", 1)

    async def test_backend_does_not_follow_references(self, backend: Backend) -> None:
        # Cascades and reference integrity are the store's job; the backend only does what it is told.
        await _create(backend, "graph.Node", [1], label=["a"])
        await _create(backend, "graph.Edge", [7], u=[1], v=[1])

        await _commit(backend, _delete("graph.Node", 1))

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Edge", [7]) == {"u": [1], "v": [1]}

    # --- Deletion and transactions ---

    async def test_uncommitted_deletion_is_discarded(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            await tx.apply(_delete("graph.Node", 1))

        assert await _exists(backend, "graph.Node", 1)

    async def test_uncommitted_deletion_is_invisible_to_other_transactions(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as writer:
            await writer.apply(_delete("graph.Node", 1))

            async with backend.transaction() as reader:
                assert await reader.fields("graph.Node", [1]) == {"label": ["a"]}

    async def test_entity_created_and_deleted_in_one_transaction(self, backend: Backend) -> None:
        await _commit(backend, _node(1), _delete("graph.Node", 1))

        assert not await _exists(backend, "graph.Node", 1)

    async def test_entity_created_and_deleted_in_one_change_set(self, backend: Backend) -> None:
        # Creations are applied before deletions, so a change set may create an entity and delete it again.
        change_set = ChangeSet(
            created=[CreatedBatch("graph.Node", [1], {"label": ["a"]})],
            deleted=[DeletedBatch("graph.Node", [1])],
        )

        await _commit(backend, change_set)

        assert not await _exists(backend, "graph.Node", 1)

    # --- Rejected deletions ---

    async def test_deleting_an_unknown_id_is_rejected(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            with pytest.raises(UnknownEntityError, match="99"):
                await tx.apply(_delete("graph.Node", 1, 99))

    async def test_deleting_under_the_wrong_type_is_rejected(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            with pytest.raises(UnknownEntityError, match="graph.Edge"):
                await tx.apply(_delete("graph.Edge", 1))

    async def test_deleting_the_same_id_twice_is_rejected(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            with pytest.raises(UnknownEntityError):
                await tx.apply(_delete("graph.Node", 1, 1))

    async def test_deleting_an_already_deleted_entity_is_rejected(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])
        await _commit(backend, _delete("graph.Node", 1))

        async with backend.transaction() as tx:
            with pytest.raises(UnknownEntityError):
                await tx.apply(_delete("graph.Node", 1))

    async def test_rejected_deletion_writes_nothing(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            with pytest.raises(UnknownEntityError):
                await tx.apply(
                    ChangeSet(
                        created=[CreatedBatch("graph.Node", [2], {"label": ["b"]})],
                        deleted=[DeletedBatch("graph.Node", [1, 99])],
                    )
                )
            assert await tx.fields("graph.Node", [1]) == {"label": ["a"]}
            with pytest.raises(UnknownEntityError):
                await tx.fields("graph.Node", [2])

    # --- Ids: no two live entities share one, and the mark only moves forward ---
    #
    # The store is the one issuing ids and it never issues the same id twice; the backend keeps the
    # mark the store continues from. Operations run concurrently and may commit in any order, so the
    # backend must not expect ids to arrive sorted.

    async def test_id_of_a_live_entity_cannot_be_taken_in_the_same_change_set(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])

        async with backend.transaction() as tx:
            with pytest.raises(DuplicateIdError):
                await tx.apply(
                    ChangeSet(
                        created=[CreatedBatch("graph.Node", [1], {"label": ["again"]})],
                        deleted=[DeletedBatch("graph.Node", [1])],
                    )
                )

    async def test_id_from_a_rolled_back_deletion_is_still_taken(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1], label=["a"])
        async with backend.transaction() as tx:
            await tx.apply(_delete("graph.Node", 1))
            await tx.rollback()

        async with backend.transaction() as tx:
            with pytest.raises(DuplicateIdError):
                await tx.apply(_node(1))

    async def test_id_from_a_rolled_back_creation_is_free(self, backend: Backend) -> None:
        # The entity never existed for anyone else, so nothing can still refer to its id.
        async with backend.transaction() as tx:
            await tx.apply(_node(1))
            await tx.rollback()

        await _commit(backend, _node(1, "second attempt"))

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [1]) == {"label": ["second attempt"]}

    async def test_ids_may_be_committed_out_of_order(self, backend: Backend) -> None:
        # Two operations took ids 3 and 5; the one holding 5 happened to commit first.
        await _create(backend, "graph.Node", [5], label=["late id"])

        await _create(backend, "graph.Node", [3], label=["early id"])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [3, 5]) == {"label": ["early id", "late id"]}

    async def test_ids_inside_one_batch_need_not_be_sorted(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [2, 0, 1], label=["c", "a", "b"])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [0, 1, 2]) == {"label": ["a", "b", "c"]}

    async def test_gaps_between_ids_are_allowed(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1, 5, 9], label=["a", "b", "c"])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [9, 1]) == {"label": ["c", "a"]}
        assert not await _exists(backend, "graph.Node", 3)

    async def test_mark_is_the_highest_id_ever_taken_not_the_latest(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [5], label=["a"])
        await _create(backend, "graph.Node", [3], label=["b"])

        assert await _next_id(backend, "graph.Node") == 6

    async def test_mark_is_not_lowered_by_deleting_the_highest_entity(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [1, 2], label=["a", "b"])
        await _commit(backend, _delete("graph.Node", 2))

        assert await _next_id(backend, "graph.Node") == 3

    async def test_mark_counts_an_entity_created_and_deleted_in_one_transaction(self, backend: Backend) -> None:
        await _commit(backend, _node(4), _delete("graph.Node", 4))

        assert await _next_id(backend, "graph.Node") == 5

    async def test_mark_moved_by_a_rolled_back_transaction_is_restored(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.apply(_node(50))
            await tx.rollback()

        assert await _next_id(backend, "graph.Node") == 0

    # --- Reading the mark: the store continues numbering from it ---

    async def test_mark_of_a_type_without_entities_is_zero(self, backend: Backend) -> None:
        assert await _next_id(backend, "graph.Node") == 0

    async def test_mark_is_one_past_the_highest_id(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1, 5], label=["a", "b", "c"])

        assert await _next_id(backend, "graph.Node") == 6

    async def test_each_type_reports_its_own_mark(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1, 2], label=["a", "b", "c"])
        await _create(backend, "graph.Edge", [0], u=[0], v=[1])

        assert await _next_id(backend, "graph.Node") == 3
        assert await _next_id(backend, "graph.Edge") == 1
        assert await _next_id(backend, "graph.Other") == 0

    async def test_mark_reflects_the_transaction_own_changes(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.apply(_node(4))

            assert await tx.next_id("graph.Node") == 5

    async def test_uncommitted_mark_is_invisible_to_other_transactions(self, backend: Backend) -> None:
        async with backend.transaction() as writer:
            await writer.apply(_node(4))

            assert await _next_id(backend, "graph.Node") == 0

    async def test_reported_mark_is_not_lowered_by_deletion(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1], label=["a", "b"])
        await _commit(backend, _delete("graph.Node", 1), _delete("graph.Node", 0))

        assert await _next_id(backend, "graph.Node") == 2

    async def test_reported_mark_is_restored_by_rollback(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0], label=["a"])
        async with backend.transaction() as tx:
            await tx.apply(_node(40))
            await tx.rollback()

        assert await _next_id(backend, "graph.Node") == 1

    async def test_ids_taken_from_the_mark_are_accepted(self, backend: Backend) -> None:
        # What a store does: read the mark once, then number new entities from it.
        await _create(backend, "graph.Node", [0, 1], label=["a", "b"])
        start = await _next_id(backend, "graph.Node")

        await _create(backend, "graph.Node", [start, start + 1], label=["c", "d"])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", [2, 3]) == {"label": ["c", "d"]}
        assert await _next_id(backend, "graph.Node") == 4

    async def test_mark_cannot_be_read_from_a_closed_transaction(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.commit()

            with pytest.raises(TransactionClosedError):
                await tx.next_id("graph.Node")

    async def test_empty_batches_are_no_ops(self, backend: Backend) -> None:
        await _commit(backend, ChangeSet(created=[CreatedBatch("graph.Node", [])], deleted=[DeletedBatch("graph.Edge", [])]))

        assert await _next_id(backend, "graph.Node") == 0
        assert await _next_id(backend, "graph.Edge") == 0

    # --- Listing all entities of a type ---

    async def test_all_lists_the_ids_of_a_type(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1, 2], label=["a", "b", "c"])

        assert await _all_ids(backend, "graph.Node") == [0, 1, 2]

    async def test_all_is_sorted_by_id(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [3, 7], label=["a", "b"])
        await _create(backend, "graph.Node", [9], label=["c"])
        await _commit(backend, _delete("graph.Node", 7))
        await _create(backend, "graph.Node", [12, 20], label=["d", "e"])

        assert await _all_ids(backend, "graph.Node") == [3, 9, 12, 20]

    async def test_all_of_a_type_without_entities_is_empty(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0], label=["a"])

        assert await _all_ids(backend, "graph.Edge") == []

    async def test_all_lists_only_the_requested_type(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1], label=["a", "b"])
        await _create(backend, "graph.Edge", [0, 5], u=[0, 1], v=[1, 0])

        assert await _all_ids(backend, "graph.Node") == [0, 1]
        assert await _all_ids(backend, "graph.Edge") == [0, 5]

    async def test_all_skips_deleted_entities(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1, 2], label=["a", "b", "c"])
        await _commit(backend, _delete("graph.Node", 1))

        assert await _all_ids(backend, "graph.Node") == [0, 2]

    async def test_all_is_empty_after_everything_is_deleted(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1], label=["a", "b"])
        await _commit(backend, _delete("graph.Node", 0, 1))

        assert await _all_ids(backend, "graph.Node") == []

    async def test_all_reflects_the_transaction_own_changes(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1], label=["a", "b"])

        async with backend.transaction() as tx:
            await tx.apply(_node(2))
            await tx.apply(_delete("graph.Node", 0))

            assert await tx.all("graph.Node") == [1, 2]

    async def test_all_does_not_see_uncommitted_changes_of_others(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0], label=["a"])

        async with backend.transaction() as writer:
            await writer.apply(_node(1))
            await writer.apply(_delete("graph.Node", 0))

            assert await _all_ids(backend, "graph.Node") == [0]

    async def test_all_returns_a_list_the_caller_may_change(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1], label=["a", "b"])

        async with backend.transaction() as tx:
            ids = await tx.all("graph.Node")
            ids.clear()

            assert await tx.all("graph.Node") == [0, 1]

    async def test_all_ids_can_be_passed_straight_to_fields(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 4], label=["a", "b"])

        async with backend.transaction() as tx:
            assert await tx.fields("graph.Node", await tx.all("graph.Node")) == {"label": ["a", "b"]}

    async def test_all_cannot_be_read_from_a_closed_transaction(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.commit()

            with pytest.raises(TransactionClosedError):
                await tx.all("graph.Node")

    # --- Asking which entities exist ---

    async def test_existing_returns_the_ids_that_exist(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1, 2], label=["a", "b", "c"])

        async with backend.transaction() as tx:
            assert await tx.existing("graph.Node", [2, 5, 0]) == [0, 2]

    async def test_existing_lists_each_id_once(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1], label=["a", "b"])

        async with backend.transaction() as tx:
            assert await tx.existing("graph.Node", [1, 1, 0, 1]) == [0, 1]

    async def test_existing_of_nothing_or_of_an_unknown_type_is_empty(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0], label=["a"])

        async with backend.transaction() as tx:
            assert await tx.existing("graph.Node", []) == []
            assert await tx.existing("graph.Edge", [0]) == []

    async def test_existing_skips_deleted_entities(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0, 1], label=["a", "b"])
        await _commit(backend, _delete("graph.Node", 0))

        async with backend.transaction() as tx:
            assert await tx.existing("graph.Node", [0, 1]) == [1]

    async def test_existing_reflects_the_transaction_own_changes_only(self, backend: Backend) -> None:
        await _create(backend, "graph.Node", [0], label=["a"])

        async with backend.transaction() as writer:
            await writer.apply(_node(1))
            await writer.apply(_delete("graph.Node", 0))

            assert await writer.existing("graph.Node", [0, 1]) == [1]
            async with backend.transaction() as reader:
                assert await reader.existing("graph.Node", [0, 1]) == [0]

    async def test_existing_cannot_be_read_from_a_closed_transaction(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.commit()

            with pytest.raises(TransactionClosedError):
                await tx.existing("graph.Node", [0])

    # --- Reverse lookup: which entities hold one of these ids in a given column ---
    #
    # The backend does not know which columns are references: the store names the column to search.

    async def test_referencing_finds_entities_by_a_column_value(self, backend: Backend) -> None:
        await _edges(backend)

        assert await _referencing(backend, "graph.Edge", "u", 0) == [0, 2]
        assert await _referencing(backend, "graph.Edge", "v", 2) == [1, 2, 3]

    async def test_referencing_searches_only_the_named_column(self, backend: Backend) -> None:
        await _edges(backend)

        assert await _referencing(backend, "graph.Edge", "u", 1) == [1]
        assert await _referencing(backend, "graph.Edge", "v", 1) == [0]

    async def test_referencing_accepts_several_targets(self, backend: Backend) -> None:
        await _edges(backend)

        assert await _referencing(backend, "graph.Edge", "u", 0, 1) == [0, 1, 2]

    async def test_referencing_result_is_sorted_and_has_no_duplicates(self, backend: Backend) -> None:
        await _edges(backend)

        assert await _referencing(backend, "graph.Edge", "v", 2, 1, 2) == [0, 1, 2, 3]

    async def test_referencing_nothing_returns_nothing(self, backend: Backend) -> None:
        await _edges(backend)

        assert await _referencing(backend, "graph.Edge", "u") == []

    async def test_referencing_an_id_nobody_holds_returns_nothing(self, backend: Backend) -> None:
        await _edges(backend)

        assert await _referencing(backend, "graph.Edge", "u", 99) == []

    async def test_referencing_in_an_unknown_type_or_column_returns_nothing(self, backend: Backend) -> None:
        await _edges(backend)

        assert await _referencing(backend, "graph.Missing", "u", 0) == []
        assert await _referencing(backend, "graph.Edge", "missing", 0) == []

    async def test_referencing_searches_only_the_named_type(self, backend: Backend) -> None:
        await _edges(backend)
        await _create(backend, "sockets.Socket", [0, 1], node=[0, 2])

        assert await _referencing(backend, "sockets.Socket", "node", 0) == [0]
        assert await _referencing(backend, "graph.Edge", "node", 0) == []

    # --- Columns holding several ids, and empty links ---

    async def test_referencing_looks_inside_tuples(self, backend: Backend) -> None:
        # A Refs / OptionalRefs column stores a tuple of ids per entity.
        await _create(backend, "team.Team", [0, 1, 2], members=[(5, 6), (6,), ()])

        assert await _referencing(backend, "team.Team", "members", 6) == [0, 1]
        assert await _referencing(backend, "team.Team", "members", 5) == [0]
        assert await _referencing(backend, "team.Team", "members", 7) == []

    async def test_entity_holding_several_targets_is_listed_once(self, backend: Backend) -> None:
        await _create(backend, "team.Team", [0], members=[(5, 6, 5)])

        assert await _referencing(backend, "team.Team", "members", 5, 6) == [0]

    async def test_empty_link_references_nothing(self, backend: Backend) -> None:
        # An empty OptionalRef is stored as None; an empty link inside OptionalRefs is None too.
        await _create(backend, "note.Note", [0, 1, 2], target=[None, 4, None])
        await _create(backend, "team.Team", [0], members=[(None, 4)])

        assert await _referencing(backend, "note.Note", "target", 4) == [1]
        assert await _referencing(backend, "team.Team", "members", 4) == [0]

    # --- Reverse lookup follows the same rules as every other read ---

    async def test_referencing_skips_deleted_entities(self, backend: Backend) -> None:
        await _edges(backend)
        await _commit(backend, _delete("graph.Edge", 2))

        assert await _referencing(backend, "graph.Edge", "u", 0) == [0]

    async def test_referencing_still_finds_holders_of_a_deleted_target(self, backend: Backend) -> None:
        # The backend does not follow references: a column keeps the id of a deleted entity.
        await _edges(backend)
        await _commit(backend, _delete("graph.Node", 0))

        assert await _referencing(backend, "graph.Edge", "u", 0) == [0, 2]

    async def test_referencing_reflects_the_transaction_own_changes(self, backend: Backend) -> None:
        await _edges(backend)

        async with backend.transaction() as tx:
            await tx.apply(ChangeSet(created=[CreatedBatch("graph.Edge", [4], {"u": [0], "v": [0]})]))
            await tx.apply(_delete("graph.Edge", 0))

            assert await tx.referencing("graph.Edge", "u", [0]) == [2, 4]

    async def test_referencing_does_not_see_uncommitted_changes_of_others(self, backend: Backend) -> None:
        await _edges(backend)

        async with backend.transaction() as writer:
            await writer.apply(ChangeSet(created=[CreatedBatch("graph.Edge", [4], {"u": [0], "v": [0]})]))

            assert await _referencing(backend, "graph.Edge", "u", 0) == [0, 2]

    async def test_referencing_cannot_be_read_from_a_closed_transaction(self, backend: Backend) -> None:
        async with backend.transaction() as tx:
            await tx.commit()

            with pytest.raises(TransactionClosedError):
                await tx.referencing("graph.Edge", "u", [0])

    async def test_cascade_can_be_planned_with_referencing(self, backend: Backend) -> None:
        # What a store does to delete node 0: find the edges holding it in `u` or `v`, then delete all at once.
        await _edges(backend)

        async with backend.transaction() as tx:
            doomed = sorted({*await tx.referencing("graph.Edge", "u", [0]), *await tx.referencing("graph.Edge", "v", [0])})
            await tx.apply(ChangeSet(deleted=[DeletedBatch("graph.Edge", doomed), DeletedBatch("graph.Node", [0])]))
            await tx.commit()

        assert await _all_ids(backend, "graph.Edge") == [1, 3]
        assert await _all_ids(backend, "graph.Node") == [1, 2]

import asyncio
import weakref
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, TypeGuard, TypeVar

from fluon._core.backend import Backend, ChangeSet, CreatedBatch, DeletedBatch, Transaction
from fluon._core.context import current_operation
from fluon._core.entity import fill_handle, make_handle, mark_dead, set_operation, unload
from fluon._core.errors import AlreadyAddedError, AwaitRequiredError, ForeignEntityError, NoActiveOperationError, NotAddedError, UnknownEntityError
from fluon._core.registry import Registry
from fluon._core.registry import registry as default_registry
from fluon._core.types.descriptors import Link
from fluon._core.utils import id_of, registry_of

T = TypeVar("T")


def _is_link(obj: object) -> TypeGuard[Link[Any]]:
    # A plain isinstance narrows to Link[Unknown] in pyright, which strict mode then refuses to pass on.
    return isinstance(obj, Link)


class Operation:
    def __init__(self, store: "Store", state: "_StoreState") -> None:
        self.store = store
        self._state = state
        # (class, id) -> handle, in creation order. Ordinary references: the store itself holds handles
        # only weakly, so an entity nobody kept would vanish before it is written.
        self.created: dict[tuple[type, int], Any] = {}
        self.removed: dict[tuple[type, int], Any] = {}
        self.closed = False  # set when the block ends: the operation takes nothing more

    def add(self, entity: T) -> T:
        """Add a new entity to the store: it gets its id at once and is written when the operation ends."""
        if self.closed:
            raise NoActiveOperationError("op.add")
        cls = type(entity)
        if registry_of(cls) is None:
            raise TypeError(f"Expected an entity, got {cls.__name__!r}")
        self._state.registry.by_class(cls)  # the type has to belong to the registry of this store
        draft: dict[str, Any] | None = getattr(entity, "_draft")
        if draft is None:
            raise AlreadyAddedError(entity)
        values: dict[str, Any] = {}
        for name, value in draft.items():
            field_type = vars(cls)[name].field_type
            try:
                values[name] = field_type.dump(value, self.store)
            except (NotAddedError, ForeignEntityError) as e:
                raise type(e)(e.entity, where=f"{cls.__name__}.{name}") from None
        # Nothing can fail from here on: a rejected entity takes no id and stays as it was.
        id_ = self._state.issue(cls)
        fill_handle(entity, self.store, id_, values)
        set_operation(entity, self)
        self._state.handles[(cls, id_)] = entity
        self.created[(cls, id_)] = entity
        return entity

    def remove(self, entity: object) -> None:
        """Remove an entity from the store: it is deleted when the operation ends."""
        if self.closed:
            raise NoActiveOperationError("op.remove")
        cls, id_ = type(entity), id_of(entity)
        if getattr(entity, "_src") is not self.store:
            raise ForeignEntityError(entity)
        if getattr(entity, "_dead"):
            return  # already removed
        if (cls, id_) in self.created:
            del self.created[(cls, id_)]
            mark_dead(entity)  # never written and never will be: dead at once, for everyone
            return  # created and removed in the same operation: nothing to write
        self.removed[(cls, id_)] = entity

    def change_set(self) -> ChangeSet:
        created_by_type: dict[type, list[tuple[int, dict[str, Any]]]] = {}
        deleted_by_type: dict[type, list[int]] = {}
        for (cls, id_), handle in self.created.items():
            created_by_type.setdefault(cls, []).append((id_, handle._values))
        for cls, id_ in self.removed:
            deleted_by_type.setdefault(cls, []).append(id_)
        return ChangeSet(
            created=[
                CreatedBatch(
                    type_key=self._state.registry.by_class(cls).key,
                    ids=[id_ for id_, _ in rows],
                    columns={name: [values[name] for _, values in rows] for name in rows[0][1]},
                )
                for cls, rows in created_by_type.items()
            ],
            deleted=[
                DeletedBatch(
                    type_key=self._state.registry.by_class(cls).key,
                    ids=[id_ for id_ in rows],
                )
                for cls, rows in deleted_by_type.items()
            ],
        )


class _StoreState:
    """Everything a store and its operations share. Never handed to users."""

    def __init__(self, backend: Backend, registry: Registry) -> None:
        self.backend = backend
        self.registry = registry
        self.next_id: dict[type, int] = {}
        self.handles: weakref.WeakValueDictionary[tuple[type, int], Any] = weakref.WeakValueDictionary()
        self.lock = asyncio.Lock()

    def issue(self, cls: type) -> int:
        id_ = self.next_id.get(cls, 0)
        self.next_id[cls] = id_ + 1
        return id_


class Store:
    def __init__(self, backend: Backend, *, registry: Registry | None = None) -> None:
        self._state = _StoreState(backend, registry if registry is not None else default_registry)

    # --- Operations ---

    @asynccontextmanager
    async def op(self) -> AsyncGenerator[Operation, None]:
        await self._load_marks()
        operation = Operation(self, self._state)
        token = current_operation.set(operation)
        try:
            yield operation
        finally:
            operation.closed = True
            current_operation.reset(token)

        # Reached only when the block finished without an exception.
        if not operation.created and not operation.removed:
            return
        async with self._state.lock, self._state.backend.transaction() as tx:
            changes = ChangeSet(created=operation.change_set().created, deleted=await self._plan_removals(operation, tx))
            await tx.apply(changes)
            await tx.commit()
        for created in operation.created.values():
            set_operation(created, None)
        for deleted in operation.removed.values():
            mark_dead(deleted)

    async def _plan_removals(self, operation: Operation, tx: Transaction) -> list[DeletedBatch]:
        """What the backend is asked to delete: only entities it is known, or found, to hold."""
        sure: dict[type, list[int]] = {}
        unsure: dict[type, list[int]] = {}
        for (cls, id_), handle in operation.removed.items():
            known = handle._values is not None and handle._op is None  # loaded and written by this store
            (sure if known else unsure).setdefault(cls, []).append(id_)
        for cls, ids in unsure.items():
            present = await tx.existing(self._state.registry.by_class(cls).key, ids)
            if present:
                sure.setdefault(cls, []).extend(present)
        return [DeletedBatch(self._state.registry.by_class(cls).key, sorted(ids)) for cls, ids in sure.items()]

    async def _load_marks(self) -> None:
        missing = [cls for cls in self._state.registry.classes() if cls not in self._state.next_id]
        if not missing:
            return
        async with self._state.backend.transaction() as tx:
            for cls in missing:
                self._state.next_id[cls] = await tx.next_id(self._state.registry.by_class(cls).key)

    # --- Reading ---

    async def fetch(self, cls: type[T], id_: int) -> T:
        """The loaded handle of one entity."""
        if self._gone(cls, id_):
            raise UnknownEntityError(self._state.registry.by_class(cls).key, id_)
        held = self._held(cls, id_)
        if held is None:
            held = (await self._read({cls: [id_]}))[(cls, id_)]
        result: T = held
        return result

    async def all(self, cls: type[T]) -> list[T]:
        """Loaded handles of every entity of a type, sorted by id."""
        async with self._state.backend.transaction() as tx:
            ids = await tx.all(self._state.registry.by_class(cls).key)
        found = {id_: self._held(cls, id_) for id_ in ids}
        removed = self._removed_here(cls)
        for id_ in removed:
            if id_ in found:
                del found[id_]
        missing = [id_ for id_, handle in found.items() if handle is None]
        loaded = await self._read({cls: missing} if missing else {})
        found.update({id_: handle for (_, id_), handle in loaded.items()})
        found.update(self._created_here(cls))
        result: list[T] = [found[id_] for id_ in sorted(found)]
        return result

    async def load(self, *handles: object) -> None:
        """Load the given handles; the ones the store already holds are left alone."""
        await self._read(self._group(handles, skip_held=True))

    async def reload(self, *handles: object) -> None:
        """Read the given handles from the backend again, whether loaded or not."""
        await self._read(self._group(handles, skip_held=False), force=True)

    async def alive(self, entity: object) -> bool:
        if _is_link(entity):
            if entity.id is None:
                return False
            target: type = getattr(entity, "_target_type")  # the core reads what a Link keeps to itself
            cls, id_ = target, entity.id
        elif registry_of(type(entity)) is None:
            raise TypeError(f"Expected an entity or a Link, got {type(entity).__name__!r}")
        else:
            cls, id_ = type(entity), id_of(entity)

        if self._gone(cls, id_):
            return False  # known to be removed
        if self._held(cls, id_) is not None:
            return True  # known to exist
        async with self._state.backend.transaction() as tx:  # not known: ask
            return bool(await tx.existing(self._state.registry.by_class(cls).key, [id_]))

    def is_alive(self, cls: type[T], id_: int) -> bool:
        """The synchronous question a source is asked by `alive(e)` and `link.alive`; a live store cannot answer it."""
        raise AwaitRequiredError("alive()", "await store.alive(...)")

    def handle(self, cls: type[Any], id_: int) -> Any:
        """The handle of an entity, loaded or not: the one already given out, or a new unloaded one."""
        found: Any = self._state.handles.get((cls, id_))
        if found is None:
            found = make_handle(cls, self, id_, None)
            self._state.handles[(cls, id_)] = found
        return found

    def _gone(self, cls: type[T], id_: int) -> bool:
        """Whether the store knows the entity is removed: written as removed, or being removed right now."""
        found = self._state.handles.get((cls, id_))
        if found is not None and found._dead:
            return True
        operation = current_operation.get()
        return operation is not None and operation.store is self and (cls, id_) in operation.removed

    def _held(self, cls: type[T], id_: int) -> Any:
        """The loaded handle of an entity that is written, or is being created by the current operation.

        The store is the only writer to its backend, so such a handle needs no confirmation from it.
        A handle left behind by another or a discarded operation is not trusted.
        """
        found = self._state.handles.get((cls, id_))
        if found is None or found._values is None or self._gone(cls, id_):
            return None
        if found._op is None or found._op is current_operation.get():
            return found
        return None

    def _created_here(self, cls: type) -> dict[int, Any]:
        """Entities of a type created by the current operation of this store and not yet written."""
        operation = current_operation.get()
        if operation is None or operation.store is not self:
            return {}
        return {id_: handle for (created_cls, id_), handle in operation.created.items() if created_cls is cls}

    def _removed_here(self, cls: type) -> dict[int, Any]:
        """Entities of a type removed by the current operation of this store and not yet written."""
        operation = current_operation.get()
        if operation is None or operation.store is not self:
            return {}
        return {id_: handle for (removed_cls, id_), handle in operation.removed.items() if removed_cls is cls}

    def _group(self, handles: tuple[object, ...], *, skip_held: bool) -> dict[type, list[int]]:
        """Sort handles into {type: ids}, each entity once."""
        wanted: dict[type, list[int]] = {}
        operation = current_operation.get()
        for handle in handles:
            cls, id_ = type(handle), id_of(handle)
            if operation is not None and getattr(handle, "_op") is operation:
                continue  # being created right now: the backend has nothing to say about it yet
            if skip_held and self._held(cls, id_) is not None:
                continue
            ids = wanted.setdefault(cls, [])
            if id_ not in ids:
                ids.append(id_)
        return wanted

    async def _read(self, wanted: dict[type, list[int]], *, force: bool = False) -> dict[tuple[type, int], Any]:
        """Read these entities from the backend and return their loaded handles.

        The returned dict keeps the handles alive for the caller: the store itself holds them only weakly.
        """
        loaded: dict[tuple[type, int], Any] = {}
        if not wanted:
            return loaded
        async with self._state.backend.transaction() as tx:
            for cls, ids in wanted.items():
                try:
                    columns = await tx.fields(self._state.registry.by_class(cls).key, ids)
                except UnknownEntityError:
                    # The backend no longer has one of them: none of these handles can be trusted as loaded.
                    for id_ in ids:
                        stale = self._state.handles.get((cls, id_))
                        if stale is not None:
                            unload(stale)
                    raise
                for i, id_ in enumerate(ids):
                    values = {name: column[i] for name, column in columns.items()}
                    loaded[(cls, id_)] = self._materialize(cls, id_, values, force=force)
        return loaded

    def _materialize(self, cls: type, id_: int, values: dict[str, Any], *, force: bool = False) -> Any:
        """Give the handle of an entity the values just read from the backend."""
        found = self.handle(cls, id_)
        if found._values is None or force:
            fill_handle(found, self, id_, values)
        set_operation(found, None)
        return found

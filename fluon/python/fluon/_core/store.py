import asyncio
import weakref
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from fluon._core.backend import Backend, ChangeSet, CreatedBatch
from fluon._core.context import current_operation
from fluon._core.entity import fill_handle, make_handle, set_operation, unload
from fluon._core.errors import UnknownEntityError
from fluon._core.registry import Registry
from fluon._core.registry import registry as default_registry
from fluon._core.types.field import Field, resolve

T = TypeVar("T")


class Operation:
    def __init__(self, store: "Store", state: "_StoreState") -> None:
        self.store = store
        self._state = state
        # (class, id) -> handle, in creation order. Ordinary references: the store itself holds handles
        # only weakly, so an entity nobody kept would vanish before it is written.
        self.created: dict[tuple[type, int], Any] = {}

    def create(self, handle: object, kwargs: dict[str, Any]) -> None:
        cls = type(handle)
        resolve(cls)
        values: dict[str, Any] = {}
        fields = vars(cls).items()
        field_names = {name for name, field in fields if isinstance(field, Field)}
        if extra := set(kwargs) - field_names:
            raise TypeError(f"{cls.__name__} got unexpected keyword arguments: {', '.join(repr(name) for name in extra)}")

        for name, field in fields:
            if not isinstance(field, Field):
                continue
            if name in kwargs:
                try:
                    assert field.field_type is not None
                    values[name] = field.field_type.dump(kwargs[name])
                except TypeError as e:
                    raise TypeError(f"{cls.__name__}.{name}: {e}") from None
            elif field.has_default:
                values[name] = field.default
            else:
                raise TypeError(f"{cls.__name__} is missing required field {name!r}")
        id_ = self._state.issue(cls)
        fill_handle(handle, self.store, id_, values)
        set_operation(handle, self)
        self._state.handles[(cls, id_)] = handle
        self.created[(cls, id_)] = handle

    def change_set(self) -> ChangeSet:
        by_type: dict[type, list[tuple[int, dict[str, Any]]]] = {}
        for (cls, id_), handle in self.created.items():
            by_type.setdefault(cls, []).append((id_, handle._values))
        return ChangeSet(
            created=[
                CreatedBatch(
                    type_key=self._state.registry.by_class(cls).key,
                    ids=[id_ for id_, _ in rows],
                    columns={name: [values[name] for _, values in rows] for name in rows[0][1]},
                )
                for cls, rows in by_type.items()
            ]
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
            current_operation.reset(token)

        # Reached only when the block finished without an exception.
        changes = operation.change_set()
        if not changes.created and not changes.deleted:
            return
        async with self._state.lock, self._state.backend.transaction() as tx:
            await tx.apply(changes)
            await tx.commit()
        for created in operation.created.values():
            set_operation(created, None)

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

    def handle(self, cls: type[Any], id_: int) -> Any:
        """The handle of an entity, loaded or not: the one already given out, or a new unloaded one."""
        found: Any = self._state.handles.get((cls, id_))
        if found is None:
            found = make_handle(cls, self, id_, None)
            self._state.handles[(cls, id_)] = found
        return found

    def _held(self, cls: type, id_: int) -> Any:
        """The loaded handle of an entity that is written, or is being created by the current operation.

        The store is the only writer to its backend, so such a handle needs no confirmation from it.
        A handle left behind by another or a discarded operation is not trusted.
        """
        found = self._state.handles.get((cls, id_))
        if found is None or found._values is None:
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

    def _group(self, handles: tuple[object, ...], *, skip_held: bool) -> dict[type, list[int]]:
        """Sort handles into {type: ids}, each entity once."""
        wanted: dict[type, list[int]] = {}
        operation = current_operation.get()
        for handle in handles:
            cls, id_ = type(handle), getattr(handle, "_id")
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

from collections.abc import Iterable
from typing import Any, Generic, Self, TypeVar, overload

from fluon._core.errors import MissingError

T = TypeVar("T")


# Reference markers. `Ref[Node]` and friends exist for type checkers: the signatures of __get__ and
# __set__ tell them what a field accepts on creation and what it gives back when read. At run time
# these methods are never called; the attribute on the class is a `Field` (see field.py).


class Link(Generic[T]):
    """What an OptionalRef field reads as: a reference whose target may be gone.

    An empty link (the field was given None) has no id and is never alive.
    """

    def __init__(self, _id: int | None, src: Any, target_type: type) -> None:
        self._id = _id
        self._src = src
        self._target_type = target_type

    @property
    def id(self) -> int | None:
        return self._id

    @property
    def alive(self) -> bool:
        return self.id is not None and self._src.alive(self._target_type, self.id)

    def get(self) -> T:
        if not self.alive:
            raise MissingError(self._target_type, self.id)
        target: T = self._src.handle(self._target_type, self.id)
        return target


class Ref(Generic[T]):
    """A strong reference: created from a T, read as a T. The holder is removed with the target."""

    # Read through the class, a field gives its descriptor; through an instance, its value.
    @overload
    def __get__(self, obj: None, owner: Any) -> Self: ...

    @overload
    def __get__(self, obj: object, owner: Any) -> T: ...

    def __get__(self, obj: object, owner: Any) -> Any:
        raise NotImplementedError

    def __set__(self, obj: object, value: T) -> None:
        raise NotImplementedError


class OptionalRef(Generic[T]):
    """A weak reference: created from a T or None, read as a Link[T]. The holder outlives the target."""

    @overload
    def __get__(self, obj: None, owner: Any) -> Self: ...

    @overload
    def __get__(self, obj: object, owner: Any) -> Link[T]: ...

    def __get__(self, obj: object, owner: Any) -> Any:
        raise NotImplementedError

    def __set__(self, obj: object, value: T | None) -> None:
        raise NotImplementedError


class Refs(Generic[T]):
    """A flat collection of strong references: created from any iterable of T, read as a tuple of T."""

    @overload
    def __get__(self, obj: None, owner: Any) -> Self: ...

    @overload
    def __get__(self, obj: object, owner: Any) -> tuple[T, ...]: ...

    def __get__(self, obj: object, owner: Any) -> Any:
        raise NotImplementedError

    def __set__(self, obj: object, value: Iterable[T]) -> None:
        raise NotImplementedError


class OptionalRefs(Generic[T]):
    """A flat collection of weak references: read as a tuple of Link[T]."""

    @overload
    def __get__(self, obj: None, owner: Any) -> Self: ...

    @overload
    def __get__(self, obj: object, owner: Any) -> tuple[Link[T], ...]: ...

    def __get__(self, obj: object, owner: Any) -> Any:
        raise NotImplementedError

    def __set__(self, obj: object, value: Iterable[T | None]) -> None:
        raise NotImplementedError

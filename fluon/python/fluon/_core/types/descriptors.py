from collections.abc import Iterable
from typing import Any, Generic, Self, TypeVar, overload

from fluon._core.errors import MissingError

T = TypeVar("T")


class Link(Generic[T]):
    def __init__(self, _id: int | None, src: Any, target_type: type) -> None:  # TODO: replace with special id type`
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
    @overload
    def __get__(self, obj: None, owner: Any) -> Self: ...

    @overload
    def __get__(self, obj: object, owner: Any) -> T: ...

    def __get__(self, obj: object, owner: Any) -> Any:
        raise NotImplementedError

    def __set__(self, obj: object, value: T) -> None:
        raise NotImplementedError


class OptionalRef(Generic[T]):
    @overload
    def __get__(self, obj: None, owner: Any) -> Self: ...

    @overload
    def __get__(self, obj: object, owner: Any) -> Link[T]: ...

    def __get__(self, obj: object, owner: Any) -> Any:
        raise NotImplementedError

    def __set__(self, obj: object, value: T | None) -> None:
        raise NotImplementedError


class Refs(Generic[T]):
    @overload
    def __get__(self, obj: None, owner: Any) -> Self: ...

    @overload
    def __get__(self, obj: object, owner: Any) -> tuple[T, ...]: ...

    def __get__(self, obj: object, owner: Any) -> Any:
        raise NotImplementedError

    def __set__(self, obj: object, value: Iterable[T]) -> None:
        raise NotImplementedError


class OptionalRefs(Generic[T]):
    @overload
    def __get__(self, obj: None, owner: Any) -> Self: ...

    @overload
    def __get__(self, obj: object, owner: Any) -> tuple[Link[T], ...]: ...

    def __get__(self, obj: object, owner: Any) -> Any:
        raise NotImplementedError

    def __set__(self, obj: object, value: Iterable[T | None]) -> None:
        raise NotImplementedError

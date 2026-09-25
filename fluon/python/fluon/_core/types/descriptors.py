from collections.abc import Iterable
from typing import Any, Generic, Self, TypeVar, overload

T = TypeVar("T")


class Link(Generic[T]):
    # Placeholder: used only as a type in signatures until links get a source and a target type.
    def __init__(self, _id: str) -> None:  # TODO: replace with special id type
        raise NotImplementedError

    @property
    def id(self) -> str:
        raise NotImplementedError

    @property
    def alive(self) -> bool:
        # Placeholder for actual implementation
        raise NotImplementedError

    def get(self) -> T:
        # Placeholder for actual implementation
        raise NotImplementedError


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

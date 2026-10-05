from dataclasses import dataclass

from fluon._core.errors import InvalidTypeKeyError, NotRegisteredError, TypeKeyCollisionError, UnknownTypeError


@dataclass(frozen=True)
class TypeInfo:
    """What the registry knows about a registered type."""

    key: str
    version: int
    cls: type


@dataclass(frozen=True)
class _RegistryState:
    """Opaque saved state of a registry; see Registry._snapshot."""

    by_key: dict[str, TypeInfo]
    by_class: dict[type, TypeInfo]


class Registry:
    """Maps stable type keys to registered classes and back."""

    def __init__(self) -> None:
        self._by_key: dict[str, TypeInfo] = {}
        self._by_class: dict[type, TypeInfo] = {}

    def register(self, key: str, version: int, cls: type) -> TypeInfo:
        # The only way in: every key held by a registry has passed these checks.
        _check_key(key)
        _check_version(version)
        if key in self._by_key:
            raise TypeKeyCollisionError(key)
        info = TypeInfo(key, version, cls)
        self._by_key[key] = info
        self._by_class[cls] = info
        return info

    def classes(self) -> list[type]:
        """Every registered class, in registration order."""
        return list(self._by_class.keys())

    def by_key(self, key: str) -> TypeInfo:
        try:
            return self._by_key[key]
        except KeyError:
            raise UnknownTypeError(key) from None

    def by_class(self, cls: type) -> TypeInfo:
        try:
            return self._by_class[cls]
        except KeyError:
            raise NotRegisteredError(cls.__name__) from None

    def is_registered(self, obj: object) -> bool:
        """Tell whether obj is a registered class. Any object is accepted; non-classes are never registered."""
        return isinstance(obj, type) and obj in self._by_class

    def _snapshot(self) -> _RegistryState:
        """Save the current state. Meant for tests: the registry is process-wide."""
        return _RegistryState(dict(self._by_key), dict(self._by_class))

    def _restore(self, state: _RegistryState) -> None:
        """Return to a state saved by _snapshot, dropping everything registered since."""
        self._by_key = dict(state.by_key)
        self._by_class = dict(state.by_class)


registry = Registry()
"""The process-wide registry: types are registered here on import."""


def _check_key(key: str) -> None:
    # "<package>.<Name>": dot-separated identifiers, at least two of them.
    parts = key.split(".")
    if len(parts) < 2 or not all(part.isidentifier() for part in parts):
        raise InvalidTypeKeyError(key)


def _check_version(version: object) -> None:
    # bool is a subclass of int, but True is not a meaningful schema version.
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError(f"version must be an int, got {type(version).__name__}")
    if version < 1:
        raise ValueError(f"version must be positive, got {version}")

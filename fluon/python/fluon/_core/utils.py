from fluon._core.errors import NotAddedError
from fluon._core.registry import Registry
from fluon._core.types.descriptors import Link


def alive(entity: object) -> bool:
    """Return whether the entity is still alive in its source."""
    if type(entity) is Link:
        raise TypeError("Expected an entity, got a Link. Use the `alive` property of the Link instead.")
    if registry_of(type(entity)) is None:
        raise TypeError(f"Expected an entity, got {type(entity).__name__!r}")
    id_ = id_of(entity)  # first: a new entity has no source to ask
    result: bool = getattr(entity, "_src").is_alive(type(entity), id_)
    return result


def id_of(entity: object) -> int:
    """Return the internal ID of the entity."""
    if type(entity) is Link:
        raise TypeError("Expected an entity, got a Link. Use the `id` property of the Link instead.")
    if registry_of(type(entity)) is None:
        raise TypeError(f"Expected an entity, got {type(entity).__name__!r}")
    result: int | None = getattr(entity, "_id")
    if result is None:
        raise NotAddedError(entity)
    return result


def registry_of(cls: object) -> Registry | None:
    """The registry an entity class belongs to, or None if `cls` is not an entity class."""
    # The mark alone is not enough: a subclass inherits it, and a registry may have dropped the class.
    owner = getattr(cls, "__fluon_registry__", None)
    if isinstance(owner, Registry) and owner.is_registered(cls):
        return owner
    return None

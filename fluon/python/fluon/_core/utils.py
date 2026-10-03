from fluon._core.types.descriptors import Link


def alive(entity: object) -> bool:
    """Return whether the entity is still alive in its source."""
    if type(entity) is Link:
        raise TypeError("Expected an entity, got a Link. Use the `alive` property of the Link instead.")
    if not hasattr(entity, "_src"):
        raise TypeError(f"Expected an entity, got {type(entity).__name__!r}")
    result: bool = getattr(entity, "_src").alive(type(entity), id_of(entity))
    return result


def id_of(entity: object) -> int:
    """Return the internal ID of the entity."""
    if type(entity) is Link:
        raise TypeError("Expected an entity, got a Link. Use the `id` property of the Link instead.")
    if not hasattr(entity, "_id"):
        raise TypeError(f"Expected an entity, got {type(entity).__name__!r}")
    result: int = getattr(entity, "_id")
    return result

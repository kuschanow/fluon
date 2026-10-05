class NotLoadedError(Exception):
    """Raised when a field of an entity is read before the entity was loaded from its store."""

    def __init__(self, entity: object) -> None:
        self.entity = entity
        super().__init__(f"{entity!r} is not loaded; call `await store.load(...)` first")

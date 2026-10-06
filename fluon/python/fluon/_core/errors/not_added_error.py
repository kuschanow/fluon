class NotAddedError(Exception):
    """Raised when a new entity is used as a stored one before it was passed to `op.add`."""

    def __init__(self, entity: object, where: str | None = None) -> None:
        self.entity = entity
        self.where = where
        prefix = f"{where}: " if where else ""
        super().__init__(f"{prefix}{entity!r} is not added to a store; pass it to `op.add(...)` first")

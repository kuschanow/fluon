class ForeignEntityError(Exception):
    """Raised when a store is given an entity that belongs to another store."""

    def __init__(self, entity: object, where: str | None = None) -> None:
        self.entity = entity
        self.where = where
        prefix = f"{where}: " if where else ""
        super().__init__(f"{prefix}{entity!r} belongs to another store")

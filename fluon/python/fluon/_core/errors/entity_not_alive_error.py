class EntityNotAliveError(Exception):
    """Raised when a removed entity is used as if it still existed."""

    def __init__(self, entity: object) -> None:
        self.entity = entity
        super().__init__(f"{entity!r} is not alive")

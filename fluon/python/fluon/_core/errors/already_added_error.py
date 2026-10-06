class AlreadyAddedError(Exception):
    """Raised when `op.add` is given an entity that already belongs to a store."""

    def __init__(self, entity: object) -> None:
        self.entity = entity
        super().__init__(f"{entity!r} is already added to a store")

class CrossRegistryReferenceError(Exception):
    """Raised when a reference field points to an entity type from a different registry."""

    def __init__(self, owner: type, field: str, target: type) -> None:
        self.owner = owner
        self.field = field
        self.target = target
        super().__init__(f"{owner.__name__}.{field} refers to {target.__name__}, which belongs to a different registry")

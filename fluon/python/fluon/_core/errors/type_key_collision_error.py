class TypeKeyCollisionError(Exception):
    """Raised when there is a collision in entity type keys."""

    def __init__(self, key: str):
        self.message = f"Entity type key '{key}' is already registered."
        super().__init__(self.message)

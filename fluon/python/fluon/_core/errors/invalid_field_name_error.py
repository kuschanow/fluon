class InvalidFieldNameError(Exception):
    """Raised when a field name is invalid."""

    def __init__(self, owner: type, field: str):
        self.owner = owner
        self.field = field
        super().__init__(f"Invalid field name: {field} for owner: {owner.__name__}")

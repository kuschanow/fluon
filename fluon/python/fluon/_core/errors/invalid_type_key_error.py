class InvalidTypeKeyError(Exception):
    """Raised when a type key is invalid."""

    def __init__(self, type_key: str):
        self.type_key = type_key
        super().__init__(f"Invalid type key {type_key!r}: expected '<package>.<Name>', dot-separated identifiers")

class UnknownTypeError(Exception):
    """Raised when an unknown type is encountered."""

    def __init__(self, key: str):
        self.message = f"Unknown type encountered: {key}"
        super().__init__(self.message)

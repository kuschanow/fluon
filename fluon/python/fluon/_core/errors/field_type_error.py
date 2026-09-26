class FieldTypeError(Exception):
    """Raised when a field has an invalid type."""

    def __init__(self, hint: object, reason: str) -> None:
        self.hint = hint
        self.reason = reason
        super().__init__(f"Unsupported field type: {hint!r}: {reason}")

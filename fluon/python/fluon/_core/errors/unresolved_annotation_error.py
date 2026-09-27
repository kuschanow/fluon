class UnresolvedAnnotationError(Exception):
    """Raised when an annotation cannot be resolved."""

    def __init__(self, class_name: str, field_name: str) -> None:
        self.class_name = class_name
        self.field_name = field_name
        super().__init__(f"Unresolved annotation in {class_name}.{field_name}")

class UnknownEntityError(Exception):
    """Raised when a backend is asked for an entity it does not have under the given type."""

    def __init__(self, type_key: str, id_: int) -> None:
        self.type_key = type_key
        self.id = id_
        super().__init__(f"No entity of type {type_key} with id {id_}")

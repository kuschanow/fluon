class DuplicateIdError(Exception):
    """Raised when a duplicate ID is encountered in the system."""

    def __init__(self, type_key: str, id_: int) -> None:
        self.type_key = type_key
        self.id = id_
        super().__init__(f"Entity id {id_} of type {type_key} is already taken")

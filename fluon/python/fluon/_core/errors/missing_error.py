class MissingError(Exception):
    """Raised when a required value is missing."""

    def __init__(self, target: type, _id: int | None) -> None:
        self.target = target
        self.id = _id
        super().__init__(f"Missing {target.__name__} with id {_id}")

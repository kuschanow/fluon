class TransactionConflictError(Exception):
    """Raised on commit when another transaction has committed since this one started."""

    def __init__(self) -> None:
        super().__init__("Another transaction committed first; retry on the new state")

class TransactionClosedError(Exception):
    """Raised when a transaction is used after it was committed, rolled back or left."""

    def __init__(self) -> None:
        super().__init__("The transaction is already finished")

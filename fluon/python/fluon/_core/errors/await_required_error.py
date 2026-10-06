class AwaitRequiredError(Exception):
    """Raised when something that needs the backend is asked of a live store without awaiting."""

    def __init__(self, what: str, instead: str) -> None:
        self.what = what
        self.instead = instead
        super().__init__(f"{what} needs the backend on a live store; use `{instead}`")

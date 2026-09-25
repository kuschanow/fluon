class NoActiveOperationError(Exception):
    def __init__(self, operation: str):
        super().__init__(f"No active operation for {operation}")

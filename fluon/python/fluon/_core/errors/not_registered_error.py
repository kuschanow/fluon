class NotRegisteredError(Exception):
    """Raised when an entity is not registered in the system."""

    def __init__(self, cls_name: str):
        self.message = f"Entity '{cls_name}' is not registered."
        super().__init__(self.message)

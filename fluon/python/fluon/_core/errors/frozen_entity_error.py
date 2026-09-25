class FrozenEntityError(Exception):
    def __init__(self, field_name: str):
        super().__init__(f"Cannot set value for field '{field_name}' on a frozen entity.")

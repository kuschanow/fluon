from typing import Any


class _FieldType:
    def load(self, src: str, raw: Any) -> Any:
        raise NotImplementedError


class Field:
    def __init__(self, name: str):
        self.name = name
        self._type: _FieldType | None = None  # filled later by resolver

    def __get__(self, obj: Any, owner: type) -> Any:
        if obj is None:
            return self
        raw = obj._values[self.name]
        return raw  # self._type.load(obj._src, raw)

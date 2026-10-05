from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fluon._core.store import Operation

# The operation whose block is running in the current task. `Node(...)` takes no store argument:
# it finds the operation here. A ContextVar, not a global: every asyncio task sees its own value,
# so operations running in different tasks do not mix.
current_operation: ContextVar["Operation | None"] = ContextVar("fluon_current_operation", default=None)

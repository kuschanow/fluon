# `fluon` is both a regular package and a namespace: models and addons (fluon.graph, ...) ship as
# separate distributions and are found through this line. It has to stay first.
__path__ = __import__("pkgutil").extend_path(__path__, __name__)

# The public API. Everything else lives in `fluon._core` and is internal.

from fluon._core.backend import Backend, ChangeSet, CreatedBatch, DeletedBatch, Transaction
from fluon._core.entity import entity
from fluon._core.errors import FrozenEntityError, NoActiveOperationError, TypeKeyCollisionError
from fluon._core.registry import Registry, TypeInfo
from fluon._core.store import Store
from fluon._core.types.descriptors import Link, OptionalRef, OptionalRefs, Ref, Refs
from fluon._core.utils import alive, id_of, registry_of

__all__ = [
    "Backend",
    "ChangeSet",
    "CreatedBatch",
    "DeletedBatch",
    "Transaction",
    "entity",
    "FrozenEntityError",
    "NoActiveOperationError",
    "TypeKeyCollisionError",
    "Registry",
    "TypeInfo",
    "Link",
    "OptionalRef",
    "OptionalRefs",
    "Ref",
    "Refs",
    "Store",
    "alive",
    "id_of",
    "registry_of",
]

import pytest

from fluon._core.errors import InvalidTypeKeyError, NotRegisteredError, TypeKeyCollisionError, UnknownTypeError
from fluon._core.registry import Registry, TypeInfo


class Node:
    pass


class Edge:
    pass


@pytest.fixture
def registry() -> Registry:
    # A private instance: these tests never touch the process-wide registry.
    return Registry()


# --- Registration ---


def test_register_returns_type_info(registry: Registry) -> None:
    info = registry.register("graph.Node", 1, Node)

    assert info == TypeInfo(key="graph.Node", version=1, cls=Node)


def test_type_info_is_immutable(registry: Registry) -> None:
    info = registry.register("graph.Node", 1, Node)

    with pytest.raises(AttributeError):
        info.version = 2  # type: ignore[misc]


def test_registering_the_same_key_twice_is_rejected(registry: Registry) -> None:
    registry.register("graph.Node", 1, Node)

    with pytest.raises(TypeKeyCollisionError, match="graph.Node"):
        registry.register("graph.Node", 1, Edge)


def test_rejected_registration_changes_nothing(registry: Registry) -> None:
    registry.register("graph.Node", 1, Node)

    with pytest.raises(TypeKeyCollisionError):
        registry.register("graph.Node", 2, Edge)

    assert registry.by_key("graph.Node").cls is Node
    assert not registry.is_registered(Edge)


# --- Lookup by key ---


def test_by_key_finds_a_registered_type(registry: Registry) -> None:
    registry.register("graph.Node", 3, Node)

    info = registry.by_key("graph.Node")

    assert (info.key, info.version, info.cls) == ("graph.Node", 3, Node)


def test_by_key_raises_for_an_unknown_key(registry: Registry) -> None:
    with pytest.raises(UnknownTypeError, match="graph.Missing"):
        registry.by_key("graph.Missing")


# --- Lookup by class ---


def test_by_class_finds_a_registered_type(registry: Registry) -> None:
    registry.register("graph.Node", 1, Node)

    assert registry.by_class(Node).key == "graph.Node"


def test_by_class_raises_for_an_unregistered_class(registry: Registry) -> None:
    with pytest.raises(NotRegisteredError, match="Node"):
        registry.by_class(Node)


def test_is_registered(registry: Registry) -> None:
    registry.register("graph.Node", 1, Node)

    assert registry.is_registered(Node)
    assert not registry.is_registered(Edge)


def test_is_registered_accepts_any_object(registry: Registry) -> None:
    # Callers use it to ask "is this an entity type?" about arbitrary values, including unhashable ones.
    assert not registry.is_registered(42)
    assert not registry.is_registered([Node])


# --- Key format: "<package>.<Name>", dot-separated identifiers, at least two parts ---


@pytest.mark.parametrize("key", ["graph.Node", "my_app.models.Edge", "sockets.Plug2", "a.b"])
def test_valid_keys_are_accepted(registry: Registry, key: str) -> None:
    assert registry.register(key, 1, Node).key == key


@pytest.mark.parametrize(
    "key",
    ["", "Node", "graph.", ".Node", "graph..Node", "graph.No de", "graph.1Node", "graph/Node", "graph.Node ", "graph-x.Node"],
)
def test_malformed_keys_are_rejected(registry: Registry, key: str) -> None:
    with pytest.raises(InvalidTypeKeyError):
        registry.register(key, 1, Node)


def test_malformed_key_error_shows_the_key_and_the_expected_format(registry: Registry) -> None:
    with pytest.raises(InvalidTypeKeyError, match=r"'Node'.*<package>\.<Name>"):
        registry.register("Node", 1, Node)


# --- Version: a positive integer ---


@pytest.mark.parametrize("version", [0, -1])
def test_non_positive_version_is_rejected(registry: Registry, version: int) -> None:
    with pytest.raises(ValueError, match="version"):
        registry.register("graph.Node", version, Node)


@pytest.mark.parametrize("version", ["1", 1.0, None, True])
def test_non_integer_version_is_rejected(registry: Registry, version: object) -> None:
    with pytest.raises(TypeError, match="version"):
        registry.register("graph.Node", version, Node)  # type: ignore[arg-type]


# --- Isolation: registries are independent, and state can be saved and restored ---


def test_registries_do_not_share_state() -> None:
    first, second = Registry(), Registry()
    first.register("graph.Node", 1, Node)

    assert not second.is_registered(Node)


def test_restore_drops_types_registered_after_the_snapshot(registry: Registry) -> None:
    registry.register("graph.Node", 1, Node)
    state = registry._snapshot()
    registry.register("graph.Edge", 1, Edge)

    registry._restore(state)

    assert registry.is_registered(Node)
    assert not registry.is_registered(Edge)
    with pytest.raises(UnknownTypeError):
        registry.by_key("graph.Edge")


def test_restored_registry_accepts_the_dropped_key_again(registry: Registry) -> None:
    state = registry._snapshot()
    registry.register("graph.Node", 1, Node)
    registry._restore(state)

    assert registry.register("graph.Node", 1, Edge).cls is Edge


def test_snapshot_is_not_affected_by_later_registrations(registry: Registry) -> None:
    state = registry._snapshot()
    registry.register("graph.Node", 1, Node)
    registry._restore(state)
    registry.register("graph.Edge", 1, Edge)

    registry._restore(state)

    assert not registry.is_registered(Edge)

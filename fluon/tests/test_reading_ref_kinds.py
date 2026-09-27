import pytest
from fakes import FakeSource

from fluon._core.entity import entity
from fluon._core.errors import MissingError
from fluon._core.types.descriptors import Link, OptionalRef, OptionalRefs, Refs


@entity("kinds.Node", version=1)
class Node:
    label: str


@entity("kinds.Group", version=1)
class Group:
    owners: Refs[Node]


@entity("kinds.Note", version=1)
class Note:
    target: OptionalRef[Node]


@entity("kinds.Team", version=1)
class Team:
    members: OptionalRefs[Node]


# --- Refs: a tuple of handles ---


def test_refs_field_returns_a_tuple_of_target_handles(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    src.add(Node, 2, label="b")
    group = src.add(Group, 10, owners=(1, 2))

    assert isinstance(group.owners, tuple)
    assert [n.label for n in group.owners] == ["a", "b"]


def test_refs_field_keeps_the_stored_order(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    src.add(Node, 2, label="b")
    group = src.add(Group, 10, owners=(2, 1, 2))

    assert [n._id for n in group.owners] == [2, 1, 2]  # type: ignore[attr-defined]


def test_empty_refs_field_is_an_empty_tuple(src: FakeSource) -> None:
    group = src.add(Group, 10, owners=())

    assert group.owners == ()


def test_refs_elements_are_handles_of_the_target_type(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    group = src.add(Group, 10, owners=(1,))

    assert isinstance(group.owners[0], Node)
    assert group.owners[0]._src is src  # type: ignore[attr-defined]


# --- OptionalRef: a Link ---


def test_optional_ref_field_returns_a_link(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    note = src.add(Note, 10, target=1)

    assert isinstance(note.target, Link)


def test_link_exposes_the_target_id(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    note = src.add(Note, 10, target=1)

    assert note.target.id == 1


def test_link_to_a_live_target_is_alive(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    note = src.add(Note, 10, target=1)

    assert note.target.alive is True


def test_link_get_returns_the_target_handle(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    note = src.add(Note, 10, target=1)

    target = note.target.get()

    assert isinstance(target, Node)
    assert target.label == "a"


def test_link_to_a_removed_target_is_dead(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    note = src.add(Note, 10, target=1)
    src.remove(1)

    assert note.target.alive is False


def test_link_get_on_a_removed_target_raises_missing(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    note = src.add(Note, 10, target=1)
    src.remove(1)

    with pytest.raises(MissingError):
        note.target.get()


def test_dead_link_keeps_the_target_id(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    note = src.add(Note, 10, target=1)
    src.remove(1)

    assert note.target.id == 1


def test_link_state_is_not_cached(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    note = src.add(Note, 10, target=1)
    link = note.target
    assert link.alive is True

    src.remove(1)

    assert link.alive is False


def test_reading_an_optional_ref_does_not_touch_the_source(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    note = src.add(Note, 10, target=1)

    _ = note.target

    assert (src.handle_calls, src.alive_calls) == (0, 0)


# --- OptionalRef set to None: an empty link ---


def test_empty_link_has_no_id(src: FakeSource) -> None:
    note = src.add(Note, 10, target=None)

    assert note.target.id is None


def test_empty_link_is_dead(src: FakeSource) -> None:
    note = src.add(Note, 10, target=None)

    assert note.target.alive is False


def test_empty_link_get_raises_missing(src: FakeSource) -> None:
    note = src.add(Note, 10, target=None)

    with pytest.raises(MissingError):
        note.target.get()


def test_empty_link_never_asks_the_source(src: FakeSource) -> None:
    note = src.add(Note, 10, target=None)

    _ = note.target.alive
    with pytest.raises(MissingError):
        note.target.get()

    assert (src.handle_calls, src.alive_calls) == (0, 0)


# --- OptionalRefs: a tuple of links ---


def test_optional_refs_field_returns_a_tuple_of_links(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    src.add(Node, 2, label="b")
    team = src.add(Team, 10, members=(1, 2))

    assert isinstance(team.members, tuple)
    assert all(isinstance(m, Link) for m in team.members)
    assert [m.get().label for m in team.members] == ["a", "b"]


def test_optional_refs_report_each_member_separately(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    src.add(Node, 2, label="b")
    team = src.add(Team, 10, members=(1, 2))
    src.remove(2)

    assert [m.alive for m in team.members] == [True, False]


def test_optional_refs_may_contain_empty_links(src: FakeSource) -> None:
    src.add(Node, 1, label="a")
    team = src.add(Team, 10, members=(1, None))

    assert [m.id for m in team.members] == [1, None]
    assert [m.alive for m in team.members] == [True, False]

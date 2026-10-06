"""Static typing contract of the public API.

This file is never executed. It is checked by mypy and pyright (see `make typecheck`):
  - `assert_type` lines pin what a type checker must infer;
  - lines marked `# type: ignore[...]` must be errors: if a checker stops reporting one,
    the ignore becomes unused and the check fails.
"""

from typing import assert_type

from fluon import Link, Operation, OptionalRef, OptionalRefs, Ref, Refs, Registry, alive, entity, id_of


@entity("checks.Node", version=1)
class Node:
    label: str = ""


@entity("checks.Edge", version=1)
class Edge:
    u: Ref[Node]
    v: Ref[Node]
    note: OptionalRef[Node]
    weight: float = 1.0


@entity("checks.Group", version=1)
class Group:
    name: str
    owners: Refs[Node]
    members: OptionalRefs[Node]


models = Registry()


@entity("checks.Customer", version=1, registry=models)
class Customer:
    name: str


def explicit_registry(customer: Customer) -> None:
    assert_type(Customer(name="Ann"), Customer)
    assert_type(customer.name, str)
    entity("checks.Bad", version=1, registry="models")  # type: ignore[arg-type]  # not a Registry


def introspection(node: Node) -> None:
    assert_type(id_of(node), int)
    assert_type(alive(node), bool)


def construction(a: Node, b: Node) -> None:
    assert_type(Node(), Node)
    assert_type(Node(label="a"), Node)
    assert_type(Edge(u=a, v=b, note=a), Edge)
    assert_type(Edge(u=a, v=b, note=None, weight=2.0), Edge)
    assert_type(Group(name="g", owners=[a, b], members=(a, None)), Group)
    assert_type(Group(name="g", owners=(), members=()), Group)


def adding(op: Operation, a: Node, b: Node) -> None:
    # `op.add` gives back what it was given, with its type.
    assert_type(op.add(Node(label="a")), Node)
    assert_type(op.add(Edge(u=a, v=b, note=None)), Edge)


def reading(node: Node, edge: Edge, group: Group) -> None:
    assert_type(node.label, str)
    assert_type(edge.weight, float)
    assert_type(edge.u, Node)
    assert_type(edge.u.label, str)
    assert_type(edge.note, Link[Node])
    assert_type(edge.note.alive, bool)
    assert_type(edge.note.id, int | None)
    assert_type(edge.note.get(), Node)
    assert_type(group.owners, tuple[Node, ...])
    assert_type(group.members, tuple[Link[Node], ...])
    assert_type(group.members[0].get().label, str)


def rejected_construction(a: Node, b: Node) -> None:
    Edge(u=a, v=b)  # type: ignore[call-arg]  # missing `note`
    Edge(u=a, v=b, note=a, extra=1)  # type: ignore[call-arg]  # unknown field
    Edge(a, b, a)  # type: ignore[call-arg]  # fields are keyword-only
    Edge(u="x", v=b, note=a)  # type: ignore[arg-type]  # str is not a Node
    Edge(u=a, v=b, note=a, weight="heavy")  # type: ignore[arg-type]  # str is not a float
    Group(name="g", owners=(a, "x"), members=())  # type: ignore[arg-type]  # str among owners
    Group(name="g", owners=a, members=())  # type: ignore[arg-type]  # a single Node is not a collection


def rejected_usage(edge: Edge, other: Node) -> None:
    edge.u = other  # type: ignore[misc]  # entities are frozen
    edge.weight = 2.0  # type: ignore[misc]  # entities are frozen
    _ = edge.note.label  # type: ignore[attr-defined]  # a Link must be resolved with .get() first

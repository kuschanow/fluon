import pytest
from fakes import FakeSource

from fluon import Registry, alive, entity, id_of
from fluon._core.errors import CrossRegistryReferenceError, FieldTypeError, UnknownTypeError
from fluon._core.registry import registry as default_registry
from fluon._core.types.descriptors import OptionalRef, Ref
from fluon._core.types.field import resolve
from fluon._core.types.field_type import Reference, parse

# A model kept apart from the default registry, as an application with its own registry would declare it.
models = Registry()


@entity("shop.Customer", version=1, registry=models)
class Customer:
    name: str


@entity("shop.Order", version=1, registry=models)
class Order:
    customer: Ref[Customer]
    gift_for: OptionalRef["Customer"]


@entity("explicit.Default", version=1)
class InDefault:
    label: str


# --- Registration goes to the given registry only ---


def test_type_is_registered_in_the_given_registry() -> None:
    assert models.by_key("shop.Customer").cls is Customer
    assert models.by_class(Order).key == "shop.Order"


def test_type_is_not_registered_in_the_default_registry() -> None:
    assert not default_registry.is_registered(Customer)
    with pytest.raises(UnknownTypeError):
        default_registry.by_key("shop.Customer")


def test_omitting_the_registry_uses_the_default_one() -> None:
    assert default_registry.is_registered(InDefault)
    assert not models.is_registered(InDefault)


def test_the_same_key_may_live_in_two_registries() -> None:
    first, second = Registry(), Registry()

    @entity("dup.Thing", version=1, registry=first)
    class ThingA:
        label: str

    @entity("dup.Thing", version=1, registry=second)
    class ThingB:
        label: str

    assert first.by_key("dup.Thing").cls is ThingA
    assert second.by_key("dup.Thing").cls is ThingB


def test_registry_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        entity("shop.Extra", 1, models)  # type: ignore[misc]


# --- Entities of an explicit registry behave like any other ---


def test_fields_and_references_are_read(src: FakeSource) -> None:
    src.add(Customer, 1, name="Ann")
    order = src.add(Order, 2, customer=1, gift_for=None)

    assert order.customer.name == "Ann"
    assert order.gift_for.alive is False


def test_forward_references_resolve_within_the_registry(src: FakeSource) -> None:
    src.add(Customer, 1, name="Ann")
    order = src.add(Order, 2, customer=1, gift_for=1)

    assert order.gift_for.get().name == "Ann"


def test_id_of_and_alive_accept_entities_of_any_registry(src: FakeSource) -> None:
    customer = src.add(Customer, 7, name="Ann")

    assert id_of(customer) == 7
    assert alive(customer) is True


# --- References never cross registries ---


def test_reference_into_another_registry_is_rejected() -> None:
    other = Registry()

    @entity("other.Review", version=1, registry=other)
    class Review:
        author: Ref[Customer]  # Customer lives in `models`, not in `other`

    with pytest.raises(CrossRegistryReferenceError, match="registry"):
        resolve(Review)


def test_reference_from_an_explicit_registry_into_the_default_one_is_rejected() -> None:
    other = Registry()

    @entity("other.Tag", version=1, registry=other)
    class Tag:
        target: Ref[InDefault]

    with pytest.raises(CrossRegistryReferenceError, match="registry"):
        resolve(Tag)


def test_reference_from_the_default_registry_into_an_explicit_one_is_rejected() -> None:
    @entity("explicit.Note", version=1)
    class Note:
        about: Ref[Customer]

    with pytest.raises(CrossRegistryReferenceError, match="registry"):
        resolve(Note)


# --- parse itself is registry-agnostic: the boundary is checked by resolve, which knows the owner ---


def test_parse_accepts_an_entity_of_any_registry() -> None:
    assert parse(Ref[Customer]) == Reference(Customer, optional=False, many=False)
    assert parse(Ref[InDefault]) == Reference(InDefault, optional=False, many=False)


def test_bare_entity_hint_is_given_for_an_entity_of_any_registry() -> None:
    with pytest.raises(FieldTypeError, match=r"Ref\[.*\].*OptionalRef\[.*\]"):
        parse(Customer)


def test_cross_registry_error_names_the_owner_and_the_field() -> None:
    other = Registry()

    @entity("other.Review", version=1, registry=other)
    class Review:
        author: Ref[Customer]

    with pytest.raises(CrossRegistryReferenceError, match=r"Review\.author.*Customer") as exc_info:
        resolve(Review)

    error = exc_info.value
    assert (error.owner, error.field, error.target) == (Review, "author", Customer)


def test_cross_registry_error_is_not_a_field_type_error() -> None:
    # The annotation itself is a valid field type; what is violated is the registry boundary.
    assert not issubclass(CrossRegistryReferenceError, FieldTypeError)

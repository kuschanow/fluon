from collections.abc import Iterator

import pytest
from fakes import FakeSource

from fluon._core.registry import registry


@pytest.fixture(autouse=True)
def isolated_registry() -> Iterator[None]:
    # The registry is process-wide. Types registered at import stay visible;
    # whatever a test registers itself is dropped afterwards, so type keys never collide between tests.
    state = registry._snapshot()
    yield
    registry._restore(state)


@pytest.fixture
def src() -> FakeSource:
    return FakeSource()

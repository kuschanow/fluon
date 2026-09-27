import pytest
from fakes import FakeSource

import fluon._core.entity as entity_module


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    # The registry is global: each test gets an empty one so type keys never collide between tests.
    monkeypatch.setattr(entity_module, "_registry", {})


@pytest.fixture
def src() -> FakeSource:
    return FakeSource()

import pytest

from fluon import Backend
from fluon._core.dict_backend import DictBackend
from fluon.testing import BackendContract


class TestDictBackend(BackendContract):
    @pytest.fixture
    def backend(self) -> Backend:
        return DictBackend()
